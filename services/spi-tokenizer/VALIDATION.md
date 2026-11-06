
## Source-only local counter validation completed — 2026-11-06

CODE_READY for source only; **not activation or live acceptance**. This supersedes
the earlier unfinished lifecycle validation, not the blocked three-card live gate.
No current cards were queried or forced. Default remains byte-bound-v1.

### Installed-reference actual-payload oracles

Read-only SQLite historical prefixes were reconstructed through actual
Model.analyze; Model.call was intercepted before admission/transport. Payloads
were passed in pipes only, not persisted or printed. Installed CPU-only
AutoTokenizer.from_pretrained(local_files_only=True) in the existing vLLM
container applied add_generation_prompt=True, enable_thinking=False to the
actual messages. No generation/inference endpoint was used. Local native IDs
(add_special_tokens=False) matched reference IDs by SHA256 of canonical JSON
integer lists; rendered UTF-8 hashes and counts also matched in every row.

| Prefix | Input JSON bytes | Local reservation | Reference prompt | Prompt + 2500 | Headroom | IDs/render/count match |
|---|---:|---:|---:|---:|---:|---|
| e712 | 18421 | 9315 | 5366 | 7866 | 1449 | true |
| de23 | 22703 | 10999 | 7050 | 9550 | 1449 | true |
| 1cbe | 27564 | 12023 | 8074 | 10574 | 1449 | true |
| 0900 | 27203 | 12433 | 8484 | 10984 | 1449 | true |
| 613a | 28594 | 13229 | 9280 | 11780 | 1449 | true |
| 1482 | 21683 | 10826 | 6877 | 9377 | 1449 | true |
| 9b7 | 20980 | 10335 | 6386 | 8886 | 1449 | true |

Public ASCII contractions, NFC café, four-byte emoji, combining e+acute,
escaping and literal template/special-token injection fixtures also matched.
Empty-system rendering is separately exercised by the maximum-size fixture.
The manual render was confirmed for these supported inputs, not replaced by
rounding or a chars-per-token guess. Unsupported models/roles/tools/thinking
remain fail-closed. No private body/encoding cache exists.

Pinned public source base:
https://huggingface.co/RedHatAI/Qwen3.8-27B-INT4/resolve/91bd022d5b49442a868bc35008f6c21e1860edfa/

- tokenizer.json SHA256 06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523
- chat_template.jinja SHA256 c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041
- tokenizer_config.json SHA256 5f7aa0d810000c4a0940b35c8f16e56c3439260fccc13a321826ebc3ccf2501f
- tokenizers 0.22.2 musllinux wheel SHA256 38337540fbbddff8e999d59970f3c6f35a82de10053206a7562f1ea02d046fa5; immutable public wheel URL in services/spi-tokenizer/wheel-url.txt.

Reservation is exact supported rendered prompt count + full response-format
UTF-8 bytes + 256 allowance + explicit completion cap (2500 or 768), not exact
provider usage. Historic headroom is 1193 schema bytes + 256; public {} fixtures
have 258 headroom. Reservations are materially below the validated byte bound;
no provider-alias equivalence beyond this pinned contract is asserted.

### Regression, memory and effective scheduling

Separate ephemeral validation image added only Node v24.22.1 and git 2.54.0 to
the existing candidate, Python 3.13.18 unchanged. Production Dockerfile has no
Node/git. Absolute real paths were used for Docker mounts; the existing common
Git directory was mounted read-only at /Users/antonmoss/code/homelab/.git.
Final validation image 9b64190ce002ebfb12132816baa06129dd33d2c890bf67ce02e3af4538a84af3
is the tool-extended candidate with the same legal files overlaid, not a runtime
artifact. Source-only packaged production image:
5b9b9c6da929f902902d7b415d923000004e3ddcb6560bbb568c9d86fd4841d1.

All **206** SPI tests pass in local mode, 384MiB/1CPU/network none, zero skips,
errors or OOM; 41.337s, 277800 KiB peak process RSS, 24 retained Models share
one native counter (8.538s initialization/validation). Peak is not steady RSS.
All original correctness fixtures remain; no runtime feature edits. Native
asset/template/library/manifest failures reject Model construction before any
recovery/admission/HTTP calls; request model/roles/tools/thinking failures reject
accounting before admission/HTTP. Local 60k compressible JSON succeeds with a
valid fake response; deterministic incompressible 60k rejects before HTTP.
Legacy assertion explicitly selects byte-bound mode instead of hiding failures.

Byte-bound compatibility in the asset-equipped validation image: 206 tests pass,
zero skips (29.585s). Native host: 206 tests pass, three optional native class
cases skipped because the host lacks /opt/spi-tokenizer (4.095s); this is not
substituted for the zero-skip local image result. Helper suites: 4 chart + 1
writer-secret tests pass. Ingress JS: 9 pass, zero skips. Helm lint/template and
git diff --check pass.

New typed integer-cost fake-clock durable-ledger regression uses actual native
costs [3586,3586,3586], sum 10758 vs byte-bound [18299,18299,18299], sum 54897.
Three serial calls fit 30k TPM/3RPM; parallel reservation rejects; fourth rejects
until first completion+61 (161.999 rejects, 162 accepts). Reopening Store after
each completion retains charges; actual=1 never refunds. Upward actual=30000
persists across restart, blocks until completion+61 (223.999 rejects,224 accepts).
This proves synthetic effective admission, not live throughput or a card ETA.

### Packaging and operations

Build is deliberately a strict verified preloaded asset context, not a universal
fetch script: sh services/spi-tokenizer/build-local.sh /path/to/verified/assets.
No repeat 20MB download is required. Build/runtime pins and wheel are unchanged.
Matching immutable upstream tokenizers LICENSE and Rust LICENSE pointer are
preserved in services/spi-tokenizer/legal and copied into the internal image.
Commit f383101a26663708484cac0727792aad74f78234 (v0.22.2) recursive upstream tree
contains no NOTICE; none invented. See legal/PROVENANCE.md for exact public URLs,
hashes, model Apache-2.0 declaration/attribution and canonical Apache license.
No model weights, third-party shipping or certification of all transitives.

No push/deploy/queue/provider/resource changes; runtime network remains disabled
for validation. No source-phase claim about current three cards, no new probes,
nominee grouping or lifecycle redesign. Credentials, IDs, PVC, calendar/Yandex,
blog-off, Root network, Mac/DNS/edge unchanged. Rollback selects original image
and byte-bound-v1, preserving database/cache/v3 proofs and integer ledger charges.
