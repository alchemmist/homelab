# Rollback

Disconnect and remove only the `wg-socrat-admin.conf` profile from the WireGuard macOS app, then remove the generated profile and key files from the configured WireGuard application directory. Remove only the three resolver files managed by this role if split DNS is no longer needed:

```sh
sudo rm /etc/resolver/0.socrat.alchemmist.xyz /etc/resolver/1.socrat.alchemmist.xyz /etc/resolver/2.socrat.alchemmist.xyz
```

Leave unrelated files in `/etc/resolver` and `/etc/resolv.conf` unchanged. Remove the Mac peer from each node separately after confirming the profile is disconnected.
