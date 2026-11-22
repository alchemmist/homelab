# LMS: the course workspace

> **PostgreSQL (2026-11-20):** The working DB is `pg-common/lms`; `lms-postgres` is stopped, `lms-ha` is in hibernation. [Operation and CA](../../data/postgresql/postgres-platform.md).

> **Current app-roles:** `app-lms-student` and `app-lms-teacher` are enabled through
> the common [app-groups mechanism](../../auth/applications/app-access-groups.md). Per-client
> OIDC mappings project them into the existing native student/teacher claims,
> without global inheritance and without an LMS restart. The native role-selection
> function is verified: both groups → teacher, an empty set → deny. Assigning a role
> does not automatically open all lessons; the existing lesson grants are preserved.
> A full browser/JIT acceptance of the new groups is not yet claimed. Below is the original cut.

Cut on **2 November 2026**. A memo, not a replacement for checking the live pod. Do not write client secrets and passwords here.

## Where it lives

| What | Where |
| --- | --- |
| Code | the `alchemmist/lms` repository |
| The student's site | Hugo + the hugo-docs theme. This is not the React prototype in `teacher/` |
| API | FastAPI, `backend/app` |
| Database | PostgreSQL `lms-postgres`, Secret `lms-db`, key `LMS_DATABASE_URL` |
| Image | `ghcr.io/alchemmist/lms` |
| Deployment | `.github/workflows/publish-image.yml` → `alchemmist/deploy-to-socrat@v1` writes `image.tag` and `image.digest` into `deploy/lms/values.yaml` and `charts/lms/values.yaml`. The Argo CD application `lms` syncs the chart |
| Address | https://lms.alchemmist.xyz |
| Locally | `http://localhost:8000`. `127.0.0.1` gives 403: local mode matches the Host against `LMS_PUBLIC_URL` |

The last image successfully rolled out in this session: tag `521b39731a7e0a837418532580a300e8d6a30775`, digest `sha256:55f7befcea8046177aea2465c6ab8edd5be4adc28a2363a0c0ee322aad11cf64`. The pod is Ready. The **Checks** workflow is often red at the same time: `runner/tests/test_catalog.py` expects 78 tasks, the tree has hundreds of them. This does not affect the image publication. The publication fails separately if the backend/OIDC tests fail, and then the tag in homelab does not change.

## Login

Authentik only. LMS does not store its own passwords.

- Issuer: `https://auth.socrat.alchemmist.xyz/application/o/lms/` (the trailing slash must match).
- Client id: `socrat-lms`. Redirect: `https://lms.alchemmist.xyz/auth/callback`.
- Scope: `openid profile email groups`. Groups in the ID token are a list of names. The mapping expression must return `{"groups": [group.name ...]}`, not a bare list.
- An unauthorized entry immediately goes to Authentik (`/login` → `/auth/login`), without a button on an intermediate page. Only so when the issuer and secret are set.
- Admission: an intersection of the token's groups with `LMS_OIDC_ALLOWED_GROUP` (`lms-students` by default, a comma-separated list) or with `LMS_OIDC_TEACHER_GROUP` (`lms-teachers` by default). The role is written into the session. If a person is in both groups, they are a teacher.
- `alchemmist` is added to `lms-teachers` and stays a teacher. The Authentik test student: login `lms-student`, only the `lms-students` group. Do not store the password in git.
- After changing groups, a new login is needed: the old session remembers the old role. The user's role in the `users` table is updated on login.

The client secret: `socrat-authentik-lms` in the namespace `lms`. The Authentik application policy admits `homelab-owner` and `lms-students`. The `lms-teachers` group was created live and recorded in `deploy/identity/services.json`; ansible does not run by itself on a git push.

## What a person sees

The interface is English: Sign in, Sign out, Submit solution, View solution, View tests, search, API errors. The course, block, lesson names and the text itself remain Russian.

The role and Sign out stand on one line in the bottom-right corner. They are taken from `data-role` on `<html>`, which the backend writes in when serving the page, and do not wait for a separate round to `/api/session`.

On the task page, a teacher sees the same Submit solution plus View solution and View tests. The panel slides in from the right over the page. Repeating the same button or a click outside the panel closes it. The solution is a Python code block in the theme's chroma classes, without a heading and a Close button. The tests are a full-panel-width Input / Expected table, without an Origin column.

The solution reference does not read the generator's database. It is baked into the image: `backend/app/data/reference.json`. At build time there were about 22 tasks with a saved solution text, of them 4 are certified. The rest are empty in the panel. A student gets 403 for this API.

## Opening lessons

The `lesson_access` table (`lesson_path`, `user_id`). A student sees in the menu only the lessons opened to them; a direct URL of a closed lesson — 404. While there are no grants, the student's menu is empty. A teacher sees everything. Local mode (`LMS_AUTH_MODE=local` on loopback) does not enable the filter, otherwise the local workspace would be empty.

Management on the Textbook page, before the lesson text: name tags, **+** opens a list of not-yet-added students, **Add** writes a grant, a cross on hover removes it. The list has only users who already logged in as student. A teacher does not enter this list after a new login.

## What not to commit together with LMS

In the `lms` working tree there lie hundreds of `statement.md` edits, an uncommitted `migration/pipeline.py` and a separate `teacher/` prototype. This is not the student's site and not the image, unless specifically committed. The generator is described in [lms-generation.md](lms-generation.md).

## A copy of the database into the HA cluster

The production web still goes to `lms-postgres`. The chart can disable this Deployment via `database.legacyReplicas` and, when `database.ha.enabled: true`, mount the CA `lms-ha-ca` into `/etc/postgres-ca`. By default HA is disabled. The web Deployment rolls with a Recreate strategy: the solution-submission queue lives in the process, you cannot have two web pods at once.

`scripts/lms-ha-copy.py` creates a one-time Job `postgres:17`. It reads the passwords from the Secrets `lms-db` and `lms-ha-app`, takes a custom dump from `lms-postgres`, encrypts it on the PVC `lms-database-backups` and restores it into `lms-ha-rw` with `verify-full`. A rehearsal (`--rehearsal`) does not require stopping the web and does not reconcile the table fingerprint. A final copy requires `--confirm-web-stopped` and zero replicas of the `lms` Deployment. Only SHA-256 and the fact of a fingerprint match end up in the Job log, not the table rows.
