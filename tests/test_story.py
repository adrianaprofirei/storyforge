"""Arc planner, continuity (rules + log), beat-edit diffs and bible versioning (demo provider)."""

from __future__ import annotations

import copy

from storyforge.config import ASSETS_DIR, get_settings
from storyforge.project import bible_diff
from storyforge.providers.llm import get_llm
from storyforge.story.arc import arc_semantic_errors, plan_arc
from storyforge.story.continuity import check_and_fix, prior_entries, rule_issues
from storyforge.story.screenplay_tools import apply_edits, diff_edits, normalize
from storyforge.util.io import read_json

SP1 = ASSETS_DIR / "samples" / "screenplays" / "part1.json"


def test_plan_arc_registers_episodes_in_the_bible(fresh_project):
    arc = plan_arc(fresh_project, "Gus finds a library book that rewrites its own ending every night.", 3,
                   llm=get_llm(get_settings()))
    assert len(arc["parts"]) == 3
    assert arc["parts"][0]["recap"] is None and arc["parts"][-1]["cliffhanger"] is None
    assert all(p["cliffhanger"] for p in arc["parts"][:-1])
    bible = fresh_project.bible()
    assert any(a["id"] == arc["arc_id"] for a in bible["arcs"])
    eids = [e["id"] for e in bible["episodes"] if e["arc_id"] == arc["arc_id"]]
    assert eids == [f"{arc['arc_id']}_p{i}" for i in (1, 2, 3)]
    assert fresh_project.episode_meta(eids[1])["part"] == 2


def test_arc_semantic_rules():
    arc = {"parts": [{"part": 1, "cast": ["milo"], "location": "library", "cliffhanger": None, "hook": "x"},
                     {"part": 2, "cast": ["ghost"], "location": "mars", "cliffhanger": "y", "recap": None, "hook": "x"}]}
    errors = arc_semantic_errors(arc, 2, {"milo"}, {"library"})
    text = " ".join(errors)
    assert "part 1 must end on a cliffhanger" in text
    assert "finale" in text and "recap" in text and "ghost" in text and "mars" in text


def test_rule_based_continuity_checks():
    bible = {"world": {"content_rules": ["kid-safe, no violence or weapons", "no real brands or logos"]},
             "characters": [{"id": "milo"}, {"id": "zara"}], "locations": [{"id": "library"}]}
    sp = {"cast": ["milo", "zara"], "location": "library", "beats": [
        {"id": "b01", "line": "I'll play Roblox later.", "action": "", "props": []},
        {"id": "b02", "line": "", "action": "Milo shows the key.", "props": [{"character": "milo", "prop": "key", "action": "show"}]},
        {"id": "b03", "line": "Grab the knife!", "action": "", "props": []},
    ]}
    prior = [{"episode_id": "p1", "object_states": [{"object": "key", "holder": None, "status": "lost"}],
              "open_threads": ["Who rang the stopped clock tower bell?"]}]
    issues = rule_issues(sp, bible, prior, previous_entry=prior[0])
    kinds = {(i["beat_id"], i["kind"], i["severity"]) for i in issues}
    assert ("b01", "content_rule", "error") in kinds        # real brand
    assert ("b03", "content_rule", "error") in kinds        # weapon
    assert ("b02", "object", "warning") in kinds            # lost key used again
    assert any(i["kind"] == "forgotten_event" for i in issues)


def test_check_and_fix_in_demo_mode_reports_but_never_rewrites():
    bible = read_json(ASSETS_DIR / "samples" / "arc.json")  # any dict works for the demo path below
    sp = read_json(SP1)
    llm = get_llm(get_settings())
    report, out = check_and_fix(llm, sp, {"world": {"content_rules": []}, "characters": [{"id": c} for c in sp["cast"]],
                                          "locations": [{"id": sp["location"]}]}, [])
    assert report["passed"] and out == sp
    assert bible  # sanity


def test_prior_entries_respect_episode_order():
    bible = {"episodes": [{"id": "a_p1"}, {"id": "a_p2"}, {"id": "a_p3"}],
             "continuity_log": [{"episode_id": "a_p1"}, {"episode_id": "a_p2"}, {"episode_id": "a_p3"}]}
    assert [e["episode_id"] for e in prior_entries(bible, "a_p2")] == ["a_p1"]
    assert [e["episode_id"] for e in prior_entries(bible, "a_p3")] == ["a_p1", "a_p2"]


def test_beat_edit_diff_round_trip():
    base = normalize(read_json(SP1))
    edited = copy.deepcopy(base)
    edited["beats"][2]["line"] = "Totally new line."
    edited["beats"][2]["emotion"] = "smug"
    removed = edited["beats"].pop(4)["id"]
    new_beat = dict(copy.deepcopy(edited["beats"][0]), id="b99", line="Added!")
    edited["beats"].insert(1, new_beat)
    edits = diff_edits(base, edited)
    assert set(edits["beats"]) == {base["beats"][2]["id"]}
    assert edits["deleted"] == [removed]
    assert [b["id"] for b in edits["added"]] == ["b99"]
    assert "order" in edits
    rebuilt = normalize(apply_edits(base, edits))
    assert [b["id"] for b in rebuilt["beats"]] == [b["id"] for b in edited["beats"]]
    assert rebuilt["beats"][3]["line"] == "Totally new line."
    assert diff_edits(base, base) == {}


def test_bible_versions_diff_and_restore(fresh_project):
    v0 = fresh_project.bible()["version"]
    v1 = fresh_project.update_bible(lambda b: b["world"].update(tone="spooky"), "tone change")
    assert v1 == v0 + 1
    d = bible_diff(fresh_project.bible_version(v0), fresh_project.bible_version(v1))
    assert [x["path"] for x in d] == ["world.tone"]
    v2 = fresh_project.restore_bible_version(v0)
    assert fresh_project.bible()["world"]["tone"] == fresh_project.bible_version(v0)["world"]["tone"]
    assert v2 == v1 + 1, "restoring creates a new version; history is never rewritten"


def test_continuity_entry_upsert_is_idempotent(fresh_project):
    entry = {"episode_id": "x_p1", "summary": "Things happened.", "changes": {}, "status": "scripted", "logged_at": "t1"}
    v = fresh_project.upsert_continuity_entry(entry)
    assert v is not None
    assert fresh_project.upsert_continuity_entry({**entry, "logged_at": "t2"}) is None  # nothing changed
    assert len([e for e in fresh_project.bible()["continuity_log"] if e["episode_id"] == "x_p1"]) == 1
