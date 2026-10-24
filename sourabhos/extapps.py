"""Outside Linux apps (Chrome) running next to the Sourabh desktop.

In the OS image a tiny window manager (Openbox) gives those apps real windows;
this module launches them and lists their windows (via wmctrl) so they can
appear on the Sourabh taskbar.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import webbrowser

BROWSERS = ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser"]
CHROME_FLAGS = ["--no-first-run", "--no-default-browser-check", "--start-maximized"]
INSTALLER = "/usr/local/sbin/sourabh-install-chrome"
OWN_WM_CLASS = "sourabhos"


def find_browser():
    for b in BROWSERS:
        p = shutil.which(b)
        if p:
            return p
    return None


def launch_browser(url=None, appliance=False):
    """Start Chrome. Returns (ok, message)."""
    exe = find_browser()
    if exe:
        args = [exe, *CHROME_FLAGS] + ([url] if url else [])
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        return True, f"Opening {'Chrome' if 'chrome' in exe else 'Chromium'}…"
    if not appliance:
        # Running on your own PC: just use its default browser
        webbrowser.open(url or "https://www.google.com")
        return True, "Opened your system browser"
    return False, "Chrome isn't installed yet — run 'install-chrome' in the Terminal"


AI_ENGINE_INSTALLER = "/usr/local/sbin/sourabh-install-ai-engine"


def run_installer(path, on_line):
    """Run one of the OS image's sudo installers, streaming its output. True on success."""
    p = subprocess.Popen(["sudo", "-n", path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    for line in p.stdout:
        on_line(line.rstrip())
    return p.wait() == 0


def install_chrome(on_line):
    """Run the installer (OS image only), streaming its output. Returns True on success."""
    if not os.path.exists(INSTALLER):
        on_line("install-chrome works inside the Sourabh OS image.")
        on_line("On your own PC, install Chrome from https://www.google.com/chrome/")
        return False
    p = subprocess.Popen(["sudo", "-n", INSTALLER], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    for line in p.stdout:
        on_line(line.rstrip())
    return p.wait() == 0


class ExtWindow:
    """A window owned by another program (e.g. Chrome)."""
    icon = "browser"
    minimized = False

    def __init__(self, wid, wm_class, title):
        self.wid, self.wm_class, self.title = wid, wm_class, title

    def activate(self):
        if shutil.which("wmctrl"):
            subprocess.Popen(["wmctrl", "-i", "-a", self.wid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self):
        if shutil.which("wmctrl"):
            subprocess.Popen(["wmctrl", "-i", "-c", self.wid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse_wmctrl(out: str):
    """Parse `wmctrl -lx` output into ExtWindows, skipping the Sourabh desktop itself."""
    wins = []
    for ln in out.splitlines():
        parts = ln.split(None, 4)
        if len(parts) < 4:
            continue
        wid, desk, wm_class = parts[0], parts[1], parts[2]
        title = parts[4] if len(parts) > 4 else wm_class
        if desk == "-1" or OWN_WM_CLASS in wm_class.lower() or title == "Sourabh OS":
            continue
        wins.append(ExtWindow(wid, wm_class, title))
    return wins


class ExternalWindows:
    """Polls the window list in the background (no-op where wmctrl isn't available)."""

    def __init__(self, interval=1.5):
        self.windows: list[ExtWindow] = []
        self.enabled = bool(shutil.which("wmctrl")) and bool(os.environ.get("DISPLAY"))
        if self.enabled:
            threading.Thread(target=self._loop, args=(interval,), daemon=True, name="ext-windows").start()

    def _loop(self, interval):
        while True:
            try:
                out = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True, timeout=3).stdout
                self.windows = parse_wmctrl(out)
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(interval)
