# Authwall

Owner gallery for the Authentik login background. [Architecture, RustFS object layout, image-quality decisions, migration history and operator checks](../../docs/applications/authwall/README.md).

Production workflow: [`n8n/derivatives-v2.json`](n8n/derivatives-v2.json). Application: `src/authwall/`; browser UI: `ui/`.

Local tests (with project dependencies installed):

```sh
cd services/authwall && PYTHONPATH=src python3 -m unittest discover -s tests -v
```
