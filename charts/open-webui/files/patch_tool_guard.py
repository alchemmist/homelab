import ast
import pathlib
import sys

IMPORT = 'from open_webui.utils.homelab_tool_guard import guarded_execute, guard_stopped, guard_stop_message, record_no_progress_round\n'
FUNCTION = 'async def execute_tool_call(form_data, metadata, event_caller, tool_call):\n'
CONTINUATION = '''                    await emit_output()

                    try:
                        new_form_data = {'''
GUARDED_CONTINUATION = '''                    await emit_output()

                    record_no_progress_round(metadata, output)

                    if guard_stopped(metadata):
                        await emit_message_error(guard_stop_message(metadata))
                        break

                    try:
                        new_form_data = {'''

FILE_RESULT = "    if tool_function_name != 'display_file' or not isinstance(tool_result, dict) or tool_result.get('exists') is False:"
FILE_RESULT_GUARD = "    if _is_tool_result_error(tool_result):\n        return None\n\n" + FILE_RESULT
EVENT = "    if not event_emitter:\n        return\n\n    if tool_function_name == 'display_file':"
EVENT_GUARD = "    if not event_emitter or _is_tool_result_error(tool_result):\n        return\n\n    if tool_function_name == 'display_file':"


def patch(source):
    if IMPORT in source:
        raise ValueError('Tool guard already present; expected pristine middleware')
    for anchor in (FUNCTION, CONTINUATION, FILE_RESULT, EVENT):
        if source.count(anchor) != 1:
            raise ValueError('Unsupported WebUI middleware; tool guard anchor count differs')
    result = IMPORT + source.replace(FUNCTION, '@guarded_execute\n' + FUNCTION).replace(CONTINUATION, GUARDED_CONTINUATION).replace(FILE_RESULT, FILE_RESULT_GUARD).replace(EVENT, EVENT_GUARD)
    ast.parse(result)
    return result


if __name__ == '__main__':
    source = pathlib.Path(sys.argv[1])
    target = pathlib.Path(sys.argv[2])
    target.write_text(patch(source.read_text()))
