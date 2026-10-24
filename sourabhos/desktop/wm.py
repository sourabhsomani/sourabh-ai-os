"""Window manager, desktop, taskbar and start menu."""
from __future__ import annotations

import getpass
import time

import pygame

from .theme import C, THEMES, font, icon, rrect, text, set_theme, blend, lighten

TITLE_H = 32
TASKBAR_H = 46
GRIP = 14


class Window:
    def __init__(self, app, rect):
        self.app = app
        self.rect = pygame.Rect(rect)
        self.title = app.title
        self.minimized = False
        self.maximized = False
        self.restore = None
        app.window = self

    @property
    def content(self):
        return pygame.Rect(self.rect.x + 1, self.rect.y + TITLE_H, self.rect.w - 2, self.rect.h - TITLE_H - 1)

    def buttons(self):
        r = self.rect
        y = r.y + 8
        return {"close": pygame.Rect(r.right - 30, y, 16, 16),
                "max": pygame.Rect(r.right - 54, y, 16, 16),
                "min": pygame.Rect(r.right - 78, y, 16, 16)}


class Desktop:
    APPS = None  # filled in by apps package: list of App classes

    def __init__(self, screen, system):
        self.screen = screen
        self.sys = system
        self.windows: list[Window] = []
        self.drag = None          # (window, mode, offset)
        self.capture = None       # window receiving drag events inside content
        self.start_open = False
        self.last_click = (0, None)
        self.selected_icon = None
        self.toasts = []          # (text, expire)
        self.running = True
        self.quit_action = None
        self.apply_theme()
        from .apps import APP_LIST
        from ..extapps import ExternalWindows
        self.app_list = APP_LIST
        self.ext = ExternalWindows()
        system.listeners.append(self._console_toast)

    # ---------------- theme / wallpaper
    def apply_theme(self):
        self.theme = set_theme(self.sys.settings.get("theme", "Midnight"))
        self.wallpaper = None

    def _make_wallpaper(self):
        w, h = self.screen.get_size()
        surf = pygame.Surface((w, h))
        top, bot = self.theme["wall_top"], self.theme["wall_bottom"]
        for y in range(h):
            pygame.draw.line(surf, blend(top, bot, y / h), (0, y), (w, y))
        acc = self.theme["accent"]
        glow = pygame.Surface((w, h), pygame.SRCALPHA)
        for i, rad in enumerate(range(int(min(w, h) * .55), 0, -24)):
            a = min(40, 3 + i)
            pygame.draw.circle(glow, (*acc, a // 4), (int(w * .78), int(h * .32)), rad)
        surf.blit(glow, (0, 0))
        # faint grid, a nod to memory pages
        grid = blend(bot, acc, .12)
        for x in range(0, w, 48):
            pygame.draw.line(surf, grid, (x, 0), (x, h))
        for y in range(0, h, 48):
            pygame.draw.line(surf, grid, (0, y), (w, y))
        text(surf, "Sourabh OS", (w - 40, h - TASKBAR_H - 70), blend(bot, (255, 255, 255), .25), "bold", 44, "bottomright")
        text(surf, "the AI operating system, written in Python", (w - 42, h - TASKBAR_H - 44),
             blend(bot, (255, 255, 255), .2), "sans", 15, "bottomright")
        self.wallpaper = surf

    # ---------------- windows
    def open(self, app_cls, **kw):
        if hasattr(app_cls, "launch"):      # launchers start outside programs (Chrome)
            self.start_open = False
            app_cls.launch(self, **kw)
            return None
        if app_cls.single:
            for w in self.windows:
                if isinstance(w.app, app_cls):
                    self.focus(w)
                    return w
        sw, sh = self.screen.get_size()
        aw = min(app_cls.size[0], sw - 40)
        ah = min(app_cls.size[1] + TITLE_H, sh - TASKBAR_H - 40)
        n = len(self.windows)
        x = (sw - aw) // 2 + (n % 6) * 28 - 70
        y = max(10, (sh - TASKBAR_H - ah) // 2 + (n % 6) * 28 - 70)
        app = app_cls(self, **kw)
        w = Window(app, (max(10, x), y, aw, ah))
        self.windows.append(w)
        self.start_open = False
        return w

    def open_by_name(self, name, **kw):
        for cls in self.app_list:
            if cls.__name__.lower() == name.lower() or cls.title.lower() == name.lower():
                return self.open(cls, **kw)
        return None

    def close(self, w):
        if w in self.windows and w.app.on_close() is not False:
            self.windows.remove(w)

    def focus(self, w):
        w.minimized = False
        if w in self.windows:
            self.windows.remove(w)
            self.windows.append(w)

    @property
    def active(self):
        for w in reversed(self.windows):
            if not w.minimized:
                return w
        return None

    def toggle_max(self, w):
        sw, sh = self.screen.get_size()
        if w.maximized:
            w.rect = w.restore
        else:
            w.restore = w.rect.copy()
            w.rect = pygame.Rect(0, 0, sw, sh - TASKBAR_H)
        w.maximized = not w.maximized

    def toast(self, msg, secs=3.5):
        self.toasts.append((msg, time.time() + secs))
        self.toasts = self.toasts[-4:]

    def _console_toast(self, line):
        if line.startswith("[kernel]") or "FAULT" in line:
            self.toast(line)

    # ---------------- desktop icons
    def icon_rects(self):
        out = []
        x, y = 22, 22
        for cls in self.app_list:
            if not getattr(cls, "on_desktop", True):
                continue
            out.append((pygame.Rect(x, y, 92, 88), cls))
            y += 100
            if y + 88 > self.screen.get_height() - TASKBAR_H:
                y, x = 22, x + 104
        return out

    # ---------------- taskbar & start menu geometry
    def start_btn(self):
        return pygame.Rect(8, self.screen.get_height() - TASKBAR_H + 6, 112, TASKBAR_H - 12)

    def task_buttons(self):
        h = self.screen.get_height()
        x = 132
        out = []
        for w in list(self.windows) + list(self.ext.windows):
            r = pygame.Rect(x, h - TASKBAR_H + 6, 170, TASKBAR_H - 12)
            out.append((r, w))
            x += 176
        return out

    def start_menu_items(self):
        h = self.screen.get_height()
        items = [(cls.title, cls.icon, ("app", cls)) for cls in self.app_list]
        items += [None, ("Log out", "power", ("quit", None)),
                  ("Restart", "power", ("reboot", None)),
                  ("Shut down", "power", ("shutdown", None))]
        menu = pygame.Rect(8, 0, 280, 0)
        rows = []
        y = 74
        for it in items:
            if it is None:
                y += 10
                continue
            rows.append((pygame.Rect(16, y, 264, 36), it))
            y += 38
        menu.h = y + 10
        menu.bottom = h - TASKBAR_H - 6
        dy = menu.y
        rows = [(r.move(0, dy), it) for r, it in rows]
        return menu, rows

    def power(self, action):
        """quit = leave the desktop; shutdown/reboot also power off the machine
        when running as the OS image (otherwise they just close the app)."""
        if action != "quit":
            self.sys.power(action)
        self.quit_action = action
        self.running = False

    # ---------------- event handling
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
        elif ev.type == pygame.VIDEORESIZE:
            self.wallpaper = None
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3):
            self._mouse_down(ev)
        elif ev.type == pygame.MOUSEBUTTONUP:
            if self.capture and self.capture in self.windows:
                c = self.capture.content
                self.capture.app.on_mouse_up((ev.pos[0] - c.x, ev.pos[1] - c.y), ev.button)
            self.drag = None
            self.capture = None
        elif ev.type == pygame.MOUSEMOTION:
            self._mouse_move(ev)
        elif ev.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            w = self.window_at(pos)
            if w:
                c = w.content
                w.app.on_wheel(ev.y, (pos[0] - c.x, pos[1] - c.y))
        elif ev.type == pygame.KEYDOWN:
            mods = ev.mod
            if ev.key == pygame.K_F4 and mods & pygame.KMOD_ALT:
                if self.active:
                    self.close(self.active)
                return
            if ev.key == pygame.K_t and mods & pygame.KMOD_CTRL and mods & pygame.KMOD_ALT:
                self.open_by_name("Terminal")
                return
            if ev.key == pygame.K_SPACE and mods & pygame.KMOD_CTRL and mods & pygame.KMOD_ALT:
                self.open_by_name("AI Chat")
                return
            if ev.key in (pygame.K_LGUI, pygame.K_RGUI):
                self.start_open = not self.start_open
                return
            if ev.key == pygame.K_ESCAPE and self.start_open:
                self.start_open = False
                return
            if self.active:
                self.active.app.on_key(ev)
        elif ev.type == pygame.TEXTINPUT:
            if self.active and not self.start_open:
                self.active.app.on_text(ev.text)

    def window_at(self, pos):
        for w in reversed(self.windows):
            if not w.minimized and w.rect.collidepoint(pos):
                return w
        return None

    def _mouse_down(self, ev):
        pos = ev.pos
        now = time.time()
        sh = self.screen.get_height()
        # start menu
        if self.start_open:
            menu, rows = self.start_menu_items()
            if menu.collidepoint(pos):
                for r, (label, _, (kind, cls)) in rows:
                    if r.collidepoint(pos):
                        self.start_open = False
                        if kind == "app":
                            self.open(cls)
                        else:
                            self.power(kind)
                return
            if not self.start_btn().collidepoint(pos):
                self.start_open = False
        # taskbar
        if pos[1] >= sh - TASKBAR_H:
            if self.start_btn().collidepoint(pos):
                self.start_open = not self.start_open
                return
            for r, w in self.task_buttons():
                if r.collidepoint(pos):
                    if not isinstance(w, Window):     # Chrome etc.: bring it to the front
                        w.activate()
                    elif w is self.active:
                        w.minimized = True
                    else:
                        self.focus(w)
                    return
            return
        # windows
        w = self.window_at(pos)
        if w:
            self.focus(w)
            for name, r in w.buttons().items():
                if r.inflate(6, 6).collidepoint(pos) and ev.button == 1:
                    if name == "close":
                        self.close(w)
                    elif name == "max":
                        self.toggle_max(w)
                    else:
                        w.minimized = True
                    return
            if pos[1] < w.rect.y + TITLE_H and ev.button == 1:
                double = self.last_click[1] is w and now - self.last_click[0] < .4
                self.last_click = (now, w)
                if double:
                    self.toggle_max(w)
                    return
                self.drag = (w, "move", (pos[0] - w.rect.x, pos[1] - w.rect.y))
                return
            grip = pygame.Rect(w.rect.right - GRIP, w.rect.bottom - GRIP, GRIP, GRIP)
            if grip.collidepoint(pos) and not w.maximized:
                self.drag = (w, "resize", (w.rect.right - pos[0], w.rect.bottom - pos[1]))
                return
            c = w.content
            local = (pos[0] - c.x, pos[1] - c.y)
            key = ("content", w)
            double = self.last_click[1] == key and now - self.last_click[0] < .4
            self.last_click = (now, key)
            self.capture = w
            if not w.app.dispatch_click(local) or ev.button == 3:
                w.app.on_click(local, ev.button, double)
            return
        # desktop icons
        for r, cls in self.icon_rects():
            if r.collidepoint(pos):
                double = self.last_click[1] == cls and now - self.last_click[0] < .45
                self.last_click = (now, cls)
                self.selected_icon = cls
                if double:
                    self.open(cls)
                return
        self.selected_icon = None

    def _mouse_move(self, ev):
        pos = ev.pos
        if self.drag:
            w, mode, off = self.drag
            sw, sh = self.screen.get_size()
            if mode == "move":
                if w.maximized:
                    w.maximized = False
                    w.rect.size = w.restore.size
                    off = (w.rect.w // 2, off[1])
                    self.drag = (w, mode, off)
                w.rect.x = max(-w.rect.w + 80, min(sw - 80, pos[0] - off[0]))
                w.rect.y = max(0, min(sh - TASKBAR_H - TITLE_H, pos[1] - off[1]))
            else:
                mw, mh = w.app.min_size
                w.rect.w = max(mw, pos[0] + off[0] - w.rect.x)
                w.rect.h = max(mh + TITLE_H, pos[1] + off[1] - w.rect.y)
            return
        for w in self.windows:
            c = w.content
            w.app.hover = (pos[0] - c.x, pos[1] - c.y) if w is self.window_at(pos) else (-1, -1)
        if self.capture and ev.buttons[0]:
            c = self.capture.content
            self.capture.app.on_drag((pos[0] - c.x, pos[1] - c.y))

    # ---------------- drawing
    def draw(self):
        scr = self.screen
        if self.wallpaper is None or self.wallpaper.get_size() != scr.get_size():
            self._make_wallpaper()
        scr.blit(self.wallpaper, (0, 0))
        mouse = pygame.mouse.get_pos()
        for r, cls in self.icon_rects():
            sel = cls is self.selected_icon
            if sel or (r.collidepoint(mouse) and not self.window_at(mouse)):
                s = pygame.Surface(r.size, pygame.SRCALPHA)
                rrect(s, (255, 255, 255, 40 if sel else 22), s.get_rect(), 10)
                scr.blit(s, r)
            icon(scr, cls.icon, (r.centerx - 24, r.y + 8, 48, 48))
            text(scr, cls.title, (r.centerx, r.y + 64), (240, 242, 246), "sans", 13, "midtop", r.w - 4)
        for w in self.windows:
            if not w.minimized:
                self._draw_window(w, w is self.active)
        self._draw_taskbar()
        if self.start_open:
            self._draw_start()
        self._draw_toasts()

    def _draw_window(self, w, active):
        scr = self.screen
        r = w.rect
        shadow = pygame.Surface((r.w + 24, r.h + 24), pygame.SRCALPHA)
        for i in range(12, 0, -3):
            rrect(shadow, (0, 0, 0, 10), shadow.get_rect().inflate(-i * 2, -i * 2).move(0, 4), 14)
        scr.blit(shadow, (r.x - 12, r.y - 12))
        rrect(scr, C["bg"], r, 10)
        title_col = C["title_active"] if active else C["title"]
        pygame.draw.rect(scr, title_col, (r.x, r.y, r.w, TITLE_H), border_top_left_radius=10, border_top_right_radius=10)
        if active:
            pygame.draw.line(scr, C["accent"], (r.x + 10, r.y + TITLE_H - 1), (r.right - 10, r.y + TITLE_H - 1), 2)
        icon(scr, w.app.icon, (r.x + 10, r.y + 7, 18, 18))
        text(scr, w.title, (r.x + 36, r.y + TITLE_H // 2), C["text"] if active else C["dim"],
             "bold", 13, "midleft", r.w - 130)
        mouse = pygame.mouse.get_pos()
        for name, b in w.buttons().items():
            hot = b.inflate(6, 6).collidepoint(mouse)
            col = {"close": C["danger"], "max": C["ok"], "min": C["warn"]}[name]
            pygame.draw.circle(scr, col if (active or hot) else C["line"], b.center, 7)
            if hot:
                cx, cy = b.center
                dark = (40, 20, 20)
                if name == "close":
                    pygame.draw.line(scr, dark, (cx - 3, cy - 3), (cx + 3, cy + 3), 2)
                    pygame.draw.line(scr, dark, (cx - 3, cy + 3), (cx + 3, cy - 3), 2)
                elif name == "min":
                    pygame.draw.line(scr, dark, (cx - 3, cy), (cx + 3, cy), 2)
                else:
                    pygame.draw.rect(scr, dark, (cx - 3, cy - 3, 7, 7), 1)
        c = w.content
        if c.w > 0 and c.h > 0:
            surf = pygame.Surface(c.size)
            surf.fill(C["bg"])
            w.app.begin_frame()
            w.app.draw(surf)
            scr.blit(surf, c.topleft)
        rrect(scr, C["accent"] if active else C["line"], r, 10, 1)
        if not w.maximized:
            gx, gy = r.right - 4, r.bottom - 4
            for i in (4, 8):
                pygame.draw.line(scr, C["dim"], (gx - i, gy), (gx, gy - i), 1)

    def _draw_taskbar(self):
        scr = self.screen
        sw, sh = scr.get_size()
        bar = pygame.Rect(0, sh - TASKBAR_H, sw, TASKBAR_H)
        s = pygame.Surface(bar.size, pygame.SRCALPHA)
        s.fill((*C["taskbar"], 235))
        scr.blit(s, bar)
        pygame.draw.line(scr, C["line"], bar.topleft, bar.topright)
        sb = self.start_btn()
        rrect(scr, lighten(C["taskbar"], 26) if (self.start_open or sb.collidepoint(pygame.mouse.get_pos())) else C["taskbar"], sb, 8)
        icon(scr, "logo", (sb.x + 6, sb.y + 5, sb.h - 10, sb.h - 10))
        text(scr, "Start", (sb.x + sb.h + 4, sb.centery), C["text"], "bold", 14, "midleft")
        for r, w in self.task_buttons():
            if r.right > sw - 350:
                break
            act = w is self.active
            rrect(scr, lighten(C["taskbar"], 30 if act else 12), r, 8)
            if act:
                pygame.draw.line(scr, C["accent"], (r.x + 12, r.bottom - 2), (r.right - 12, r.bottom - 2), 3)
            icon(scr, w.app.icon if isinstance(w, Window) else w.icon, (r.x + 8, r.y + 7, r.h - 14, r.h - 14))
            text(scr, w.title, (r.x + r.h + 2, r.centery), C["text"] if not w.minimized else C["dim"],
                 "sans", 13, "midleft", r.w - r.h - 8)
        # system tray: VM status + clock
        st = self.sys.ai_status
        running = len(self.sys.jobs.running())
        ready = bool(st["models"])
        dot = C["ok"] if ready else (C["warn"] if st["local"] else C["danger"])
        tray_x = sw - 330
        pygame.draw.circle(scr, dot, (tray_x, bar.centery), 5)
        label = ("AI ready" if ready else ("AI: no model" if st["local"] else "AI engine offline"))
        label += f" · {running} job{'s' if running != 1 else ''} running" if running else ""
        text(scr, label, (tray_x + 12, bar.centery), C["dim"], "sans", 12, "midleft", 190)
        fmt = "%H:%M" if self.sys.settings.get("clock_24h", True) else "%I:%M %p"
        text(scr, time.strftime(fmt), (sw - 14, bar.y + 13), C["text"], "bold", 13, "topright")
        text(scr, time.strftime("%d %b %Y"), (sw - 14, bar.y + 29), C["dim"], "sans", 11, "topright")

    def _draw_start(self):
        scr = self.screen
        menu, rows = self.start_menu_items()
        s = pygame.Surface(menu.size, pygame.SRCALPHA)
        rrect(s, (*C["taskbar"], 245), s.get_rect(), 12)
        scr.blit(s, menu)
        rrect(scr, C["line"], menu, 12, 1)
        icon(scr, "logo", (menu.x + 16, menu.y + 14, 40, 40))
        text(scr, "Sourabh OS", (menu.x + 66, menu.y + 16), C["text"], "bold", 17)
        text(scr, f"user: {getpass.getuser()} · up {self.sys.uptime()}",
             (menu.x + 66, menu.y + 38), C["dim"], "sans", 12)
        mouse = pygame.mouse.get_pos()
        for r, (label, ic, (kind, _)) in rows:
            if r.collidepoint(mouse):
                rrect(scr, lighten(C["taskbar"], 28), r, 8)
            icon(scr, ic, (r.x + 8, r.y + 7, 22, 22), C["danger"] if kind in ("shutdown", "reboot") else None)
            text(scr, label, (r.x + 40, r.centery), C["text"], "sans", 14, "midleft")

    def _draw_toasts(self):
        now = time.time()
        self.toasts = [t for t in self.toasts if t[1] > now]
        sw, sh = self.screen.get_size()
        y = sh - TASKBAR_H - 12
        for msg, _ in reversed(self.toasts):
            f = font("sans", 13)
            w = min(460, f.size(msg)[0] + 28)
            r = pygame.Rect(sw - w - 14, y - 38, w, 34)
            rrect(self.screen, C["panel"], r, 8)
            rrect(self.screen, C["accent"], r, 8, 1)
            text(self.screen, msg, (r.x + 14, r.centery), C["text"], "sans", 13, "midleft", w - 24)
            y -= 42
