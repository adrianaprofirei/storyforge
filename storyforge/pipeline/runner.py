"""Stage graph execution with content-hash caching.

Order (episode level)::

    screenplay -> review -> voices -> lipsync -> timeline -> shots -> audio_mix
      -> scene -> build -> render -> captions -> mux -> quality -> deliverables

``bible`` and ``arc plan`` live above the episode level (see :mod:`storyforge.story`): their
outputs (bible version, arc part plan) are inputs of the ``screenplay`` and ``review`` stages,
so editing the bible re-runs exactly the stages that read it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from storyforge.pipeline.cache import StageRecords, stage_key
from storyforge.pipeline.context import EpisodeContext

PKG_DIR = Path(__file__).resolve().parents[1]


def code_hash(*patterns: str) -> str:
    """Hash of the backend source files a stage depends on (so code changes invalidate caches)."""
    from storyforge.util.hashing import tree_hash

    return tree_hash(PKG_DIR, patterns)


class Stage:
    name: str = "stage"
    version: str = "1"
    # rough share of total runtime, used for progress bars and ETAs
    weight: float = 1.0
    # backend source globs (relative to the storyforge package) whose changes invalidate this stage
    code: tuple[str, ...] = ()

    def inputs(self, ctx: EpisodeContext) -> dict:
        return {}

    def outputs(self, ctx: EpisodeContext) -> list[Path]:
        return []

    def enabled(self, ctx: EpisodeContext) -> bool:
        return True

    def run(self, ctx: EpisodeContext) -> dict | None:
        raise NotImplementedError

    def on_complete(self, ctx: EpisodeContext, status: str) -> None:
        """Called after the stage ran or was served from cache (idempotent bookkeeping)."""


@dataclass
class StageReport:
    stage: str
    status: str  # ran | cached | skipped | failed
    seconds: float = 0.0
    key: str = ""
    info: dict = field(default_factory=dict)
    error: str | None = None


def default_stages() -> list[Stage]:
    from storyforge.pipeline.stages import ALL_STAGES

    return [cls() for cls in ALL_STAGES]


def _flush_llm_calls(ctx: EpisodeContext, stage: str, start: int) -> None:
    """Append the LLM calls a stage made (task, attempts, tokens, served model) to llm_calls.jsonl."""
    llm = getattr(ctx, "_llm", None)
    if llm is None or len(llm.calls) <= start:
        return
    import json
    from dataclasses import asdict

    with open(ctx.path("llm_calls.jsonl"), "a", encoding="utf-8") as fh:
        for call in llm.calls[start:]:
            fh.write(json.dumps({"t": round(time.time(), 1), "stage": stage, **asdict(call)}) + "\n")


def run_episode(ctx: EpisodeContext, stages: list[Stage] | None = None) -> list[StageReport]:
    stages = stages or default_stages()
    records = StageRecords(ctx.dir)
    reports: list[StageReport] = []
    active = [s for s in stages if s.enabled(ctx)]
    total_w = sum(s.weight for s in active) or 1.0
    done_w = 0.0
    for st in stages:
        ctx.check_cancel()
        ctx.stage_name = st.name
        if not st.enabled(ctx):
            reports.append(StageReport(st.name, "skipped"))
            continue
        ctx._stage_weight = (done_w / total_w, (done_w + st.weight) / total_w)
        inputs = st.inputs(ctx)
        if st.code:
            inputs = {"_inputs": inputs, "_code": code_hash(*st.code)}
        key = stage_key(st.name, st.version, inputs)
        outputs = st.outputs(ctx)
        if st.name not in ctx.options.force and records.is_fresh(st.name, key, outputs):
            reports.append(StageReport(st.name, "cached", key=key))
            ctx.log("cached")
            st.on_complete(ctx, "cached")
        else:
            ctx.log("running")
            ctx.progress(0.0, "start")
            t0 = time.time()
            n_calls = len(ctx._llm.calls) if getattr(ctx, "_llm", None) is not None else 0
            try:
                info = st.run(ctx) or {}
            except Exception as exc:
                reports.append(StageReport(st.name, "failed", time.time() - t0, key, error=str(exc)))
                ctx.log(f"FAILED: {exc}")
                _flush_llm_calls(ctx, st.name, n_calls)
                raise
            _flush_llm_calls(ctx, st.name, n_calls)
            seconds = time.time() - t0
            # outputs may depend on what run() produced (e.g. file names); re-query. Inputs too: a
            # stage may create its own input (screenplay.json) or fix upstream files (preflight), and
            # the record must describe the state it left behind so the next run is a cache hit.
            outputs = st.outputs(ctx)
            post = st.inputs(ctx)
            if st.code:
                post = {"_inputs": post, "_code": code_hash(*st.code)}
            key = stage_key(st.name, st.version, post)
            records.put(st.name, key, outputs, seconds, {"info": info})
            reports.append(StageReport(st.name, "ran", seconds, key, info))
            ctx.log(f"done in {seconds:.1f}s")
            st.on_complete(ctx, "ran")
        done_w += st.weight
        ctx.progress(1.0, "done")
        if ctx.options.until and st.name == ctx.options.until:
            break
    ctx.stage_name = ""
    return reports


def run_subset(ctx: EpisodeContext, names: list[str]) -> list[StageReport]:
    """Re-run (cache-aware) some stages from inside another stage, e.g. after the preflight applied
    auto-fixes. Progress of the nested run is not reported (the caller owns the progress bar)."""
    from storyforge.pipeline.stages import ALL_STAGES

    saved = (ctx.stage_name, ctx._stage_weight, ctx._on_progress, ctx.options.until)
    ctx._on_progress = None
    ctx.options.until = None
    try:
        return run_episode(ctx, [cls() for cls in ALL_STAGES if cls.name in names])
    finally:
        ctx.stage_name, ctx._stage_weight, ctx._on_progress, ctx.options.until = saved


def summarize(reports: list[StageReport]) -> str:
    rows = []
    for r in reports:
        extra = f" ({r.seconds:.1f}s)" if r.status == "ran" else ""
        rows.append(f"  {r.stage:<14} {r.status}{extra}")
    return "\n".join(rows)
