# Guardian UI review

## Baseline — 16 October 2026

Reviewed the running local app in headless Google Chrome at 1280 × 900 and 390 × 900, with LIVE=0, an isolated empty HOME and Telegram disabled. Screenshots: `ui-review/before-1280.png`, `ui-review/before-390.png` (full page). No backend, API or fixture changes are in scope.

The first impression is a developer simulator rather than a reassuring family product. Within ten seconds the visitor learns about suspicious calls, but not older people in Poland, SMS scams, or what the next useful action is. Large controls, heavy borders and the empty phone compete for attention. There is no horizontal overflow in the initial baseline, but mobile requires considerable scrolling before reaching the conversation and evidence.

## Prioritized findings

| Priority | Finding | Required improvement |
| --- | --- | --- |
| P0 | SAFE / score 0 appears before any analysis. It suggests reassurance without evidence. | Neutral initial and loading states; describe SAFE as no warning signs, not a guarantee. |
| P0 | Replay appears only in a dense model badge; Listen live and family calling imply more than the demo does. | Explain recorded answers, rule fallback, microphone limitations and simulated phone calls before use. |
| P1 | No clear audience, SMS proposition or single quick entry point. | Explain protection for older people in Poland and offer a one-click example. |
| P1 | Empty phone dominates desktop; evidence occupies only half a row. Cards touch on mobile. | Consistent spacing, restrained borders, compact transcript, balanced grid and full-width evidence. |
| P1 | Raw request errors, empty message submission and repeated submissions are poorly handled. Loading can leave a previous verdict visible. | Actionable errors, input validation, busy controls and reset stale results. |
| P1 | Tabs use aria-selected without tab semantics or arrow-key support. Focus exists but is visually heavy. | Complete accessible tabs, visible keyboard focus, descriptive labels and status announcements. |
| P1 | Concurrent call, SMS and microphone activity can overwrite the same result. | Prevent mode changes during requests and stop recognition when changing modes. |
| P2 | Technical phrases include template fallback, secure session and seeded. Speech warning claims playback without confirmation. | Plain-language labels and accurate playback feedback; retain evidence provenance. |
| P2 | Flat typography, all controls equally prominent, heavy blue/green blocks. | Clear type scale, strong primary action, quieter secondary controls, readable contrast. |

Baseline colors are generally readable and native controls have a visible focus outline. The main accessibility problems are semantic tabs, unclear initial status, long mobile reading order and competing visual emphasis. No user-facing “judge failed” text was found in the page source.

## Implemented

- Rebuilt the first screen around the audience, scam calls and SMS, a one-click BLIK example, and a three-step explanation. All original demo functions remain available.
- Added a warm neutral/green visual system, clear heading scale, consistent spacing, quiet secondary buttons, a compact conversation panel and a responsive evidence grid. No remote fonts, CDN assets or new dependencies are used by the page.
- Replaced premature SAFE with a neutral initial assessment. Loading clears stale results; failed requests show an incomplete assessment and retry guidance. Empty messages are validated locally; busy controls prevent conflicting checks. Requests have a 20-second timeout.
- Distinguished recorded Nemotron advice, offline rules, recorded Tavily results and hand-picked sources. Microphone limitations and the simulated family call are explained in place. Voice playback is opt-in and no longer claims confirmed playback.
- Added semantic tabs with arrow/Home/End navigation, a skip link, keyboard focus, live status, a focusable transcript and reduced-motion support. Source excerpts are expandable with native keyboard-accessible disclosure controls; full text and links remain available.

## Verification

Headless Google Chrome, 1280 × 900 and 390 × 900, full-page screenshots:

- `ui-review/after-1280.png`, `ui-review/after-390.png`: initial state.
- `ui-review/after-example-1280.png`, `ui-review/after-example-390.png`: completed scam SMS, evidence and family preview.
- `ui-review/after-error-1280.png`, `ui-review/after-error-390.png`: deliberately failed request, with recovery controls enabled.
- `ui-review/after-loading-390.png`: pending request and disabled controls.

Both viewport runs passed: initial neutral state; one-click scam example; family call simulation; empty message validation; safe parcel example; family alert hidden after a safe check; keyboard tabs; typed microphone fallback; all six turns of the fake-police call at 3×; and network-failure recovery. No horizontal overflow or JavaScript/console errors occurred during normal flows. The deliberately aborted request produces the expected browser network error; this is separate from the normal-flow console checks. Results are in `ui-review/browser-checks.json`.

Additional checks passed for busy state, expanded source excerpts without overflow, a visible keyboard focus outline, and typed input when SpeechRecognition is unavailable (microphone stays disabled after analysis). Screenshots were visually inspected at both widths. This is a targeted accessibility review, not a full WCAG audit.

Final automated checks, with isolated HOME, LIVE=0 and empty Telegram configuration:

```text
.venv/bin/pytest -q
115 passed in 3.52s

.venv/bin/python -m guardian.demo --offline
scams detected: 4/4, false alarms: 0/2
```

Full outputs: `ui-review/pytest.txt`, `ui-review/offline-demo.txt`.

## Remaining limitations

This is still a prototype: no phone-call interception, no real phone call from the family preview, and no live model or search in offline mode. Browser microphone transcription may require an external browser service; it was not activated in this offline review. Actual speech audio and Telegram delivery were not exercised. The interface and supplied demo examples are English; Polish is available in the microphone language selector and in some source material, not as a complete interface localization. Detection quality and backend behavior were deliberately left unchanged. The initial broken .venv symlink was replaced with an ignored local environment; the main checkout was not modified. Nothing was deployed or pushed.

Measured CSS contrast ratios: body ink/background 12.31:1, muted text/card 6.08:1, primary-button white/green 6.97:1, phone secondary text/background 9.49:1, scam heading/card 6.99:1.

## v2 design direction

«Тревожная кнопка, которой доверяешь»: телефон и наблюдаемая угроза становятся центром первого экрана. Центрированная композиция с разговором, выделенными фразами и шкалой SAFE → CAUTION → SCAM заменяет кремово-зелёный лендинг и шаги 1–2–3. Начальный разговор явно обозначен как иллюстрация; короткий переход CAUTION → SCAM завершается автоматически. После запуска примера шкала отражает фактический verdict и исходный score API (не процент). Звонок прокручивает экран к транскрипту.

Палитра: чернильный фон `#0b1423`, панели `#142136`, янтарный `#ffca70` для действия и предупреждений, красный `#ff939b` для SCAM. Зелёный используется только для SAFE. Atkinson Hyperlegible (Google Fonts, 400/700), основной размер 18 px, транскрипт 20 px на десктопе; пояснения преимущественно 16 px. Шрифт выбран ради различимости букв для людей со сниженным зрением. Кнопки от 50 px, заметный фокус, клавиатурные вкладки, reduced motion, SVG-иконки в HTML. Измеренный контраст: основной текст 14.80:1, вторичный текст на пузыре 7.07:1, кнопка 10.81:1, SCAM 7.00:1, граница поля 4.79:1. Это целевая проверка, не полный аудит WCAG.

Проверено локально в Chrome при LIVE=0 с изолированным HOME и отключённым Telegram: мошеннический и безопасный SMS, подсветка и шкала, симуляция семейного звонка, пустой ввод, клавиатурные вкладки и фокус, текстовый ввод вместо микрофона, все шесть реплик fake_police на скорости 3×, раскрытие источника. На 1280 × 900 и 390 × 900 нет горизонтальной прокрутки и ошибок консоли. Сохранены ограничения записанных ответов Nemotron / Tavily, офлайн-правил, микрофона и семейного звонка. Google Fonts требует сети при первом открытии; при недоступности используется Arial. Сам анализ проверен только офлайн, микрофон и внешние уведомления не запускались.

Скриншоты: [первый экран 1280](ui-review/v2-first-1280.png), [первый экран 390](ui-review/v2-first-390.png), [результат 1280](ui-review/v2-example-1280.png), [результат 390](ui-review/v2-example-390.png). Результаты сняты на полную высоту страницы, чтобы показать транскрипт, оценку, семейный блок и источники.

```text
.venv/bin/pytest -q
115 passed in 1.70s

.venv/bin/python -m guardian.demo --offline
scams detected: 4/4, false alarms: 0/2
```

Изменены только guardian/static/ и запрошенные материалы обзора. Бэкенд, API и фикстуры не менялись; secrets.env не читался. Без деплоя, push и merge; ветка design-v2.
