"""screenplay + script review (with the continuity check) + continuity log stages."""

from __future__ import annotations

from storyforge.pipeline.runner import Stage
from storyforge.schemas import ValidationFailed, schema_errors
from storyforge.story.review import llm_review, rule_based_review
from storyforge.story.screenplay_tools import apply_edits, apply_review, normalize, semantic_errors
from storyforge.util.hashing import maybe_file_hash, stable_hash
from storyforge.util.io import read_json, write_json


def _bible_story_view(bible: dict) -> dict:
    """The parts of the bible that affect writing/reviewing (not e.g. the continuity of later parts)."""
    return {k: bible.get(k) for k in ("title", "world", "characters", "relationships", "running_gags",
                                      "locations", "format")}


def _continuity_view(entries: list[dict]) -> list:
    return [{k: e.get(k) for k in ("episode_id", "summary", "changes", "open_threads", "object_states",
                                   "character_states")} for e in entries]


class ScreenplayStage(Stage):
    """Write the part's screenplay with the LLM (or demo writer) unless one exists; validate it."""

    code = ("story/*.py", "schemas/*.py")
    name = "screenplay"
    version = "1"
    weight = 2.0

    def inputs(self, ctx):
        return {"screenplay": maybe_file_hash(ctx.path("screenplay.json"))}

    def outputs(self, ctx):
        return [ctx.path("screenplay.json")]

    def run(self, ctx):
        from storyforge.story.continuity import prior_entries

        p = ctx.path("screenplay.json")
        bible = ctx.bible()
        if not p.is_file():
            from storyforge.story.writer import write_screenplay

            meta = ctx.meta()
            arc = ctx.project.arc(meta.get("arc_id", "")) or {}
            plan = next((x for x in arc.get("parts", []) if x["part"] == meta.get("part", 1)), None)
            if plan is None:
                raise ValidationFailed([f"episode {ctx.episode_id} has no screenplay and no arc part plan"])
            prior = prior_entries(bible, ctx.episode_id)
            prev = ctx.project.previous_episode(ctx.episode_id)
            prev_summary = next((e.get("summary") for e in prior if e.get("episode_id") == prev), None)
            ctx.log(f"writing screenplay with {ctx.llm.name}")
            sp = write_screenplay(ctx.llm, bible, arc, plan, set(ctx.cast()), prev_summary, continuity=prior,
                                  variation=int(meta.get("variation", 0) or 0))
            sp["episode_id"] = ctx.episode_id
            write_json(p, sp)
            ctx.project.save_episode_meta(ctx.episode_id, {"status": "written", "title": sp["title"]})
        sp = read_json(p)
        errors = schema_errors("screenplay", sp)
        if errors:
            raise ValidationFailed(errors)
        sem = semantic_errors(sp, bible, set(ctx.cast()), {loc["id"] for loc in bible.get("locations", [])})
        if sem:
            raise ValidationFailed(sem)
        return {"beats": len(sp["beats"]), "title": sp["title"]}


class ReviewStage(Stage):
    """Story-editor review (rule-based + LLM), user edits, then the continuity check (+ auto-fix)
    against the bible and earlier episodes -> screenplay.final.json + review.json + continuity.json."""

    code = ("story/*.py", "schemas/*.py")
    name = "review"
    version = "2"
    weight = 2.0

    def inputs(self, ctx):
        from storyforge.story.continuity import prior_entries

        bible = ctx.bible()
        return {"screenplay": maybe_file_hash(ctx.path("screenplay.json")),
                "edits": maybe_file_hash(ctx.path("edits.json")),
                "bible": stable_hash(_bible_story_view(bible)),
                "continuity": stable_hash(_continuity_view(prior_entries(bible, ctx.episode_id))),
                "provider": [ctx.llm.name, ctx.llm.model]}

    def outputs(self, ctx):
        return [ctx.path("screenplay.final.json"), ctx.path("review.json"), ctx.path("continuity.json")]

    def run(self, ctx):
        from storyforge.story.continuity import check_and_fix, prior_entries

        sp = read_json(ctx.path("screenplay.json"))
        bible = ctx.bible()
        meta = ctx.meta()
        arc = ctx.project.arc(meta.get("arc_id", "")) or {}
        parts_total = len(arc.get("parts", [])) or 1
        is_finale = meta.get("part", 1) >= parts_total
        plan = next((x for x in arc.get("parts", []) if x["part"] == meta.get("part", 1)), None)
        prior = prior_entries(bible, ctx.episode_id)
        findings = rule_based_review(sp, bible, is_finale)
        review = findings
        if ctx.llm.name != "demo":
            try:
                review = llm_review(ctx.llm, sp, bible, plan, findings, is_finale, continuity=prior)
            except Exception as exc:  # the rule-based review is still valid; never block the pipeline here
                ctx.log(f"LLM review failed ({exc}); using rule-based review")
                review = findings
        else:
            review = ctx.llm.generate_json("script_review", "", "", "review",
                                           context={"screenplay": sp, "findings": findings})
        reviewed = apply_review(sp, review)
        cast_ids = set(ctx.cast())
        loc_ids = {loc["id"] for loc in bible.get("locations", [])}

        def validate(doc):
            return schema_errors("screenplay", doc) + semantic_errors(doc, bible, cast_ids, loc_ids)

        if validate(reviewed):
            ctx.log("review rewrites produced an invalid screenplay; keeping the original beats")
            reviewed = sp
            review["rejected_rewrites"] = True
        edits = read_json(ctx.path("edits.json"), {})
        final = normalize(apply_edits(reviewed, edits))
        errors = validate(final)
        if errors:
            raise ValidationFailed(errors)
        review["applied_rewrites"] = [r.get("id") for r in review.get("rewrites", [])]
        review["rule_based"] = findings
        write_json(ctx.path("review.json"), review)
        # continuity check against the bible + earlier episodes; errors on beats the user did not
        # edit by hand are rewritten by the LLM (validated like any screenplay)
        fmt = bible.get("format", {}) or {}
        prev_id = ctx.project.previous_episode(ctx.episode_id)
        prev_entry = next((e for e in prior if e.get("episode_id") == prev_id), None)
        locked = set((edits.get("beats") or {}).keys()) | {b.get("id") for b in edits.get("added") or []}
        report, final = check_and_fix(ctx.llm, final, bible, prior, previous_entry=prev_entry, locked_beats=locked,
                                      autofix=bool(fmt.get("continuity_autofix", True)), validate=validate,
                                      log=ctx.log)
        final = normalize(final)
        report["gate"] = fmt.get("continuity_gate", "warn")
        write_json(ctx.path("continuity.json"), report)
        write_json(ctx.path("screenplay.final.json"), final)
        ctx.project.save_episode_meta(ctx.episode_id, {"status": "reviewed", "title": final["title"]})
        open_errors = [i for i in report["issues"] if i["status"] == "open" and i["severity"] == "error"]
        for i in report["issues"]:
            if i["status"] == "open":
                ctx.log(f"continuity {i['severity']}: {i.get('beat_id') or '-'} {i['message']}")
        if open_errors and report["gate"] == "block":
            raise ValidationFailed([f"continuity ({i.get('beat_id') or 'script'}): {i['message']}"
                                    for i in open_errors]
                                   + ["fix these beats in the beat editor, or set format.continuity_gate: warn"])
        return {"scores": review.get("scores"), "rewrites": len(review.get("rewrites", [])),
                "continuity": report["counts"], "continuity_fixed": report["auto_fixed"]}


class ContinuityLogStage(Stage):
    """Write what happened in this part into the bible's continuity log (the series' memory)."""

    code = ("story/continuity.py", "story/demo_writer.py", "schemas/*.py")
    name = "continuity_log"
    version = "1"
    weight = 0.5

    def inputs(self, ctx):
        meta = ctx.meta()
        return {"screenplay": maybe_file_hash(ctx.path("screenplay.final.json")),
                "provider": [ctx.llm.name, ctx.llm.model], "episode": [meta.get("arc_id"), meta.get("part")]}

    def outputs(self, ctx):
        return [ctx.path("continuity_entry.json")]

    def run(self, ctx):
        from storyforge.project import now_iso
        from storyforge.providers.llm import LLMError
        from storyforge.story.continuity import prior_entries, write_log_entry
        from storyforge.story.demo_writer import template_continuity

        sp = read_json(ctx.path("screenplay.final.json"))
        bible = ctx.bible()
        try:
            entry = write_log_entry(ctx.llm, sp, bible, prior_entries(bible, ctx.episode_id))
        except (LLMError, ValidationFailed) as exc:
            ctx.log(f"LLM continuity log failed ({exc}); using the template entry")
            entry = template_continuity(sp)
            entry.pop("_lines", None)
        meta = ctx.meta()
        entry = {"episode_id": ctx.episode_id, "arc_id": meta.get("arc_id"), "part": meta.get("part"),
                 "title": sp.get("title"), **entry, "status": "scripted", "logged_at": now_iso(),
                 "screenplay_hash": maybe_file_hash(ctx.path("screenplay.final.json")), "provider": ctx.llm.name}
        write_json(ctx.path("continuity_entry.json"), entry)
        version = ctx.project.upsert_continuity_entry(entry)
        return {"summary": entry["summary"][:160], "bible_version": version}
