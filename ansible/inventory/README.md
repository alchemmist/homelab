# Ansible inventory

## Where to look

- `hosts.yml`: the complete `Socrat` group (`socrat-0` through `socrat-3`) and SSH connection settings.
- `host_vars/<node>.yml`: configuration specific to one node (boot services, desktop, storage, etc.). Ansible loads these automatically for that hostname.
- `group_vars/Socrat.yml`: shared cluster settings, including the default public SSH hostname and WireGuard registry.
- `group_vars/all.yml`: defaults shared by all inventory hosts.
- `netbird-controller.yml`: a separate connection alias, deliberately outside `Socrat`; cluster-wide plays must not target it.
- `direct.yml` and `lan.yml`: optional SSH connection overrides, not complete cluster inventories. Load them **after** `hosts.yml`.

`../ansible.cfg` loads `hosts.yml` and `netbird-controller.yml` by default. Do not point it at this entire directory: that would load maintenance overrides as ordinary defaults.

Connection settings stay in inventory files because `host_vars` has higher precedence: moving them there would prevent the maintenance inventories from overriding them. Other node configuration belongs in `host_vars`.

## Inspect without connecting

Run from `ansible/`:

```sh
ansible-inventory --graph
ansible-playbook playbooks/starship.yml --list-hosts
ansible-playbook playbooks/starship.yml --list-hosts --limit socrat-3
```

`hosts: Socrat` selects all four nodes unless narrowed by `--limit`. It does not select the separate controller alias. These commands only inspect inventory/play scope; they do not apply changes.

## Explicit inventory and maintenance access

```sh
# All four nodes, using the normal connections:
ansible-inventory -i inventory/hosts.yml --graph

# All four nodes, with direct connection overrides for nodes 0/1/2:
ansible-inventory -i inventory/hosts.yml -i inventory/direct.yml --graph

# All four nodes, with LAN connection overrides for nodes 0/1:
ansible-inventory -i inventory/hosts.yml -i inventory/lan.yml --graph
```

Explicit `-i` arguments replace the configured inventory sources. If a playbook needs the controller alias as well, also supply `-i inventory/netbird-controller.yml`.

The former `socrat-3.yml` inventory was merged into `hosts.yml`; its node configuration now lives in `host_vars/socrat-3.yml`. Old commands using both inventory files should use only `-i inventory/hosts.yml`. This consolidation preserves the previous default resolved inventory; commands explicitly using only `hosts.yml` now include node 3 too. Use `--limit 'Socrat:!socrat-3'` if intentionally targeting only nodes 0/1/2.

## Adding a node

1. Add its hostname and connection settings to `hosts.yml` under `Socrat`.
2. Add its configuration to `host_vars/<hostname>.yml`.
3. Review the WireGuard registry and other explicit node maps separately: inventory membership alone does not provision networking or enroll Kubernetes.
4. Inspect inventory and each relevant playbook with `--list-hosts` before applying anything.

Local regression tests: `python3 -m unittest discover -s tests -p 'test_inventory.py'` from the repository root. Resolved-inventory tests require `ansible-inventory` and never open SSH connections.
