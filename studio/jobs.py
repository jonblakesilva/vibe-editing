"""Background jobs with real progress, cancellation and crash recovery.

Each job is persisted as JSON, so the dashboard shows true status even after a
restart. A job that was running when the app stopped is marked 'interrupted' and
can be retried; renders resume from cached sections instead of starting over."""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from . import config, media

JOBS_DIR = config.DATA_HOME / "jobs"


class JobManager:
    def __init__(self, workers: int = 1):
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.cancels: dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        self.specs: dict[str, tuple[Callable, dict]] = {}
        self._recover()

    def _path(self, jid: str) -> Path:
        return JOBS_DIR / f"{jid}.json"

    def _write(self, job: dict) -> None:
        with self.lock:
            p = self._path(job["id"])
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(job, indent=1, default=str), encoding="utf-8")
            tmp.replace(p)

    def get(self, jid: str) -> dict:
        return json.loads(self._path(jid).read_text(encoding="utf-8"))

    def list(self, project: str | None = None, limit: int = 50) -> list[dict]:
        jobs = []
        for p in sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit * 3]:
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if project is None or j.get("project") == project:
                jobs.append(j)
        return jobs[:limit]

    def _recover(self) -> None:
        for p in JOBS_DIR.glob("*.json"):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if j.get("status") in ("running", "queued"):
                j["status"] = "interrupted"
                j["message"] = "The app stopped while this was running. Retry to resume from where it left off."
                self._write(j)

    def submit(self, kind: str, project: str | None, fn: Callable, **kwargs) -> dict:
        jid = f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        job = {"id": jid, "kind": kind, "project": project, "status": "queued", "stage": "", "progress": 0.0,
               "message": "Waiting to start", "created": time.time(), "started": None, "finished": None,
               "result": None, "error": None, "args": {k: v for k, v in kwargs.items() if _jsonable(v)}}
        self._write(job)
        cancel = threading.Event()
        self.cancels[jid] = cancel
        self.specs[jid] = (fn, kwargs)
        self.pool.submit(self._run, job, fn, kwargs, cancel)
        return job

    def retry(self, jid: str) -> dict:
        old = self.get(jid)
        if jid in self.specs:
            fn, kwargs = self.specs[jid]
        else:
            raise ValueError("This job cannot be retried automatically after a restart; start it again.")
        return self.submit(old["kind"], old["project"], fn, **kwargs)

    def cancel(self, jid: str) -> bool:
        ev = self.cancels.get(jid)
        if ev:
            ev.set()
            return True
        return False

    def _run(self, job: dict, fn: Callable, kwargs: dict, cancel: threading.Event) -> None:
        job.update(status="running", started=time.time(), message="Started")
        self._write(job)
        last = [0.0]

        def progress(stage: str, p: float) -> None:
            now = time.time()
            job["stage"], job["progress"] = stage, round(float(p), 4)
            job["message"] = f"{stage} {p * 100:.0f}%"
            if now - last[0] > 0.5 or p >= 1:  # throttle disk writes
                last[0] = now
                self._write(job)

        try:
            result = fn(progress=progress, cancel=cancel, **kwargs)
            job.update(status="done", progress=1.0, message="Finished", result=_safe_result(result))
        except media.Cancelled:
            job.update(status="cancelled", message="Cancelled. Already-rendered sections are kept for next time.")
        except Exception as e:  # report every failure to the dashboard in plain text
            job.update(status="failed", error=config.redact(f"{type(e).__name__}: {e}"),
                       message="Failed - see error", trace=config.redact(traceback.format_exc()[-4000:]))
        finally:
            job["finished"] = time.time()
            self._write(job)
            self.cancels.pop(job["id"], None)


def _jsonable(v) -> bool:
    try:
        json.dumps(v)
        return True
    except TypeError:
        return False


def _safe_result(r):
    try:
        json.dumps(r, default=str)
        return r
    except TypeError:
        return str(r)
