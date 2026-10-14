# Desktop panel

The role installs the common Waybar JSON configuration and CSS into the existing
`~/.config/waybar/hypr-config.json` and `hypr-style.css` paths. Symlinks are followed
and previous contents are backed up. It does not restart the graphical session.

`homelab_waybar_profile` selects `desktop` or `laptop`; override
`homelab_waybar_modules_right` to customize the right-hand module list. The laptop
profile retains battery, brightness, personal VPN, update counters and caffeine.
The desktop profile retains GPU monitoring and its notification tray.

`homelab_hide_flameshot_tray: true` sets Flameshot's `disabledTrayIcon` option;
screenshot functionality and other tray applications remain available. To update
the running application, run `flameshot config --trayicon false` inside the user's
graphical environment.

The role also delivers its GPU, screen-sharing toggle, battery degradation and
package-update helper scripts to `~/scripts`, following existing symlinks and
backing up previous contents. The laptop caffeine helper is managed by the
`desktop_environment` role.

The laptop's personal VPN manager (`~/scripts/wireguard-manager.sh`) and `pinglo`
remain external desktop dependencies. The VPN toggle targets `wg0`, not the
cluster's `wg-socrat`; this role does not change either tunnel or grant network
administration privileges. Remove their modules from the profile on new nodes
where these personal integrations are not installed.

Both profiles use Waybar, Hyprland, jq, wofi, pamixer, gammastep and swaync.
Laptop brightness uses brightnessctl; battery degradation uses upower and bc;
update counters use checkupdates and paru. These programs are provided by the
existing desktop installation, not by this configuration role.
