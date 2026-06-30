# Echo — A WhatsApp AI Personal Assistant

> *"You are Echo, my calm assistant in WhatsApp."*

Echo is a Hebrew‑first personal assistant that lives **inside WhatsApp**. Users chat with it (by text or voice note) and it manages their reminders, tasks, and calendar events, schedules outgoing messages to other people, and searches their chat history — all through natural language, with a deliberate *confirm‑then‑commit* safety model.

It is built around a single LangGraph ReAct agent (GPT‑4.1), backed by Firestore, and wired into WhatsApp through **two** different providers: one for talking *to* Echo and one for sending messages *as the user*.

---

## Business Features

| Feature | What the user can say (Hebrew) | What happens |
| --- | --- | --- |
| **Reminders** | "תזכיר לי להתקשר מחר ב‑9" | Creates a self‑reminder; absolute & relative times. No confirmation needed to create. |
| **Tasks & lists** | "תעשה רשימת סופר" → "תוסיף חלב לרשימת הסופר" | Tasks with sub‑tasks (`parent_id`), completion tracking. |
| **Calendar events** | "תקבע פגישה עם רותם מחר ב‑10" | Google Calendar events with start/end, recurrence, participants, reminders. |
| **Scheduled / outgoing messages** | "שלח לנועה הודעה מחר ב‑8: 'בהצלחה במבחן!'" | Resolves the contact, **confirms**, then sends the message from the user's *own* WhatsApp number at the scheduled time. |
| **Chat‑history search** | "מה אמרתי לאייל לגבי התקציב?" | Searches a specific WhatsApp conversation (via Green API). |
| **Voice notes** | (send an audio message) | Transcribed via Google Cloud Speech (`he‑IL`) and treated like text. |
| **Contact sharing** | (forward a contact card) | Saved into the user's recent‑chats index for easier name resolution. |


## How It Works (high level)

```
                        ┌─────────────────────────────┐
   User on WhatsApp ──▶ │ 360dialog Cloud API webhook │ ── inbound (talk TO Echo)
                        └──────────────┬──────────────┘
                                       │  dedup • voice→STT • "חושב רגע..." placeholder
                                       ▼
                        ┌─────────────────────────────┐
                        │  Echo agent (LangGraph /     │
                        │  GPT‑4.1 ReAct, ≤5 tools)    │
                        └──────────────┬──────────────┘
            ┌──────────────────────────┼───────────────────────────┐
            ▼                          ▼                           ▼
   reminders / tasks /        scheduled message to          chat‑history search
   events  (Firestore)        another person                (Green API) + Tavily web
            │                          │
            ▼                          ▼
   ┌──────────────────┐      ┌────────────────────────────┐
   │ trigger loop     │      │ Green API per‑user instance │ ── outbound (send AS the user)
   │ (every 10s)      │ ───▶ │ (claimed from a warm pool)  │
   └──────────────────┘      └────────────────────────────┘
```

**The two WhatsApp channels are the key architectural idea:**

- **Inbound (360dialog Cloud API):** Echo's own business number receives everything the user says.
- **Outbound (Green API):** each user is assigned their *own* WhatsApp instance (logged in via QR), so scheduled messages are delivered from the user's personal number — not from a bot.

---

## Architecture & Layout

The latest refactor moved the project to a clean, layered (ports‑and‑adapters) structure. The dependency direction is **infra → assistant → domain**, with `domain` depending on nothing.

```
domain/      pure contracts — no framework or I/O dependencies
assistant/   the agent: prompt, tools, orchestration glue, evals
infra/       the FastAPI app, dependency wiring, and service implementations
adapters/    WhatsApp provider adapters (inbound webhooks + send)
green_api/   per‑user "send as the user" + warm instance pool
store/       Firestore repositories
shared/      cross‑cutting services (scheduler, calendar, STT, metrics)
context/     typed domain models (Pydantic) + conversation memory window
db/          Firebase / Firestore initialization
apps/        deprecated launcher shim
agents/      deprecated entrypoint shim
```

### `domain/` — contracts (no dependencies)
- `inbound.py` — neutral DTOs: `InboundMessage` and `UserContext` dataclasses that the infra layer produces and the agent consumes.
- `ports.py` — `Protocol` interfaces the agent depends on: `SchedulingService`, `MessagingService`, `UserContextService`, and `Assistant`.
- `contracts.py` — Pydantic models such as `ActionItemSummary` and `ScheduledMessageItem` (recipient `chat_id` must match `.+@(c|g)\.us`).

### `assistant/` — the brain
- `runtime.py` — builds the LangGraph ReAct agent (the big Hebrew system prompt, the tool list, per‑user prompt injection of recent chats, the windowed checkpointer) and exposes `EchoAssistant`, which implements `domain.ports.Assistant`.
- `glue.py` — per‑turn orchestration: parses the `stt:` / `text:` input source, builds the user prompt with the current time, invokes the agent, and records token/cost/latency metrics.
- `tools/` — the tools: `process_reminder`, `process_task`, `process_event`, `process_scheduled_message` (which also holds `process_contact_message`, `get_candidate_recipient_chat_ids`, `search_chat_history`, `get_items`), plus `process_action_item.py` and `helper.py`.
- `schemas.py` — tool argument / payload schemas.
- `evals/` — the TDD harness that asserts the agent picks the **right tool** for ~16 Hebrew prompts (reminders, contact messages, chat search, and a "tell me a joke" → fallback case).

### `infra/` — app, wiring, services
- `app/server.py` — the FastAPI app. Serves the marketing/legal pages (`index`, `login`, `privacy`, `terms`, `contact`) via Jinja2, plus the onboarding API:
  - `POST /login-user` — validates an Israeli number (`972XXXXXXXXX`), claims a WhatsApp instance, returns a QR code to scan.
  - `GET /instance-state` — polls whether the WhatsApp instance is `authorized`.
  - `GET /refresh-contact` — re‑syncs a user's contacts and sends a welcome template.
  - Mounts routers for the 360dialog webhook, Google OAuth, Calendar, and Contacts.
  - Defines a `lifespan` that **does** start the background event‑trigger loop and the instance‑pool worker (see Caveats for the one loop still commented out).
- `app/wiring.py` — constructs the singletons (`SchedulingService`, `MessagingService`, `UserContextService`) and binds them into a single `EchoAssistant`. Also reads the opt‑in LangSmith tracing env vars.
- `services/` — concrete implementations of the domain ports: `scheduling_service.py`, `messaging_service.py` (recipient resolution + Green‑API chat‑history search), `user_context_service.py`.

### `adapters/whatsapp/` — provider adapters
- `whatsapp_adapter.py` — abstract base (`parse_incoming`, `send_message`, `detect_direction`, …).
- `dialog360/webhook.py` — the live inbound webhook at `POST /webhook/whatsapp`: bearer‑token check against `WEBHOOK_SECRET`, message dedup (TTL cache), voice‑note download + transcription, contact‑card handling, "thinking…" placeholder, then the agent reply.
- `cloudapi/` — Cloud API adapter + `x‑Hub‑Signature` verification.

### `green_api/` — sending "as the user"
- `instance_mng/` — create, list, QR, config, and a transactional **pool** (`claim_instance` / `release_instance`) so users get a *warm* instance instantly instead of waiting for one to spin up.
- `send.py`, `groups.py`, `contacts.py`, `chats_history.py` — WhatsApp actions on behalf of the user (chat‑history search now reads through here).

### `context/` — typed domain models (Pydantic)
Message / identity / media primitives, `scheduled_message.py`, `scheduled_event.py`, `user.py`, `response_format.py`, and `windowed_InMemorySaver.py` (the conversation‑memory window).

### `store/` — Firestore repositories
`action_item_store`, `scheduled_messages_store`, `delivery_mng_store` (send status + retries), `people_store`, `chat_index`, `google_calendar_store`, `user`.

### `shared/` — cross‑cutting services
- `event_trigger.py` — the scheduler loop (see below).
- `google_calendar/` — OAuth, calendar, people/contacts, token cache.
- `google_tts.py` — `ffmpeg` → `wav` → Google Cloud Speech (`he‑IL`), using the user's recent‑chat names as phrase hints.
- `user.py`, `token_tracker.py`, `delivery_mng.py`, `result.py`, `time.py`.
- `observability/` — GA4 metrics (`track_agent_run`, `track_stt_transcribed`, `track_tool_call`), logging, tracing.

### `db/base.py`
Initializes Firebase Admin / Firestore from a service‑account file under `SECRETS_DIR`.

### Deprecated shims
- `apps/bot.py` — keeps `python apps/bot.py` and `uvicorn apps.bot:app` working; it just re‑exports `infra.app.server:app`.
- `agents/main.py` — keeps the old `handleUserInput()` callable working; it now delegates to the wired `EchoAssistant`.

---

## The Agent & Its Tools

A single **`create_react_agent`** (LangGraph) on **`gpt‑4.1`**, with a per‑user system prompt and a `WindowedInMemorySaver` checkpointer (last ~30 messages / 15 interactions, keyed by `thread_id = user_id`).

| Tool | Purpose | Confirmation |
| --- | --- | --- |
| `process_reminder` | create / update / delete reminders | create: no · update/delete: **yes** |
| `process_task` | tasks, sub‑tasks, completion | mutations & "mark complete": **yes** |
| `process_event` | Google Calendar events, recurrence, participants | always **yes** |
| `process_contact_message` | schedule/send a message to someone else | always **yes**, with recipient + chatId + cleaned text + absolute time |
| `get_candidate_recipient_chat_ids` | resolve a name → `chatId` (asks to disambiguate / save aliases) | — |
| `search_chat_history` | search one conversation | — |
| `get_items` | list reminders/tasks/events/scheduled messages before update/delete | — |

**Behavioral rules baked into the prompt:** never pass raw names into the send tool (always resolve first); strip time phrases from message bodies and use them only as scheduling metadata; default to 1 tool call (2 max); be forgiving of speech‑to‑text errors when `input_source == "stt"`; reply in the user's language; keep a calm, efficient, no‑chit‑chat tone.

---

## The Scheduler (`shared/event_trigger.py`)

A loop runs roughly every 10 seconds and looks back over the last 10 minutes for anything due:

- **Action items (reminders):** sent to the user via 360dialog.
- **Scheduled messages:** sent from the user's own number via Green API.
- Each send is tracked in a delivery‑status store with retry counting. Scheduled messages retry up to **5** times; on final failure Echo messages the user with the undelivered text so they can send it manually.

The loop is started automatically by the app's `lifespan` (in `infra/app/server.py`), alongside the warm‑instance pool worker.

---

## Data & Integrations

- **Database:** Firebase / Firestore (`users`, `instances_pool`, action items, scheduled messages, delivery status, people, chat index, calendar tokens).
- **LLM:** OpenAI GPT‑4.1 via `langchain-openai`.
- **Speech‑to‑text:** Google Cloud Speech (`speech_v1p1beta1`, `he‑IL`).
- **Web search:** Tavily (available to the message tool).
- **Calendar / contacts:** Google Calendar + People APIs (OAuth).
- **WhatsApp:** 360dialog Cloud API (inbound) + Green API (outbound, per‑user, and chat‑history search).
- **Analytics:** Google Analytics 4 measurement protocol for agent runs, STT, and tool calls — with token and USD cost estimation.
- **Tracing (optional):** LangSmith, opt‑in via `LANGCHAIN_TRACING_V2` + `LANGCHAIN_API_KEY`.

---

## Running It

> ⚠️ Early‑stage / work‑in‑progress repo. The most recent commit ("config refactor") reorganized the codebase into the layered layout above and resolved the previous import‑path and webhook‑secret issues. See **Caveats** for what's still rough.

### Prerequisites
- Python 3.11+ and **ffmpeg** on the host (for voice transcription).
- A Firebase project + service‑account JSON.
- A Google Cloud service account with the Speech‑to‑Text API enabled.
- Google OAuth credentials (Calendar + People).
- A 360dialog WhatsApp number (inbound) and a Green API partner account (outbound).
- An OpenAI API key and a Tavily API key.

### Install
```bash
pip install -r requirements.txt
# ensure ffmpeg is installed, e.g.  sudo apt-get install ffmpeg
```

### Configure environment
Copy the template and fill it in. Locally the code loads variables from `.venv/.env`
(that's the path passed to `load_dotenv(...)` in the source), so:

```bash
cp .example.env .venv/.env
# then edit .venv/.env
```

In hosted environments (e.g. Render), set the same variables as platform env vars
instead of using a file. See **`.example.env`** for the full annotated list. The
required ones are `OPENAI_API_KEY`, `TAVILY_API_KEY`, `GREEN_API_PARTNER_TOKEN`,
`WEBHOOK_SECRET`, and the 360dialog Cloud‑API trio (`D360_API_KEY`,
`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`).

### Secrets (credential files, not env vars)
Place credential JSONs under `.secrets/` (overridable with `SECRETS_DIR`):
- Firebase service account (loaded by `db/base.py`).
- Google Cloud STT service account (filename set via `GOOGLE_SPEECH_CREDENTIALS`).

### Environment variables

| Var | Required | Default | Meaning |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | ✅ | — | LLM access (langchain‑openai) |
| `TAVILY_API_KEY` | ✅ | — | Web search tool |
| `GREEN_API_PARTNER_TOKEN` | ✅ | — | Green API partner token (raises if missing) |
| `WEBHOOK_SECRET` | ✅ | — | Inbound webhook bearer secret (raises if missing) |
| `D360_API_KEY` | ✅ | — | 360dialog API key (sending) |
| `WHATSAPP_PHONE_NUMBER_ID` | ✅ | — | Cloud API phone number id |
| `WHATSAPP_ACCESS_TOKEN` | ✅ | — | Cloud API access token |
| `SECRETS_DIR` | | `.secrets` | Where credential JSONs live |
| `GOOGLE_SPEECH_CREDENTIALS` | | `tami-…json` | STT service‑account filename under `SECRETS_DIR` |
| `APP_BASE_URL` | | `https://inme-1.onrender.com` | Public base URL (login links, OAuth redirect) |
| `PORT` | | `8000` | Web server port |
| `GREEN_API_PARTNER_API_URL` | | `https://api.green-api.com` | Green API base URL |
| `WHATSAPP_APP_SECRET` | | `your_app_secret` | x‑Hub‑Signature verification |
| `NODE_URL` | | `http://localhost:3000` | Node service base URL (instance deployment URLs) |
| `CONTACTS_REFRESH_SEC` | | `3600` | Contact re‑sync interval |
| `POOL_SIZE` | | `1` | Warm Green API instances to keep ready |
| `LLM_MODEL_NAME` | | `gpt-4_1` | Model label for metrics |
| `LLM_PRICE_PER_M_TOKEN` | | `6.00` | Cost estimate per 1M tokens |
| `STT_PRICE_PER_MIN_USD` | | `0.024` | Cost estimate per STT minute |
| `GA4_MEASUREMENT_ID` / `GA4_API_SECRET` / `GA4_COLLECT_URL` / `GA4_DEBUG` / `GA4_CLIENT_SALT` | | (built‑in) | Google Analytics 4 reporting |
| `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` / `LANGCHAIN_PROJECT` | | off | LangSmith tracing (opt‑in) |
| `INTEGRATION_TEST_USER_ID` | | — | Real user id for opt‑in integration tests |

### Start the server
```bash
uvicorn infra.app.server:app --host 0.0.0.0 --port 8000
# or, via the compatibility shim:
python apps/bot.py
```

### Onboard a user
1. Open `/login?user_id=972XXXXXXXXX`.
2. Scan the returned QR with WhatsApp (links a Green API instance to that user).
3. Point your 360dialog WhatsApp number's webhook at `POST /webhook/whatsapp`
   (it must send `Authorization: Bearer <WEBHOOK_SECRET>`).
4. Message the Echo number — try *"תזכיר לי להתקשר מחר ב‑9"*.

### Tests
- **Agent evals** (right‑tool selection, offline): under `assistant/evals/`.
- **Integration tests** (`tests/test_int_*.py`): hit real services — Firebase, Green API, 360dialog, STT, scheduler — and need the matching credentials/env (and `INTEGRATION_TEST_USER_ID`).

```bash
pytest                       # everything
pytest assistant/evals       # just the agent evals
```

---

## Interesting / Notable Things

- **Two WhatsApp providers, on purpose.** Inbound conversation flows through 360dialog (one shared business number), while *outbound* scheduled messages go out via each user's *own* Green API instance — so a "remind my mom" message actually arrives from the user, not a bot. That asymmetry is the cleverest part of the design.
- **A warm instance pool.** Spinning up a WhatsApp instance is slow, so a background worker keeps a pool of pre‑created instances in Firestore and hands them out transactionally (`claim_instance` / `release_instance`) — login feels instant.
- **Clean layering.** The refactor split the code into `domain` (contracts), `assistant` (the agent), and `infra` (app + service implementations), with `domain` depending on nothing. The agent talks to the outside world only through the `domain.ports` Protocols.
- **Opinionated minimalism.** The Hebrew design notes are almost a manifesto: one agent, no handoffs, ≤5 tools, TDD. The codebase mostly honors it — only the scheduled‑message flow is treated as a real sub‑agent.
- **STT with context hints.** Voice transcription feeds the user's recent‑chat *names* in as phrase hints, so it's better at hearing the right contact names.
- **Cost‑aware from day one.** Every agent run and every transcription is metered into GA4 with estimated USD cost.

### Caveats (it's a WIP)
- **One background loop is still off.** The `lifespan` starts the event‑trigger loop and the pool worker, but the periodic `contacts_reload_loop` is commented out — contact refresh currently happens via the `/refresh-contact` endpoint rather than on a timer.
- **`apps/bot.py` and `agents/main.py` are shims.** They re‑export the real entrypoints for backward compatibility; new code should import from `infra.app.server` and `infra.app.wiring`.
- **Some defaults are baked in.** GA4 IDs and a default STT credential filename have hard‑coded fallbacks in code; override them via env (`.example.env`) before any real deployment.
- **Israel‑only onboarding.** Login validation hard‑requires a `972…` number.
- **`.example.env` is git‑ignored.** The repo's `.gitignore` matches `*.env`, so this template won't be committed unless you force‑add it (`git add -f .example.env`) or add a `!.example.env` negation rule.

---

*Languages: Python + HTML. Hosting referenced in‑code: Render (`inme‑1.onrender.com`).*
