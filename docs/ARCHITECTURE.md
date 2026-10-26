# Guardian — architecture

Guardian listens to a phone call (or reads a message) on behalf of an elderly person,
recognises a scam script as it unfolds, warns the person in plain words, alerts a
relative, and tells them exactly what to do next.

Core rule: **no evidence — no alarm.** Every "this is a scam" verdict carries
machine-checkable evidence: verbatim quotes from the call and, where possible, an
official source found through Tavily that describes the same scheme. The code cannot
raise a SCAM verdict without that evidence; tests prove it.

## Why there is no real phone line in the demo

- Ordinary apps cannot hear a GSM call: Android blocks the `VOICE_CALL` audio stream for
  third-party apps since Android 10, iOS never exposed it. Pixel Scam Detection works only
  because it is part of Google's own dialer.
- A real line is possible through a VoIP bridge (Twilio / Telnyx Media Streams: the call is
  forwarded to a virtual number and the audio is streamed over a WebSocket). It costs money
  and a Polish number needs KYC (ID + Polish address). That is Lev's decision, not part of
  the hackathon MVP.
- Judges must be able to try the demo for free until 15.12. A phone number they have to
  call would cost us per minute and would not work for most of them.

So the demo is a **call simulator in the browser**, and the call source is a pluggable
adapter. A Twilio adapter can be added later without touching the pipeline.

## Call sources (adapters)

All sources produce the same thing: a stream of `Turn(speaker, text, t)` objects.

| Source | What it is | Status |
|---|---|---|
| `scenario` | Scripted call from `scenarios/*.json`; the browser speaks the caller's lines with `speechSynthesis` and the transcript scrolls in real time | MVP |
| `message` | Pasted SMS / WhatsApp text, analysed as one turn | MVP |
| `mic` | Browser microphone, Web Speech API transcribes on the client, text chunks go to the server | done (*Listen live* tab) |
| `twilio` | Media Streams WebSocket + STT | only with Lev's approval (paid) |

## Pipeline (runs after every new caller turn)

```
Turn ──► Transcript (append) ──► 1. Signal extraction (Nemotron)
                                     │  tactic id + verbatim quote
                                     ▼
                                 2. Quote validator (deterministic)
                                     │  quote must be a substring of what the CALLER said
                                     ▼
                                 3. Claim check (Tavily, official domains)
                                     │  "police never ask you to move money" → URL + snippet
                                     ▼
                                 4. Risk scorer (deterministic) ──► Verdict
                                     ▼
                                 5. Advisor (Nemotron) ──► warning for the elder,
                                                          alert for the relative,
                                                          safe next step
```

1. **Signal extraction — Nemotron** (`nvidia/nemotron-3-super-120b-a12b` via Token Factory,
   JSON output). Input: the transcript so far. Output: a list of
   `{tactic, quote, explanation}`. Tactics are a closed taxonomy (`guardian/taxonomy.py`):
   `impersonation_authority` (police, CBŚP, prosecutor), `impersonation_bank`,
   `impersonation_family`, `urgency_pressure`, `secrecy_request`, `money_transfer_request`,
   `cash_handover_courier`, `blik_code_request`, `credentials_request`,
   `remote_access_install`, `safe_account`. Unknown tactic ids are dropped.
2. **Quote validator** — deterministic. A signal survives only if its quote (normalised:
   case, whitespace, punctuation) occurs in a caller turn. This kills hallucinated
   evidence. The guardian's own lines and the elder's lines do not count.
3. **Claim check — Tavily.** For each new tactic, one search restricted with
   `include_domains` to official sources (`policja.pl`, `cbzc.policja.gov.pl`, `cert.pl`,
   `knf.gov.pl`, `zbp.pl`, `gov.pl`, `uokik.gov.pl`, plus `europol.europa.eu` for English).
   Results are cached per tactic for the session. A source counts only if it is on the
   allow-list and its snippet is non-empty. Tavily is in the core flow: it is what turns
   "the model thinks so" into "the police say this is exactly how the scam works".
4. **Risk scorer** — deterministic, no LLM. Weighted sum of validated tactics, with
   combination bonuses (authority + money request, family emergency + cash courier,
   bank + remote access). Levels: `SAFE`, `CAUTION`, `SCAM`.
   Hard rule enforced in the `Verdict` model: `SCAM` requires **≥2 distinct validated
   tactics with quotes and ≥1 official source**. Otherwise it is capped at `CAUTION`.
5. **Advisor — Nemotron.** Writes three short texts from the verdict and evidence:
   a big-font warning for the elder (≤ 25 words, no jargon), an alert for the relative
   (what happened, quotes, sources, a "call her now" button in the UI), and one safe action
   ("Hang up. Call your bank on the number printed on your card."). If the model is
   unavailable, a template fallback is used — the warning must never depend on the network.

## Offline mode (mandatory)

Every external call goes through a thin client with a replay layer:

- `LIVE=0` (default, tests, demo without keys): responses come from `fixtures/`.
- `LIVE=1`: real calls; `scripts/record_fixtures.py` stores real responses into `fixtures/`.

Fixture key = `<kind>-<sha256(canonical request)[:16]>.json`. A missing fixture in replay
mode is an error in tests (so fixtures cannot silently go stale) and falls back to the
deterministic template path in the demo.

Keys come only from env (`NEBIUS_API_KEY`, `NEMOTRON_MODEL`, `TAVILY_API_KEY`), loaded from
`~/.config/hackathon/secrets.env` if it exists. Never committed, printed or logged.

## Layout

```
guardian/
  models.py        Turn, Signal, Source, Verdict (with the SCAM evidence guard)
  taxonomy.py      tactic ids, weights, combination bonuses, Tavily queries per tactic
  evidence.py      quote normalisation + validation against caller turns
  llm.py           Nemotron client (OpenAI-compatible) + replay
  search.py        Tavily client + replay + domain allow-list
  scorer.py        deterministic risk scoring
  advisor.py       warning / relative alert / safe action (LLM + template fallback)
  pipeline.py      CallSession: on_turn(turn) -> Verdict
  app.py           FastAPI: scenarios list, session start, turn, SSE/JSON verdict
  demo.py          python -m guardian.demo --offline  (CLI run of all scenarios)
  static/index.html  phone simulator + evidence panel + relative's phone
scenarios/         synthetic calls (no real people or numbers)
fixtures/          recorded / seeded model and search responses
tests/
```

## Scenarios (synthetic)

1. `grandson_accident` — "na wnuczka": crying "grandson", car accident, a "lawyer" sends a courier for cash.
2. `fake_police` — "na policjanta / CBŚP": your savings are at risk, move them to a safe account, tell no one.
3. `fake_bank_anydesk` — bank "security department", suspicious loan, install AnyDesk.
4. `blik_friend` — message from a "friend" asking for a BLIK code.
5. `real_grandson` — a benign call from the actual grandson asking about Sunday dinner (must stay `SAFE`).
6. `real_bank_reminder` — a benign bank call about an appointment, no money or codes asked (must stay `SAFE`/`CAUTION`, never `SCAM`).

The benign scenarios are as important as the scams: a guardian that cries wolf is useless.

## Metrics shown to judges

- Time to first warning (turn number and seconds into the call) per scam scenario.
- False alarms on benign scenarios (target: 0).
- Every verdict in the UI expands to its evidence: quotes highlighted in the transcript,
  source links.
