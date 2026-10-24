"""Sourabh OS entry point: boot splash, then the desktop main loop."""
import argparse
import os
import sys
import time

import pygame

from .system import System, VERSION, is_appliance
from .desktop.theme import C, icon, text, font, blend
from .desktop.wm import Desktop


BOOT_STEPS = [
    "Starting Sourabh OS kernel services",
    "Mounting home directory",
    "Starting TinyVM memory manager",
    "Initialising scheduler (priority round-robin)",
    "Loading window manager",
    "Starting desktop",
]


def draw_splash(screen, system, t, spin):
    """One frame of the Sourabh OS boot screen. t = progress 0..1."""
    import math
    w, h = screen.get_size()
    top, bot = (10, 13, 22), (22, 34, 50)
    for y in range(0, h, 4):
        pygame.draw.rect(screen, blend(top, bot, y / h), (0, y, w, 4))
    acc = C["accent"]
    cx, cy = w // 2, h // 2 - 70
    glow = pygame.Surface((340, 340), pygame.SRCALPHA)
    for r in range(170, 60, -10):
        pygame.draw.circle(glow, (*acc, 6), (170, 170), r)
    screen.blit(glow, (cx - 170, cy - 170))
    # spinning arc around the logo
    rect = pygame.Rect(cx - 82, cy - 82, 164, 164)
    pygame.draw.circle(screen, blend(bot, acc, .25), rect.center, 82, 3)
    a = spin * 4
    pygame.draw.arc(screen, acc, rect, a, a + math.pi * .6, 4)
    icon(screen, "logo", (cx - 56, cy - 56, 112, 112), acc)
    text(screen, "Sourabh OS", (cx, cy + 120), C["text"], "bold", 46, "center")
    text(screen, "the AI operating system, written in Python", (cx, cy + 162), C["dim"], "sans", 15, "center")
    bar = pygame.Rect(cx - 170, cy + 200, 340, 6)
    pygame.draw.rect(screen, (40, 46, 60), bar, border_radius=3)
    pygame.draw.rect(screen, acc, (bar.x, bar.y, max(6, int(bar.w * min(1, t))), bar.h), border_radius=3)
    step = BOOT_STEPS[min(len(BOOT_STEPS) - 1, int(min(.999, t) * len(BOOT_STEPS)))]
    text(screen, step + "…", (cx, cy + 226), C["dim"], "sans", 13, "center")
    text(screen, f"version {VERSION}  ·  TinyVM {system.vm.cfg.physical_memory} B RAM, "
                 f"{system.vm.nframes} page frames", (cx, h - 28), blend(bot, (255, 255, 255), .35), "mono", 12, "center")


def splash(screen, system, clock):
    start = time.time()
    total = 2.2
    while True:
        for ev in pygame.event.get():
            if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                total = 0.0001
            elif ev.type == pygame.QUIT:
                return False
        el = time.time() - start
        t = el / total
        draw_splash(screen, system, t, el)
        pygame.display.flip()
        clock.tick(60)
        if t >= 1:
            return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sourabh OS desktop")
    ap.add_argument("--fullscreen", action="store_true", help="take over the whole screen (used by the OS image)")
    ap.add_argument("--size", default="1280x800", help="window size, e.g. 1366x768")
    ap.add_argument("--home", help="home directory (default ~/SourabhHome)")
    ap.add_argument("--no-splash", action="store_true")
    ap.add_argument("--screenshot", help=argparse.SUPPRESS)
    ap.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--splash-shot", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    os.environ.setdefault("SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR", "0")
    os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "sourabhos")        # lets the taskbar skip itself
    os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")     # stay put while Chrome is in front
    pygame.display.init()
    pygame.font.init()
    pygame.key.set_repeat(380, 32)
    pygame.display.set_caption("Sourabh OS")
    if args.fullscreen or is_appliance():
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        w, h = (int(v) for v in args.size.lower().split("x"))
        screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)

    system = System(args.home)
    clock = pygame.time.Clock()
    if args.splash_shot:
        draw_splash(screen, system, .62, .4)
        pygame.image.save(screen, args.splash_shot)
        return 0
    if not args.no_splash and not args.screenshot:
        if not splash(screen, system, clock):
            return 0
    desk = Desktop(screen, system)

    if args.demo or args.screenshot:
        _demo(desk)

    frames = 0
    while desk.running:
        dt = clock.tick(60) / 1000
        for ev in pygame.event.get():
            if ev.type == pygame.VIDEORESIZE and not (args.fullscreen or is_appliance()):
                desk.screen = pygame.display.set_mode(ev.size, pygame.RESIZABLE)
            desk.handle(ev)
        system.tick(dt)
        for w in list(desk.windows):
            w.app.update(dt)
        desk.draw()
        pygame.display.flip()
        frames += 1
        if args.screenshot and frames >= 90:
            pygame.image.save(screen, args.screenshot)
            break
    system.save()
    pygame.quit()
    return 0


def _demo(desk):
    """Open a few windows and start programs (used for screenshots)."""
    from .desktop.apps import Terminal, Monitor, Files
    sysm = desk.sys
    sysm.settings["vm_speed"] = 4
    for prog in ("memhog.tvm", "producer.tvm", "consumer.tvm", "countdown.tvm", "idle.tvm"):
        sysm.run_program(sysm.home / "Programs" / prog)
    f = desk.open(Files)
    f.rect.topleft = (150, 40)
    t = desk.open(Terminal)
    t.rect.topleft = (190, 420)
    t.rect.size = (640, 300)
    for cmd in ("ls Programs", "run fib.tvm", "uname"):
        t.app.say(t.app.prompt() + cmd, C["dim"])
        t.app.execute(cmd)
    m = desk.open(Monitor)
    sw, sh = desk.screen.get_size()
    m.rect.topleft = (sw - m.rect.w - 20, 20)
    m.app.sel = 1


if __name__ == "__main__":
    sys.exit(main())
