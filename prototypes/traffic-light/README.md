# Traffic Light — current Argo state strip (supersedes historical landscapes)

Owner rejected the historical stacked graph, including Symlog refinement, and
requested one thin real-time module with no title, legend, axes or history.

<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light?kiosk=1&hideLogo=1&autofitpanels=true>

## Current panel909

Native horizontal Bar chart, one stacked bar, x12,y8,w6,h1 (formerly h6).
All other panels stay put; the30 freed grid cells remain empty for owner plans.
Title/legend/axes/value labels hidden; no borders, full opacity. Fixed state colors.
Instant Prometheus **table** query, not range; newest observed argocd_app_info
labels per Application, excluding root, grouped once per app. A constant row label
plus native groupingToMatrix/organize transforms yields ONE row with six numeric
state columns. Percent stacking fills the module width; segment widths are shares
of the current observed inventory, not a timeline. Source values remain app counts.

- Ready (green): Healthy+Synced.
- Progressing (blue): health Progressing, not yet ready; not proof of Pod rollout.
- Suspended (amber): paused, deliberately distinct from active Progressing.
- Git drift (amber): OutOfSync unless a higher-priority state applies.
- Unhealthy (red): Degraded/Missing.
- Unknown (grey): unknown/unrecognized health or sync state.

Priority: Unhealthy > Unknown > Progressing > Suspended > drift > Ready. Unknown
sync prevents a healthy green state. Latest timestamp wins over older label sets;
contradictory same-time states still contribute once. No counter, increase, rate,
rolling window, last12h state history, top-k, Symlog, smoothing or synthetic sync.
Argo app health status has no separate generic Pending state; progressing/unknown
are rendered from actual exported status, never inferred from cumulative counters.

The dashboard refreshes5s. Raw Argo cadence was measured15s; refresh does not create
new samples faster than collection.90s freshness limit is a stale-data guard,
not averaging. Failed/down/absent/partially stale telemetry gives no data, not a
fully green bar. Fresh zero categories remain zero-width and do not draw outlines.
Inventory silently lost beyond Prometheus lookback cannot be distinguished from
actual deletion without a separate inventory source. Counts are Applications,
not Pods, deploys or full service availability. Hover gives state/count details.

## Build / validation / isolation

```sh
python3 scripts/build-traffic-light-argo.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
python3 -m unittest discover -s tests -p 'test_overview_capacity.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

32 tests cover instant/non-range native rendering configuration, no title/legend/
axes, single-row matrix shaping, six colors, current-state classification and
fresh zero/missing/down/partially stale telemetry plus lingering old status labels.
Suspended now has its own category. Fixture909 height1 leaves52 intentional empty
cells in24×16 grid. All other panel content/geometry and dashboard metadata remain
unchanged. Overview capacity gauges and Traffic Light CPU/Memory/Disk bars are
untouched. Helm diff changes only canonical ConfigMap payload. Live owner/source
comparison before edits found only API defaults/schema normalization, no uncaptured
manual edits. Existing canonical UID, public share and Fully/TV configuration stay.

TMP UID/ConfigMap and previews were retired earlier with exact UID/resourceVersion
cleanup; they are not recreated. Prior timeline/line/mosaic/landscape/Symlog
experiments remain in Git history only. No plugins, custom CSS/JS, collector
configuration, sync/prune, rollout or global dashboard-setting changes.

Native rendering refinement: percent scale is explicitly bounded0..1 so all-green
fills100% of the width (auto-ranging with integer decimals otherwise leaves half
empty). Both groupWidth/barWidth0.2 make the strip genuinely thin. Native transparent
panel option enabled. These are display bounds on normalized stacking; hover still
shows original counts, e.g. Ready48, not48% or a clipped value1. Mixed-color rendering
was checked only in an isolated browser response fixture, never by changing Argo
apps or production telemetry. Live data is checked separately without that fixture.

Acceptance: inspected the final deployed bar at1920×1080 in an isolated Viewer
browser on real data (HTTP200): Ready48, other categories0; full-width green thin
strip, hover retains count48. No history or visible legend/axis/title. Compared
live dashboard before/after: only909 differs; all nonversion settings and other
panels match.32 tests passed, Argo Synced/Healthy. Physical-TV acceptance remains
owner-side. Local synthetic mixed-state rendering was separate from this live check.

Owner thickness refinement: groupWidth/barWidth increased0.2→0.4, approximately
 doubling visible thickness. Panel remains x12,y8,w6,h1; no layout/query changes.

## Superseding owner layout capture — 11 November 2026

Owner manually rearranged live Traffic Light; captured separately before changes.
Current layout24×20: resourcesh10 atx8/13/18, right node columnx23, Argo strip
x0,y19,w12,h1. UP908 stays removed per owner. New node927 (socrat-5) is cloned from
node4926, in free x23,y7; IP tiles and all other owner panels stay put.98 empty cells.
Both width factors now1 for maximum native visible strip thickness, preserving
module bounds and raw current-state query. `build()` now updates thickness in the
existing canonical panel without rebuilding or resetting owner-edited geometry.
This supersedes earlier historical position/thickness/cell-count notes above.

Owner-layout refinement acceptance:32 tests passed and scoped Helm diff changes
only canonical ConfigMap. Live before/after comparison (normalizing empty API
defaults) confirms all existing owner panels/settings retained, except requested
909 width factors, plus new927. Node5 health query returns0 (OK), not stale fallback.
Inspected actual deployed TV URL at1920×1080 in isolated Viewer browser: right
column includes green5 and bottom Argo strip fills its existing module height;
current instant query HTTP200, Ready48. Physical television itself not inspected.

Latest owner-only recapture: node5 now immediately follows4 atx23,y5; VPS IP and
Home IP nowy6/y7. Panel907 width8→7, stillx16,y10,h4.102 intentionally empty cells.
Pulled live dashboard without additional design/query changes; updated geometry
fixture and assertions.32 tests passed. Supersedes earlier node5/IP positions and
empty-cell count. Existing strip and remaining owner edits retained.

TV/public thickness correction: width factors already1; fresh real public scene
at1920×1080 had strip canvas only27px withh1. Changed only909 gridPos.h1→2,
x0,y19,w12 unchanged.21-row fit,114 empty cells; other saved geometry untouched.
Preserved Fully settings, existing presentation assets, query/data and all owner
edits. Device ADB/Termux unavailable in current LAN; no physical-TV verification
or reload possible yet. New geometry needs page reload, not merely5s metric refresh.

## Current owner-approved direction: per-Application Bar gauge

Owner rejected continuous state-count strip and requested h1 battery-like blocks.
Captured live manual909.h1 first (e5c33ed). Native bargauge909 now x0,y19,w12,h1,
transparent, hidden values/names/legend, no unfilled area. One vertical equal-full
block per Application, sorted alphabetically via seriesToRows→sortBy(Metric)→
rowsToFields. One instant query, no history/count aggregation/averaging. Latest
priority classification retained; codes1..6 = original codes+1. Positive categorical
codes saturate display max1 equally; NOT readiness percentages or utilization.
Value mappings encode all6 state colors. Up/fresh90s/inventory completeness guards
still yield no data on absent/down/partial stale telemetry; no fabricated blocks.

Native Gradient display with fixed color mode + value mappings gives SOLID fills,
not a multistate gradient; avoids Basic mode's inherent2px outline and translucent
fill. Retro LCD subdivisions are NOT applications, so not used. Minimum size0,
name/value hidden: no reserved text area. Native Bar gauge has built-in outer
padding and10px inter-bar spacing without a supported override; no fake padding
option, plugins, CSS or Fully injection added. Header/title/legend absent.

Isolated browser-only48-app mixed-status fixture verified exact colors and stable
alphabetical order (reversed input frames), no production data/workload mutations.
Live bounded query independently returned48 unique app names, all code5=Ready.
32 tests pass, including extended promtool positive per-app code/gap/overlap tests.
Physical-TV access remains blocked as documented; actual public route checked
separately after deployment. Reload Fully page to pick up new visualization.

Deployed acceptance2e1c05ce: actual anonymous public scene (no interception),
1920×1080 and55%-viewport emulation both returned48 unique app frames and rendered
exactly48 blocks. Visible panel text empty; borders0px. Native blocks9.64×27.91px;
emulated26×72.09CSSpx. Live snapshot47 green Ready +1 grey Unknown (not synthetic).
Actual public screenshot inspected. Live normalized before/after confirms only909
changed and all other owner panels/settings retained. Argo Synced/Healthy.
Physical device/reload still not verified; mixed6-color renderer fixture was a
separate browser-only test, never production metric/app mutation.

## Inventory/fit/hover correction, latest request

Bounded live K8s inventory49 Applications. Actual public909 query returned48
unique names; set difference was exactlyroot, with no other missing/extra apps.
Official MCP Prometheus query was temporarily blocked by its Grafana-service DNS
lookup, so comparison used actual successful public panel-query frames instead.
Current per-app query now includesroot so total matches Argo (49 at this snapshot).
Historical `queries()` count tests retain default exclude-root semantics; current
`application_query()` explicitly usesinclude_root=True with completeness/freshness
across ALL Applications. Tests verifyroot is classified, not just added as zero.

Native Auto sizing ignores customminVizWidth0, uses default8. With48 bars, a narrow
signed-in panel showed last targets outside its right edge; DOM count alone was
insufficient acceptance. Sizing nowmanual,minVizWidth0,minVizHeight0. Browser tests
must verify every colored block AND link target is fully inside its panel, not
merely count DOM nodes. Native10px gaps remain. No CSS/JS/plugin changes.

Owner-requested height2 atx0,y19,w12;21-row fit and114 empty cells. One native data
link per field: title${__field.name}, URL Argo/applications/argocd/${__field.name},
targetBlank. Standard browser title on hover, not a custom Grafana tooltip; click
opens the matching app. No permanent text. Authenticated normal + kiosk preview
verified49 named links sorted identically to49 real query frames, native title
attributes resolved and first/middle/last target hover succeeds. TV public mode
remains intentionally noninteractive; user hover works on ordinary signed-in route.

Post-deployeb7cd6a3 acceptance: actual public query and signed-in normal/kiosk
routes return49 unique app frames, names exactly equal live K8s Application names.
All49 native link titles resolved; hovered EACH of49 targets successfully in normal
and kiosk at1920×1080 AND1440×900. All targets fully inside panel (no clipping).
Normal narrow viewport requires scrolling panel into view before lazy queries run;
not a missing-data failure. Public actual scene and55%-viewport emulation render49
colored blocks, each completely inside panel, no visible text/borders. Native public
block height76.66px at1920×1080. No query interception/fixtures in live acceptance.
Live dashboard comparison ignoring empty defaults/version confirms only909 changed;
32 tests pass, scoped Helm only canonical CM, Argo Synced/Healthy.

Device status changed during this run: documented192.168.0.19:5555 now responds but
ADB saysunauthorized (SSH useralchemmist). Model cannot be verified until authorized.
No authorization bypass, key reset, Fully reload or physical screenshot performed.

Physical-TV correction: real authorized ADB screenshot showed sparse hairlines,
not49 readable blocks, even after reloading Fully. AndroidDPR2, actual page viewport
1024×575/visualScale0.9375, NOT previous3491CSSpx emulation. Real CDP DOM49 bars:
panel503CSSpx, content485, native48×10px gaps480, eachbar0.10156CSSpx (≈0.19 physical).
Thus mere positive width/count/bounds acceptance was inadequate. Native fix only909
w12→24, use otherwise-empty right half; h2,x0,y19 and other panels unchanged. New
unit regression requires49 visible≥8CSSpx bars at1024/1440/1920. No data/workload
mutation or new CSS/JS/plugin. Fully55/font75/desktop/wideViewport kept unchanged.
Debugging temporarily enabled through UI for read-only DOM audit, to be restored
false and SSH/ADB forwards removed after real screenshot acceptance.

Physical acceptance0a5f53fb: real TV WebView after reload49 bars and49 named app
links; w24 panel1014CSSpx, every bar10.523CSSpx vs0.10156before; height28.578CSSpx
unchanged. Final ADB screenshot visually inspected and independently PNG scanline
counted49 colored runs of18–20physicalpixels.33 tests pass; exact live dashboard
comparison changes ONLY909.w12→24; scoped Helm only canonical CM, ArgoSynced/Healthy.
Debugging originalfalse restored via native UI, debug socket absent, ADB/SSHforwards
removed. Fully foreground and actual updated TV page left loaded, no owner reload
needed. No zoom/font/VPN/DNS/remote/HDMI changes; unrelated dirty VPN work untouched.

Owner manual recapture:322h1;323y8;312y9/h1;920y10/h5;909w12/h1.
Preserve owner compact layout; generator must not force full-width/h2 back.
20rows,94 intentional emptycells before adding Moscow indicator. Native fixed10px
Bar gauge gaps remain a known compact-TV limitation; no CSS change approved.

Moscow IP: new nativeStat928 atx23,y8,w1,h1 underHomeIP; source91.189.82.238:443,
service_id=edge-moscow, alertSocratServiceEdgeMoscowUnavailable, same grey/stale,
pending,down,ready semantics as existingpublic edges. TCP443 reachability from
blackbox, NOT authenticatedVPN/client or whole-nodehealth. No other panel altered.
Frozen nativeCollector bundles need additivejob as well asServiceMonitor; maintained
refresh_public_edge_probe now appends exact catalog-drivenjob cloned from owned
VPS blackboxjob, rejects conflicts, preserves oldjobs, idempotent. Native activation
is PENDING: current SSH user has no noninteractive sudo for the existing isolated
Collector activationplaybook. Do not claim live probe success fromArgoSync alone;
unavailable telemetry must remain grey, not fabricatedgreen. No broadPod/Prometheus
restart, privilegeddebug workaround, sudo bypass or TVpresentation change approved.
Live receiptb29ae9dd: monitoring-k3sSynced/Healthy; GrafanaAPI has928MoscowIP at
x23,y8,w1,h1. Its actual PromQL result=-2 (No telemetry), consistent with NOT yet
activating nativeCollectorjob. Scoped Helm4resources: canonicaldashboardCM,
service-probeServiceMonitor and rule, exporterDeployment onlychecksum/probes
annotation changed.40 focused tests passed. CollectorCM/runtime NOT patched or
restarted; existingprobe exporter rolled by its own Helm checksum. Completion
blocked on legitimate sudo for existing isolated native activation, not onArgo.

Moscow activation ACCEPTED (supersedes pending status above),11November2026:
sourcee5bd8332 uses stable owned /edge-moscow pool name because captured historical
numeric endpoint indices collide with current catalog indices. Collision was
caught BEFORE any write; regression added,41 focused tests pass. Fresh CM CAS
UID/resourceVersion/full-data tests; append exactly onejob, all priorjobs and
collector.yaml unchanged. Kubelet projected SHA matched candidate; nativebinary
validate passed in actual container environment; existing exact-image/PodUID/
containerID/fullbinarySHA guards then graceful stop of ONLY otel-cluster.
Same PodUID/volumes; Collector restartCount+1, otherthree containerIDs unchanged,
all Ready. Actual Grafana928 expression0=OK; probe_success1 at91.189.82.238:443,
fresh~5seconds. monitoring-k3sSynced/Healthy at e5bd8332. This proves TCP entrance
reachability fromblackbox, not authenticatedVPN/service/fullnode health.
Owner-supplied sudo used through ephemeral0600 passwordfile, removed in finally;
no credentials committed or printed. Private/tmp/moscow-activation-* receipts;
no Prometheus/Thanos/reloader/Pod/TV/DNS/VPN changes, unrelateddirtyfiles preserved.

Owner-approved TV-only CSS exception (supersedes prior no-CSS restriction for
this one panel): publicopt-in socratTv=1 + canonicalUID + native909 vertical
Gradient/hiddenlabels and verified native DOM only. Existing TV asset now marks
native row/cells/fills, padding8→3px, gap10→2px. Flex redistributes widths AND link
wrappers fill cells; changing margin alone leaves native JS-computed subpixel
widths. No generatedbars, colors/data/query/fieldconfig/links/layout edits. All
native states remain intact; unsupportedDOM/duplicateNames/noData fail closed.
Normal signed-in viewing/editing/kiosk and unrelated dashboards unchanged.

Preview acceptance: actualCSSviewport1024×575/DSF1.875 gives49 bars8.140625×12.640625
CSSpx in existingw12/h1, gap2px; before0.09375×2.640625. All other panel bounds
identical. Live49 and isolatedmixed-statefixture preserve nativecolors, alphabetical
names andcontainment.1920TVpreview passes; normal1920 has no compactionmarkers and
keeps8px padding.76 focusedtests pass; reviewedhandofffixture updatedONLYGrafana
policyCM/proxyDeployment hashes. ScopedHelm ONLY TVasset plus proxychecksum;
Nginx/SSO/routes/Grafana/database/otherworkloads unchanged. PhysicalTV pending.

PHYSICAL acceptancef37bdda6 (c6121e1feature + ordinarymerge of concurrentSPI work):
real WebView viewport1024×575,DPR2,visualScale0.9375 unchanged; before/after EXACT
panel rectx5,y549.34375,w502.9921875,h20.6484375.49 nativebars and49same names/order;
width0.10156→8.14CSSpx,height2.640625→12.6484375; gap2CSSpx, padding3CSSpx. Final
actualADB screenshot1920×1080 visually inspected and PNG scanline1050 independently
counts49 separate colored runs14–15physicalpx wide. Still ownerw12/h1; no full-row
stretch. No query/colors/native link/text data changes. Other panels/fonts/Fully
scale/network untouched. Screenshotprivate/tmp/tv-compact-actual-final.png, paired
DOMreceiptsprivate/tmp/tv-compact-dom-before.json/after.json. Debugfalse restored
throughnativeUI; socket absent, ADBforward andSSHloopback closed, ownUIXMLdeleted;
Fullyforeground and refreshedpage left loaded. ArgoGrafanaSynced/Healthy; HTTPasset
byte-identical toGitsource. No backendGrafana/database/Prometheus restarts.

Security diagnostic incident: closing an isolated Playwrightfixture emitted a
private public-share URL via default route.fetch error handler. Owner informed;
no token repeated here, no unauthorizedshare rotation. Explicit page.unrouteAll
wait + catch/suppressed private request details added to temporary verifier;
rerun completes cleanly. Viewer bearer not printed in this run. Capability renewal
is a separate owner decision; do not silently invalidate the TV URL.

Owner-approved quality expansion: nativepanels930–935 use ONLY88 formerly empty
cells, leaving5. Existing57panels, settings/publicshare and909CSS untouched;20rows.
930Resourcewait x12,y10,w4,h4: worst-node CPU/memory/I/O PSI some ratio5m, complete
fresh nodeinventory/up/pressurecollector guards; manual native sizing avoids clips,
leftnames; amber25%CPU/10%memory+I/O matches existingboundaries, not10m alert status.
931–933 x12/16/20,y14,w4,h4: localvLLM waitingcurrent+1htrend; TTFTp95 over15m only
with≥20 observations (Low sample distinct from No telemetry); rolling5m generated
tokens/s+1htrend. Not remoteLLM metrics/billing/full streamedHTTP duration. TTFT10/60s
visualbands are guidance, not owner-agreedSLO.934/935 x12/18,y18,w6,h2: lastsuccessful
LMS/n8n backupJob age, missing/never-successful/staletelemetry distinct; no restore
or offhost-integrity claim. Thresholds6/8h LMS,24/26h n8n. Explicitlatest -2 sentinel
and last reducer prevent oldrange values masquerading as fresh; no absent→green0.

Generator scripts/build-traffic-light-quality.py idempotent, preserves unrelated
panels/settings and newownergeometry, aborts onoverlap instead of movingpanels.
37dashboardtests +18TVstyle tests passed. All6 PromQLqueries accepted bynative
GrafanaAPI; isolated1024CSS preview used fresh native-query response snapshots,
NOT synthetic production activity or physicalTV proof. ScopedHelm onlycanonical
TrafficLightCM; nativeCollector/exporters/CSS/Fully/Argoapps otherwise unchanged.

Physicalquality acceptance8091d22b:63 panels, existing57 unchanged,49nativeArgo
fills retained; actualWebView1024×575/DPR2. All6 newpanel rects and EVERY rendered
text range fully inside panel/viewport. Firstrealcheck caught nativeleftname
ellipsis; shortened only930 labels toCPU·4/RAM·2/I/O·3 usingPromQL label_replace,
keeping fullnode labels and CPU25%override. Removed unusedstatemappings to retain
existing <240000 serializedConfigMap regression guard; did NOT relax size limit.
55focused tests pass. monitoring-k3sSynced/Healthy; onlycanonicaldashboardCM changed.

Final actualPNGprivate/tmp/tv-quality-final-fit.png inspected, independent scanline
counts49coloredArgo fills; nativeUIXML verifiedAI andbackup labels on screen.
Low sample shown honestly (<20observations), not fake0; queue0 is legitimate with
healthyfreshmetrics. Addedno workload probes/exporters/alerts/CSS/productionload.
Debugoriginalfalse restored, socket absent, ADB/SSHforward removed, ownUIXMLsdeleted.
Returning from Fullysettings transiently changed visualzoom and cropped page;
resolved via ONLY Fullyrestart after confirming no pending settingsimport, with
all saved zoom/font/VPN/DNS/presentation settings unchanged. Rechecked REAL final
fit AFTER cleanup/restart (not the earliercroppedPNG). TVleftloaded andforeground.
Private nativeAPI reads used after MCP fetchtimeouts; no credentials/logs exposed.

Current owner correction (featurec84e31dd) supersedes above AI/PSI expansion:
930HTTPworst3business5xx/1h;931RustFS RX/TXpurple,932Harborregistry RX/TXteal,
both x12/18,y14,w6,h4;934/935backupages remain;933retired.62panels/5holes.
Original57panels/settings/909CSS/VPN exact unchanged. Bothnetworkdirections5mB/s
with1hNativeStat sparklines; realcAdvisor counters, notS3objects/OCIcounts. Complete
freshcurrentPodcoverage and latestNoTelemetry sentinel; last reducer. HTTP0 only
fromfreshobservedcounter, missingbackendnothealthy. No nativeHarbor/RustFS business
scrape enabled/no workloads restarted. Currentsemantics/physicalacceptance and
safety details in llm-wiki/android-tv.md#current-service-diverse-layout--owner-correction11november2026.
60focusedtests; scopedHelmONLYTrafficLightCM, sizeguardretained. FinalactualTVPNG
/tmp/tv-services-final-fit.png afterdebugcleanup/restart inspected;4RX/TX labels,
units/backups fit,49Argo runs counted, purple/teal pixels confirmed. No newblue.

Latestownerdecision eb238f5e supersedesHTTPpanel:930 is ONEcompactpinkAIStat
(currentqueue +localTTFTp95/15m with20-observationLow sample guard). HTTPworst3
removed, other61panels includingRustFS/Harbor/backups exact unchanged. Missing
sourceboth-2, no fake0; no inventedlatencySLO.60focusedtests, scopedHelmONLYdashboard
CM, ArgoSynced/Healthy. ActualfinalTV `/tmp/tv-ai-final-fit.png` inspected: bothAI
labels fit, HTTPabsent,49Argo fills, pinkAI; debugremainedfalse/preferencesunchanged.
