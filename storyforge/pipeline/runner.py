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


class Stage:
    name: str = "stage"
    version: str = "1"
    # rough share of total runtime, used for progress bars and ETAs
    weight: float = 1.0

    def inputs(self, ctx: EpisodeContext) -> dict:
        return {}

    def outputs(self, ctx: EpisodeContext) -> list[Path]:
        return []

    def enabled(self, ctx: EpisodeContext) -> bool:
        return True

    def run(self, ctx: EpisodeContext) -> dict | None:
        raise NotImplementedError


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
        key = stage_key(st.name, st.version, inputs)
        outputs = st.outputs(ctx)
        if st.name not in ctx.options.force and records.is_fresh(st.name, key, outputs):
            reports.append(StageReport(st.name, "cached", key=key))
            ctx.log("cached")
        else:
            ctx.log("running")
            ctx.progress(0.0, "start")
            t0 = time.time()
            try:
                info = st.run(ctx) or {}
            except Exception as exc:
                reports.append(StageReport(st.name, "failed", time.time() - t0, key, error=str(exc)))
                ctx.log(f"FAILED: {exc}")
                raise
            seconds = time.time() - t0
            # outputs may depend on what run() produced (e.g. file names); re-query
            outputs = st.outputs(ctx)
            records.put(st.name, key, outputs, seconds, {"info": info})
            reports.append(StageReport(st.name, "ran", seconds, key, info))
            ctx.log(f"done in {seconds:.1f}s")
        done_w += st.weight
        ctx.progress(1.0, "done")
        if ctx.options.until and st.name == ctx.options.until:
            break
    ctx.stage_name = ""
    return reports


def summarize(reports: list[StageReport]) -> str:
    rows = []
    for r in reports:
        extra = f" ({r.seconds:.1f}s)" if r.status == "ran" else ""
        rows.append(f"  {r.stage:<14} {r.status}{extra}")
    return "\n".join(rows)
