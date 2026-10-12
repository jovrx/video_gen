# Bilingual interface validation — 2026-10-12

The language selector in the top bar supports English and Simplified Chinese.
New browsers use English regardless of browser locale. The selected language is
saved under `h3-studio-language` in local storage; unsupported preferences fall
back to English. Switching remains available if storage is disabled.

Translations cover static labels, accessible names, placeholders, task phases,
queue positions, countdowns, pagination, workflow and system settings, task
details, confirmation dialogs, notices, and application errors from old records.
User prompts, filenames, and workflow node names retain their original content.
Switching preserves drafts, selected images, filters, settings inputs, and videos.

Verification:

- Python regression suite: 74 tests passed.
- `node --test tests/i18n.test.cjs`: 5 tests passed, including disabled storage,
  parameterized errors, Chinese filenames/field names, and singular counts.
- `tests/browser_i18n.cjs`: Chromium passed default English with a Chinese browser
  locale, both switch directions, refresh persistence, unsupported preferences,
  dynamic states/errors, dialogs, and preservation of form drafts and video nodes.
- Desktop widths 1024, 1280, 1366, 1440, and 1920 preserve the two panes without
  page overflow; a 390px touch viewport also has no page overflow.
- Independent playback probe confirmed playback remained active and time advanced
  across a language switch.
- Ruff, JavaScript syntax, and Git whitespace checks passed.

Run the browser check against a running local studio using a Playwright Node
installation. Set `PLAYWRIGHT_MODULE` if the module is outside the normal Node
module search path, `CHROMIUM_PATH` for a custom browser executable, and
`STUDIO_URL` if the studio is not at `http://127.0.0.1:8765`.

README images were captured from the current interface using demo records and
an existing local video, without submitting generation tasks:

- English: `images/workspace.png`, `images/system-settings.png`.
- Simplified Chinese: `images/workspace.zh-CN.png`, `images/system-settings.zh-CN.png`.
