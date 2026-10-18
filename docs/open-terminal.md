# Open Terminal on socrat-1

Open Terminal 0.14.1 runs as one CPU-only pod in namespace `llm`, pinned to `socrat-1`. The official full image is pinned by digest. Its 10Gi local-path PVC persists `/home/user` and is retained on Helm uninstall. Local-path capacity is nominal, not a hard quota. The container has a 2 CPU / 4Gi memory limit and a 5Gi ephemeral-storage limit. Installed packages outside `/home/user` do not persist across recreation.

The service is internal: `http://open-terminal.llm.svc.cluster.local:8000`. There is no ingress, NodePort, host filesystem mount, Docker socket, or Kubernetes service-account token. NetworkPolicy permits inbound traffic only from Open WebUI pods and outbound traffic to cluster DNS and public HTTP/HTTPS destinations, excluding private and link-local networks. The image's passwordless sudo applies inside the container only.

This single-workspace deployment was initially administrator-only. At the operator’s request, its connection now has a `user:*` read grant and is visible to all authenticated Open WebUI users. All conversations that select it share the same workspace. Users share files and processes in this deployment. Use isolated workspaces or a suitable multi-user deployment for unrelated users.

Deploy from `ansible/`:

```sh
ansible-playbook playbooks/open-terminal.yml
```

The playbook generates `llm/open-terminal-api` once and deploys the chart. Preserve this Secret and PVC. To connect, copy `scripts/connect-open-terminal.py` to the controller and run it with `--admin-email <email>`; it prompts for the Open WebUI password without echo. The script verifies the server, preserves other connections, and registers `Socrat Terminal` with administrator-only access. It does not print API keys or save passwords.

Alternatively use Settings > Admin > Integrations > Open Terminal: add the internal URL, Bearer authentication and the `api-key` from Secret `open-terminal-api`. The key stays server-side. Select `Socrat Terminal` using the terminal/cloud icon in the chat composer. Native tool calling and Builtin Tools must be enabled for the selected model. Open Terminal provides `write_file`, `run_command`, and `display_file`; use the latter to present a generated artifact in the chat. Model inference continues through LiteLLM.

## Chat attachments

The deployment maintains a block in `/home/user/AGENTS.md` instructing the model to use a fresh conversation directory with `work/` and `outputs/`, and deliver final files with `display_file(path=..., inline=true)`. Open WebUI reads these instructions on every message with the terminal selected. Apply only these instructions without restarting services using `ansible-playbook playbooks/open-terminal-instructions.yml`. Other existing instructions are preserved. This is a model instruction, not enforced filesystem isolation. Published outputs must remain at their original paths for existing chat cards to work; no automatic deletion is configured.

The connection uses `config.chat_uploads: filesystem`. Select Socrat Terminal before attaching a file in a normal chat. Open WebUI uploads images and other attachments to the terminal's current directory and includes the file path in the message. The model can use `read_file` to inspect an image, `run_command` to process it with Python, and `display_file` to return the generated file. Uploading an image alone does not automatically include its pixels in the model context in this mode.

For an existing connection, apply the setting without restarting either service:

```sh
cd ansible
ansible-playbook playbooks/open-terminal-uploads.yml
```

The playbook preserves connection credentials, permissions and other connections, and verifies the setting through the client API. Its local administrative helper requires exactly one administrator with no MFA requirement; installations with MFA should set Chat Uploads to Filesystem through the authenticated administration UI. The registration script also applies filesystem uploads when creating or updating the connection.

Reload an already-open WebUI page after changing the setting. Existing attachments are not copied retroactively: attach them again with the terminal selected. Open WebUI v0.12.3 temporary chats keep images inline and bypass terminal uploads; use a normal chat for file processing. Without a terminal selected, attachments continue to use the usual WebUI upload flow.

Validation on 2026-10-18: in chat `00ce1d0b-9be0-4b7d-8781-f450514b41ab`, a synthetic 48×32 red/cyan PNG uploaded through the composer appeared immediately in the terminal Files view. The model processed it through `run_command` and returned a downloadable grayscale PNG using `display_file`. Browser verification confirmed the dimensions and every pixel's grayscale values (76 and 135). A second Ansible run reported zero changes.

References:
- https://github.com/open-webui/open-terminal/releases/tag/v0.14.1
- https://docs.openwebui.com/features/open-terminal/setup/connecting/

Validation on 2026-10-16: pod Ready on socrat-1 with zero restarts; anonymous file API rejected with 401; ordinary Open WebUI user cannot see the shared terminal; Kubernetes API egress blocked; public PyPI reachable; Python execution returned 42. In chat `603ea38b-c920-466c-9730-b6d74e58f2f4`, Qwen called `write_file` and `display_file`, created `/home/user/terminal-check.txt`, and the browser downloaded it successfully. The file contained `SOCRAT_TERMINAL_OK`.

## Dataset execution and HTML preview

For Qwen, the browser Code Interpreter capability is disabled in the persisted model metadata; Terminal and Builtin Tools remain enabled. Select Socrat Terminal in the chat. Python runs via `run_command` in the pod, with results saved under `/home/user`, then presented via `display_file`. Pyodide's `/mnt/uploads` is a separate browser filesystem and is not the terminal volume.

The failed cat analysis in chat `603ea38b-c920-466c-9730-b6d74e58f2f4` used Pyodide `execute_code`, whose urllib request failed. The proposed upstream CSV URL also returns HTTP 404. The model then hit a scalar `.clip` error, corrected it, and successfully generated a synthetic CSV; its subsequent model request timed out in LiteLLM at 600 seconds while vLLM had a single running sequence and up to seven queued requests. LiteLLM model request and stream timeouts are now 1800 seconds. This accommodates longer waits but does not increase GPU throughput or guarantee completion under arbitrary queue load.

A server-side validation retrieved the real MASS cats dataset from `https://vincentarelbundock.github.io/Rdatasets/csv/MASS/cats.csv`, verified 144 observations, generated two PNG charts, and saved `cat-analysis/report.html`. Open Files > cat-analysis > report.html in Open WebUI: the report renders in the right-hand sandboxed HTML Preview iframe. Both chart images were verified loaded. No same-origin relaxation or extra public port is needed. For live web apps, a server started inside the terminal appears under Ports and is proxied through Open WebUI.
