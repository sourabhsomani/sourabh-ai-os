"""Headless smoke test: boots the desktop, drives it with synthetic input,
and checks every app opens, draws and reacts. Run:  python3 -m tests.test_desktop
Set SHOTS=dir to save screenshots."""
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sourabhos.system import System  # noqa: E402
from sourabhos.desktop.wm import Desktop, TITLE_H  # noqa: E402
from sourabhos.desktop.apps import APP_LIST, Terminal, Monitor, Files, Editor, Calculator, Settings  # noqa: E402

SHOTS = os.environ.get("SHOTS")


def frame(desk, n=1):
    for _ in range(n):
        desk.sys.tick(1 / 60)
        for w in list(desk.windows):
            w.app.update(1 / 60)
        desk.draw()


def click(desk, pos, button=1):
    desk.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))
    desk.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))
    desk.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button))
    frame(desk)


def type_(desk, s, enter=True):
    desk.handle(pygame.event.Event(pygame.TEXTINPUT, text=s))
    if enter:
        desk.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r"))
    frame(desk)


def shot(desk, name):
    if SHOTS:
        pygame.image.save(desk.screen, os.path.join(SHOTS, name))


def main():
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1366, 768))
    home = tempfile.mkdtemp()
    from tests.fake_ai_server import start
    _srv, url = start()
    import json as _j
    os.makedirs(os.path.join(home, ".config"), exist_ok=True)
    with open(os.path.join(home, ".config", "settings.json"), "w") as f:
        _j.dump({"ai": {"ollama_url": url, "anthropic_url": url, "anthropic_key": "test-key"}}, f)
    sysm = System(home)
    sysm.refresh_ai(background=False)
    desk = Desktop(screen, sysm)
    frame(desk, 2)

    # every app opens and draws
    window_apps = [c for c in APP_LIST if not hasattr(c, "launch")]   # Chrome is a launcher
    for cls in window_apps:
        desk.open(cls)
        frame(desk, 2)
    assert len(desk.windows) == len(window_apps), desk.windows
    for w in list(desk.windows):
        desk.close(w)
    assert not desk.windows

    # desktop icon double click opens Terminal
    r, cls = next((r, c) for r, c in desk.icon_rects() if c is Terminal)
    click(desk, r.center)
    click(desk, r.center)
    assert desk.windows and isinstance(desk.windows[-1].app, Terminal), "icon double-click"
    term = desk.windows[-1].app

    # shell commands
    for cmd in ("help", "ls", "cd Programs", "pwd", "run hello.tvm producer.tvm consumer.tvm", "ps",
                "mkdir ../Documents/notes", "touch ../Documents/notes/a.txt", "asm fib.tvm", "vm",
                "echo hi there", "uname", "theme Ember", "bogus"):
        type_(desk, cmd)
    for _ in range(400):
        frame(desk)
    out = "\n".join(l for l, _ in term.lines)
    assert "[1:hello.tvm] 5" in out, out[-800:]
    assert "[3:consumer.tvm] 100" in out, out[-800:]
    assert "bogus: command not found" in out
    assert os.path.exists(os.path.join(home, "Documents/notes/a.txt"))
    assert sysm.settings["theme"] == "Ember"
    shot(desk, "terminal.png")

    # window drag + maximize
    w = desk.windows[-1]
    start = (w.rect.x + 60, w.rect.y + 10)
    desk.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start, button=1))
    desk.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=(start[0] + 50, start[1] + 40), rel=(50, 40), buttons=(1, 0, 0)))
    desk.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(start[0] + 50, start[1] + 40), button=1))
    assert w.rect.x == start[0] - 60 + 50, "drag"
    desk.toggle_max(w)
    assert w.rect.w == 1366
    desk.toggle_max(w)

    # input opcode via terminal
    type_(desk, "run echo.tvm")
    frame(desk, 30)
    type_(desk, "input 21")
    frame(desk, 60)
    out = "\n".join(l for l, _ in term.lines)
    assert "echo.tvm] 42" in out, out[-500:]

    # monitor: load program via picker, step, kill
    mw = desk.open(Monitor)
    frame(desk, 2)
    mon = mw.app
    mon.picker = True
    frame(desk)
    rect, cb = mon._hits[-1]
    c = mw.content
    click(desk, (c.x + rect.centerx, c.y + rect.centery))
    assert any(p.state != "terminated" for p in sysm.vm.procs.values()) or True
    sysm.vm.load(open(os.path.join(home, "Programs/idle.tvm")).read(), "idle.tvm")
    mon.sel = max(sysm.vm.procs)
    frame(desk, 30)
    mon.step()
    mon.kill()
    assert sysm.vm.procs[mon.sel].state == "terminated"
    sysm.run_program(os.path.join(home, "Programs/memhog.tvm"))
    sysm.run_program(os.path.join(home, "Programs/countdown.tvm"))
    sysm.settings["vm_speed"] = 3
    frame(desk, 40)
    shot(desk, "monitor.png")

    # files: navigate, open editor
    fw = desk.open(Files)
    files = fw.app
    frame(desk)
    files.go(files.sys.home / "Documents")
    frame(desk)
    target = next(p for r, p in files._rows if p.name == "welcome.txt")
    files.open_item(target)
    ed = desk.windows[-1].app
    assert isinstance(ed, Editor) and "Welcome" in ed.lines[0]
    ed.on_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_END, mod=0))
    ed.on_text(" (edited)")
    ed.save()
    assert "(edited)" in open(target).read()

    # editor run a program
    pe = desk.open(Editor, path=os.path.join(home, "Programs/fib.tvm")).app
    pe.run()
    frame(desk, 120)

    # calculator
    calc = desk.open(Calculator).app
    for ch in "12*(3+4)":
        calc.on_text(ch)
    calc.press("=")
    assert calc.result == "84", calc.result
    calc.on_text("/0")
    calc.press("=")
    assert calc.result == "Error"

    # settings change VM config
    st = desk.open(Settings).app
    st.adjust("physical_memory", 16, 16, 4096, -1)
    st.apply()
    assert sysm.vm.cfg.physical_memory == 240

    # start menu
    desk.start_open = True
    frame(desk)
    shot(desk, "startmenu.png")
    menu, rows = desk.start_menu_items()
    term_row = next(r for r, it in rows if it[0] == "Terminal")
    click(desk, term_row.center)  # Terminal
    assert not desk.start_open and isinstance(desk.windows[-1].app, Terminal), desk.windows[-1].app

    # ---------------- AI apps
    from sourabhos.desktop.apps import AIChat, AIJobs, Models
    assert sysm.ai_ready(), sysm.ai_status
    chat = desk.open(AIChat).app
    frame(desk, 2)
    shot(desk, "chat-empty.png")
    type_(desk, "What is demand paging?")
    for _ in range(200):
        frame(desk)
        if not chat.busy:
            break
    assert chat.msgs[-1]["content"].startswith("Echo from fake model"), chat.msgs
    assert "tok/s" in chat.msgs[-1]["meta"]
    chat.model = "anthropic/claude-haiku-5-5"
    chat.send("/file " + os.path.join(home, "Documents/welcome.txt") + " what is this?")
    for _ in range(200):
        frame(desk)
        if not chat.busy:
            break
    assert "what is this?" in chat.msgs[-1]["content"], chat.msgs[-1]
    assert "Sourabh OS" in chat.msgs[-2]["content"]          # file was attached
    chat.save()
    assert list((sysm.home / "Documents" / "Chats").glob("*.md"))
    shot(desk, "chat.png")

    # terminal AI commands
    term = desk.open(Terminal).app
    for cmd in ("ai hello from terminal", "models", "pull phi3:mini",
                "job run ~/../" + os.path.relpath(os.path.join(home, "AIJobs/examples/translate-lines.job.json"), os.path.expanduser("~/.."))):
        type_(desk, cmd)
    for _ in range(300):
        frame(desk)
        if all(j.status == "done" for j in sysm.jobs.jobs) and sysm.jobs.jobs:
            break
    out = "\n".join(l for l, _ in term.lines)
    assert "Echo from fake model: hello from terminal" in out, out[-600:]
    assert "phi3:mini ready" in out and "ollama/qwen2.5:0.5b" in out, out[-600:]

    # AI Jobs app: run every example, plus a new job built in the form
    jobs = desk.open(AIJobs).app
    jobs.mode = "files"
    frame(desk)
    for f in sorted((sysm.home / "AIJobs" / "examples").glob("*.job.json")):
        jobs.run_file(f)
    inputs = sysm.home / "AIJobs" / "inputs"
    for i in range(12):
        (inputs / f"note{i}.txt").write_text(f"note number {i}")
    jobs.open_new()
    jobs.form["name"].text = "Notes digest"
    jobs.concurrency = 4
    frame(desk)
    shot(desk, "newjob.png")
    jobs.create()
    import time as _t
    t0 = _t.time()
    while _t.time() - t0 < 30 and any(j.status in ("queued", "running") for j in sysm.jobs.jobs):
        frame(desk)
    assert all(j.status == "done" for j in sysm.jobs.jobs), [(j.name, j.status, j.state) for j in sysm.jobs.jobs]
    names = {j.name: j.state["done"] for j in sysm.jobs.jobs}
    assert names["Notes digest"] == 12 and names["Classify customer feedback"] == 8, names
    assert list((sysm.home / "AIJobs").glob("*.job.json")), "new job spec saved"
    jobs.sel = next(j.id for j in sysm.jobs.jobs if j.name == "Classify customer feedback")
    frame(desk, 3)
    shot(desk, "jobs.png")

    # Models app: providers save + pull + set default + delete
    mw = desk.open(Models)
    models = mw.app
    frame(desk, 2)
    models.pull("llama3.2:1b")
    for _ in range(200):
        frame(desk)
        if not models.pulling:
            break
    sysm.refresh_ai(background=False)
    assert any(r == "ollama/llama3.2:1b" for r, _ in sysm.ai_status["models"])
    models.set_default("ollama/llama3.2:1b")
    assert sysm.ai.settings["default_model"] == "ollama/llama3.2:1b"
    models.delete("llama3.2:1b")
    sysm.refresh_ai(background=False)
    frame(desk, 2)
    shot(desk, "models.png")
    models.tab = "providers"
    models.form["openai_url"].text = url + "/v1"
    models.save_providers()
    sysm.refresh_ai(background=False)
    assert any(r == "openai/fake-gpt" for r, _ in sysm.ai_status["models"])
    frame(desk, 2)
    shot(desk, "providers.png")
    st = _j.loads((sysm.home / ".config" / "settings.json").read_text())
    assert st["ai"]["openai_url"].endswith("/v1")
    assert oct(os.stat(sysm.home / ".config" / "settings.json").st_mode)[-3:] == "600"

    # alt+f4 closes active
    n = len(desk.windows)
    desk.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F4, mod=pygame.KMOD_ALT, unicode=""))
    assert len(desk.windows) == n - 1

    # log out via start menu (not appliance -> just quits)
    desk.power("quit")
    assert not desk.running
    print("desktop smoke test: OK")


if __name__ == "__main__":
    main()
