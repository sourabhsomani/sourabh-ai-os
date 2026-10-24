"""AI Chat: talk to local or cloud models, with streaming and file attachments."""
import threading
import time
from pathlib import Path

import pygame

from ...ai import AIError
from ..theme import C, font, rrect, text, wrap, lighten, blend, icon
from ..ui import App, LineEdit, draw_field, clipboard_put

SUGGESTIONS = [
    "Explain how virtual memory paging works, simply",
    "Write a Python function that removes duplicate lines from a file",
    "/file ~/SourabhHome/Documents/welcome.txt  What can this OS do?",
    "Give me 5 ideas for batch AI jobs I could run on my documents",
]


class AIChat(App):
    title = "AI Chat"
    icon = "ai"
    size = (820, 600)
    min_size = (460, 360)

    def __init__(self, desk, **kw):
        super().__init__(desk, **kw)
        self.msgs = []           # dicts: role, content, meta
        self.edit = LineEdit(mono=False, size=14, placeholder="Message the AI…   (/file <path> to attach a file)")
        self.model = self.sys.ai.settings["default_model"]
        self.busy = False
        self.stop = threading.Event()
        self.scroll = 0
        self.picker = False
        self._chips = []

    # ---------------- actions
    def send(self, prompt=None):
        prompt = (prompt if prompt is not None else self.edit.commit()).strip()
        if not prompt or self.busy:
            return
        content, shown = self._attach(prompt)
        self.msgs.append({"role": "user", "content": content, "shown": shown})
        reply = {"role": "assistant", "content": "", "meta": "thinking…"}
        self.msgs.append(reply)
        self.busy, self.scroll = True, 0
        self.stop.clear()
        history = [{"role": "system", "content": self.sys.ai.settings.get("system_prompt", "")}] if \
            self.sys.ai.settings.get("system_prompt") else []
        history += [{"role": m["role"], "content": m["content"]} for m in self.msgs[:-1]]

        def on_tok(t):
            reply["content"] += t
            reply["meta"] = "…"

        def work():
            try:
                r = self.sys.ai.chat(self.model, history, on_token=on_tok, stop=self.stop)
                reply["meta"] = f"{self.model} · {r['tokens']} tokens · {r.tokens_per_s:.1f} tok/s"
                if self.stop.is_set():
                    reply["meta"] += " · stopped"
            except AIError as e:
                reply["meta"] = "error"
                reply["error"] = str(e)
            finally:
                self.busy = False
        threading.Thread(target=work, daemon=True).start()

    def _attach(self, prompt):
        """'/file path rest-of-prompt' → put the file's text in the message."""
        if not prompt.startswith("/file "):
            return prompt, prompt
        rest = prompt[6:].strip()
        path, _, question = rest.partition(" ")
        p = Path(path).expanduser()
        try:
            body = p.read_text(errors="replace")[:20000]
        except OSError as e:
            return prompt, f"{prompt}\n[could not read file: {e}]"
        q = question.strip() or "Summarise this file."
        return f"--- {p.name} ---\n{body}\n--- end of {p.name} ---\n\n{q}", f"[attached {p.name}]\n{q}"

    def new_chat(self):
        self.stop.set()
        self.msgs.clear()
        self.scroll = 0

    def save(self):
        d = self.sys.home / "Documents" / "Chats"
        d.mkdir(parents=True, exist_ok=True)
        f = d / time.strftime("chat-%Y%m%d-%H%M%S.md")
        lines = [f"# Chat with {self.model}\n"]
        for m in self.msgs:
            lines.append(f"**{'You' if m['role'] == 'user' else 'AI'}:**\n\n{m.get('shown', m['content'])}\n")
        f.write_text("\n".join(lines))
        self.desk.toast(f"Saved Documents/Chats/{f.name}")

    def copy_last(self):
        for m in reversed(self.msgs):
            if m["role"] == "assistant" and m["content"]:
                self.desk.toast("Copied reply" if clipboard_put(m["content"]) else "Clipboard not available")
                return

    def pick(self, ref):
        self.model = ref
        self.picker = False

    # ---------------- input
    def on_text(self, s):
        self.edit.on_text(s)

    def on_key(self, ev):
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.send()
        elif ev.key == pygame.K_ESCAPE:
            if self.busy:
                self.stop.set()
            self.picker = False
        elif ev.key == pygame.K_PAGEUP:
            self.scroll += 200
        elif ev.key == pygame.K_PAGEDOWN:
            self.scroll = max(0, self.scroll - 200)
        else:
            self.edit.on_key(ev)

    def on_wheel(self, dy, pos):
        self.scroll = max(0, self.scroll + dy * 40)

    def on_click(self, pos, button, double=False):
        self.picker = False

    # ---------------- drawing
    def draw(self, s):
        W, H = s.get_size()
        st = self.sys.ai_status
        # header
        pygame.draw.rect(s, C["panel"], (0, 0, W, 46))
        mr = self.btn(s, (10, 8, min(330, W - 330), 30), "▾  " + self.model,
                      lambda: setattr(self, "picker", not self.picker), "normal")
        x = mr.right + 8
        x = self.btn(s, (x, 8, 86, 30), "New chat", self.new_chat).right + 6
        x = self.btn(s, (x, 8, 56, 30), "Save", self.save, enabled=bool(self.msgs)).right + 6
        self.btn(s, (x, 8, 56, 30), "Copy", self.copy_last, enabled=bool(self.msgs))
        ok = st["local"] or not self.model.startswith("ollama/")
        pygame.draw.circle(s, C["ok"] if ok else C["danger"], (W - 18, 23), 5)

        # transcript
        area = pygame.Rect(0, 46, W, H - 46 - 64)
        bubble_w = int(area.w * .78)
        blocks = []
        for m in self.msgs:
            body = m.get("shown", m["content"]) or ("" if m["role"] == "user" else " ")
            lines = self._lines(body, bubble_w - 28)
            blocks.append((m, lines))
        lh = font("sans", 14).get_linesize()
        total = sum(len(l) * lh + 46 for _, l in blocks)
        max_scroll = max(0, total - area.h + 20)
        self.scroll = min(self.scroll, max_scroll)
        y = area.bottom - 10 - total + self.scroll if total > area.h - 20 else area.y + 16
        clip = s.get_clip()
        s.set_clip(area)
        for m, lines in blocks:
            h = len(lines) * lh + 20
            user = m["role"] == "user"
            bw = min(bubble_w, max(120, max((font(k, 14).size(t)[0] for t, k in lines), default=0) + 28))
            bx = W - bw - 14 if user else 14
            if y + h > area.y and y < area.bottom:
                col = blend(C["bg"], C["accent"], .22) if user else C["panel"]
                rrect(s, col, (bx, y, bw, h), 12)
                if not user:
                    rrect(s, C["line"], (bx, y, bw, h), 12, 1)
                ty = y + 10
                for t, kind in lines:
                    if kind == "mono":
                        pygame.draw.rect(s, C["field"], (bx + 8, ty - 1, bw - 16, lh))
                    text(s, t, (bx + 14, ty), C["text"], kind, 13 if kind == "mono" else 14)
                    ty += lh
                if not user:
                    meta = m.get("meta", "")
                    if m.get("error"):
                        meta = "⚠ " + m["error"]
                    if self.busy and m is self.msgs[-1] and (pygame.time.get_ticks() // 400) % 2:
                        pygame.draw.rect(s, C["accent"], (bx + 14, ty - lh + 2, 8, lh - 4))
                    text(s, meta, (bx + 4, y + h + 4), C["danger"] if m.get("error") else C["dim"],
                         "sans", 11, maxw=W - 40)
            y += h + 26
        s.set_clip(clip)

        if not self.msgs:
            self._empty(s, area)

        # input row
        pygame.draw.rect(s, C["panel"], (0, H - 64, W, 64))
        draw_field(s, (12, H - 50, W - 120, 36), self.edit, True)
        if self.busy:
            self.btn(s, (W - 100, H - 50, 88, 36), "Stop", self.stop.set, "danger")
        else:
            self.btn(s, (W - 100, H - 50, 88, 36), "Send", self.send, "accent", enabled=bool(self.edit.text.strip()))

        if self.picker:
            self._draw_picker(s, mr)

    def _lines(self, body, width):
        """Wrap text; fenced ``` blocks are drawn in mono."""
        out, mono = [], False
        for para in body.split("\n"):
            if para.strip().startswith("```"):
                mono = not mono
                continue
            kind = "mono" if mono else "sans"
            for ln in (wrap(para, width, kind, 13 if mono else 14) or [""]):
                out.append((ln, kind))
        while out and out[-1][0] == "" and len(out) > 1:
            out.pop()
        return out

    def _empty(self, s, area):
        W = s.get_width()
        cy = area.y + area.h // 2 - 120
        icon(s, "ai", (W // 2 - 32, cy, 64, 64))
        text(s, "What should we work on?", (W // 2, cy + 86), C["text"], "bold", 20, "center")
        if not self.sys.ai_ready():
            msg = "No model ready yet — open Models to download one or add an API key."
            text(s, msg, (W // 2, cy + 118), C["warn"], "sans", 13, "center", W - 40)
            self.btn(s, (W // 2 - 70, cy + 140, 140, 32), "Open Models",
                     lambda: self.desk.open_by_name("Models"), "accent")
            return
        text(s, f"Using {self.model}", (W // 2, cy + 116), C["dim"], "sans", 13, "center")
        y = cy + 146
        for sug in SUGGESTIONS:
            r = pygame.Rect(W // 2 - min(260, W // 2 - 20), y, min(520, W - 40), 32)
            self.btn(s, r, sug, lambda t=sug: self.send(t), "flat")
            y += 38

    def _draw_picker(self, s, anchor):
        models = self.sys.ai_status["models"]
        r = pygame.Rect(anchor.x, anchor.bottom + 4, max(anchor.w, 330), 16 + 30 * max(1, len(models)))
        r.h = min(r.h, s.get_height() - r.y - 70)
        rrect(s, C["title_active"], r, 8)
        rrect(s, C["accent"], r, 8, 1)
        y = r.y + 8
        for ref, m in models:
            if y + 28 > r.bottom:
                break
            label = f"{ref}   {m.get('params', '')}"
            self.btn(s, (r.x + 6, y, r.w - 12, 28), label, lambda ref=ref: self.pick(ref),
                     "accent" if ref == self.model else "flat")
            y += 30
        if not models:
            text(s, "No models found. Open Models to add one.", (r.x + 12, r.y + 12), C["dim"], "sans", 13)
