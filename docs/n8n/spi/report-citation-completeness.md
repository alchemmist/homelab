#19135: complete sentences ending with artifact citations

Root cause was the worker's generation-only punctuation guard, not malformed
JSON/truncation/S3. Retained response: normal stop,294 completion tokens; exact
generation schema/caps/candidate enum/facts regex passed. Four non-fact fields
contained complete sentences then allowlisted trailing citations. The guard
mistook the final closing bracket for an unfinished sentence.

Source888e47050aba33237e0aad7474f8fb9d2fddee44 interprets known trailing `[E###]`
groups only for sentence checking, returns original object unchanged. Unknown
trailing IDs, fragments, ellipses and arbitrary tails are not excused. No context
means no permission to ignore citation endings. No length/token/repair increase,
partial-output salvage or extra paid request. Rejection logs contain only fixed
field/reason/count metadata. Fact prompt now agrees with its mandatory period.

Offline original-response RED/GREEN proof plus459 native regressions, zero skips.
Original job naturally completed19140 before this fix, primary#16 comment6806785355.
Neither historical execution nor publication is rewritten. No manual replay.

Release43116486150; image sha256:6cb82014012eb042721b63400ac701015bfb0ea28a61ee9bfc3539af3e0ccf7f;
image-only homelab62e1443e645347e91d5e1f2bb61f7aae5a271f05. Initial global native
drain blocked on Calendar19300: no dispatch until natural success and fresh
asserted all-workflow native pending empty/logical owner0/paid0/processing0. SPI
admission paused/restored; no occupied replacement. Runtime hashes exact, Argo
Synced/Healthy. Native workflow graph/settings/credentials/static/pin/version and
unrelated automations unchanged; n8n not rolled out. No natural new report or
forced paid acceptance is inferred from runtime/tests or historical19140.
