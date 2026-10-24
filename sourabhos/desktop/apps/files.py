import shutil
import time
from pathlib import Path

import pygame

from ..theme import C, icon, rrect, text, lighten
from ..ui import App, LineEdit, draw_field

PROGRAM_EXT = {".tvm"}


class Files(App):
    title = "Files"
    icon = "folder"
    size = (720, 460)

    def __init__(self, desk, path=None, **kw):
        super().__init__(desk, **kw)
        self.cwd = Path(path) if path else self.sys.home
        self.sel = None
        self.scroll = 0
        self.dialog = None   # (prompt, LineEdit, callback)
        self.set_title(f"Files — {self.cwd.name}")

    def entries(self):
        try:
            items = [p for p in self.cwd.iterdir() if not p.name.startswith(".")]
        except OSError:
            return []
        return sorted(items, key=lambda p: (not p.is_dir(), p.name.lower()))

    def go(self, p):
        self.cwd, self.sel, self.scroll = p, None, 0
        self.set_title(f"Files — {p.name or '/'}")

    def open_item(self, p):
        if p.is_dir():
            self.go(p)
        elif p.suffix in PROGRAM_EXT or (p.parent.name == "Programs" and p.suffix == ".txt"):
            self.desk.toast(self.sys.run_program(p))
            self.sys.vm_running = True
        else:
            self.desk.open_by_name("Editor", path=p)

    def ask(self, prompt, cb, initial=""):
        self.dialog = (prompt, LineEdit(initial, mono=False), cb)

    def _new_file(self, name):
        if name:
            (self.cwd / name).touch()

    def _new_dir(self, name):
        if name:
            (self.cwd / name).mkdir(exist_ok=True)

    def _rename(self, name):
        if name and self.sel:
            self.sel.rename(self.cwd / name)
            self.sel = self.cwd / name

    def delete(self):
        if self.sel and self.sel.exists():
            shutil.rmtree(self.sel) if self.sel.is_dir() else self.sel.unlink()
            self.desk.toast(f"Deleted {self.sel.name}")
            self.sel = None

    # ---------------- input
    def on_key(self, ev):
        if self.dialog:
            prompt, edit, cb = self.dialog
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.dialog = None
                try:
                    cb(edit.text.strip())
                except OSError as e:
                    self.desk.toast(str(e))
            elif ev.key == pygame.K_ESCAPE:
                self.dialog = None
            else:
                edit.on_key(ev)
            return
        if ev.key == pygame.K_DELETE:
            self.delete()
        elif ev.key == pygame.K_BACKSPACE:
            self.go(self.cwd.parent)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.sel:
            self.open_item(self.sel)

    def on_text(self, s):
        if self.dialog:
            self.dialog[1].on_text(s)

    def on_wheel(self, dy, pos):
        self.scroll = max(0, self.scroll - dy * 30)

    def on_click(self, pos, button, double=False):
        if self.dialog:
            return
        for r, p in self._rows:
            if r.collidepoint(pos):
                if double and p == self.sel:
                    self.open_item(p)
                self.sel = p
                return
        self.sel = None

    # ---------------- drawing
    def draw(self, s):
        W, H = s.get_size()
        pygame.draw.rect(s, C["panel"], (0, 0, W, 46))
        x = self.btn(s, (10, 8, 40, 30), "↑", lambda: self.go(self.cwd.parent)).right + 6
        x = self.btn(s, (x, 8, 60, 30), "Home", lambda: self.go(self.sys.home)).right + 10
        x = self.btn(s, (x, 8, 84, 30), "New file", lambda: self.ask("New file name", self._new_file, "untitled.txt")).right + 6
        x = self.btn(s, (x, 8, 96, 30), "New folder", lambda: self.ask("New folder name", self._new_dir)).right + 6
        sel = self.sel is not None
        x = self.btn(s, (x, 8, 70, 30), "Rename", lambda: self.ask("Rename to", self._rename, self.sel.name), enabled=sel).right + 6
        x = self.btn(s, (x, 8, 64, 30), "Delete", self.delete, "danger", enabled=sel).right + 6
        if sel and self.sel.is_file():
            runnable = self.sel.suffix in PROGRAM_EXT or self.sel.parent.name == "Programs"
            self.btn(s, (x, 8, 64, 30), "Run" if runnable else "Open", lambda: self.open_item(self.sel), "accent")
        # sidebar
        side = pygame.Rect(0, 46, 150, H - 46)
        pygame.draw.rect(s, C["panel"], side)
        pygame.draw.line(s, C["line"], side.topright, side.bottomright)
        places = [("Home", self.sys.home), ("Documents", self.sys.home / "Documents"),
                  ("Programs", self.sys.home / "Programs"), ("Root /", Path("/"))]
        for i, (name, p) in enumerate(places):
            r = pygame.Rect(8, 56 + i * 34, 134, 30)
            if p == self.cwd:
                rrect(s, lighten(C["panel"], 20), r, 6)
            self.btn(s, r, name, lambda p=p: self.go(p), "flat", icon_kind="folder") if p != self.cwd else \
                (icon(s, "folder", (r.x + 6, r.y + 5, 20, 20)), text(s, name, (r.x + 32, r.centery), C["text"], "sans", 13, "midleft"))
        # path bar
        text(s, str(self.cwd), (162, 54), C["dim"], "mono", 12, maxw=W - 175)
        # list
        self._rows = []
        y = 78 - self.scroll
        for p in self.entries():
            r = pygame.Rect(156, y, W - 166, 30)
            if r.bottom > 74 and r.y < H:
                if p == self.sel:
                    rrect(s, C["accent"], r, 6)
                elif r.collidepoint(self.hover):
                    rrect(s, lighten(C["bg"], 12), r, 6)
                kind = "folder" if p.is_dir() else ("program" if (p.suffix in PROGRAM_EXT or p.parent.name == "Programs") else "file")
                icon(s, kind, (r.x + 8, r.y + 4, 22, 22))
                fg = (16, 18, 24) if p == self.sel else C["text"]
                text(s, p.name, (r.x + 40, r.centery), fg, "sans", 13, "midleft", maxw=r.w - 260)
                try:
                    st = p.stat()
                    info = "folder" if p.is_dir() else f"{st.st_size:,} B"
                    text(s, info, (r.right - 160, r.centery), fg if p == self.sel else C["dim"], "sans", 12, "midright")
                    text(s, time.strftime("%d %b %H:%M", time.localtime(st.st_mtime)), (r.right - 10, r.centery),
                         fg if p == self.sel else C["dim"], "sans", 12, "midright")
                except OSError:
                    pass
            self._rows.append((r, p))
            y += 32
        if not self._rows:
            text(s, "This folder is empty", (170, 90), C["dim"])
        if self.dialog:
            prompt, edit, _ = self.dialog
            shade = pygame.Surface((W, H), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 120))
            s.blit(shade, (0, 0))
            d = pygame.Rect(0, 0, 360, 120)
            d.center = (W // 2, H // 2)
            rrect(s, C["title_active"], d, 10)
            rrect(s, C["accent"], d, 10, 1)
            text(s, prompt, (d.x + 16, d.y + 14), C["text"], "bold", 14)
            draw_field(s, (d.x + 16, d.y + 44, d.w - 32, 32), edit)
            text(s, "Enter to confirm · Esc to cancel", (d.x + 16, d.y + 88), C["dim"], "sans", 12)
