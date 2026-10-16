# Socrat-3 lightweight family desktop

Socrat-3 uses Sway with floating windows, Waybar and a mouse-operated launcher.
GNOME remains installed as a fallback, but does not run in the Sway session.
GDM automatically logs alchemmist into `homelab-sway`. SSH, WireGuard and k3s
remain independent system services; switching the desktop does not reboot the
node or restart its networking.

## Everyday use

The desktop has single-click shortcuts for Firefox ESR, Files, Yandex Mail,
Gmail, Telegram, MAX, Video and Monitoring. Mail and messengers open their
official web versions in Firefox; account sign-in is left to the user.
Firefox is the default browser for links. Desktop applications use Russian;
both English and Russian UTF-8 locales remain installed.

Windows float rather than automatically tiling. Drag title bars to move them
and borders to resize them. The bottom panel provides a menu, open-window
icons, minimized-window chooser, minimize/maximize/close buttons, desktop
button, network settings, volume, language and clock. The window buttons
operate on the focused application. Click its taskbar icon or use «Окна» to restore a minimized window.
Volume supports wheel adjustment and a click opens the mixer.

- Alt+Shift or the language indicator switches English/Russian.
- Alt+Tab switches windows; Alt+F4 closes the focused window.
- Super+Return opens a terminal; Super+D opens the menu.
- Super+F toggles fullscreen.

Monitoring is not auto-opened over the desktop. Its shortcut starts Alacritty
with the dedicated `homelab-monitor` tmux session and the shared btm settings,
including the 600-second history. Closing that terminal preserves the monitor
session. The previous `tmp` session was retained during migration.

## Managed setup

The host inventory sets `homelab_laptop_desktop: sway`. From `ansible/`:

```bash
ansible-playbook playbooks/debian-laptop.yml \
  -i inventory/hosts.yml -i inventory/socrat-3.yml \
  --tags sway --ask-become-pass
```

The role installs the distribution packages, copies helpers under
`/usr/local/bin/homelab-sway-*`, deploys account configurations, validates Sway,
and sets the next graphical session preference. It does not automatically
close an existing graphical session during configuration updates.

Sway: `~/.config/sway/config`; Waybar: `~/.config/waybar/`; launcher styling:
`~/.config/wofi/`. The original wallpaper asset and transparent Alacritty
settings are retained. Desktop shortcuts use GTK3 layer-shell surfaces below
normal windows; the lightweight Polkit agent supports permission dialogs.

To reload the active Sway configuration from SSH, discover the account's
`/run/user/1000/sway-ipc.*.sock` and pass it through `swaymsg -s SOCKET reload`.
Helper executable changes apply on their next launch; restart the shortcut
process when changing its code. Do not assume the Wayland display is always
`wayland-0`; the active session used `wayland-1` during validation.

## GNOME fallback

To make GNOME the next session again:

```bash
ansible-playbook playbooks/debian-laptop.yml \
  -i inventory/hosts.yml -i inventory/socrat-3.yml \
  --tags gnome -e homelab_laptop_desktop=gnome --ask-become-pass
```

Update the inventory choice as well if the rollback should remain permanent.
After saving graphical work, restarting `gdm3` applies the selected session;
it closes graphical applications but does not restart SSH or the system.

## Validation and limits

Sway configuration validation and real GDM autologin succeeded. Screenshot
inspection confirmed wallpaper, shortcuts, panel and terminal transparency.
Mouse checks covered terminal minimization, the restore chooser, and browser
launch. English/Russian switching, btm startup and preservation after closing
its window were checked. All Kubernetes nodes remained Ready and SSH stayed
reachable throughout the desktop switch.

A comparable idle snapshot used approximately 1.0 GiB RAM with Sway versus
1.36 GiB with the previous GNOME session. This is a snapshot, not a controlled
benchmark or a guarantee for browser workloads. `vainfo` confirms hardware
H.264 decoding support; it does not advertise VP9/AV1 decoding. Actual video
performance still depends on the site's chosen codec and resolution.

This desktop migration does not activate the separate network-recovery test
boot image. The Wi-Fi routing and alx kernel fixes still require the planned
controlled test boot described in `socrat-3-network-recovery.md`.
