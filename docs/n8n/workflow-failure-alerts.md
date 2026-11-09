# Native n8n workflow failure notifications

Source: `workflow-failure-alerts.json`; operator sync:
`scripts/n8n/sync_failure_alerts.py` (default read-only plan, explicit `--apply`).
This is a native Error Trigger workflow, NOT a Prometheus error-count threshold.
The six current business workflows are enrolled through `settings.errorWorkflow`.
No business graph, credential reference, application static data, execution history
or active state is intentionally changed. Native re-registration can replace a
GitHub trigger subscription ID/signing secret; its event selection and other
node/global state must remain unchanged. Verify a single active replacement hook
and removal of the old one; do not restore obsolete hook secrets. New workflows must also be enrolled; this is not an
instance-wide automatic default. Run the plan/sync after provisioning new ones.

## Delivery and privacy

`Workflow Failed → Prepare Safe Notification → Send Failure Alert` posts directly
to existing Socrat bot `/v1/messages` using the existing encrypted `httpHeaderAuth`
credential reference from Socrat Alerts. It does NOT call the Socrat Alerts
webhook, queue SPI analysis or depend on the failing workflow's credentials.
A Socrat Alerts failure can therefore be reported without recursively invoking it.
No separate Telegram bot token, model call or workflow-error credential is created.

The English notification includes workflow name, original execution ID, failed
node if available and a fixed-origin authenticated execution link. It never
forwards raw error.message/stack/context, credentials, headers, node input/output
or caller-provided execution URL. Trigger failures without an execution ID link
to the workflow instead. Normal failures have a stable per-execution fingerprint;
trigger-only events use the handler execution ID. These are notifications, not
continuous incidents: no invented Resolved event or 20-minute recovery window.

Native n8n necessarily hands its private error payload to Error Trigger. The
handler disables success/error/manual execution-body retention and execution
progress saving; that is not a guarantee against transient storage on a crash.
Raw original failure details remain behind the existing n8n SSO, not in Telegram.
Transport retries are disabled: a timeout can be an ambiguous successful send;
no exactly-once delivery or acknowledgement is claimed.

## Runtime semantics and limits

- Normal automatic production execution errors invoke Error Trigger. Manual test
  executions do not, as implemented by n8n's native lifecycle hooks. Waiting,
  cancellation and a caught/continued error that ends in success are not failed
  executions. Process crashes/total n8n outages may prevent native notification.
- The handler needs no schedule/webhook activation; native error hooks invoke it
  while it is inactive. It has no `errorWorkflow` target. It cannot report its own
  broken transport through that same transport; retain independent service-health
  monitoring. Existing SPI/Grafana alert rules are untouched.
- Settings apply to newly registered/new executions after enrollment. Existing
  in-flight/Wait executions carry saved workflow settings and are not rewritten.
- Active business workflows are updated/published with their IDENTICAL graph/settings
  plus the one error target so cached timer/trigger registrations see it. Inactive
  ones stay inactive. Existing drafts differing from published graphs, competing
  handlers, concurrent changes or unexpected readback drift cause a stop. There
  is no API CAS; immediate pre-write comparison reduces but does not eliminate
  the race. No manual execution, forced retry or deactivate call is used.
- Native API key stays stdin/in memory over approved private SSH and same-instance
  localhost API; no secret-bearing argv/env, auth fallback or database mutation.

## Acceptance

Offline tests exercise safe payload projection, stable IDs, trigger-only failures,
no raw-error/URL forwarding, no recursive/SPI ingress, update guards/idempotence,
preserved active state, only-settings changes and the narrow native GitHub
registration lifecycle exception (no broad static-data drift suppression). Live setting/published-version
readback and the first NATURAL delivery are separate acceptance steps. Do not
manufacture a failed production execution or send a test alert without approval.
