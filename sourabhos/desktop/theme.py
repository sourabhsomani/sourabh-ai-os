"""Colours, fonts and small drawing helpers shared by the desktop and apps."""
import os
import pygame

THEMES = {
    "Midnight": {"wall_top": (18, 24, 38), "wall_bottom": (34, 52, 74), "accent": (56, 189, 178)},
    "Ember":    {"wall_top": (32, 18, 22), "wall_bottom": (84, 40, 32), "accent": (245, 146, 72)},
    "Forest":   {"wall_top": (14, 28, 22), "wall_bottom": (36, 70, 52), "accent": (140, 214, 110)},
    "Paper":    {"wall_top": (206, 210, 216), "wall_bottom": (168, 178, 192), "accent": (52, 110, 210)},
}

C = {
    "bg": (28, 31, 38),          # window body
    "panel": (36, 40, 49),       # toolbars / side panels
    "field": (20, 22, 28),       # text fields, terminal
    "line": (58, 64, 78),        # borders
    "text": (226, 230, 238),
    "dim": (140, 148, 164),
    "title": (44, 49, 60),
    "title_active": (52, 58, 72),
    "taskbar": (16, 18, 24),
    "danger": (232, 84, 84),
    "warn": (236, 190, 80),
    "ok": (110, 200, 120),
    "accent": (56, 189, 178),
}

PID_COLORS = [(56, 189, 178), (245, 146, 72), (140, 120, 240), (236, 190, 80),
              (232, 96, 140), (110, 200, 120), (80, 160, 240), (200, 130, 90)]

_FONT_PATHS = {
    "sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"],
}
_cache = {}


def font(kind="sans", size=14):
    key = (kind, size)
    if key not in _cache:
        f = None
        for path in _FONT_PATHS.get(kind, []):
            if os.path.exists(path):
                f = pygame.font.Font(path, size)
                break
        if f is None:
            name = {"mono": "dejavusansmono,liberationmono,couriernew,monospace",
                    "bold": "dejavusans,arial"}.get(kind, "dejavusans,arial")
            f = pygame.font.SysFont(name, size, bold=(kind == "bold"))
        _cache[key] = f
    return _cache[key]


def set_theme(name):
    t = THEMES.get(name, THEMES["Midnight"])
    C["accent"] = t["accent"]
    return t


def text(surf, s, pos, color=None, kind="sans", size=14, anchor="topleft", maxw=None):
    f = font(kind, size)
    s = str(s)
    if maxw is not None and f.size(s)[0] > maxw:
        while s and f.size(s + "…")[0] > maxw:
            s = s[:-1]
        s += "…"
    img = f.render(s, True, color or C["text"])
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def wrap(s, width, kind="sans", size=14):
    """Word-wrap text to a pixel width. Returns a list of lines."""
    f = font(kind, size)
    out = []
    for para in str(s).split("\n"):
        line = ""
        for word in para.split(" "):
            cand = word if not line else line + " " + word
            if f.size(cand)[0] <= width:
                line = cand
                continue
            if line:
                out.append(line)
            while f.size(word)[0] > width and len(word) > 1:   # very long word
                cut = len(word)
                while cut > 1 and f.size(word[:cut])[0] > width:
                    cut -= 1
                out.append(word[:cut])
                word = word[cut:]
            line = word
        out.append(line)
    return out


def rrect(surf, color, rect, radius=6, width=0):
    pygame.draw.rect(surf, color, rect, width, border_radius=radius)


def blend(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def lighten(c, amt=18):
    return tuple(min(255, v + amt) for v in c)


# ------------------------------------------------------------- vector icons
def icon(surf, kind, rect, color=None):
    """Draw a simple vector icon inside rect. No image assets needed."""
    color = color or C["accent"]
    r = pygame.Rect(rect)
    x, y, w, h = r
    if kind == "terminal":
        rrect(surf, (30, 34, 42), r, 6)
        rrect(surf, color, r, 6, 2)
        pygame.draw.lines(surf, color, False, [(x + w * .22, y + h * .32), (x + w * .42, y + h * .5),
                                               (x + w * .22, y + h * .68)], 3)
        pygame.draw.line(surf, color, (x + w * .48, y + h * .7), (x + w * .76, y + h * .7), 3)
    elif kind == "monitor":
        rrect(surf, (30, 34, 42), r, 6)
        rrect(surf, color, r, 6, 2)
        pts = [(x + w * .12, y + h * .62), (x + w * .32, y + h * .62), (x + w * .42, y + h * .3),
               (x + w * .56, y + h * .78), (x + w * .66, y + h * .5), (x + w * .88, y + h * .5)]
        pygame.draw.lines(surf, color, False, pts, 3)
    elif kind == "folder":
        pygame.draw.rect(surf, blend(color, (0, 0, 0), .25),
                         (x + w * .08, y + h * .2, w * .4, h * .2), border_radius=4)
        rrect(surf, color, (x + w * .08, y + h * .3, w * .84, h * .55), 5)
    elif kind == "file":
        pts = [(x + w * .22, y + h * .1), (x + w * .62, y + h * .1), (x + w * .8, y + h * .28),
               (x + w * .8, y + h * .9), (x + w * .22, y + h * .9)]
        pygame.draw.polygon(surf, (220, 224, 232), pts)
        for i in range(3):
            yy = y + h * (.42 + i * .14)
            pygame.draw.line(surf, (150, 156, 170), (x + w * .32, yy), (x + w * .7, yy), 2)
    elif kind == "program":
        icon(surf, "file", r)
        rrect(surf, color, (x + w * .44, y + h * .56, w * .5, h * .38), 4)
        text(surf, "VM", (x + w * .69, y + h * .75), (20, 20, 24), "bold", max(8, int(h * .2)), "center")
    elif kind == "editor":
        icon(surf, "file", r)
        pygame.draw.line(surf, color, (x + w * .45, y + h * .85), (x + w * .9, y + h * .35), 5)
    elif kind == "calc":
        rrect(surf, (30, 34, 42), r, 6)
        rrect(surf, color, r, 6, 2)
        rrect(surf, color, (x + w * .18, y + h * .14, w * .64, h * .2), 3)
        for i in range(3):
            for j in range(2):
                pygame.draw.circle(surf, color, (x + w * (.28 + i * .22), y + h * (.55 + j * .22)), max(2, w // 14))
    elif kind == "settings":
        cx, cy, rad = x + w / 2, y + h / 2, min(w, h) * .32
        import math
        for i in range(8):
            a = i * math.pi / 4
            pygame.draw.line(surf, color, (cx, cy), (cx + math.cos(a) * rad * 1.35, cy + math.sin(a) * rad * 1.35), max(3, w // 8))
        pygame.draw.circle(surf, color, (cx, cy), rad)
        pygame.draw.circle(surf, (30, 34, 42), (cx, cy), rad * .45)
    elif kind == "about":
        pygame.draw.circle(surf, color, r.center, min(w, h) * .42)
        text(surf, "i", r.center, (20, 20, 24), "bold", int(h * .5), "center")
    elif kind == "power":
        import math
        cx, cy, rad = x + w / 2, y + h / 2 + 1, min(w, h) * .36
        pygame.draw.arc(surf, color, (cx - rad, cy - rad, rad * 2, rad * 2), math.radians(120), math.radians(420), 3)
        pygame.draw.line(surf, color, (cx, cy - rad * 1.15), (cx, cy - rad * .1), 3)
    elif kind == "ai":
        import math
        cx, cy = x + w / 2, y + h / 2
        rrect(surf, (30, 34, 42), r, 8)
        rrect(surf, color, r, 8, 2)
        def star(sx, sy, rad, col):
            pts = []
            for i in range(8):
                a = i * math.pi / 4 - math.pi / 2
                rr = rad if i % 2 == 0 else rad * .32
                pts.append((sx + math.cos(a) * rr, sy + math.sin(a) * rr))
            pygame.draw.polygon(surf, col, pts)
        star(cx - w * .06, cy + h * .04, min(w, h) * .32, color)
        star(cx + w * .24, cy - h * .24, min(w, h) * .14, color)
    elif kind == "jobs":
        rrect(surf, (30, 34, 42), r, 8)
        rrect(surf, color, r, 8, 2)
        for i, frac in enumerate((.85, .6, .35)):
            yy = y + h * (.24 + i * .2)
            rrect(surf, blend(color, (30, 34, 42), .7), (x + w * .16, yy, w * .68, h * .12), 3)
            rrect(surf, color, (x + w * .16, yy, w * .68 * frac, h * .12), 3)
    elif kind == "models":
        rrect(surf, (30, 34, 42), r, 8)
        chip = pygame.Rect(x + w * .26, y + h * .26, w * .48, h * .48)
        for i in range(3):
            o = .32 + i * .18
            pygame.draw.line(surf, color, (x + w * o, y + h * .1), (x + w * o, y + h * .9), 2)
            pygame.draw.line(surf, color, (x + w * .1, y + h * o), (x + w * .9, y + h * o), 2)
        rrect(surf, (30, 34, 42), chip.inflate(4, 4), 4)
        rrect(surf, color, chip, 4)
        text(surf, "AI", chip.center, (16, 18, 24), "bold", max(8, int(h * .2)), "center")
    elif kind == "browser":   # generic globe (not any company's logo)
        cx, cy, rad = x + w / 2, y + h / 2, min(w, h) * .42
        pygame.draw.circle(surf, (30, 34, 42), (cx, cy), rad)
        pygame.draw.circle(surf, color, (cx, cy), rad, 2)
        pygame.draw.ellipse(surf, color, (cx - rad * .45, cy - rad, rad * .9, rad * 2), 2)
        pygame.draw.line(surf, color, (cx - rad, cy), (cx + rad, cy), 2)
        pygame.draw.line(surf, color, (cx - rad * .86, cy - rad * .5), (cx + rad * .86, cy - rad * .5), 1)
        pygame.draw.line(surf, color, (cx - rad * .86, cy + rad * .5), (cx + rad * .86, cy + rad * .5), 1)
    elif kind == "logo":
        rrect(surf, color, r, int(w * .22))
        text(surf, "S", r.center, (16, 18, 24), "bold", int(h * .56), "center")
