# Android TV helper apps

`tv-mode` and `tv-grafana` are small Android APKs that tvQuickActions launches for YouTube and Grafana. Their Android activities and VPN handoff logic are authored in Smali under each directory's `smali/` tree. The app manifests and Apktool configuration are alongside them.

Build the two APKs with:

```sh
./android/build.sh
```

The script downloads pinned Apktool 2.11.1 and uber-apk-signer 1.3.0 into the user cache, verifies both tool hashes, builds and signs the APKs, and checks that the signature matches the debug certificate currently installed on the TV. The checked-in build state makes an unchanged second run a no-op, avoiding APK signature timestamp churn. A fresh signed build can differ byte-for-byte because the APK signing data is not deterministic, but its signing certificate remains stable. `APKTOOL_JAR`, `UBER_APK_SIGNER_JAR`, and `ANDROID_TOOL_CACHE` can override the defaults.

The resulting `android/releases/tv-mode.apk` and `android/releases/tv-grafana.apk` are checked in so Ansible can install them without requiring Java or Android build tools on the server. Re-run the build script after changing Smali or manifests, then commit the updated APKs with their sources.

`android/releases/tv-hdmi.apk` is the original signed HDMI helper APK captured from the TV. Its signing key is not present in this repository, so it is kept as a binary recovery artifact and is not rebuilt by the script.

Install or refresh all three homelab helper apps on the authorized TV with:

```sh
cd ansible
ansible-playbook playbooks/tv-admin.yml --ask-become-pass
```

The playbook installs only the homelab helper APKs and grants their required Android permissions. Fully Kiosk, tvQuickActions, WireGuard, Happ, VPN profiles and subscription data remain external/manual setup. tvQuickActions stores button assignments in its private app data; the playbook does not rewrite them. The current assignments and the manual recovery steps are documented in [`../llm-wiki/android-tv.md`](../llm-wiki/android-tv.md).
