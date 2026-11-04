"""SQLite-backed job store (one file: $STORYFORGE_DATA_DIR/jobs.sqlite3, logs in jobs/<id>.log).

Plain sqlite3 in WAL mode, one short-lived connection per operation, so the API threads and the
worker threads never share a connection. A job row holds its parameters, lane, status, progress,
ETA, result and error; the log is an append-only text file streamed to the UI by byte offset.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

STATUSES = ("queued", "running", "done", "failed", "cancelled", "interrupted")
ACTIVE = ("queued", "running")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    lane TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    series TEXT,
    episode TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    locks TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    eta_seconds REAL,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    result TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, lane, created_at);
CREATE INDEX IF NOT EXISTS jobs_series ON jobs(series, episode, created_at);
"""

_JSON_FIELDS = ("params", "locks", "result")


class JobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        self.db_path = self.root / "jobs.sqlite3"
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k in _JSON_FIELDS:
            if d.get(k) is not None:
                try:
                    d[k] = json.loads(d[k])
                except (TypeError, ValueError):
                    pass
        return d

    def log_path(self, job_id: str) -> Path:
        return self.root / "logs" / f"{job_id}.log"

    # ------------------------------------------------------------------ writes
    def create(self, kind: str, lane: str, params: dict, *, title: str = "", series: str | None = None,
               episode: str | None = None, locks: list[str] | None = None) -> dict:
        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO jobs (id, kind, lane, title, series, episode, params, locks, status, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
                      (job_id, kind, lane, title, series, episode, json.dumps(params), json.dumps(locks or []),
                       time.time()))
        return self.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(f"{k} = ?")
            vals.append(json.dumps(v) if k in _JSON_FIELDS and v is not None else v)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", (*vals, job_id))

    def claim(self, lane: str, held_locks: set[str]) -> dict | None:
        """Atomically mark the oldest runnable queued job of `lane` as running and return it."""
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM jobs WHERE status = 'queued' AND lane = ? ORDER BY created_at",
                             (lane,)).fetchall()
            for row in rows:
                job = self._row(row)
                if set(job["locks"]) & held_locks:
                    continue
                cur = c.execute("UPDATE jobs SET status = 'running', started_at = ?, message = 'starting' "
                                "WHERE id = ? AND status = 'queued'", (time.time(), job["id"]))
                if cur.rowcount == 1:
                    job.update(status="running")
                    return job
        return None

    def mark_interrupted(self) -> int:
        """Jobs left `running` by a previous server process (crash / restart)."""
        with self._lock, self._conn() as c:
            cur = c.execute("UPDATE jobs SET status = 'interrupted', finished_at = ?, "
                            "message = 'interrupted: the server stopped while this job was running' "
                            "WHERE status = 'running'", (time.time(),))
            return cur.rowcount

    def append_log(self, job_id: str, line: str) -> None:
        with open(self.log_path(job_id), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + line.rstrip("\n") + "\n")

    def delete(self, job_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self.log_path(job_id).unlink(missing_ok=True)

    # ------------------------------------------------------------------ reads
    def get(self, job_id: str) -> dict | None:
        with self._conn() as c:
            return self._row(c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def list(self, *, series: str | None = None, episode: str | None = None, status: str | None = None,
             limit: int = 100) -> list[dict]:
        q, args = "SELECT * FROM jobs WHERE 1=1", []
        if series:
            q += " AND series = ?"
            args.append(series)
        if episode:
            q += " AND episode = ?"
            args.append(episode)
        if status:
            wanted = [x for x in status.split(",") if x in STATUSES]
            q += f" AND status IN ({','.join('?' * len(wanted))})" if wanted else " AND 0"
            args += wanted
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        with self._conn() as c:
            return [self._row(r) for r in c.execute(q, args).fetchall()]

    def read_log(self, job_id: str, offset: int = 0, max_bytes: int = 200_000) -> tuple[str, int]:
        p = self.log_path(job_id)
        if not p.is_file():
            return "", offset
        size = p.stat().st_size
        if offset > size:
            offset = 0
        with open(p, "rb") as fh:
            fh.seek(offset)
            data = fh.read(max_bytes)
        return data.decode("utf-8", errors="replace"), offset + len(data)
