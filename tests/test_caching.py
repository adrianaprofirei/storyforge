"""Content-hash caching: stages re-run only when their inputs (or their code) change."""

from __future__ import annotations

import pytest

from storyforge.pipeline.cache import ItemCache, StageRecords, stage_key
from storyforge.pipeline.context import EpisodeContext, RunOptions
from storyforge.pipeline.runner import Stage, run_episode
from storyforge.util.hashing import file_hash, stable_hash
from storyforge.util.io import read_json, write_json


def test_stage_key_is_stable_and_sensitive():
    a = stage_key("timeline", "1", {"x": 1, "y": [1, 2]})
    assert a == stage_key("timeline", "1", {"y": [1, 2], "x": 1})  # key order does not matter
    assert a != stage_key("timeline", "2", {"x": 1, "y": [1, 2]})  # version bump
    assert a != stage_key("timeline", "1", {"x": 2, "y": [1, 2]})  # input change
    assert stable_hash({"a": 1.0}) == stable_hash({"a": 1.0})


def test_file_hash_tracks_content(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("one")
    h1 = file_hash(p)
    p.write_text("two")
    assert file_hash(p) != h1


def test_stage_records_freshness(tmp_path):
    rec = StageRecords(tmp_path)
    out = tmp_path / "out.json"
    out.write_text("{}")
    rec.put("s", "k1", [out], 0.1)
    assert rec.is_fresh("s", "k1", [out])
    assert not rec.is_fresh("s", "k2", [out])       # different inputs
    out.unlink()
    assert not rec.is_fresh("s", "k1", [out])       # output missing -> re-run


def test_item_cache(tmp_path):
    ic = ItemCache(tmp_path)
    assert ic.get("abc123", ".wav") is None
    p = ic.path("abc123", ".wav")
    p.write_bytes(b"x")
    assert ic.get("abc123", ".wav") == p


class Counting(Stage):
    def __init__(self, name, src, dst):
        self.name, self.src, self.dst, self.runs = name, src, dst, 0

    def inputs(self, ctx):
        p = ctx.path(self.src)
        return {"src": file_hash(p) if p.is_file() else None}

    def outputs(self, ctx):
        return [ctx.path(self.dst)]

    def run(self, ctx):
        self.runs += 1
        data = read_json(ctx.path(self.src), {"v": 0})
        write_json(ctx.path(self.dst), {"v": data["v"] + 1})


@pytest.fixture()
def ctx(fresh_project):
    eid = "cache_test"
    fresh_project.save_episode_meta(eid, {"title": "cache test"})
    return EpisodeContext(fresh_project, eid, RunOptions(preset="proxy"), on_log=lambda _l: None)


def test_pipeline_reruns_only_changed_stages(ctx):
    write_json(ctx.path("a.json"), {"v": 1})
    s1, s2 = Counting("one", "a.json", "b.json"), Counting("two", "b.json", "c.json")
    reports = run_episode(ctx, [s1, s2])
    assert [r.status for r in reports] == ["ran", "ran"]
    reports = run_episode(ctx, [s1, s2])
    assert [r.status for r in reports] == ["cached", "cached"]
    assert (s1.runs, s2.runs) == (1, 1)
    # change the first input: both re-run (the second sees new content)
    write_json(ctx.path("a.json"), {"v": 5})
    run_episode(ctx, [s1, s2])
    assert (s1.runs, s2.runs) == (2, 2)
    assert read_json(ctx.path("c.json"))["v"] == 7
    # same content rewritten: still cached
    write_json(ctx.path("a.json"), {"v": 5})
    assert [r.status for r in run_episode(ctx, [s1, s2])] == ["cached", "cached"]
    # forcing a stage
    ctx.options.force = {"two"}
    run_episode(ctx, [s1, s2])
    assert (s1.runs, s2.runs) == (2, 3)


def test_deleted_output_triggers_rerun(ctx):
    write_json(ctx.path("a.json"), {"v": 1})
    s1 = Counting("one", "a.json", "b.json")
    run_episode(ctx, [s1])
    ctx.path("b.json").unlink()
    run_episode(ctx, [s1])
    assert s1.runs == 2


class SelfReferential(Stage):
    """Creates its own input (like the screenplay stage writing screenplay.json)."""

    name = "selfref"

    def __init__(self):
        self.runs = 0

    def inputs(self, ctx):
        p = ctx.path("made.json")
        return {"made": file_hash(p) if p.is_file() else None}

    def outputs(self, ctx):
        return [ctx.path("made.json")]

    def run(self, ctx):
        self.runs += 1
        write_json(ctx.path("made.json"), {"ok": True})


def test_stage_that_creates_its_input_is_cached_next_time(ctx):
    st = SelfReferential()
    run_episode(ctx, [st])
    run_episode(ctx, [st])
    assert st.runs == 1


def test_code_hash_invalidates(ctx, monkeypatch):
    import storyforge.pipeline.runner as runner

    write_json(ctx.path("a.json"), {"v": 1})
    s1 = Counting("one", "a.json", "b.json")
    s1.code = ("timeline.py",)
    run_episode(ctx, [s1])
    run_episode(ctx, [s1])
    assert s1.runs == 1
    monkeypatch.setattr(runner, "code_hash", lambda *p: "changed-source")
    run_episode(ctx, [s1])
    assert s1.runs == 2
