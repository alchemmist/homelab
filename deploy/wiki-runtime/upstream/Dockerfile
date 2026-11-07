FROM --platform=linux/amd64 harbor.socrat.alchemmist.xyz/homelab/wiki-runtime@sha256:9756abc78d1b3b492275240da1267185fd735f7771ba9f8a29cb9456a3ed9f27
USER root
# Preserve Socrat's existing Authentik groups-scope contract. Upstream main
# omits this scope; changing provider mappings during a theme upgrade is unsafe.
RUN python -c "from pathlib import Path; import hashlib; p=Path('/app/runtime/oidc.py'); assert hashlib.sha256(p.read_bytes()).hexdigest() == '4c13557168d761fe5d3f5ba6467754286793a374127c9aa16b952f802de7f004'; s=p.read_text(); old=\"'scope':'openid profile email'\"; assert s.count(old)==1; p.write_text(s.replace(old, \"'scope':'openid profile email groups'\"))"
USER 1000:1000
