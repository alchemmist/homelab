#!/usr/bin/python
"""Install one UTF-8 user unit and synchronously reload its owning manager."""

import grp
import os
import pwd
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile

from ansible.module_utils.basic import AnsibleModule


def main() -> None:
    """Report success only when both the file and the manager are current."""
    module = AnsibleModule(
        argument_spec={
            "dest": {"type": "path", "required": True},
            "content": {"type": "str", "required": True},
            "owner": {"type": "str", "required": True},
            "group": {"type": "str", "required": True},
        },
        supports_check_mode=True,
    )
    result = {"changed": False}
    uid = os.geteuid()
    if pwd.getpwuid(uid).pw_name != module.params["owner"]:
        module.fail_json(msg="Run this task as the unit owner", **result)
    try:
        gid = grp.getgrnam(module.params["group"]).gr_gid
        unit = Path(module.params["dest"])
        dest = unit.resolve()  # Preserve the existing copy task's follow semantics.
        pending = unit.with_name(f".{unit.name}.reload-pending")
        try:
            attrs = dest.stat()
        except FileNotFoundError:
            attrs = None
        if attrs and not stat.S_ISREG(attrs.st_mode):
            module.fail_json(msg=f"Not a regular unit file: {dest}", **result)
        content = module.params["content"].encode("utf-8")
        install = not attrs or dest.read_bytes() != content
        metadata = attrs and (
            attrs.st_uid != uid or attrs.st_gid != gid or stat.S_IMODE(attrs.st_mode) != 0o644
        )
        if not (install or metadata or pending.exists()):
            module.exit_json(**result)
        if module.check_mode:
            module.exit_json(changed=True)
        # Leave a per-unit retry record before publication: a failed/interrupted
        # reload must not look converged on the next run just because bytes match.
        pending.mkdir(mode=0o700, exist_ok=True)
        result["changed"] = True
        if install or metadata:
            if attrs and install:
                result["backup_file"] = module.backup_local(str(dest))
            with NamedTemporaryFile(dir=dest.parent, delete=False) as staged:
                module.add_cleanup_file(staged.name)
                staged.write(content)
                os.fchown(staged.fileno(), uid, gid)
                os.fchmod(staged.fileno(), 0o644)
            module.atomic_move(staged.name, str(dest), keep_dest_attrs=False)
            # atomic_move applies directory defaults on creation.
            os.chown(dest, uid, gid)
            dest.chmod(0o644)
        runtime = f"/run/user/{uid}"
        rc, _, stderr = module.run_command(
            ["systemctl", "--user", "daemon-reload"],
            handle_exceptions=False,
            environ_update={
                "XDG_RUNTIME_DIR": runtime,
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
            },
        )
        if rc:
            module.fail_json(msg="User daemon-reload failed", rc=rc, stderr=stderr, **result)
        pending.rmdir()
    except (OSError, KeyError) as exc:
        module.fail_json(msg=str(exc), **result)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
