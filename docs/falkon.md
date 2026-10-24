# Falkon trial on socrat-3

Falkon was rejected after this trial. `ansible/playbooks/socrat-3-browser.yml`
now removes the Falkon package without autoremoving shared dependencies.
Use the main inventory together with `ansible/inventory/socrat-3.yml`.
The playbook does not change the default browser, desktop shortcuts, or Happ.

The trial used an explicit local Happ proxy:

```sh
env QTWEBENGINE_CHROMIUM_FLAGS='--proxy-server=http://127.0.0.1:10809' falkon https://chatgpt.com
```

This is a launch-time setting, not a provisioned browser preference. Happ must
already be connected. Do not enable TUN or disable the browser sandbox.

## Trial results, 2026-10-20

- Installed Debian package `25.04.1-1` without recommended packages.
- ChatGPT reached a Cloudflare human-verification prompt, not the application.
- A process-tree sample at that prompt measured approximately 575 MiB PSS.
  This is not a settled-page benchmark or a comparison with Firefox.
- The node had about 730 MiB available memory before installation, with no swap.
- During the trial, substantial memory and I/O pressure was observed. The node
  subsequently stopped reporting Kubernetes status and SSH connections stalled,
  while WireGuard ping still worked. The exact cause was not established.
- The trial was stopped. Telegram, YouTube playback, and a controlled Firefox
  comparison were not completed. Falkon is not selected as the default browser.
- A delayed SSH command terminated the trial's Falkon processes. The node
  returned to Ready without rebooting, and memory pressure subsided. No OOM-kill
  records were found in the inspected kernel journal. Happ remained running,
  but its proxy connection needed to be re-established.
- After restarting the Happ GUI and daemon and reconnecting the existing Main
  profile, both local proxy listeners returned. The SOCKS egress IP was
  `176.98.185.59`, Telegram returned HTTP 200 through that proxy, and all four
  Kubernetes nodes were Ready. TUN remained disabled. The Happ window was hidden
  again, and neither browser was left running.

Do not repeat the trial on the live control-plane node without sufficient memory
headroom and an independent way to stop the browser if SSH becomes unresponsive.
