# Authentik wallpapers

Owner gallery for the Authentik login background. [Architecture, RustFS object layout, image-quality decisions, migration history and operator checks](../../docs/applications/authentik-wallpapers/README.md).

Production workflow: [`n8n/derivatives-v2.json`](n8n/derivatives-v2.json). `n8n/workflow.json` is obsolete. Application: `src/wallpapers/`; browser UI: `ui/`.

Local tests (with project dependencies installed):

```sh
cd services/authentik-wallpapers && PYTHONPATH=src python3 -m unittest discover -s tests -v
```
