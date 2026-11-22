# Ansible helpers

Controller-side programs and files that playbooks and roles install on managed hosts.
Use `ansible/scripts/` for helpers shared across plays; role-private payloads can also
live in `roles/<role>/files/`. Paths under `/usr/local/` in tasks refer to the
installed copies, not this source tree. Moving a source here does not authorize
running it locally or against a host.
