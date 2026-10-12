from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager

from app.config import SystemSettings

TERMINAL_PHASES = {"succeeded", "failed", "submission_unknown", "download_failed", "interrupted"}


class CooldownError(ValueError):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"提交过于频繁，请等待 {retry_after} 秒后再试")


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL, state TEXT)")
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created DESC, id DESC)")
            conn.execute("CREATE TABLE IF NOT EXISTS system_settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT)")
            conn.execute("INSERT OR IGNORE INTO system_settings VALUES (1, ?)",
                         (SystemSettings().model_dump_json(),))
            conn.execute("CREATE TABLE IF NOT EXISTS client_submissions (id TEXT PRIMARY KEY, submitted REAL)")
            # Old unknown submissions may already exist on the platform; count them conservatively.
            conn.execute("UPDATE jobs SET state=json_set(state, '$.slot_reserved', json('true')) "
                         "WHERE json_extract(state, '$.phase')='submission_unknown'")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def system_settings(self) -> SystemSettings:
        with self.connect() as conn:
            return SystemSettings.model_validate_json(
                conn.execute("SELECT value FROM system_settings WHERE id=1").fetchone()[0])

    def save_system_settings(self, value: SystemSettings) -> SystemSettings:
        with self.connect() as conn:
            conn.execute("UPDATE system_settings SET value=? WHERE id=1", (value.model_dump_json(),))
        return value

    def client_status(self, client_id: str) -> dict:
        now = time.time()
        with self.connect() as conn:
            conn.execute("BEGIN")
            cooldown = SystemSettings.model_validate_json(
                conn.execute("SELECT value FROM system_settings WHERE id=1").fetchone()[0]).client_cooldown_seconds
            row = conn.execute("SELECT submitted FROM client_submissions WHERE id=?", (client_id,)).fetchone()
        next_submit = row[0] + cooldown if row else 0
        return {"retry_after": max(0, math.ceil(next_submit - now)),
                "next_submit_at": next_submit, "server_time": now, "client_cooldown_seconds": cooldown}

    def create(self, *, prompt: str, duration: int, image_count: int, private: dict,
               client_id: str | None = None) -> dict:
        now = time.time()
        state = {"id": uuid.uuid4().hex, "prompt": prompt, "duration": duration,
                 "image_count": image_count, "created_at": now, "updated_at": now,
                 "phase": "created", "remote_task_id": None, "progress": {}, "video_ready": False,
                 "error": None, "notice": None, "private": private,
                 "queue_position": None, "slot_reserved": False}
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if client_id:
                cooldown = SystemSettings.model_validate_json(conn.execute(
                    "SELECT value FROM system_settings WHERE id=1").fetchone()[0]).client_cooldown_seconds
                row = conn.execute("SELECT submitted FROM client_submissions WHERE id=?", (client_id,)).fetchone()
                if row and (remaining := math.ceil(row[0] + cooldown - now)) > 0:
                    raise CooldownError(remaining)
                conn.execute("INSERT INTO client_submissions VALUES (?, ?) "
                             "ON CONFLICT(id) DO UPDATE SET submitted=excluded.submitted", (client_id, now))
            conn.execute("INSERT INTO jobs VALUES (?, ?, ?)", (state["id"], now, json.dumps(state)))
        return state

    def get(self, job_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, job_id: str, **changes) -> dict:
        if changes.get("phase") == "submission_unknown":
            changes["slot_reserved"] = True
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            state = json.loads(row[0])
            state.update(changes, updated_at=time.time())
            conn.execute("UPDATE jobs SET state=? WHERE id=?", (json.dumps(state), job_id))
        return state

    def list(self, limit: int = 100) -> list[dict]:
        terminal = tuple(sorted(TERMINAL_PHASES))
        placeholders = ",".join("?" for _ in terminal)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT state FROM jobs WHERE json_extract(state, '$.phase') NOT IN ({placeholders}) "
                "OR id IN (SELECT id FROM jobs ORDER BY created DESC LIMIT ?) ORDER BY created DESC",
                (*terminal, limit),
            ).fetchall()
        return [self.public(json.loads(row[0])) for row in rows]

    def recoverable(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT state FROM jobs ORDER BY created, rowid").fetchall()
        return [state for row in rows if (state := json.loads(row[0]))["phase"] not in TERMINAL_PHASES]

    def queue_status(self) -> dict:
        with self.connect() as conn:
            conn.execute("BEGIN")
            reserved = conn.execute("SELECT COUNT(*) FROM jobs WHERE json_extract(state, '$.slot_reserved')=1"
                                    " AND json_extract(state, '$.phase') NOT IN"
                                    " ('succeeded','failed','download_failed','interrupted')").fetchone()[0]
            waiting = conn.execute("SELECT COUNT(*) FROM jobs WHERE json_extract(state, '$.phase')='waiting'").fetchone()[0]
            unknown = conn.execute("SELECT COUNT(*) FROM jobs WHERE json_extract(state, '$.slot_reserved')=1"
                                   " AND json_extract(state, '$.phase')='submission_unknown'").fetchone()[0]
        return {"active": reserved, "waiting": waiting, "unknown": unknown,
                "limit": self.system_settings().max_concurrent_generations}

    def refresh_queue_positions(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT id, state FROM jobs WHERE json_extract(state, '$.phase')='waiting' "
                                "ORDER BY created, rowid").fetchall()
            for position, (job_id, encoded) in enumerate(rows, 1):
                state = json.loads(encoded)
                if state.get("queue_position") != position:
                    state.update(queue_position=position, updated_at=time.time())
                    conn.execute("UPDATE jobs SET state=? WHERE id=?", (json.dumps(state), job_id))

    def history(self, *, page: int = 1, page_size: int = 12, status: str = "all",
                search: str = "", sort: str = "newest") -> dict:
        phase = "json_extract(state, '$.phase')"
        terminal = tuple(sorted(TERMINAL_PHASES))
        markers = ",".join("?" for _ in terminal)
        active = f"{phase} NOT IN ({markers})"
        clauses, params = [], []
        if status == "active":
            clauses.append(active)
            params.extend(terminal)
        elif status == "succeeded":
            clauses.append(f"{phase} = 'succeeded'")
        elif status == "attention":
            clauses.append(f"{phase} IN ({markers}) AND {phase} != 'succeeded'")
            params.extend(terminal)
        if search.strip():
            needle = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(json_extract(state, '$.prompt') LIKE ? ESCAPE '\\' "
                           "OR id LIKE ? ESCAPE '\\' OR json_extract(state, '$.remote_task_id') LIKE ? ESCAPE '\\')")
            params.extend([f"%{needle}%"] * 3)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order_params = []
        order = "created DESC, id DESC"
        if sort == "oldest":
            order = "created ASC, id ASC"
        elif sort == "active":
            order = f"CASE WHEN {active} THEN 0 ELSE 1 END, created DESC, id DESC"
            order_params = list(terminal)
        with self.connect() as conn:
            # Keep counts and page rows in the same read snapshot during live updates.
            conn.execute("BEGIN")
            groups = conn.execute(f"SELECT {phase}, COUNT(*) FROM jobs GROUP BY {phase}").fetchall()
            counts = {"all": 0, "active": 0, "succeeded": 0, "attention": 0}
            for job_phase, count in groups:
                counts["all"] += count
                bucket = ("succeeded" if job_phase == "succeeded" else
                          "attention" if job_phase in TERMINAL_PHASES else "active")
                counts[bucket] += count
            total = conn.execute("SELECT COUNT(*) FROM jobs" + where, params).fetchone()[0]
            page = max(1, min(page, max(1, (total + page_size - 1) // page_size)))
            rows = conn.execute("SELECT state FROM jobs" + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                                (*params, *order_params, page_size, (page - 1) * page_size)).fetchall()
        return {"items": [self.public(json.loads(row[0])) for row in rows], "total": total,
                "page": page, "page_size": page_size, "counts": counts}

    @staticmethod
    def public(state: dict) -> dict:
        keys = ("id", "prompt", "duration", "image_count", "created_at", "updated_at", "phase",
                "remote_task_id", "progress", "video_ready", "error", "notice", "queue_position", "slot_reserved")
        result = {key: state.get(key) for key in keys}
        result["video_url"] = f"/api/jobs/{state['id']}/video" if state.get("video_ready") else None
        return result
