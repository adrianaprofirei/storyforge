"""screenplay + script review stages."""

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


class ScreenplayStage(Stage):
    """Write the part's screenplay with the LLM (or demo writer) unless one exists; validate it."""

    name = "screenplay"
    version = "1"
    weight = 2.0

    def inputs(self, ctx):
        return {"screenplay": maybe_file_hash(ctx.path("screenplay.json"))}

    def outputs(self, ctx):
        return [ctx.path("screenplay.json")]

    def run(self, ctx):
        p = ctx.path("screenplay.json")
        bible = ctx.bible()
        if not p.is_file():
            from storyforge.story.writer import write_screenplay

            meta = ctx.meta()
            arc = ctx.project.arc(meta.get("arc_id", "")) or {}
            plan = next((x for x in arc.get("parts", []) if x["part"] == meta.get("part", 1)), None)
            if plan is None:
                raise ValidationFailed([f"episode {ctx.episode_id} has no screenplay and no arc part plan"])
            prev = ctx.project.previous_episode(ctx.episode_id)
            prev_summary = None
            if prev:
                for e in bible.get("continuity_log", []):
                    if e.get("episode_id") == prev:
                        prev_summary = e.get("summary")
            ctx.log(f"writing screenplay with {ctx.llm.name}")
            sp = write_screenplay(ctx.llm, bible, arc, plan, set(ctx.cast()), prev_summary)
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
    """Story-editor review (rule-based + LLM), then user edits -> screenplay.final.json."""

    name = "review"
    version = "1"
    weight = 2.0

    def inputs(self, ctx):
        bible = ctx.bible()
        return {"screenplay": maybe_file_hash(ctx.path("screenplay.json")),
                "edits": maybe_file_hash(ctx.path("edits.json")),
                "bible": stable_hash(_bible_story_view(bible)),
                "provider": ctx.llm.name}

    def outputs(self, ctx):
        return [ctx.path("screenplay.final.json"), ctx.path("review.json")]

    def run(self, ctx):
        sp = read_json(ctx.path("screenplay.json"))
        bible = ctx.bible()
        meta = ctx.meta()
        arc = ctx.project.arc(meta.get("arc_id", "")) or {}
        parts_total = len(arc.get("parts", [])) or 1
        is_finale = meta.get("part", 1) >= parts_total
        plan = next((x for x in arc.get("parts", []) if x["part"] == meta.get("part", 1)), None)
        findings = rule_based_review(sp, bible, is_finale)
        review = findings
        if ctx.llm.name != "demo":
            try:
                review = llm_review(ctx.llm, sp, bible, plan, findings, is_finale)
            except Exception as exc:  # the rule-based review is still valid; never block the pipeline here
                ctx.log(f"LLM review failed ({exc}); using rule-based review")
                review = findings
        else:
            review = ctx.llm.generate_json("script_review", "", "", "review",
                                           context={"screenplay": sp, "findings": findings})
        reviewed = apply_review(sp, review)
        cast_ids = set(ctx.cast())
        loc_ids = {loc["id"] for loc in bible.get("locations", [])}
        if schema_errors("screenplay", reviewed) or semantic_errors(reviewed, bible, cast_ids, loc_ids):
            ctx.log("review rewrites produced an invalid screenplay; keeping the original beats")
            reviewed = sp
            review["rejected_rewrites"] = True
        edits = read_json(ctx.path("edits.json"), {})
        final = normalize(apply_edits(reviewed, edits))
        errors = schema_errors("screenplay", final) + semantic_errors(final, bible, cast_ids, loc_ids)
        if errors:
            raise ValidationFailed(errors)
        review["applied_rewrites"] = [r.get("id") for r in review.get("rewrites", [])]
        review["rule_based"] = findings
        write_json(ctx.path("review.json"), review)
        write_json(ctx.path("screenplay.final.json"), final)
        ctx.project.save_episode_meta(ctx.episode_id, {"status": "reviewed", "title": final["title"]})
        return {"scores": review.get("scores"), "rewrites": len(review.get("rewrites", []))}
