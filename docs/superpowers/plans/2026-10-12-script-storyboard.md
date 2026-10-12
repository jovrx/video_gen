# Script and Storyboard Implementation Plan

**Goal:** Generate editable scripts and model-specific textual storyboards, then transfer an edited shot Prompt into the existing video composer.

**Architecture:** Independent httpx text client and FastAPI router; separate creation.js owns the creation dialog and browser draft. Existing video jobs, queue and workflow mapping remain the integration boundary.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, httpx, vanilla JavaScript, pytest, Chromium/Playwright.

**Spec:** docs/superpowers/specs/2026-10-12-script-storyboard-design.md

## Global Constraints

- User approved implementation; continue without further process approvals.
- Work in current shared workspace on feat/script-storyboard; do not commit or push as part of this request.
- No secrets returned in APIs; LLM credentials are independent .env settings.
- Text output is editable, rendered as text, and retained when failures occur.
- 1–24 shots (default 6), integer shot duration (default 8), script 40000 characters, Prompt 20000 characters.
- H3 / generic / custom target formats; optional visual_style; actual video model stays defined by RunningHub workflow.
- PC-first layout, English and Chinese UI; language changes preserve user text.
- Canonical execution state is the script-storyboard work_state list.

## Task 1: Text service and generation APIs

Files: create app/llm.py, app/storyboard.py, tests/test_creation.py; modify app/config.py, app/main.py, .env.example.

Interfaces: create_app(settings, client=None, llm=None) accepts an injected TextModel client. GET /api/creation/config returns configured, model, target_models. POST /api/creation/script accepts prompt and returns title/content. POST /api/creation/storyboard accepts script/shot_count/duration/target_model/custom_model/visual_style and returns shots [{number,title,duration,visual,camera,audio,prompt}]. All fields trimmed; empty text rejected. Shots must have exact count, sequential numbers, exact requested duration.

- Write endpoint tests before implementation. Example: `with TestClient(create_app(Settings(data_dir=tmp_path))) as client: assert client.post('/api/creation/script', json={'prompt':'story'}).status_code == 503`. Run `.venv/Scripts/python.exe -m pytest tests/test_creation.py -q` and confirm missing routes fail.
- Add Settings fields llm_base_url (https://api.openai.com/v1), llm_api_key (empty, repr=False), llm_model (empty), llm_timeout_seconds (120); read LLM_* environment variables. Build httpx client lazily, timeout bounded, no automatic retry or redirect, close with application lifecycle.
- TextModel.complete(system,user) posts model/messages to /chat/completions; validate finish_reason, nonempty choices/message/content and pure or fenced JSON. Return stable safe errors for missing config, timeout, auth, limit and malformed responses; never raw upstream content.
- Use a router factory to define request/result validation, script and storyboard generation prompts. Pass current edited script, count, duration, format and visual style as structured user data. H3 core fields in order, English visual descriptions and original-language dialogue; no fictional asset labels.
- Mock only upstream HTTP with httpx.MockTransport; test full endpoint flow, all error branches and malformed output. Assert URL/auth/model/request values and returned edited-script-based result. Run pytest and Ruff for changed Python files.

## Task 2: Creation dialog and draft

Files: create app/static/creation.js and tests/browser_creation.cjs; modify app/static/index.html, app/static/style.css, app/static/i18n.js. Do not modify app.js or Python (Task 1 ownership).

Consumes the exact Task 1 endpoints. Existing global api(), toast(), showError(), configuration, #prompt input handler are reusable. Load creation.js after app.js. Separate IIFE avoids global variable collisions.

- Write a Playwright flow using routed upstream results before UI implementation; run and confirm missing creation entrance fails. Test with STUDIO_URL and PLAYWRIGHT_MODULE environment variables so no paid generation is used.
- Add wide PC dialog, accessible labels, creative input/script editor, count/duration/format/style inputs, and editable shot cards. Show LLM configuration independently of video setup; lack of LLM config allows manual script editing and saved shot use.
- Treat all model text as text/value; escape any dynamic HTML. Store a versioned localStorage draft with validation; flush edit saves synchronously or on page lifecycle. Handle corrupt/quota/unavailable storage without blocking functionality.
- During generation disable editing and duplicate generation for its dependent inputs, restoring state on errors; preserve existing outputs. Show that existing boards need regeneration when script changes. Prevent invalid overlength manual Prompt transfer.
- Transfer current edited shot Prompt via #prompt.value and dispatch input; only sync duration if current mapping range supports it, otherwise retain video duration and toast an adjustment notice. Close dialog and focus video Prompt; never auto-submit video.
- Support copy with graceful clipboard error; clear draft with normal user confirmation. Language change updates UI and dynamic labels without rerendering away edits.
- Browser acceptance: generate/edit script, generate/edit multiple shots, check custom format/style request, refresh draft, copy, Prompt transfer/count, duration out of range, errors keep outputs, language switch, 1440/1024 PC and 390 touch layout.

## Task 3: Integration, documentation and review

Files: update README.md, README.zh-CN.md, docs/technical-guide.md; write docs/creation-validation.md.

- Check both tasks against the spec; resolve any API/UI mismatch before full verification.
- Run full pytest, node --test tests/i18n.test.cjs, Ruff, node --check for every changed JS, git diff --check.
- Run browser_creation.cjs against local app assets with intercepted API results; run existing browser_i18n.cjs to detect regressions. Confirm static creation.js cache revalidation and no console errors.
- Independently review final diff for contracts, malformed provider output, draft loss, language preservation and accidental paid video submissions. Fix actionable findings, rerun relevant tests, and record results.
- Document independent LLM_BASE_URL/LLM_API_KEY/LLM_MODEL/LLM_TIMEOUT_SECONDS config, all three steps, new endpoints and real-provider verification limitation when no credentials supplied.
