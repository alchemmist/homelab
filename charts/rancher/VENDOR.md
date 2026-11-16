# Rancher chart2.15.2, unchanged server version

Upstream: https://releases.rancher.com/server-charts/stable/rancher-2.15.2.tgz
UPSTREAM-SHA256.json records every original packaged file. All packaged scripts,
templates and README retained. No standalone license file shipped in that chart;
upstream licensing is not changed here. Only optional Pod hostAliases added to
template/default values, empty by default. Render with actual kube1.36.5; do not
bypass upstream kubeVersion. No bootstrap/user/AuthConfig/TLS changes.
