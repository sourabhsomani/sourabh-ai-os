"""AI Jobs: run one prompt over many inputs, in parallel, with a queue."""
import json
import time
from pathlib import Path

import pygame

from ...ai.jobs import load_items
from ..theme import C, rrect, text, wrap, lighten, blend
from ..ui import App, Form, LineEdit

STATUS_COL = {"queued": "dim", "running": "accent", "paused": "warn", "done": "ok",
              "failed": "danger", "cancelled": "dim"}
INPUT_TYPES = ["folder", "lines", "csv"]


def _dur(sec):
    if sec is None:
        return "–"
    sec = int(sec)
    return f"{sec // 3600}h {sec // 60 % 60}m" if sec >= 3600 else f"{sec // 60}m {sec % 60}s"


class AIJobs(App):
    title = "AI Jobs"
    icon = "jobs"
    size = (960, 600)
    min_size = (700, 440)
    single = True

    def __init__(self, desk, **kw):
        super().__init__(desk, **kw)
        self.sel = None
        self.mode = None            # None | "new" | "files"
        self.form = None
        self.input_type = 0
        self.concurrency = 2
        self.model_idx = 0

    @property
    def jm(self):
        return self.sys.jobs

    # ---------------- actions
    def open_new(self):
        home = self.sys.home
        self.form = Form([
            ("name", "Job name", LineEdit("My batch job", mono=False)),
            ("path", "Input path", LineEdit(str(home / "AIJobs" / "inputs"), mono=False)),
            ("extra", "Glob / CSV column", LineEdit("*.txt", mono=False)),
            ("prompt", "Prompt template", LineEdit("Summarise {name} in 3 bullet points:\\n\\n{input}", mono=False)),
            ("system", "System prompt", LineEdit("You are a precise assistant.", mono=False)),
        ])
        models = [r for r, _ in self.sys.ai_status["models"]] or [self.sys.ai.settings["default_model"]]
        d = self.sys.ai.settings["default_model"]
        self.model_idx = models.index(d) if d in models else 0
        self.mode = "new"

    def _models(self):
        return [r for r, _ in self.sys.ai_status["models"]] or [self.sys.ai.settings["default_model"]]

    def create(self):
        v = self.form.values()
        kind = INPUT_TYPES[self.input_type]
        inputs = {"type": kind, "path": v["path"]}
        if kind == "folder":
            inputs["glob"] = v["extra"] or "*"
        elif kind == "csv" and v["extra"] and v["extra"] != "*.txt":
            inputs["column"] = v["extra"]
        spec = {"name": v["name"] or "Batch job", "model": self._models()[self.model_idx % len(self._models())],
                "system": v["system"], "prompt": v["prompt"].replace("\\n", "\n"), "inputs": inputs,
                "concurrency": self.concurrency, "retries": 2}
        try:
            job = self.jm.submit(spec, base=self.sys.home)
        except (ValueError, OSError, KeyError) as e:
            self.desk.toast(f"Can't start job: {e}")
            return
        # also save the spec so it can be re-run from a terminal
        out = self.sys.home / "AIJobs" / f"{job.dir.name.split('-', 3)[-1]}.job.json"
        out.write_text(json.dumps(spec, indent=2))
        self.sel = job.id
        self.mode = None

    def run_file(self, path):
        try:
            job = self.jm.submit_file(path)
            self.sel = job.id
        except (ValueError, OSError, KeyError) as e:
            self.desk.toast(f"Can't start job: {e}")
        self.mode = None

    def selected(self):
        return next((j for j in self.jm.jobs if j.id == self.sel), None)

    def open_results(self, job):
        self.desk.open_by_name("Files", path=job.dir / "outputs" if (job.dir / "outputs").exists() else job.dir)

    # ---------------- input
    def on_text(self, s):
        if self.mode == "new":
            self.form.on_text(s)

    def on_key(self, ev):
        if self.mode and ev.key == pygame.K_ESCAPE:
            self.mode = None
        elif self.mode == "new":
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.create()
            else:
                self.form.on_key(ev)

    # ---------------- drawing
    def draw(self, s):
        W, H = s.get_size()
        pygame.draw.rect(s, C["panel"], (0, 0, W, 46))
        x = self.btn(s, (10, 8, 96, 30), "+ New job", self.open_new, "accent").right + 6
        x = self.btn(s, (x, 8, 120, 30), "Run job file…", lambda: setattr(self, "mode", "files")).right + 14
        job = self.selected()
        if job:
            if job.status in ("running", "queued"):
                x = self.btn(s, (x, 8, 70, 30), "Pause", lambda: self.jm.pause(job)).right + 6
            elif job.status in ("paused", "failed", "cancelled") or (job.status == "done" and job.state["failed"]):
                label = "Retry failed" if job.status == "done" else "Resume"
                x = self.btn(s, (x, 8, 100, 30), label, lambda: self.jm.resume(job)).right + 6
            if job.status in ("running", "queued", "paused"):
                x = self.btn(s, (x, 8, 70, 30), "Cancel", lambda: self.jm.cancel(job), "danger").right + 6
            x = self.btn(s, (x, 8, 70, 30), "Results", lambda: self.open_results(job)).right + 6
            if job.status not in ("running",):
                self.btn(s, (x, 8, 70, 30), "Delete", lambda: (self.jm.remove(job), setattr(self, "sel", None)))
        running = len(self.jm.running())
        text(s, f"{running} running · {sum(1 for j in self.jm.jobs if j.status == 'queued')} queued",
             (W - 12, 23), C["dim"], "sans", 12, "midright")

        # job list
        lst = pygame.Rect(10, 56, int(W * .42), H - 66)
        rrect(s, C["panel"], lst, 8)
        text(s, "Jobs", (lst.x + 12, lst.y + 8), C["text"], "bold", 13)
        y = lst.y + 32
        jobs = sorted(self.jm.jobs, key=lambda j: j.state.get("created", 0), reverse=True)
        if self.sel is None and jobs:
            self.sel = jobs[0].id
        for j in jobs:
            if y + 50 > lst.bottom:
                break
            r = pygame.Rect(lst.x + 6, y, lst.w - 12, 50)
            if j.id == self.sel:
                rrect(s, lighten(C["panel"], 16), r, 6)
            self._hits.append((r, lambda j=j: setattr(self, "sel", j.id)))
            col = C[STATUS_COL[j.status]]
            text(s, j.name, (r.x + 10, r.y + 6), C["text"], "bold", 13, maxw=r.w - 110)
            text(s, j.status, (r.right - 10, r.y + 6), col, "sans", 12, "topright")
            st = j.state
            bar = pygame.Rect(r.x + 10, r.y + 28, r.w - 110, 6)
            rrect(s, C["field"], bar, 3)
            if st["total"]:
                rrect(s, col, (bar.x, bar.y, max(4, int(bar.w * j.progress)), bar.h), 3)
            text(s, f"{st['done'] + st['failed']}/{st['total']}", (r.right - 10, r.y + 26), C["dim"], "mono", 11, "topright")
            y += 54
        if not jobs:
            for i, ln in enumerate(["No jobs yet.", "", "Click 'Run job file…' to try an", "example, or '+ New job' to",
                                    "process your own files."]):
                text(s, ln, (lst.x + 14, lst.y + 40 + i * 20), C["dim"], "sans", 13)

        # detail
        det = pygame.Rect(lst.right + 10, 56, W - lst.right - 20, H - 66)
        rrect(s, C["panel"], det, 8)
        if job:
            self._detail(s, det, job)

        if self.mode == "files":
            self._draw_files(s)
        elif self.mode == "new":
            self._draw_new(s)

    def _detail(self, s, r, job):
        st = job.state
        text(s, job.name, (r.x + 14, r.y + 12), C["text"], "bold", 16, maxw=r.w - 28)
        text(s, f"{job.spec.get('model')} · {job.spec.get('inputs', {}).get('type')} · "
                f"{job.spec.get('concurrency', 2)} workers", (r.x + 14, r.y + 38), C["dim"], "sans", 12, maxw=r.w - 28)
        # stats tiles
        tps = st["tokens"] / st["seconds"] if st["seconds"] else 0
        tiles = [("Done", f"{st['done']}/{st['total']}"), ("Failed", str(st["failed"])),
                 ("Tokens", f"{st['tokens']:,}"), ("ETA", _dur(job.eta()) if job.status == "running" else job.status)]
        tw = (r.w - 28 - 30) // 4
        for i, (k, v) in enumerate(tiles):
            t = pygame.Rect(r.x + 14 + i * (tw + 10), r.y + 64, tw, 56)
            rrect(s, C["field"], t, 8)
            text(s, k, (t.x + 10, t.y + 8), C["dim"], "sans", 11)
            text(s, v, (t.x + 10, t.y + 26), C["danger"] if k == "Failed" and st["failed"] else C["text"],
                 "bold", 16, maxw=t.w - 16)
        bar = pygame.Rect(r.x + 14, r.y + 132, r.w - 28, 8)
        rrect(s, C["field"], bar, 4)
        rrect(s, C[STATUS_COL[job.status]], (bar.x, bar.y, max(6, int(bar.w * job.progress)), bar.h), 4)
        y = bar.bottom + 12
        if tps:
            text(s, f"average {tps / max(1, job.spec.get('concurrency', 1)):.1f} tok/s per worker", (r.x + 14, y), C["dim"], "sans", 11)
            y += 18
        text(s, "Prompt", (r.x + 14, y), C["text"], "bold", 12)
        y += 20
        for ln in wrap(job.spec.get("prompt", ""), r.w - 40, "mono", 12)[:4]:
            text(s, ln, (r.x + 20, y), C["dim"], "mono", 12)
            y += 17
        y += 8
        if job.active:
            text(s, "Working on: " + ", ".join(sorted(job.active))[:120], (r.x + 14, y), C["accent"], "sans", 12, maxw=r.w - 28)
            y += 22
        if st.get("error"):
            text(s, "Last error: " + st["error"], (r.x + 14, y), C["danger"], "sans", 12, maxw=r.w - 28)
            y += 22
        recent = job.recent or self._recent_from_disk(job)
        if recent:
            text(s, "Latest results", (r.x + 14, y), C["text"], "bold", 12)
            y += 22
            for name, prev in reversed(recent):
                if y + 40 > r.bottom:
                    break
                box = pygame.Rect(r.x + 14, y, r.w - 28, 40)
                rrect(s, C["field"], box, 6)
                text(s, name, (box.x + 8, box.y + 4), C["accent"], "sans", 11, maxw=box.w - 16)
                text(s, prev.replace("\n", " "), (box.x + 8, box.y + 20), C["text"], "sans", 12, maxw=box.w - 16)
                y += 46
        text(s, str(job.dir), (r.x + 14, r.bottom - 20), C["dim"], "mono", 10, maxw=r.w - 28)

    def _recent_from_disk(self, job):
        f = job.dir / "results.jsonl"
        if not f.exists():
            return []
        cache = getattr(job, "_disk_recent", None)
        if cache and cache[0] == f.stat().st_mtime:
            return cache[1]
        out = []
        for ln in f.read_text().splitlines()[-5:]:
            try:
                rec = json.loads(ln)
                out.append((rec["name"], rec["output"].strip()[:160] or rec.get("error", "")))
            except (ValueError, KeyError):
                pass
        job._disk_recent = (f.stat().st_mtime, out)
        return out

    def _overlay(self, s, w, h, title):
        W, H = s.get_size()
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 130))
        s.blit(shade, (0, 0))
        d = pygame.Rect(0, 0, min(w, W - 20), min(h, H - 20))
        d.center = (W // 2, H // 2)
        rrect(s, C["title_active"], d, 10)
        rrect(s, C["accent"], d, 10, 1)
        text(s, title, (d.x + 18, d.y + 14), C["text"], "bold", 15)
        self.btn(s, (d.right - 40, d.y + 10, 28, 26), "✕", lambda: setattr(self, "mode", None), "flat")
        return d

    def _describe(self, f):
        """(name, '12 items · model') for a job file, cached by modification time."""
        cache = self.__dict__.setdefault("_fcache", {})
        key = (f, f.stat().st_mtime)
        if key not in cache:
            try:
                spec = json.loads(f.read_text())
                n = len(load_items(spec, f.parent))
                cache[key] = (spec.get("name", f.stem), f"{n} items · {spec.get('model', 'default model')}")
            except (ValueError, OSError, KeyError) as e:
                cache[key] = (f.stem, f"invalid: {e}")
        return cache[key]

    def _count_inputs(self, spec):
        """Count items for the New-job preview at most twice a second."""
        key = json.dumps(spec, sort_keys=True)
        c = self.__dict__.get("_ccache")
        if c and c[0] == key and time.time() - c[1] < 0.5:
            return c[2]
        try:
            n = len(load_items(spec, self.sys.home))
            res = (f"{n} items found", C["ok"] if n else C["warn"])
        except (OSError, ValueError, KeyError) as e:
            res = (f"input not readable yet: {e}", C["warn"])
        self._ccache = (key, time.time(), res)
        return res

    def _draw_files(self, s):
        roots = [self.sys.home / "AIJobs" / "examples", self.sys.home / "AIJobs"]
        files = []
        for r in roots:
            files += sorted(r.glob("*.job.json")) if r.exists() else []
        d = self._overlay(s, 520, 120 + 40 * max(1, len(files)), "Run a job file")
        y = d.y + 50
        for f in files:
            name, info = self._describe(f)
            r = pygame.Rect(d.x + 16, y, d.w - 32, 34)
            self.btn(s, r, name, lambda f=f: self.run_file(f), "flat", icon_kind="jobs")
            text(s, info, (r.right - 10, r.centery), C["dim"], "sans", 11, "midright")
            y += 40
        if not files:
            text(s, "No *.job.json files in ~/SourabhHome/AIJobs", (d.x + 18, y), C["dim"])
        text(s, "Tip: from a terminal, run 'sourabh-ai submit my.job.json' to queue jobs here.",
             (d.x + 18, d.bottom - 26), C["dim"], "sans", 11, maxw=d.w - 36)

    def _draw_new(self, s):
        d = self._overlay(s, 680, 440, "New batch job")
        y = self.form.draw(self, s, d.x + 18, d.y + 50, d.w - 36, label_w=150)
        models = self._models()
        m = models[self.model_idx % len(models)]
        text(s, "Model", (d.x + 18, y + 9), C["dim"], "sans", 13)
        self.btn(s, (d.x + 168, y, d.w - 186, 32), "▸  " + m,
                 lambda: setattr(self, "model_idx", self.model_idx + 1))
        y += 40
        text(s, "Input type", (d.x + 18, y + 9), C["dim"], "sans", 13)
        for i, t in enumerate(INPUT_TYPES):
            self.btn(s, (d.x + 168 + i * 96, y, 90, 32), t,
                     lambda i=i: setattr(self, "input_type", i), "accent" if i == self.input_type else "normal")
        text(s, "Workers", (d.x + 476, y + 9), C["dim"], "sans", 13)
        self.btn(s, (d.x + 540, y, 30, 32), "−", lambda: setattr(self, "concurrency", max(1, self.concurrency - 1)))
        text(s, str(self.concurrency), (d.x + 590, y + 16), C["text"], "bold", 14, "center")
        self.btn(s, (d.x + 610, y, 30, 32), "+", lambda: setattr(self, "concurrency", min(32, self.concurrency + 1)))
        y += 44
        hint = {"folder": "Each file in the folder matching the glob is one item.",
                "lines": "Each non-empty line of the file is one item.",
                "csv": "Each row is one item; set the CSV column to send. Columns are usable as {name}."}[INPUT_TYPES[self.input_type]]
        text(s, hint + "  Placeholders: {input} {name} {index}", (d.x + 18, y), C["dim"], "sans", 12, maxw=d.w - 36)
        spec = {"inputs": {"type": INPUT_TYPES[self.input_type], "path": self.form["path"].text,
                           "glob": self.form["extra"].text or "*", "column": self.form["extra"].text}}
        preview, col = self._count_inputs(spec)
        text(s, preview, (d.x + 18, y + 22), col, "sans", 12, maxw=d.w - 200)
        self.btn(s, (d.right - 150, d.bottom - 48, 132, 34), "Start job", self.create, "accent")
