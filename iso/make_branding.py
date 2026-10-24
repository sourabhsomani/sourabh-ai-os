"""Generate Sourabh OS boot artwork (bootloader splash, GRUB background,
Plymouth logo) from the same theme the desktop uses.

    python3 iso/make_branding.py        # writes iso/branding/*
Run it again after changing the logo or colours in sourabhos/desktop/theme.py.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pygame  # noqa: E402
from sourabhos.desktop.theme import C, icon, text, blend  # noqa: E402

OUT = os.path.join(ROOT, "iso", "branding")
TOP, BOT = (10, 13, 22), (22, 34, 50)


def background(w, h):
    s = pygame.Surface((w, h))
    for y in range(h):
        pygame.draw.line(s, blend(TOP, BOT, y / h), (0, y), (w, y))
    glow = pygame.Surface((w, h), pygame.SRCALPHA)
    for r in range(int(h * .45), 20, -12):
        pygame.draw.circle(glow, (*C["accent"], 5), (w // 2, int(h * .36)), r)
    s.blit(glow, (0, 0))
    return s


def brand(s, cx, cy, logo, title_size, sub=True):
    icon(s, "logo", (cx - logo // 2, cy - logo // 2, logo, logo), C["accent"])
    text(s, "Sourabh OS", (cx, cy + logo // 2 + title_size), C["text"], "bold", title_size, "center")
    if sub:
        text(s, "the AI operating system, written in Python", (cx, cy + logo // 2 + title_size * 2),
             C["dim"], "sans", max(11, title_size // 3), "center")


def main():
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode((1, 1))
    os.makedirs(OUT, exist_ok=True)

    # 1) Live ISO bootloader menu (GRUB + ISOLINUX): 640x480, logo at top, menu below
    s = background(640, 480)
    icon(s, "logo", (40, 34, 56, 56), C["accent"])
    text(s, "Sourabh OS", (110, 40), C["text"], "bold", 30)
    text(s, "the AI operating system, written in Python", (112, 76), C["dim"], "sans", 13)
    pygame.image.save(s, os.path.join(OUT, "splash.png"))

    # 2) Installed-system GRUB background
    s = background(1024, 768)
    brand(s, 512, 200, 120, 40)
    pygame.image.save(s, os.path.join(OUT, "grub-bg.png"))

    # 3) Plymouth (Linux boot animation): transparent logo + 1px progress fill
    s = pygame.Surface((520, 300), pygame.SRCALPHA)
    brand(s, 260, 80, 130, 44)
    pygame.image.save(s, os.path.join(OUT, "logo.png"))
    p = pygame.Surface((4, 4))
    p.fill(C["accent"])
    pygame.image.save(p, os.path.join(OUT, "progress.png"))
    p.fill((40, 46, 60))
    pygame.image.save(p, os.path.join(OUT, "progress-bg.png"))
    print("branding written to", OUT)


if __name__ == "__main__":
    main()
