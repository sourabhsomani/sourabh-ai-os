from pathlib import Path

import pygame

from ..theme import C, font, rrect, text
from ..ui import App

try:
    import pygame.scrap as _scrap  # noqa: F401
except ImportError:
    _scrap = None


class Editor(App):
    title = "Editor"
    icon = "editor"
    size = (760, 500)

    def __init__(self, desk, path=None, **kw):
        super().__init__(desk, **kw)
        self.path = Path(path) if path else None
        self.lines = [""]
        if self.path and self.path.exists():
            try:
                self.lines = self.path.read_text(errors="replace").expandtabs(4).split("\n")
            except OSError as e:
                self.desk.toast(str(e))
        self.row = self.col = 0
        self.top = 0
        self.dirty = False
        self.clip = ""
        self._title()

    def _title(self):
        name = self.path.name if self.path else "untitled"
        self.set_title(f"{'• ' if self.dirty else ''}{name} — Editor")

    def save(self):
        if not self.path:
            self.path = self.sys.home / "Documents" / "untitled.txt"
            n = 1
            while self.path.exists():
                self.path = self.sys.home / "Documents" / f"untitled-{n}.txt"
                n += 1
        self.path.write_text("\n".join(self.lines))
        self.dirty = False
        self._title()
        self.desk.toast(f"Saved {self.path.name}")

    def run(self):
        self.save()
        self.desk.toast(self.sys.run_program(self.path))
        self.sys.vm_running = True

    def _changed(self):
        if not self.dirty:
            self.dirty = True
            self._title()

    # ---------------- editing
    def on_text(self, s):
        ln = self.lines[self.row]
        self.lines[self.row] = ln[:self.col] + s + ln[self.col:]
        self.col += len(s)
        self._changed()

    def on_key(self, ev):
        k, ctrl = ev.key, ev.mod & pygame.KMOD_CTRL
        ln = self.lines[self.row]
        if ctrl and k == pygame.K_s:
            self.save()
        elif ctrl and k == pygame.K_r:
            self.run()
        elif ctrl and k == pygame.K_k:          # cut line
            self.clip = self.lines.pop(self.row) if len(self.lines) > 1 else self.lines[0]
            if len(self.lines) == 1 and self.clip == self.lines[0]:
                self.lines[0] = ""
            self.row = min(self.row, len(self.lines) - 1)
            self.col = 0
            self._changed()
        elif ctrl and k == pygame.K_u and self.clip:  # paste line
            self.lines.insert(self.row, self.clip)
            self._changed()
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            indent = len(ln) - len(ln.lstrip(" "))
            self.lines[self.row] = ln[:self.col]
            self.lines.insert(self.row + 1, " " * indent + ln[self.col:])
            self.row += 1
            self.col = indent
            self._changed()
        elif k == pygame.K_BACKSPACE:
            if self.col:
                self.lines[self.row] = ln[:self.col - 1] + ln[self.col:]
                self.col -= 1
            elif self.row:
                prev = self.lines[self.row - 1]
                self.lines[self.row - 1] = prev + ln
                self.lines.pop(self.row)
                self.row -= 1
                self.col = len(prev)
            self._changed()
        elif k == pygame.K_DELETE:
            if self.col < len(ln):
                self.lines[self.row] = ln[:self.col] + ln[self.col + 1:]
            elif self.row < len(self.lines) - 1:
                self.lines[self.row] = ln + self.lines.pop(self.row + 1)
            self._changed()
        elif k == pygame.K_TAB:
            self.on_text("    ")
        elif k == pygame.K_LEFT:
            if self.col:
                self.col -= 1
            elif self.row:
                self.row -= 1
                self.col = len(self.lines[self.row])
        elif k == pygame.K_RIGHT:
            if self.col < len(ln):
                self.col += 1
            elif self.row < len(self.lines) - 1:
                self.row, self.col = self.row + 1, 0
        elif k == pygame.K_UP:
            self.row = max(0, self.row - 1)
        elif k == pygame.K_DOWN:
            self.row = min(len(self.lines) - 1, self.row + 1)
        elif k == pygame.K_PAGEUP:
            self.row = max(0, self.row - 20)
        elif k == pygame.K_PAGEDOWN:
            self.row = min(len(self.lines) - 1, self.row + 20)
        elif k == pygame.K_HOME:
            self.col = 0
        elif k == pygame.K_END:
            self.col = len(ln)
        self.col = min(self.col, len(self.lines[self.row]))

    def on_wheel(self, dy, pos):
        self.top = max(0, min(len(self.lines) - 1, self.top - dy * 3))

    def on_click(self, pos, button, double=False):
        f = font("mono", 14)
        lh = f.get_linesize()
        if pos[1] < 46:
            return
        r = self.top + (pos[1] - 52) // lh
        self.row = max(0, min(len(self.lines) - 1, r))
        cw = f.size("M")[0]
        self.col = max(0, min(len(self.lines[self.row]), round((pos[0] - 56) / cw)))

    def on_close(self):
        if self.dirty and self.path:
            self.save()

    # ---------------- drawing
    def draw(self, s):
        W, H = s.get_size()
        pygame.draw.rect(s, C["panel"], (0, 0, W, 46))
        x = self.btn(s, (10, 8, 70, 30), "Save", self.save, "accent").right + 6
        is_prog = self.path and (self.path.suffix == ".tvm" or self.path.parent.name == "Programs")
        x = self.btn(s, (x, 8, 112, 30), "Run in TinyVM", self.run, enabled=bool(is_prog)).right + 10
        text(s, "Ctrl+S save · Ctrl+R run · Ctrl+K cut line · Ctrl+U paste", (x, 23), C["dim"], "sans", 12, "midleft", W - x - 10)
        f = font("mono", 14)
        lh = f.get_linesize()
        rows = (H - 60) // lh
        if self.row < self.top:
            self.top = self.row
        elif self.row >= self.top + rows:
            self.top = self.row - rows + 1
        pygame.draw.rect(s, C["field"], (0, 46, W, H - 46))
        pygame.draw.rect(s, C["panel"], (0, 46, 46, H - 46))
        y = 52
        for i in range(self.top, min(len(self.lines), self.top + rows)):
            ln = self.lines[i]
            if i == self.row:
                pygame.draw.rect(s, (30, 34, 44), (46, y - 1, W - 46, lh))
            text(s, str(i + 1), (40, y), C["accent"] if i == self.row else C["dim"], "mono", 12, "topright")
            code, _, comment = ln.partition(";")
            r = text(s, code, (56, y), C["text"], "mono", 14)
            if _:
                text(s, ";" + comment, (r.right, y), C["dim"], "mono", 14)
            if i == self.row and (pygame.time.get_ticks() // 530) % 2 == 0:
                cx = 56 + f.size(ln[:self.col])[0]
                pygame.draw.rect(s, C["accent"], (cx, y + 1, 2, lh - 2))
            y += lh
        text(s, f"Ln {self.row + 1}, Col {self.col + 1}", (W - 10, H - 8), C["dim"], "mono", 11, "bottomright")
