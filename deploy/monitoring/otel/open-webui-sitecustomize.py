"""Early fail-closed pinned Open WebUI source-safe HTTP tracing bootstrap."""
import os

try:
    from source_privacy import activate
    activate()
    from open_webui_source_profile import activate as activate_profile
    activate_profile()
except BaseException:
    os.write(2, b'OTel source-safe Open WebUI bootstrap failed; refusing application startup\n')
    os._exit(78)
