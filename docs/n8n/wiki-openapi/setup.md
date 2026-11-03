# Wiki OpenAPI refresh

Same shape as Blog Updates: a GitHub push trigger in n8n, and a private worker that does the work.
The trigger cannot filter by path, so it subscribes to every push in `alchemmist/socrat-bot`.
The worker continues only when the push is to `main` and the GitHub compare shows `openapi.yaml`.

## Stages

`Bot push → Spec changed → Render wiki page → Create Pull Request → Close older proposals`

- Render runs `scripts/render_wiki.py` from the same bot commit as the spec. The page is not written by the model.
- The pull request changes only `wiki/content/platform/socrat-bot.md` in `alchemmist/homelab`.
- It is opened by the GitHub App `socrat-bot`, the same app that opens SPI issues.
  This workflow uses its own installation token (contents and pull requests on homelab). The SPI token is unchanged and still cannot open pull requests.
- After the pull request exists, Qwen via LiteLLM sees only other open pull requests that this same app opened and that carry the marker `wiki-openapi-refresh`.
  It may close those. It cannot see or close anything else. The new pull request stays open.
- No auto-merge.

## Writes

The GitHub App `socrat-bot` has Contents: Read and write on the homelab installation. The broker is running and `WRITE_ENABLED` is `true`.
The n8n workflow stays inactive until it is switched on, so a push does not open a pull request by itself yet.

## Secrets

`python3 scripts/n8n/provision_wiki_openapi.py` creates, without printing them:

- LiteLLM virtual key `socrat-wiki-openapi`, model `qwen3.8-27b`, 3 requests/minute, stored in `automation/wiki-openapi` with the worker token.
- Empty `automation/wiki-openapi-github`, filled later by the broker.
- n8n header credential. The GitHub trigger reuses the existing blog-updates GitHub credential, which must be allowed to manage webhooks on `socrat-bot`.

The workflow is synced inactive. Activate it in n8n after the credential save. Do not commit tokens.

Source: `scripts/wiki_openapi/`, `deploy/wiki-openapi/worker.yaml`, `docs/n8n/wiki-openapi/workflow.json`.
Tests: `python3 -m unittest tests/wiki_openapi/test_flow.py -v`.
Apply: `python3 scripts/wiki_openapi/deploy.py`.
