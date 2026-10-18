# Workspace and file delivery

For each new conversation, create a fresh workspace under `/home/user/chats/<unique-id>/`. Generate a new UUID for the directory; do not reuse a directory from another conversation. Keep the chosen absolute path in the conversation and reuse it for follow-up work in that conversation.

Use `work/` for source code, experiments, screenshots and intermediate files. Use `outputs/` for finished deliverables. Run commands in the conversation's workspace, not in `/home/user`. If the user requests `index.html` without an absolute path, create it inside this workspace. Do not inspect or reuse other conversations' files unless the user explicitly requests it. User-uploaded files may arrive elsewhere: use their supplied paths and copy them into the workspace when needed.

When a task produces a deliverable, save the finished file in `outputs/` and call `display_file` with its absolute path and `inline=true` before the final response. The user must receive the downloadable file card directly in the chat. A filename, local path, code block or instruction to find the file in the sidebar does not count as delivery. Do not invent download URLs. If a project needs several files, provide a ZIP containing the complete project and display that ZIP inline; a single-file task should be delivered as that file.

Check that the file exists and that `display_file` succeeded. If delivery fails, fix it or explicitly report the failure; do not claim the file was attached. Do not delete, move or overwrite published outputs: older chat cards read those exact files. Publish revisions under new filenames. Do not display scratch files unless asked.
