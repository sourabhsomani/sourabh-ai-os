"""Calculator, Settings and About."""
import ast
import operator
import platform

import pygame

from ..theme import C, THEMES, icon, rrect, text, blend
from ..ui import App

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expr):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("bad expression")
    return ev(ast.parse(expr, mode="eval"))


class Calculator(App):
    title = "Calculator"
    icon = "calc"
    size = (300, 400)
    min_size = (260, 340)
    single = True
    KEYS = ["C", "(", ")", "÷", "7", "8", "9", "×", "4", "5", "6", "−", "1", "2", "3", "+", "±", "0", ".", "="]

    def __init__(self, desk, **kw):
        super().__init__(desk, **kw)
        self.expr, self.result = "", "0"

    def press(self, k):
        if k == "C":
            self.expr, self.result = "", "0"
        elif k == "=":
            try:
                v = safe_eval(self.expr.replace("÷", "/").replace("×", "*").replace("−", "-"))
                self.result = (f"{v:.10g}" if isinstance(v, float) else str(v))
                self.expr = self.result
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
                self.result = "Error"
        elif k == "±":
            self.expr = f"-({self.expr})" if self.expr else ""
        else:
            self.expr += k

    def on_text(self, s):
        m = {"/": "÷", "*": "×", "-": "−"}
        for ch in s:
            if ch in "0123456789.()+":
                self.press(ch)
            elif ch in m:
                self.press(m[ch])
            elif ch == "=":
                self.press("=")

    def on_key(self, ev):
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.press("=")
        elif ev.key == pygame.K_BACKSPACE:
            self.expr = self.expr[:-1]
        elif ev.key == pygame.K_ESCAPE:
            self.press("C")

    def draw(self, s):
        W, H = s.get_size()
        rrect(s, C["field"], (10, 10, W - 20, 78), 8)
        text(s, self.expr or " ", (W - 22, 20), C["dim"], "mono", 14, "topright", W - 44)
        text(s, self.result, (W - 22, 78), C["text"], "bold", 28, "bottomright", W - 44)
        bw, bh = (W - 20 - 18) // 4, (H - 108 - 24) // 5
        for i, k in enumerate(self.KEYS):
            r = (10 + (i % 4) * (bw + 6), 100 + (i // 4) * (bh + 6), bw, bh)
            kind = "accent" if k == "=" else ("danger" if k == "C" else "normal")
            self.btn(s, r, k, lambda k=k: self.press(k), kind)


class Settings(App):
    title = "Settings"
    icon = "settings"
    size = (560, 470)
    single = True

    FIELDS = [("physical_memory", "Physical RAM (bytes)", 16, 16, 4096),
              ("process_memory", "Address space per process", 64, 128, 8192),
              ("page_size", "Page size (bytes)", 2, 8, 256),
              ("quantum", "Time slice (instructions)", 1, 1, 200),
              ("stack_size", "Stack size (bytes)", 16, 16, 1024)]

    def set_theme(self, name):
        self.sys.settings["theme"] = name
        self.sys.save()
        self.desk.apply_theme()

    def adjust(self, key, step, lo, hi, d):
        vm = self.sys.settings["vm"]
        if key == "page_size":
            v = vm[key] * 2 if d > 0 else vm[key] // 2
        else:
            v = vm[key] + d * step
        vm[key] = max(lo, min(hi, v))
        ps = vm["page_size"]
        for k in ("physical_memory", "process_memory"):
            vm[k] = max(ps, vm[k] - vm[k] % ps)

    def apply(self):
        self.sys.save()
        self.sys.new_vm()
        self.desk.toast("TinyVM restarted with new settings")

    def toggle_clock(self):
        self.sys.settings["clock_24h"] = not self.sys.settings.get("clock_24h", True)
        self.sys.save()

    def draw(self, s):
        W, H = s.get_size()
        text(s, "Appearance", (20, 16), C["text"], "bold", 15)
        for i, (name, t) in enumerate(THEMES.items()):
            r = pygame.Rect(20 + i * 128, 44, 118, 74)
            for yy in range(r.h):
                pygame.draw.line(s, blend(t["wall_top"], t["wall_bottom"], yy / r.h), (r.x, r.y + yy), (r.right - 1, r.y + yy))
            pygame.draw.circle(s, t["accent"], (r.right - 18, r.y + 18), 8)
            cur = self.sys.settings.get("theme") == name
            rrect(s, C["accent"] if cur else C["line"], r, 6, 3 if cur else 1)
            text(s, name, (r.x + 10, r.bottom - 22), (240, 240, 244), "bold", 12)
            self._hits.append((r, lambda n=name: self.set_theme(n)))
        self.btn(s, (20, 128, 200, 28), f"Clock: {'24-hour' if self.sys.settings.get('clock_24h', True) else '12-hour'}",
                 self.toggle_clock)

        text(s, "TinyVM kernel", (20, 174), C["text"], "bold", 15)
        text(s, "Shrink RAM to force page faults and swapping.", (20, 196), C["dim"], "sans", 12)
        vm = self.sys.settings["vm"]
        for i, (key, label, step, lo, hi) in enumerate(self.FIELDS):
            y = 222 + i * 38
            text(s, label, (20, y + 6), C["text"], "sans", 13)
            self.btn(s, (W - 170, y, 34, 28), "−", lambda a=(key, step, lo, hi): self.adjust(*a, -1))
            rrect(s, C["field"], (W - 130, y, 80, 28), 6)
            text(s, vm[key], (W - 90, y + 14), C["text"], "mono", 13, "center")
            self.btn(s, (W - 44, y, 34, 28), "+", lambda a=(key, step, lo, hi): self.adjust(*a, 1))
        self.btn(s, (W - 200, H - 44, 180, 32), "Apply & restart VM", self.apply, "accent")


class About(App):
    title = "About"
    icon = "about"
    size = (540, 400)
    single = True

    def draw(self, s):
        W, H = s.get_size()
        icon(s, "logo", (24, 24, 72, 72))
        text(s, "Sourabh OS 1.0", (112, 30), C["text"], "bold", 24)
        text(s, "The AI operating system, written in Python", (112, 64), C["dim"], "sans", 14)
        body = [
            "AI:     local models (Ollama), Claude, OpenAI-compatible;",
            "        batch jobs with queue, workers, retries, resume",
            "Desktop: pygame window manager, running directly on X11",
            "TinyVM: teaching kernel — paging, scheduler, 36 opcodes",
            "Host:   " + f"{platform.system()} {platform.release()} · Python {platform.python_version()}",
            "",
            "Inspired by Scott Hanselman's TinyOS (C#, BSD-2-Clause):",
            "github.com/shanselman/TinyOS — original TinyOS programs",
            "run unmodified in the VM Monitor.",
        ]
        y = 124
        for ln in body:
            text(s, ln, (24, y), C["text"], "mono", 13)
            y += 22
        self.btn(s, (W - 110, H - 46, 90, 32), "Close", self.close, "accent")
