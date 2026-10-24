# Start the Sourabh OS desktop on the first console.
# Escape hatch: Ctrl+Alt+F2 gives a normal login prompt (user sourabh / pass sourabh).
[ -f ~/.bashrc ] && . ~/.bashrc
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nolisten tcp vt1 >/tmp/sourabhos-x.log 2>&1
fi
