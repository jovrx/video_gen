# System Settings and Generation Queue Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to execute inline; user already authorized implementation. Canonical progress is tracked in claude-mem list system-settings-queue.

**Goal:** Provide configurable system concurrency, browser submission cooldown, and persistent FIFO video waiting with live queue positions.

**Architecture:** SQLite stores settings and browser last-submission timestamps. JobManager admits FIFO jobs into full-lifecycle generation slots and resumes remote tasks before new submissions. Existing SSE carries queue and browser cooldown state.

**Tech Stack:** FastAPI, SQLite, asyncio, vanilla JavaScript, pytest, mocked HTTP transport.

**Spec:** docs/superpowers/specs/2026-10-11-system-settings-queue-design.md

## Global Constraints

- Default concurrency 3, browser cooldown 60 seconds; multiple tabs share a server cookie.
- Single service process / single worker as already documented.
- Settings persist and apply immediately; lower limits do not cancel existing jobs.
- Queue survives restart; existing remote task IDs are never resubmitted.
- Unknown submissions retain capacity until manually resolved or associated.
- No paid live generation needed for validation.

## Task 1: Persist settings and atomically enforce cooldown

Files: app/config.py, app/store.py, tests/test_system_queue.py.

Interfaces: SystemSettings(max_concurrent_generations: int, client_cooldown_seconds: int); Store.system_settings() -> SystemSettings; Store.save_system_settings(value) -> SystemSettings; Store.client_status(client_id) -> dict; Store.create(..., client_id=None) -> dict, raising CooldownError(retry_after).

- [x] Add behavior tests for persisted settings, validation, same-client transactional cooldown, independent clients, and expiration.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_system_queue.py -q` and confirm missing behavior fails.
- [x] Add SQLite system_settings/client_submissions tables; BEGIN IMMEDIATE surrounds cooldown check and task insertion; expose only public timestamps and retry seconds.
- [x] Run the focused tests until green.

## Task 2: Admit full generation lifecycle through FIFO queue

Files: app/jobs.py, app/store.py, tests/test_system_queue.py.

Interfaces: JobManager.start(job_id), dispatch(), recover(), close(); Store.refresh_queue_positions(); Job public queue_position and slot_reserved fields.

- [x] Add tests that block mock platform tasks: first 3 admitted, next 2 numbered 1/2, completion advances FIFO; dynamic raise/lower and recovered remote tasks preserve slots.
- [x] Run focused tests and verify over-admission fails before implementation.
- [x] Replace submission-only semaphore with synchronous event-loop admission based on durable state. Persist waiting/admitted states before scheduling. Refresh positions on admission/completion/settings changes. Resume existing remote IDs before fresh submissions; keep unknown reservations.
- [x] Run existing job, progress, and recovery tests with focused tests.

## Task 3: API, browser identity, settings UI and live state

Files: app/main.py, app/static/index.html, app/static/app.js, app/static/style.css, tests/test_system_queue.py, README.md.

Interfaces: GET/PUT /api/system-settings; GET /api/client-status; SSE client event; POST /api/jobs returns queue_position; POST /api/jobs/{id}/resolve-unknown requires explicit confirmed-not-submitted flag.

- [x] Add API tests: settings validation/persistence, valid cookie identity, accepted first submission / rejected repeat, independent clients, invalid image not consuming cooldown, unknown reservation release.
- [x] Confirm focused API tests fail before wiring routes.
- [x] Add persistent HTTP-only browser cookie and backend 429 with Retry-After. Issue identity before submission, preserve cooldown through restart, synchronize via SSE. Settings route runs on event loop and dispatches after saving.
- [x] Add separate system settings dialog, cooldown countdown, queue summary and card queue positions. Existing platform queued state remains distinct. Provide explicit manual unknown-resolution action.
- [x] Verify focused tests, full pytest, Ruff, node --check, compileall, and browser fixture interaction at desktop/mobile widths.
- [x] Update README with defaults, endpoints, dynamic-limit semantics, browser identity scope, and recovery rules. Close canonical work-state list after verification.
