"""Tiny immediate-mode widget toolkit used by every app."""
import pygame
from .theme import C, font, rrect, text, lighten


class App:
    """Base class for desktop applications.

    Subclasses draw into a content-sized surface in draw(); buttons drawn with
    self.btn() are hit-tested automatically.  Coordinates passed to the
    on_* handlers are local to the content area.
    """
    title = "App"
    icon = "file"
    size = (640, 420)
    min_size = (300, 180)
    single = False  # only one instance allowed

    def __init__(self, desk, **kw):
        self.desk = desk
        self.sys = desk.sys
        self.window = None
        self._hits = []
        self.hover = (-1, -1)

    # ---- helpers
    def btn(self, surf, rect, label, cb, kind="normal", enabled=True, icon_kind=None):
        rect = pygame.Rect(rect)
        hot = rect.collidepoint(self.hover) and enabled
        base = {"normal": C["panel"], "accent": C["accent"], "danger": C["danger"],
                "flat": C["bg"]}[kind]
        col = lighten(base, 22) if hot else base
        if not enabled:
            col = C["bg"]
        rrect(surf, col, rect, 6)
        if kind in ("normal", "flat"):
            rrect(surf, C["line"], rect, 6, 1)
        fg = (16, 18, 24) if kind in ("accent",) else (C["text"] if enabled else C["dim"])
        if icon_kind:
            from .theme import icon
            s = rect.h - 10
            icon(surf, icon_kind, (rect.x + 6, rect.y + 5, s, s))
            text(surf, label, (rect.x + s + 12, rect.centery), fg, "sans", 13, "midleft", rect.w - s - 16)
        else:
            text(surf, label, rect.center, fg, "sans", 13, "center", rect.w - 8)
        if enabled:
            self._hits.append((rect, cb))
        return rect

    def begin_frame(self):
        self._hits = []

    def dispatch_click(self, pos):
        for rect, cb in reversed(self._hits):
            if rect.collidepoint(pos):
                cb()
                return True
        return False

    def close(self):
        self.desk.close(self.window)

    def set_title(self, t):
        if self.window:
            self.window.title = t

    # ---- overridable
    def draw(self, surf): pass
    def update(self, dt): pass
    def on_click(self, pos, button, double=False): pass
    def on_mouse_up(self, pos, button): pass
    def on_drag(self, pos): pass
    def on_wheel(self, dy, pos): pass
    def on_key(self, ev): pass
    def on_text(self, s): pass
    def on_close(self): return True


def clipboard_get():
    try:
        import pygame.scrap as sc
        if not sc.get_init():
            sc.init()
        t = sc.get_text() if hasattr(sc, "get_text") else sc.get(pygame.SCRAP_TEXT)
        if isinstance(t, bytes):
            t = t.decode("utf-8", "ignore")
        return (t or "").replace("\x00", "")
    except Exception:  # no clipboard (headless, Wayland without X…)
        return ""


def clipboard_put(text_):
    try:
        import pygame.scrap as sc
        if not sc.get_init():
            sc.init()
        if hasattr(sc, "put_text"):
            sc.put_text(text_)
        else:
            sc.put(pygame.SCRAP_TEXT, text_.encode())
        return True
    except Exception:
        return False


class LineEdit:
    """Single-line text field with cursor, history and Ctrl+V paste."""

    def __init__(self, text_="", mono=True, size=14, mask=False, placeholder=""):
        self.mask = mask
        self.placeholder = placeholder
        self.text = text_
        self.cur = len(text_)
        self.kind = "mono" if mono else "sans"
        self.size = size
        self.history, self.hpos = [], 0

    def on_text(self, s):
        self.text = self.text[:self.cur] + s + self.text[self.cur:]
        self.cur += len(s)

    def on_key(self, ev):
        k = ev.key
        ctrl = ev.mod & pygame.KMOD_CTRL
        if k == pygame.K_BACKSPACE and self.cur:
            self.text = self.text[:self.cur - 1] + self.text[self.cur:]
            self.cur -= 1
        elif k == pygame.K_DELETE:
            self.text = self.text[:self.cur] + self.text[self.cur + 1:]
        elif k == pygame.K_LEFT:
            self.cur = max(0, self.cur - 1)
        elif k == pygame.K_RIGHT:
            self.cur = min(len(self.text), self.cur + 1)
        elif k == pygame.K_HOME or (ctrl and k == pygame.K_a):
            self.cur = 0
        elif k == pygame.K_END or (ctrl and k == pygame.K_e):
            self.cur = len(self.text)
        elif ctrl and k == pygame.K_u:
            self.text, self.cur = "", 0
        elif ctrl and k == pygame.K_v:
            self.on_text(clipboard_get().replace("\r", "").replace("\n", " "))
        elif k == pygame.K_UP and self.history:
            self.hpos = max(0, self.hpos - 1)
            self.text = self.history[self.hpos]
            self.cur = len(self.text)
        elif k == pygame.K_DOWN and self.history:
            self.hpos = min(len(self.history), self.hpos + 1)
            self.text = self.history[self.hpos] if self.hpos < len(self.history) else ""
            self.cur = len(self.text)
        else:
            return False
        return True

    def commit(self):
        t = self.text
        if t.strip():
            self.history.append(t)
        self.hpos = len(self.history)
        self.text, self.cur = "", 0
        return t

    def draw(self, surf, pos, color=None, show_cursor=True, prefix=""):
        f = font(self.kind, self.size)
        x, y = pos
        if prefix:
            r = text(surf, prefix, (x, y), C["accent"], self.kind, self.size)
            x = r.right
        text(surf, self.text, (x, y), color or C["text"], self.kind, self.size)
        if show_cursor and (pygame.time.get_ticks() // 530) % 2 == 0:
            cx = x + f.size(self.text[:self.cur])[0]
            pygame.draw.rect(surf, C["accent"], (cx, y + 1, 2, f.get_height() - 2))


def draw_field(surf, rect, edit: LineEdit, focused=True):
    """Draw a LineEdit inside a box, scrolling horizontally to keep the cursor visible."""
    rect = pygame.Rect(rect)
    rrect(surf, C["field"], rect, 6)
    rrect(surf, C["accent"] if focused else C["line"], rect, 6, 1)
    f = font(edit.kind, edit.size)
    h = f.get_height()
    inner = rect.inflate(-14, 0)
    clip = surf.get_clip()
    surf.set_clip(inner.clip(clip) if clip else inner)
    shown = "•" * len(edit.text) if edit.mask else edit.text
    y = rect.y + (rect.h - h) // 2
    if not shown and not focused and edit.placeholder:
        text(surf, edit.placeholder, (inner.x, y), C["dim"], edit.kind, edit.size)
    elif not shown and edit.placeholder and focused:
        text(surf, edit.placeholder, (inner.x + 4, y), C["dim"], edit.kind, edit.size)
    cx = f.size(shown[:edit.cur])[0]
    off = max(0, cx - inner.w + 6)
    text(surf, shown, (inner.x - off, y), C["text"], edit.kind, edit.size)
    if focused and (pygame.time.get_ticks() // 530) % 2 == 0:
        pygame.draw.rect(surf, C["accent"], (inner.x - off + cx, y + 1, 2, h - 2))
    surf.set_clip(clip)


class Form:
    """A stack of labelled LineEdits with click/Tab focus."""

    def __init__(self, fields):
        # fields: list of (key, label, LineEdit)
        self.fields = fields
        self.focus = 0

    def __getitem__(self, key):
        for k, _, e in self.fields:
            if k == key:
                return e
        raise KeyError(key)

    def values(self):
        return {k: e.text.strip() for k, _, e in self.fields}

    def on_text(self, s):
        self.fields[self.focus][2].on_text(s)

    def on_key(self, ev):
        if ev.key == pygame.K_TAB:
            step = -1 if ev.mod & pygame.KMOD_SHIFT else 1
            self.focus = (self.focus + step) % len(self.fields)
            return True
        return self.fields[self.focus][2].on_key(ev)

    def draw(self, app, surf, x, y, w, label_w=140, row_h=40):
        for i, (key, label, edit) in enumerate(self.fields):
            text(surf, label, (x, y + 9), C["dim"], "sans", 13)
            r = pygame.Rect(x + label_w, y, w - label_w, 32)
            draw_field(surf, r, edit, i == self.focus)
            app._hits.append((r, lambda i=i: setattr(self, "focus", i)))
            y += row_h
        return y
