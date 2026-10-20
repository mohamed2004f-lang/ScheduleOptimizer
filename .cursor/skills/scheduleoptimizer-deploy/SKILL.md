---
name: scheduleoptimizer-deploy
description: >-
  Deploys ScheduleOptimizer web changes via Docker rebuild. Use when finishing
  backend/frontend fixes that must appear on the live container, after template
  or Python edits, or when the user asks to publish, rebuild, or deploy.
---

# ScheduleOptimizer deploy

## Rule

App code and Jinja templates are baked into the `web` image. Editing files on the
host does **not** update the running site until rebuild.

## Deploy steps

1. From repo root run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\rebuild_web.ps1
   ```
2. Confirm exit code 0 and container healthy (`docker compose ps`).
3. Tell the user to hard-refresh the affected page.

## Do not

- Rely on Flask auto-reload alone for production Docker.
- Run only `docker compose up -d` without `build` after code changes.
- Commit or push unless the user asked.

## Optional checks

- `docker compose exec web pg_dump --version` (script already checks).
- Hit the changed route once if a quick smoke test is practical.
