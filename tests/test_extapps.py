"""Chrome launcher / taskbar integration tests. Run: SDL_VIDEODRIVER=dummy python3 -m tests.test_extapps"""
import os
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame  # noqa: E402
from sourabhos.extapps import parse_wmctrl, launch_browser, ExtWindow  # noqa: E402

WMCTRL = """0x00e00002 -1 openbox.Openbox         vm  Openbox
0x03200006  0 sourabhos.sourabhos     vm  Sourabh OS
0x03a00003  0 google-chrome.Google-chrome  vm  New Tab - Google Chrome
0x03a0000f  0 google-chrome.Google-chrome  vm  Sourabh OS docs — with spaces
"""


def fake_bin(d, name):
    log = os.path.join(d, name + ".log")
    path = os.path.join(d, name)
    with open(path, "w") as f:
        f.write(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    os.chmod(path, 0o755)
    return log


def test_parse():
    w = parse_wmctrl(WMCTRL)
    assert [x.title for x in w] == ["New Tab - Google Chrome", "Sourabh OS docs — with spaces"], [x.title for x in w]
    assert w[0].wid == "0x03a00003"


def test_launch():
    d = tempfile.mkdtemp()
    old = os.environ["PATH"]
    os.environ["PATH"] = d                  # nothing installed
    try:
        ok, msg = launch_browser(appliance=True)
        assert not ok and "install-chrome" in msg
        log = fake_bin(d, "google-chrome-stable")
        ok, msg = launch_browser("https://example.org", appliance=True)
        assert ok and "Chrome" in msg
        for _ in range(50):
            if os.path.exists(log):
                break
            time.sleep(0.05)
        args = open(log).read()
        assert "--no-first-run" in args and "https://example.org" in args, args
    finally:
        os.environ["PATH"] = old


def test_desktop_integration():
    from sourabhos.system import System
    from sourabhos.desktop.wm import Desktop
    from sourabhos.desktop.apps import Chrome, Terminal
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1366, 768))
    sysm = System(tempfile.mkdtemp())
    desk = Desktop(screen, sysm)
    # Chrome icon with no browser inside the OS image -> Terminal pre-filled with the fix
    os.environ["SOURABHOS_SYSTEM"] = "1"
    old = os.environ["PATH"]
    os.environ["PATH"] = tempfile.mkdtemp()
    try:
        assert desk.open(Chrome) is None
    finally:
        os.environ["PATH"] = old
        del os.environ["SOURABHOS_SYSTEM"]
    t = desk.windows[-1].app
    assert isinstance(t, Terminal) and t.edit.text == "install-chrome"
    # install-chrome outside the image explains what to do
    t.execute("install-chrome")
    for _ in range(40):
        time.sleep(0.05)
        if any("google.com/chrome" in l for l, _ in t.lines) or any("already installed" in l for l, _ in t.lines):
            break
    assert any("google.com/chrome" in l or "already installed" in l for l, _ in t.lines), t.lines[-4:]
    # outside windows show up on the taskbar and clicking one activates it
    hits = []
    w = ExtWindow("0x03a00003", "google-chrome.Google-chrome", "New Tab - Google Chrome")
    w.activate = lambda: hits.append(w.wid)
    desk.ext.windows = [w]
    desk.draw()
    r, target = desk.task_buttons()[-1]
    assert target is w
    desk.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=r.center, button=1))
    assert hits == ["0x03a00003"]
    if os.environ.get("SHOTS"):
        desk.draw()
        pygame.image.save(screen, os.path.join(os.environ["SHOTS"], "chrome-taskbar.png"))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
