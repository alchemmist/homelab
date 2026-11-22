# Reviewed npm release patches

The official Argo CD Labs server 0.9.0 declares a **dependency**, not a peer,
on Zod `^3.25.0`. The 1.x MCP SDK accepts `^3.25 || ^4.0`; Umami 0.2.0
already accepts Zod 4. We keep the Labs tools, transport and read-only mode.
The patch builds the actual server with explicit `zod/v4` imports, the SDK's
`registerTool` API and matching runtime/manifest metadata. Both consumers now
resolve one Zod 4.6.7. No out-of-range override or legacy peer resolution.

Pi 1.6.0 pins `@google/genai` 2.32.0. Its preinstall just echoes a message;
its protobufjs 7.6.6 dependency has a postinstall range-style warning. Neither
generates runtime assets. The patches delete those two manifest scripts from
the **installed artifacts**, not flags from a lock. No providers are removed.

`charts/openhands/files/pi-monori/patch_npm.py` is shared by the chart init
container and `setup-official-mcp.py`. It verifies the npm release SHA-512,
rewrites the reviewed files in memory, retains licenses and runtime files,
and emits deterministic tar files beside the materialized npm lock. The output
must match lock integrity. Offline MCP setup reuses the verified patched tar
from a previous setup or reconstructs it from the warmed npm cache in a fresh destination. Do not commit these archives or put them in a ConfigMap.

The gate admits these three local archives only for their reviewed owner,
package, version, local filename and output SHA-512. It still refuses install
hooks before transport and sends upstream name/version identities to OSV.
The dependency job also does fresh script-disabled strict-peer installs, checks
actual installed manifests, exercises the protobuf codec and Pi's relay model
selection, and calls the read-only Argo server over stdio against a loopback
fixture. Umami is listed over stdio, not activated in project settings.

For upgrades, inspect registry manifests **and** packed runtime files, remove
a patch if the upstream release is compatible, otherwise review and reproduce
both hashes. Generate npm v3 locks with the patched tar inputs (no scripts,
no `--force`), gzip the Pi lock with `gzip -n`, and run the dependency audit and
`scripts/quality/npm_smoke.py` before rollout. No deployment is part of the gate.
