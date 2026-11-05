"""REST API + job queue (demo provider, no Blender needed)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(demo_project):
    from storyforge.api.app import create_app

    with TestClient(create_app()) as c:
        yield c


def wait_job(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.3)
    raise AssertionError(f"job {job_id} did not finish: {j}")


def test_health_and_options(client):
    assert client.get("/api/health").json()["ok"]
    o = client.get("/api/options").json()
    assert "happy" in o["emotions"] and "close_up" in o["shot_types"] and o["locations"]
    s = client.get("/api/system").json()
    assert s["llm"]["provider"] == "demo" and isinstance(s["tts_available"], list)


def test_series_and_bible_validation(client):
    series = client.get("/api/series").json()
    assert any(s["id"] == "clockwork_club" for s in series)
    r = client.put("/api/series/clockwork_club/bible", json={"yaml": "series_id: clockwork_club\ntitle: broken\n"})
    assert r.status_code == 422 and r.json()["detail"]["errors"]
    b = client.get("/api/series/clockwork_club/bible").json()
    bible = b["bible"]
    bible["logline"] = bible["logline"] + " (edited)"
    r = client.put("/api/series/clockwork_club/bible", json={"bible": bible, "message": "test edit"})
    assert r.status_code == 200 and r.json()["version"] == b["version"] + 1
    versions = client.get("/api/series/clockwork_club/bible/versions").json()
    assert versions[0]["message"] == "test edit"


@pytest.mark.parametrize("path", ["%2e%2e/%2e%2e/%2e%2e/etc/passwd", "..%2f..%2f..%2fetc%2fpasswd", "/etc/passwd",
                                  "%2e%2e/%2e%2e/pyproject.toml"])
def test_files_are_confined_to_the_project(client, path):
    r = client.get(f"/api/files/clockwork_club/{path}")
    assert r.status_code == 404
    assert "root:" not in r.text and "[project]" not in r.text


def test_project_files_are_served(client):
    assert client.get("/api/files/clockwork_club/bible/current.yaml").status_code == 200


def test_plan_write_and_edit_through_jobs(client):
    j = client.post("/api/series/clockwork_club/arcs/plan",
                    json={"idea": "Milo's alarm clock starts ringing backwards every morning.", "parts": 2}).json()
    assert j["lane"] == "story"
    done = wait_job(client, j["id"])
    assert done["status"] == "done", done.get("error")
    aid = done["result"]["arc_id"]
    r = wait_job(client, client.post(f"/api/series/clockwork_club/arcs/{aid}/run", json={"until": "continuity_log"}).json()["id"])
    assert r["status"] == "done", r.get("error")
    eid = f"{aid}_p1"
    sp = client.get(f"/api/series/clockwork_club/episodes/{eid}/screenplay").json()
    final = sp["final"]
    assert sp["continuity"]["passed"] and sp["continuity_entry"]["summary"]
    final["beats"][1]["line"] = "A brand new line from the editor."
    r = client.put(f"/api/series/clockwork_club/episodes/{eid}/screenplay", json=final)
    assert r.status_code == 200 and r.json()["edited_beats"] == [final["beats"][1]["id"]]
    bad = dict(final, beats=[dict(final["beats"][0], speaker="nobody")] + final["beats"][1:])
    assert client.put(f"/api/series/clockwork_club/episodes/{eid}/screenplay", json=bad).status_code == 422
    r = wait_job(client, client.post(f"/api/series/clockwork_club/episodes/{eid}/run", json={"until": "continuity_log"}).json()["id"])
    assert r["status"] == "done"
    final2 = client.get(f"/api/series/clockwork_club/episodes/{eid}/screenplay").json()["final"]
    assert final2["beats"][1]["line"] == "A brand new line from the editor."
    log = client.get(f"/api/jobs/{r['id']}/log").json()
    assert "started on lane" in log["text"]
    assert client.delete(f"/api/series/clockwork_club/arcs/{aid}").json()["ok"]


def test_cancel_queued_job(client):
    from storyforge.jobs.manager import get_manager

    mgr = get_manager()
    job = mgr.store.create("plan_arc", "nonexistent-lane", {"series": "clockwork_club", "idea": "x" * 20},
                           title="never runs", series="clockwork_club")
    assert client.post(f"/api/jobs/{job['id']}/cancel").json()["ok"]
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
