"""Batch AI job engine.

A job applies one prompt template to many inputs (files in a folder, lines of
a text file, rows of a CSV, or an inline list), runs them in parallel against
any model, retries failures, survives reboots (it resumes where it stopped),
and writes every result to disk.

Job file (JSON), e.g. ~/AIJobs/examples/summarise-docs.job.json:
    {
      "name": "Summarise documents",
      "model": "ollama/qwen2.5:0.5b",
      "system": "You are a concise analyst.",
      "prompt": "Summarise {name} in 3 bullet points:\\n\\n{input}",
      "inputs": {"type": "folder", "path": "inputs/docs", "glob": "*.txt"},
      "concurrency": 2,
      "retries": 2,
      "temperature": 0.2,
      "max_tokens": 512,
      "output": "markdown"            # or "text"; results.jsonl + results.csv always
    }

Placeholders: {input} {name} {index} and, for CSV, every column by name.
Relative paths are resolved from the job file's folder.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .providers import AIError

QUEUED, RUNNING, PAUSED, DONE, FAILED, CANCELLED = (
    "queued", "running", "paused", "done", "failed", "cancelled")


def slug(s):
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:40] or "job"


def load_items(spec: dict, base: Path) -> list[dict]:
    """Expand a job's input source into a list of {name, input, vars}."""
    src = spec.get("inputs") or {}
    kind = src.get("type", "list")

    def path(p):
        q = Path(p).expanduser()
        return q if q.is_absolute() else (base / q)

    items = []
    if kind == "folder":
        folder = path(src["path"])
        pat = src.get("glob", "*")
        for f in sorted(folder.rglob(pat) if src.get("recursive") else folder.glob(pat)):
            if f.is_file():
                items.append({"name": f.name, "input": f.read_text(errors="replace")})
    elif kind == "lines":
        for i, ln in enumerate(path(src["path"]).read_text(errors="replace").splitlines(), 1):
            if ln.strip():
                items.append({"name": f"line-{i}", "input": ln.strip()})
    elif kind == "csv":
        text = path(src["path"]).read_text(errors="replace")
        col = src.get("column")
        for i, row in enumerate(csv.DictReader(io.StringIO(text)), 1):
            key = row.get(src.get("id_column", ""), "") or f"row-{i}"
            items.append({"name": str(key), "input": row.get(col, "") if col else json.dumps(row),
                          "vars": row})
    elif kind == "list":
        for i, v in enumerate(src.get("items", []), 1):
            items.append({"name": f"item-{i}", "input": str(v)})
    else:
        raise ValueError(f"unknown input type '{kind}'")
    seen = {}
    for i, it in enumerate(items, 1):             # make names unique
        it["index"] = i
        n = it["name"]
        if n in seen:
            seen[n] += 1
            it["name"] = f"{n}-{seen[n]}"
        else:
            seen[n] = 1
    return items


def render(template: str, item: dict) -> str:
    """Fill {input} {name} {index} and CSV {column} placeholders.
    Any other braces (e.g. JSON examples in the prompt) are left untouched."""
    vals = {**(item.get("vars") or {}), "input": item["input"], "name": item["name"],
            "index": str(item["index"])}
    return re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), template)


class Job:
    def __init__(self, run_dir: Path, spec: dict, state: dict | None = None):
        self.dir = run_dir
        self.spec = spec
        self.state = state or {"id": run_dir.name, "status": QUEUED, "created": time.time(),
                               "total": 0, "done": 0, "failed": 0, "tokens": 0,
                               "seconds": 0.0, "error": ""}
        self.lock = threading.Lock()
        self.pause_ev = threading.Event()
        self.cancel_ev = threading.Event()
        self.thread = None
        self.active = set()        # item names in flight
        self.recent = []           # last few (name, preview) for the UI
        self.started_at = None
        self._done_at_start = 0
        self.external = False

    # ---- properties
    @property
    def id(self): return self.state["id"]
    @property
    def name(self): return self.spec.get("name", self.id)
    @property
    def status(self): return self.state["status"]

    @property
    def progress(self):
        t = self.state["total"]
        return (self.state["done"] + self.state["failed"]) / t if t else 0.0

    def eta(self):
        if not self.started_at or self.status != RUNNING:
            return None
        finished = self.state["done"] + self.state["failed"] - self._done_at_start
        if finished <= 0:
            return None
        rate = finished / (time.time() - self.started_at)
        return (self.state["total"] - self.state["done"] - self.state["failed"]) / rate

    def save_state(self):
        with self.lock:
            (self.dir / "state.json").write_text(json.dumps(self.state, indent=2))

    def done_names(self):
        names = set()
        f = self.dir / "results.jsonl"
        if f.exists():
            for ln in f.read_text().splitlines():
                try:
                    r = json.loads(ln)
                    if not r.get("error"):
                        names.add(r["name"])
                except ValueError:
                    pass
        return names


class JobManager:
    """Keeps a queue of jobs and runs `max_parallel` of them at a time."""

    def __init__(self, home: Path, ai, max_parallel=1, on_event=None, autostart=True):
        self.autostart = autostart
        self.root = Path(home) / "AIJobs" / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.ai = ai
        self.max_parallel = max_parallel
        self.on_event = on_event or (lambda msg: None)
        self.jobs: list[Job] = []
        self._lock = threading.Lock()
        self.rescan(first=True)

    @staticmethod
    def _owner_alive(d: Path):
        try:
            pid = int((d / "owner.pid").read_text())
        except (OSError, ValueError):
            return False
        if pid == os.getpid():
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def rescan(self, first=False):
        """Pick up jobs added by `sourabh-ai submit` and refresh jobs run by other processes."""
        known = {j.dir: j for j in self.jobs}
        for d in sorted(self.root.iterdir()):
            job = known.get(d)
            if job is not None:
                if job.external:
                    try:
                        job.state = json.loads((d / "state.json").read_text())
                    except (OSError, ValueError):
                        pass
                    job.external = self._owner_alive(d) and job.status == RUNNING
                continue
            try:
                spec = json.loads((d / "job.json").read_text())
                state = json.loads((d / "state.json").read_text())
            except (OSError, ValueError):
                continue
            job = Job(d, spec, state)
            if job.status == RUNNING:
                if self._owner_alive(d):
                    job.external = True       # another process (CLI) is running it
                else:
                    job.state["status"] = QUEUED   # interrupted by reboot/crash: resume
            with self._lock:
                self.jobs.append(job)
        self.schedule()

    # ---- public API
    def submit(self, spec: dict, base: Path | None = None) -> Job:
        """Validate a job spec, snapshot its inputs and queue it."""
        base = Path(base or Path.cwd())
        for key in ("prompt", "inputs"):
            if key not in spec:
                raise ValueError(f"job needs '{key}'")
        items = load_items(spec, base)
        if not items:
            raise ValueError("job has no inputs (empty folder/file?)")
        spec = {**spec, "model": spec.get("model") or self.ai.settings["default_model"]}
        jid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        d = self.root / f"{jid}-{slug(spec.get('name', 'job'))}"
        d.mkdir(parents=True)
        (d / "job.json").write_text(json.dumps(spec, indent=2))
        (d / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
        job = Job(d, spec)
        job.state["id"] = d.name
        job.state["total"] = len(items)
        job.save_state()
        with self._lock:
            self.jobs.append(job)
        self.on_event(f"[ai] queued job '{job.name}' ({len(items)} items, {spec['model']})")
        self.schedule()
        return job

    def submit_file(self, path) -> Job:
        path = Path(path).expanduser().resolve()
        return self.submit(json.loads(path.read_text()), base=path.parent)

    def pause(self, job):
        if job.status in (RUNNING, QUEUED):
            job.pause_ev.set()
            job.state["status"] = PAUSED
            job.save_state()
        self.schedule()

    def resume(self, job):
        if job.status in (PAUSED, FAILED, CANCELLED) or (job.status == DONE and job.state["failed"]):
            job.pause_ev.clear()
            job.cancel_ev.clear()
            job.state["status"] = QUEUED
            job.state["error"] = ""
            job.save_state()
            self.schedule()

    def cancel(self, job):
        job.cancel_ev.set()
        if job.status in (QUEUED, PAUSED, RUNNING):
            job.state["status"] = CANCELLED
            job.save_state()
        self.schedule()

    def remove(self, job):
        self.cancel(job)
        with self._lock:
            if job in self.jobs:
                self.jobs.remove(job)
        import shutil
        shutil.rmtree(job.dir, ignore_errors=True)

    def find(self, key):
        for j in self.jobs:
            if j.id == key or j.id.startswith(key) or j.name == key:
                return j
        return None

    def running(self):
        return [j for j in self.jobs if j.thread and j.thread.is_alive()]

    def start_now(self, job):
        """Run one job immediately in this process, ignoring the queue."""
        job.state["status"] = RUNNING
        job.thread = threading.Thread(target=self._run, args=(job,), daemon=True, name=f"job-{job.id}")
        job.thread.start()

    def schedule(self):
        if not self.autostart:
            return
        with self._lock:
            busy = len([j for j in self.jobs if j.thread and j.thread.is_alive()])
            for j in self.jobs:
                if busy >= self.max_parallel:
                    break
                if j.status == QUEUED and not j.external and not (j.thread and j.thread.is_alive()):
                    j.state["status"] = RUNNING
                    j.thread = threading.Thread(target=self._run, args=(j,), daemon=True, name=f"job-{j.id}")
                    j.thread.start()
                    busy += 1

    # ---- worker
    def _run(self, job: Job):
        spec = job.spec
        try:
            items = [json.loads(l) for l in (job.dir / "items.jsonl").read_text().splitlines() if l.strip()]
        except (OSError, ValueError) as e:
            job.state.update(status=FAILED, error=str(e))
            job.save_state()
            return
        done = job.done_names()
        pending = [i for i in items if i["name"] not in done]
        job.state["done"] = len(done)
        job.state["failed"] = 0
        job.state["total"] = len(items)
        job._done_at_start = len(done)
        job.started_at = time.time()
        job.save_state()
        (job.dir / "owner.pid").write_text(str(os.getpid()))
        out_dir = job.dir / "outputs"
        out_dir.mkdir(exist_ok=True)
        results = (job.dir / "results.jsonl").open("a")
        wlock = threading.Lock()
        self.on_event(f"[ai] job '{job.name}' started: {len(pending)} to do, {len(done)} already done")

        def work(item):
            if job.cancel_ev.is_set() or job.pause_ev.is_set():
                return
            with job.lock:
                job.active.add(item["name"])
            prompt = render(spec["prompt"], item)
            msgs = []
            if spec.get("system"):
                msgs.append({"role": "system", "content": spec["system"]})
            msgs.append({"role": "user", "content": prompt})
            err, res = "", None
            for attempt in range(int(spec.get("retries", 2)) + 1):
                try:
                    res = self.ai.chat(spec["model"], msgs, stop=job.cancel_ev,
                                       temperature=spec.get("temperature"),
                                       max_tokens=int(spec.get("max_tokens", 1024)))
                    err = ""
                    break
                except (AIError, OSError, ValueError) as e:
                    err = str(e)
                    if job.cancel_ev.is_set():
                        break
                    time.sleep(min(30, 2 ** attempt))
            rec = {"name": item["name"], "index": item["index"], "model": spec["model"],
                   "output": res["text"] if res else "", "tokens": res["tokens"] if res else 0,
                   "seconds": round(res["seconds"], 2) if res else 0, "error": err,
                   "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
            if job.cancel_ev.is_set() and not res:
                with job.lock:
                    job.active.discard(item["name"])
                return
            with wlock:
                results.write(json.dumps(rec, ensure_ascii=False) + "\n")
                results.flush()
                if not err:
                    ext = ".md" if spec.get("output", "markdown") == "markdown" else ".txt"
                    stem = slug(Path(item["name"]).stem) or f"item-{item['index']}"
                    (out_dir / f"{item['index']:04d}-{stem}{ext}").write_text(
                        (f"# {item['name']}\n\n" if ext == ".md" else "") + rec["output"].strip() + "\n")
            with job.lock:
                job.active.discard(item["name"])
                if err:
                    job.state["failed"] += 1
                    job.state["error"] = err
                else:
                    job.state["done"] += 1
                    job.state["tokens"] += rec["tokens"]
                    job.state["seconds"] += rec["seconds"]
                    job.recent = (job.recent + [(item["name"], rec["output"].strip()[:160])])[-5:]
            job.save_state()

        try:
            with ThreadPoolExecutor(max_workers=max(1, int(spec.get("concurrency", 2)))) as pool:
                list(pool.map(work, pending))
        finally:
            results.close()
        remaining = job.state["total"] - job.state["done"] - job.state["failed"]
        if job.cancel_ev.is_set():
            job.state["status"] = CANCELLED
        elif remaining > 0:   # stopped early: paused, or resumed while winding down
            job.state["status"] = PAUSED if job.pause_ev.is_set() else QUEUED
        elif job.state["done"] == 0 and job.state["failed"]:
            job.state["status"] = FAILED
        else:
            job.state["status"] = DONE
            self._write_csv(job)
        job.state["finished"] = time.time()
        job.save_state()
        try:
            (job.dir / "owner.pid").unlink()
        except OSError:
            pass
        if job.status in (DONE, FAILED, CANCELLED):
            self.on_event(f"[ai] job '{job.name}' {job.status}: {job.state['done']} ok, {job.state['failed']} failed")
        self.schedule()

    @staticmethod
    def _write_csv(job):
        rows = {}
        for ln in (job.dir / "results.jsonl").read_text().splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r["name"] not in rows or not r.get("error"):
                rows[r["name"]] = r
        with (job.dir / "results.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["index", "name", "output", "tokens", "seconds", "error"])
            for r in sorted(rows.values(), key=lambda r: r["index"]):
                w.writerow([r["index"], r["name"], r["output"], r["tokens"], r["seconds"], r["error"]])
