"""Chrome launcher: starts Google Chrome in its own window next to the desktop."""
from ...extapps import launch_browser
from ...system import is_appliance


class Chrome:
    title = "Chrome"
    icon = "browser"
    single = True
    size = (0, 0)

    @staticmethod
    def launch(desk, url=None, **kw):
        ok, msg = launch_browser(url, appliance=is_appliance())
        desk.toast(msg)
        if not ok:   # offer the one-line fix right away
            from .terminal import Terminal
            w = desk.open(Terminal)
            w.app.say("Chrome is not installed. Press Enter to install it (needs internet):")
            w.app.edit.text = "install-chrome"
            w.app.edit.cur = len(w.app.edit.text)
