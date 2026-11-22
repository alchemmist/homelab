# Public Wiki follow-up —16 November 2026

Read-only public checks: both `/platform/rustfs/` and `/platform/s3-storage/`
return200. The RustFS page still contains the old activation-gated text; the
S3-storage page does not. Thus the documentation discrepancy is also present in
published content, not merely a Git search result.

This session has no exposed native Wiki MCP connection/write-scoped personal
access token. `docs/applications/wiki/README.md` specifies native `/mcp`, per-user PAT and effective
account-role enforcement. Browser cookies and bootstrap credentials are not MCP
credentials; do not extract/borrow them or create a shared admin identity to
finish a documentation task. Configure the normal authorized connection through
private credential storage, never paste a token into chat or Git.

## Proposed supported update, not yet published

1. Read both authoritative pages and current editor revision through the supported
   native API/MCP; inspect outstanding publication/Git-sync state.
2. Preserve `/platform/rustfs/` as a compatibility page and existing aliases.
   Replace the obsolete operational activation checklist with a short Russian
   explanation and a link to `/platform/s3-storage/`. Keep operational/history
   details in the internal dated runbook rather than public onboarding.
3. Verify the current S3 page against actual configuration; retain correct
   least-privilege/native-auth and immutable-object guidance. Do not blanket
   replace IPs or private machine endpoints in public prose.
4. Publish only the targeted page edit against the observed base revision. On
   conflict, re-read/review; never force-overwrite or edit the runtime managed tree.
5. Verify public URLs/link/search and native publication result, then eventual Git
   sync. Do not push stale repository content over accepted runtime publications.

Draft compatibility prose:

> # RustFS: объектное хранилище
>
> RustFS используется в Socrat как S3-совместимое хранилище файлов и диагностик.
> Актуальные способы доступа, ограничения и правила работы описаны на странице
> «S3-хранилище» (/platform/s3-storage/).
>
> Старые этапы подключения и активации SPI не являются текущими инструкциями.
> Не меняйте настройки хранилища, права доступа или объекты по историческому
> чек-листу. Для выдачи доступа обратитесь к владельцу сервиса.

This draft does not claim publication, an owner login or a successful write API
call. Source README/operational storage references were corrected separately.
