"""Models & Hardware: local models, API providers, and what this machine can run."""
import threading

import pygame

from ...ai import AIError, human
from ..theme import C, rrect, text, lighten
from ..ui import App, Form, LineEdit

SUGGESTED = [("qwen2.5:0.5b", "tiny · fast on any CPU"),
             ("llama3.2:1b", "small · CPU friendly"),
             ("llama3.2:3b", "good quality · 4 GB RAM"),
             ("qwen2.5:7b", "strong · 8 GB RAM / GPU"),
             ("nomic-embed-text", "embeddings for search")]


class Models(App):
    title = "Models"
    icon = "models"
    size = (980, 620)
    min_size = (760, 480)
    single = True

    def __init__(self, desk, **kw):
        super().__init__(desk, **kw)
        self.tab = "models"
        self.pull_edit = LineEdit(mono=False, placeholder="model name, e.g. llama3.2:3b")
        self.pulling = None          # (model, status, done, total)
        self.focus = "pull"
        a = self.sys.ai.settings
        self.form = Form([
            ("ollama_url", "Ollama URL", LineEdit(a["ollama_url"], mono=False)),
            ("anthropic_key", "Anthropic API key", LineEdit(a["anthropic_key"], mono=False, mask=True,
                                                             placeholder="sk-ant-…")),
            ("openai_url", "OpenAI-compatible URL", LineEdit(a["openai_url"], mono=False,
                                                             placeholder="https://api.openai.com/v1  or  http://host:8000/v1")),
            ("openai_key", "OpenAI-compatible key", LineEdit(a["openai_key"], mono=False, mask=True)),
            ("system_prompt", "Default system prompt", LineEdit(a.get("system_prompt", ""), mono=False)),
        ])
        self.sys.refresh_ai()

    # ---------------- actions
    def pull(self, name=None):
        name = (name or self.pull_edit.text).strip()
        if not name or self.pulling:
            return
        if not self.sys.ai_status["local"]:
            self.desk.toast("Local AI engine (Ollama) isn't running")
            return
        self.pulling = [name, "starting…", 0, 0]

        def work():
            try:
                def prog(status, done, total):
                    self.pulling[1:] = [status, done, total]
                self.sys.ai.providers["ollama"].pull(name, prog)
                self.desk.toast(f"Downloaded {name}")
                if not self.sys.ai_status["models"]:
                    self.set_default(f"ollama/{name}")
            except AIError as e:
                self.desk.toast(f"Pull failed: {e}")
            finally:
                self.pulling = None
                self.sys.refresh_ai()
        threading.Thread(target=work, daemon=True).start()

    def delete(self, name):
        try:
            self.sys.ai.providers["ollama"].delete(name)
            self.desk.toast(f"Deleted {name}")
        except AIError as e:
            self.desk.toast(str(e))
        self.sys.refresh_ai()

    def set_default(self, ref):
        self.sys.ai.settings["default_model"] = ref
        self.sys.save()
        self.desk.toast(f"Default model: {ref}")

    def save_providers(self):
        self.sys.ai.settings.update(self.form.values())
        self.sys.ai.configure()
        self.sys.save()
        self.sys.refresh_ai()
        self.desk.toast("Providers saved")

    # ---------------- input
    def on_text(self, s):
        if self.tab == "providers":
            self.form.on_text(s)
        else:
            self.pull_edit.on_text(s)

    def on_key(self, ev):
        enter = ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
        if self.tab == "providers":
            if enter:
                self.save_providers()
            else:
                self.form.on_key(ev)
        else:
            if enter:
                self.pull()
            else:
                self.pull_edit.on_key(ev)

    # ---------------- drawing
    def draw(self, s):
        W, H = s.get_size()
        hw = self.sys.hw.snapshot
        st = self.sys.ai_status
        side = pygame.Rect(10, 10, 290, H - 20)
        self._hardware(s, side, hw)
        main = pygame.Rect(side.right + 10, 10, W - side.right - 20, H - 20)
        x = main.x
        for key, label in (("models", "Models"), ("providers", "Providers")):
            x = self.btn(s, (x, main.y, 110, 30), label, lambda k=key: setattr(self, "tab", k),
                         "accent" if self.tab == key else "normal").right + 6
        dot = C["ok"] if st["local"] else C["danger"]
        pygame.draw.circle(s, dot, (main.right - 230, main.y + 15), 5)
        text(s, f"Local engine: {'Ollama ' + st['version'] if st['local'] else 'not running'}",
             (main.right - 218, main.y + 15), C["dim"], "sans", 12, "midleft")
        body = pygame.Rect(main.x, main.y + 40, main.w, main.h - 40)
        rrect(s, C["panel"], body, 8)
        if self.tab == "models":
            self._models(s, body, st)
        else:
            self._providers(s, body)

    def _bar(self, s, r, frac, col):
        rrect(s, C["field"], r, 4)
        rrect(s, col, (r.x, r.y, max(4, int(r.w * min(1, frac))), r.h), 4)

    def _hardware(self, s, r, hw):
        rrect(s, C["panel"], r, 8)
        text(s, "This machine", (r.x + 14, r.y + 12), C["text"], "bold", 14)
        y = r.y + 40
        text(s, self.sys.hw.cpu_model, (r.x + 14, y), C["dim"], "sans", 11, maxw=r.w - 28)
        y += 20
        text(s, f"CPU · {self.sys.hw.cores} cores", (r.x + 14, y), C["text"], "sans", 13)
        text(s, f"{hw['cpu'] * 100:.0f}%", (r.right - 14, y), C["text"], "mono", 12, "topright")
        self._bar(s, pygame.Rect(r.x + 14, y + 20, r.w - 28, 8), hw["cpu"], C["accent"])
        y += 42
        tot = hw["ram_total"] or 1
        text(s, "Memory", (r.x + 14, y), C["text"], "sans", 13)
        text(s, f"{human(hw['ram_used'])} / {human(hw['ram_total'])}", (r.right - 14, y), C["text"], "mono", 12, "topright")
        frac = hw["ram_used"] / tot
        self._bar(s, pygame.Rect(r.x + 14, y + 20, r.w - 28, 8), frac, C["warn"] if frac > .85 else C["accent"])
        y += 42
        text(s, "GPU", (r.x + 14, y), C["text"], "sans", 13)
        y += 20
        if hw["gpus"]:
            for g in hw["gpus"][:3]:
                text(s, g["name"], (r.x + 14, y), C["text"] if g["compute"] else C["dim"], "sans", 12, maxw=r.w - 28)
                y += 18
                if g["vram"]:
                    self._bar(s, pygame.Rect(r.x + 14, y, r.w - 28, 6), g["vram_used"] / g["vram"], C["accent"])
                    text(s, f"{human(g['vram'])} VRAM · {g['util']}% busy", (r.x + 14, y + 10), C["dim"], "sans", 11)
                    y += 30
        else:
            text(s, "none detected (CPU inference)", (r.x + 14, y), C["dim"], "sans", 12)
            y += 20
        y += 8
        text(s, "Disk free", (r.x + 14, y), C["text"], "sans", 13)
        text(s, human(hw["disk_free"]), (r.right - 14, y), C["text"], "mono", 12, "topright")
        y += 34
        rrect(s, C["field"], (r.x + 10, y, r.w - 20, 86), 8)
        text(s, "What fits", (r.x + 22, y + 8), C["accent"], "bold", 12)
        from ..theme import wrap
        for i, ln in enumerate(wrap(self.sys.hw.advice(), r.w - 44, "sans", 12)[:3]):
            text(s, ln, (r.x + 22, y + 28 + i * 17), C["text"], "sans", 12)
        y += 100
        jobs_running = len(self.sys.jobs.running())
        text(s, f"AI jobs running: {jobs_running}", (r.x + 14, y), C["dim"], "sans", 12)

    def _models(self, s, r, st):
        x0 = r.x + 14
        text(s, "Installed models", (x0, r.y + 12), C["text"], "bold", 14)
        y = r.y + 40
        default = self.sys.ai.settings["default_model"]
        rows = st["models"]
        for ref, m in rows:
            if y + 34 > r.y + r.h * .55:
                text(s, f"+ {len(rows)} total", (x0, y), C["dim"], "sans", 12)
                break
            row = pygame.Rect(r.x + 8, y, r.w - 16, 32)
            if ref == default:
                rrect(s, lighten(C["panel"], 14), row, 6)
            text(s, ref, (x0, y + 8), C["text"], "sans", 13, maxw=row.w * .42)
            meta = " · ".join(v for v in (m.get("params"), m.get("quant"), human(m["size"]) if m.get("size") else "") if v)
            text(s, meta, (row.x + row.w * .45, y + 9), C["dim"], "sans", 12, maxw=row.w * .3)
            if ref == default:
                text(s, "default", (row.right - 96, y + 9), C["ok"], "bold", 12, "topright")
            else:
                self.btn(s, (row.right - 168, y + 2, 74, 28), "Use", lambda ref=ref: self.set_default(ref))
            if ref.startswith("ollama/"):
                self.btn(s, (row.right - 86, y + 2, 80, 28), "Delete", lambda n=ref[7:]: self.delete(n), "danger")
            y += 36
        if not rows:
            msg = ("No local models yet — download one below." if st["local"] else
                   "Local engine not running. Run 'install-ai-engine' in the Terminal, "
                   "or add an API key under Providers.")
            text(s, msg, (x0, y), C["warn"], "sans", 13, maxw=r.w - 28)

        # download section
        y = int(r.y + r.h * .58)
        pygame.draw.line(s, C["line"], (r.x + 10, y - 10), (r.right - 10, y - 10))
        text(s, "Download a local model", (x0, y), C["text"], "bold", 14)
        from ..ui import draw_field
        draw_field(s, (x0, y + 26, r.w - 150, 34), self.pull_edit, self.tab == "models")
        self.btn(s, (r.right - 124, y + 26, 110, 34), "Download", self.pull, "accent",
                 enabled=not self.pulling and bool(self.pull_edit.text.strip()))
        y += 70
        if self.pulling:
            name, status, done, total = self.pulling
            text(s, f"{name}: {status}", (x0, y), C["text"], "sans", 12, maxw=r.w - 28)
            if total:
                self._bar(s, pygame.Rect(x0, y + 20, r.w - 28, 8), done / total, C["accent"])
                text(s, f"{human(done)} / {human(total)}", (r.right - 14, y), C["dim"], "mono", 11, "topright")
            return
        text(s, "Suggestions", (x0, y), C["dim"], "sans", 12)
        y += 20
        cw = (r.w - 28 - 16) // 3
        for i, (name, why) in enumerate(SUGGESTED):
            cx = x0 + (i % 3) * (cw + 8)
            cy = y + (i // 3) * 46
            b = self.btn(s, (cx, cy, cw, 40), "", lambda n=name: self.pull(n), "flat")
            text(s, name, (b.x + 10, b.y + 5), C["text"], "bold", 12, maxw=b.w - 16)
            text(s, why, (b.x + 10, b.y + 22), C["dim"], "sans", 11, maxw=b.w - 16)

    def _providers(self, s, r):
        text(s, "Where models come from", (r.x + 14, r.y + 12), C["text"], "bold", 14)
        text(s, "Local models run on this machine via Ollama. Cloud providers need an API key "
                "(stored only in ~/SourabhHome/.config, readable by you only).",
             (r.x + 14, r.y + 34), C["dim"], "sans", 12, maxw=r.w - 28)
        y = self.form.draw(self, s, r.x + 14, r.y + 64, r.w - 28, label_w=180)
        st = self.sys.ai.providers
        lines = [("Local (Ollama)", self.sys.ai_status["local"]),
                 ("Anthropic (Claude)", st["anthropic"].available()),
                 ("OpenAI-compatible", st["openai"].available())]
        y += 6
        for name, ok in lines:
            pygame.draw.circle(s, C["ok"] if ok else C["dim"], (r.x + 22, y + 8), 5)
            text(s, f"{name}: {'ready' if ok else 'not configured'}", (r.x + 34, y), C["text"], "sans", 13)
            y += 22
        self.btn(s, (r.right - 140, r.bottom - 48, 126, 34), "Save", self.save_providers, "accent")
        text(s, "Model names: ollama/<model>, anthropic/claude-haiku-5-5, openai/<model>",
             (r.x + 14, r.bottom - 32), C["dim"], "sans", 11, maxw=r.w - 170)
