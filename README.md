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
| **Chat‑history search** | "מה אמרתי לאייל לגבי התקציב?" | Searches a specific WhatsApp conversation. |
| **Voice notes** | (send an audio message) | Transcribed via Google Cloud Speech (`he‑IL`) and treated like text. |
| **Contact sharing** | (forward a contact card) | Saved into the user's recent‑chats index for easier name resolution. |

**Design intent (from `הבנות טכניות.txt`, "Technical Understandings"):**

1. Exactly **one** user‑facing agent — no intent classification, no handoffs.
2. *Agent‑as‑tool*: deeper jobs are exposed to the main agent as tools.
3. The system prompt stays in one coherent conceptual space.
4. **≤ 5 tools per agent.**
5. **TDD** — understand the prompt's needs → few‑shot examples → real tests.
6. Don't over‑engineer: reminder / task / event are plain tools, **not** agents. Only the *scheduled‑message* flow is a specialized sub‑agent.

---

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
   events  (Firestore)        another person                (wwebjs) + Tavily web
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

## Components

### `apps/` — FastAPI web layer (`bot.py`)
The HTTP entrypoint. Serves the marketing/legal pages (`index`, `login`, `privacy`, `terms`, `contact`) via Jinja2 templates, and the onboarding API:

- `POST /login-user` — validates an Israeli number (`972XXXXXXXXX`), claims a WhatsApp instance, returns a QR code to scan.
- `GET /instance-state` — polls whether the WhatsApp instance is `authorized`.
- `GET /refresh-contact` — re‑syncs a user's contacts and sends a welcome template.
- Mounts routers for the 360dialog webhook, Google OAuth, Calendar, and Contacts.
- Defines (but, via a `TODO`, does **not** yet wire in) background loops for the event trigger and the instance pool.

### `adapters/whatsapp/` — provider adapters
- `whatsapp_adapter.py` — abstract base (`parse_incoming`, `send_message`, `detect_direction`, …).
- `dialog360/webhook.py` — the live inbound webhook: message dedup (TTL cache), voice‑note download + transcription, contact‑card handling, "thinking…" placeholder, then the agent reply.
- `cloudapi/` — Cloud API adapter + `x‑Hub‑Signature` verification.
- `wwebjs/` — reads chat history from a `whatsapp-web.js` Node service (used by chat‑history search).

### `agents/` — the brain
- `echo_v2/core.py` — builds the LangGraph ReAct agent: the big Hebrew system prompt, the tool list, the per‑user prompt injection (recent chats), and a windowed checkpointer.
- `echo_v2/tools/` — the tools: `process_reminder`, `process_task`, `process_event`, `process_scheduled_message` (which also holds `process_contact_message`, `get_candidate_recipient_chat_ids`, `search_chat_history`, `get_items`).
- `main.py` — `handleUserInput()`: wraps each turn, parses the `stt:` / `text:` input source, builds the user prompt with the current time, invokes the agent, and records token/cost/latency metrics.

### `green_api/` — sending "as the user"
- `instance_mng/` — create, list, QR, config, and a transactional **pool** (`claim_instance` / `release_instance`) so users get a *warm* instance instantly instead of waiting for one to spin up.
- `send.py`, `groups.py`, `contacts.py`, `chats_history.py` — WhatsApp actions on behalf of the user.

### `context/` — typed domain models (Pydantic)
`BaseActionItem` → `ReminderItem` / `TaskItem` / `EventItem`, plus `ScheduledMessageItem` (recipient `chat_id` must match `.+@(c|g)\.us`), message/identity/media primitives, and `windowed_InMemorySaver.py` (the conversation‑memory window).

### `store/` — Firestore repositories
`action_item_store`, `scheduled_messages_store`, `delivery_mng_store` (send status + retries), `people_store`, `chat_index`, `google_calendar_store`, `user`.

### `shared/` — cross‑cutting services
- `event_trigger.py` — the scheduler loop (see below).
- `google_calendar/` — OAuth, calendar, people/contacts, token cache.
- `google_tts.py` — `ffmpeg` → `wav` → Google Cloud Speech (`he‑IL`), using the user's recent‑chat names as phrase hints.
- `user.py`, `token_tracker.py`, `delivery_mng.py`, `monitor_disconnected_users.py`.
- `observability/` — GA4 metrics (`track_agent_run`, `track_stt_transcribed`, `track_tool_call`), logging, tracing.

### `db/base.py`
Initializes Firebase Admin / Firestore from a service‑account file under `SECRETS_DIR`.

### `tests/`
TDD harness that asserts the agent picks the **right tool** for ~16 Hebrew prompts (reminders, contact messages, chat search, and a "tell me a joke" → fallback case).

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

---

## Data & Integrations

- **Database:** Firebase / Firestore (`users`, `instances_pool`, action items, scheduled messages, delivery status, people, chat index, calendar tokens).
- **LLM:** OpenAI GPT‑4.1 via `langchain-openai`.
- **Speech‑to‑text:** Google Cloud Speech (`speech_v1p1beta1`, `he‑IL`).
- **Web search:** Tavily (available to the message tool).
- **Calendar / contacts:** Google Calendar + People APIs (OAuth).
- **WhatsApp:** 360dialog Cloud API (inbound) + Green API (outbound, per‑user) + a `whatsapp-web.js` Node service (history).
- **Analytics:** Google Analytics 4 measurement protocol for agent runs, STT, and tool calls — with token and USD cost estimation.

---

## Running It

> ⚠️ This is an early‑stage / work‑in‑progress repo (2 commits). See **Caveats** below — a couple of import paths don't yet match the folder names, so expect to do a little wiring before it boots cleanly.

### Prerequisites
- Python 3.11+ and **ffmpeg** on the host (for voice transcription).
- A Firebase project + service‑account JSON.
- A Google Cloud service account with the Speech‑to‑Text API enabled.
- Google OAuth credentials (Calendar + People).
- A 360dialog WhatsApp number (inbound) and a Green API partner account (outbound).
- An OpenAI API key and a Tavily API key.
- (Optional) a running `whatsapp-web.js` Node service for chat‑history search.

### Install
```bash
pip install -r requirements.txt
# ensure ffmpeg is installed, e.g.  sudo apt-get install ffmpeg
```

### Secrets & environment
Place credential files under `.secrets/` (overridable with `SECRETS_DIR`):
- `.secrets/firebase1.json` — Firebase service account
- `.secrets/<google‑speech>.json` — Google Cloud STT service account

Useful environment variables seen in the code:

| Var | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8000` | Web server port |
| `SECRETS_DIR` | `.secrets` | Where credential JSONs live |
| `LLM_MODEL_NAME` | `gpt-4_1` | Model label for metrics |
| `LLM_PRICE_PER_M_TOKEN` | `6.00` | Cost estimate per 1M tokens |
| `STT_PRICE_PER_MIN_USD` | `0.024` | Cost estimate per STT minute |
| `CONTACTS_REFRESH_SEC` | `3600` | Contact re‑sync interval |
| `NODE_URL` | `http://localhost:3000` | `whatsapp-web.js` service URL |

Also expects `OPENAI_API_KEY`, `TAVILY_API_KEY`, and Green API partner credentials (`GREEN_API_PARTNER_API_URL`, `GREEN_API_PARTNER_TOKEN`) to be configured.

### Start the server
```bash
python apps/bot.py
# or
uvicorn apps.bot:app --host 0.0.0.0 --port 8000
```

### Onboard a user
1. Open `/login?user_id=972XXXXXXXXX`.
2. Scan the returned QR with WhatsApp (links a Green API instance to that user).
3. Point your 360dialog WhatsApp number's webhook at `POST /webhook/whatsapp`.
4. Message the Echo number — try *"תזכיר לי להתקשר מחר ב‑9"*.

### Run the tests
```bash
pytest
```

---

## Interesting / Notable Things

- **Two WhatsApp providers, on purpose.** Inbound conversation flows through 360dialog (one shared business number), while *outbound* scheduled messages go out via each user's *own* Green API instance — so a "remind my mom" message actually arrives from the user, not a bot. That asymmetry is the cleverest part of the design.
- **A warm instance pool.** Spinning up a WhatsApp instance is slow, so a background worker keeps a pool of pre‑created instances in Firestore and hands them out transactionally (`claim_instance` / `release_instance`) — login feels instant.
- **Opinionated minimalism.** The Hebrew design notes are almost a manifesto: one agent, no handoffs, ≤5 tools, TDD. The codebase mostly honors it — only the scheduled‑message flow is treated as a real sub‑agent.
- **STT with context hints.** Voice transcription feeds the user's recent‑chat *names* in as phrase hints, so it's better at hearing the right contact names.
- **Cost‑aware from day one.** Every agent run and every transcription is metered into GA4 with estimated USD cost.

### Caveats (it's a WIP)
- **Module paths don't match folders yet.** Code imports `agents.echo.core`, `agents.echo_2.core`, and `agents.echo_2.tools…`, but the actual directory is `agents/echo_v2/`. A rename pass (or matching aliases) is needed before it imports cleanly — the project is clearly mid‑refactor between `echo`, `echo_2`, and `echo_v2`.
- **Background loops aren't wired in.** `bot.py` builds a `lifespan` with the trigger loop and pool worker, but the app is instantiated as plain `FastAPI()` (`# … lifespan) TODO`), so the scheduler/pool worker won't start automatically as committed.
- **Secrets in source.** The 360dialog webhook secret is hard‑coded, and credential filenames are referenced directly. These should move to environment variables / a secrets manager before any real deployment.
- **Israel‑only onboarding.** Login validation hard‑requires a `972…` number.

---

*Languages: Python (~77%) + HTML (~23%). Hosting referenced in‑code: Render (`inme‑1.onrender.com`).*
