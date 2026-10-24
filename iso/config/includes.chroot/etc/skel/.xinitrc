#!/bin/sh
xset s off -dpms 2>/dev/null
xsetroot -cursor_name left_ptr 2>/dev/null
# Tiny window manager so Chrome and other Linux apps get proper windows
command -v openbox >/dev/null && openbox &
# If the desktop crashes, start it again instead of dropping to a black screen.
while true; do
    /usr/local/bin/sourabhos --fullscreen
    [ -f /tmp/sourabhos-logout ] && rm -f /tmp/sourabhos-logout && break
    sleep 1
done
