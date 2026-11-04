"""In-process job manager: lanes of worker threads over the SQLite job store.

Lanes keep the UI responsive: `story` (LLM work: arc plans, screenplays, reviews), `render`
(Blender builds/renders/muxing; one at a time by default because a render already uses every
GPU/CPU core via RENDER_WORKERS) and `preview` (character previews and other quick Blender
stills). Jobs declare locks (episode ids, arc ids); a lane never starts a job whose locks are held
by a running job, so e.g. a beat edit + re-review never races a render of the same episode.

Progress is written at most every 0.5 s; the ETA is extrapolated from progress over elapsed time
and smoothed. Cancelling sets the job's event: pipeline stages and the Blender subprocess runner
check it and stop cleanly (everything finished so far stays cached, so a retry resumes).
"""

from __future__ import annotations

import logging
import threading
import time
import traceback

from storyforge.config import Settings, get_settings
from storyforge.jobs.store import JobStore

log = logging.getLogger("storyforge.jobs")

DEFAULT_LANES = {"story": 1, "render": 1, "preview": 1}


class JobContext:
    def __init__(self, manager: JobManager, job: dict):
        self.manager = manager
        self.job = job
        self.cancel_event = threading.Event()
        self._last_write = 0.0
        self._eta: float | None = None
        self._started = time.time()
        self._scale = (0.0, 1.0)

    def log(self, line: str) -> None:
        self.manager.store.append_log(self.job["id"], line)

    def sub_progress(self, lo: float, hi: float) -> None:
        """Map the next progress reports into [lo, hi] (multi-part jobs)."""
        self._scale = (lo, hi)

    def progress(self, fraction: float, message: str = "") -> None:
        lo, hi = self._scale
        frac = max(0.0, min(1.0, lo + (hi - lo) * max(0.0, min(1.0, fraction))))
        now = time.time()
        elapsed = now - self._started
        if frac > 0.02 and elapsed > 3:
            eta = elapsed * (1.0 - frac) / frac
            self._eta = eta if self._eta is None else 0.7 * self._eta + 0.3 * eta
        if now - self._last_write >= 0.5 or frac >= 1.0:
            self._last_write = now
            self.manager.store.update(self.job["id"], progress=round(frac, 4), message=message[:300],
                                      eta_seconds=round(self._eta, 1) if self._eta is not None else None)

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            from storyforge.util.proc import Cancelled

            raise Cancelled("job cancelled")


class JobManager:
    def __init__(self, settings: Settings | None = None, store: JobStore | None = None,
                 lanes: dict[str, int] | None = None):
        self.settings = settings or get_settings()
        self.store = store or JobStore(self.settings.data_dir / "jobs")
        self.lanes = dict(lanes or DEFAULT_LANES)
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._wake = threading.Condition()
        self._held: dict[str, str] = {}  # lock -> job id
        self._running: dict[str, JobContext] = {}
        self._mutex = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        n = self.store.mark_interrupted()
        if n:
            log.warning("%d job(s) were interrupted by a restart; retry them from the render queue", n)
        for lane, count in self.lanes.items():
            for i in range(max(1, count)):
                t = threading.Thread(target=self._loop, args=(lane,), name=f"sf-{lane}-{i}", daemon=True)
                t.start()
                self._threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._mutex:
            for jc in self._running.values():
                jc.cancel_event.set()
        with self._wake:
            self._wake.notify_all()
        for t in self._threads:
            t.join(timeout)

    # ------------------------------------------------------------------ API
    def submit(self, kind: str, params: dict) -> dict:
        from storyforge.jobs.handlers import HANDLERS

        if kind not in HANDLERS:
            raise ValueError(f"unknown job kind '{kind}'")
        h = HANDLERS[kind]
        params = h.normalize(params)
        job = self.store.create(kind, h.lane(params), params, title=h.title(params), series=params.get("series"),
                                episode=params.get("episode"), locks=h.locks(params))
        self.store.append_log(job["id"], f"queued {kind}: {job['title']}")
        with self._wake:
            self._wake.notify_all()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if not job:
            return False
        if job["status"] == "queued":
            self.store.update(job_id, status="cancelled", finished_at=time.time(), message="cancelled before start")
            return True
        with self._mutex:
            jc = self._running.get(job_id)
        if jc:
            jc.cancel_event.set()
            self.store.append_log(job_id, "cancel requested")
            return True
        return False

    def retry(self, job_id: str) -> dict:
        job = self.store.get(job_id)
        if not job:
            raise KeyError(job_id)
        return self.submit(job["kind"], job["params"])

    def running(self) -> list[str]:
        with self._mutex:
            return list(self._running)

    # ------------------------------------------------------------------ worker loop
    def _loop(self, lane: str) -> None:
        while not self._stop.is_set():
            with self._mutex:
                held = set(self._held)
            job = self.store.claim(lane, held)
            if job is None:
                with self._wake:
                    self._wake.wait(timeout=1.0)
                continue
            with self._mutex:
                conflict = bool(set(job["locks"]) & set(self._held))
                if not conflict:
                    for lk in job["locks"]:
                        self._held[lk] = job["id"]
                    jc = JobContext(self, job)
                    self._running[job["id"]] = jc
            if conflict:  # lost a race with another lane: put it back and wait a moment
                self.store.update(job["id"], status="queued", started_at=None, message="")
                self._stop.wait(0.5)
                continue
            try:
                self._execute(jc)
            finally:
                with self._mutex:
                    for lk in job["locks"]:
                        self._held.pop(lk, None)
                    self._running.pop(job["id"], None)
                with self._wake:
                    self._wake.notify_all()

    def _execute(self, jc: JobContext) -> None:
        from storyforge.jobs.handlers import HANDLERS
        from storyforge.util.proc import Cancelled

        job = jc.job
        jc.log(f"started on lane '{job['lane']}'")
        t0 = time.time()
        try:
            result = HANDLERS[job["kind"]].run(jc, job["params"], self.settings)
        except Cancelled:
            jc.log("cancelled")
            self.store.update(job["id"], status="cancelled", finished_at=time.time(), message="cancelled",
                              eta_seconds=None)
            return
        except Exception as exc:  # report every failure to the UI with its traceback in the log
            jc.log("FAILED: " + str(exc))
            jc.log(traceback.format_exc())
            msg = str(exc).strip().splitlines()[0][:300] if str(exc).strip() else exc.__class__.__name__
            self.store.update(job["id"], status="failed", finished_at=time.time(), error=str(exc)[:4000],
                              message=msg, eta_seconds=None)
            return
        jc.log(f"done in {time.time() - t0:.1f}s")
        self.store.update(job["id"], status="done", finished_at=time.time(), progress=1.0, result=result,
                          message="done", eta_seconds=0)


_MANAGER: JobManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager(start: bool = True) -> JobManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = JobManager()
            if start:
                _MANAGER.start()
        return _MANAGER


def reset_manager() -> None:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER.stop()
        _MANAGER = None
