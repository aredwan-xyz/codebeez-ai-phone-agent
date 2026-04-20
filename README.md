# CodeBeez AI Phone Agent

> Production-ready AI phone agent: real-time voice, sub-800ms latency, barge-in interruption, multi-tool orchestration, and cross-call memory.

## Architecture

```
Caller → Twilio Media Streams (WebSocket, μ-law 8kHz)
           │
           ▼
     FastAPI WebSocket Handler
           │
     ┌─────┴──────────────────┐
     │                        │
     ▼                        ▼
  Deepgram STT           BargeIn VAD
  (streaming)          (interrupts TTS)
     │
     ▼ transcript (speech_final)
  CallOrchestrator
     │
     ▼
  Claude claude-sonnet-4-6 (streaming + tools)
  ┌────────────────────────────────────────┐
  │  Tools: schedule_appointment           │
  │         lookup_crm / update_crm        │
  │         search_knowledge_base          │
  │         transfer_to_human              │
  │         send_sms / end_call            │
  └────────────────────────────────────────┘
     │ text stream (sentence boundaries)
     ▼
  ElevenLabs TTS (streaming PCM → μ-law 8kHz)
     │
     ▼
  Twilio → Caller
```

**Latency target: < 800ms** from end of caller utterance to first audio byte.

## Stack

| Component | Technology |
|---|---|
| Web framework | FastAPI + uvicorn |
| Telephony | Twilio Voice + Media Streams |
| STT | Deepgram Nova-3 (streaming, mulaw passthrough) |
| LLM | Anthropic Claude claude-sonnet-4-6 (streaming + tool use) |
| TTS | ElevenLabs Turbo v2.5 (streaming PCM) |
| Session state | Redis |
| Call history / profiles | PostgreSQL + SQLAlchemy async |
| Calendar | Google Calendar API |
| CRM | HubSpot |
| RAG | FAISS + PostgreSQL chunks |
| Observability | structlog + Prometheus + OpenTelemetry |
| Container | Docker + docker-compose |

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/yourname/ai-phone-agent.git
cd ai-phone-agent
make setup         # creates venv, installs deps, starts Postgres + Redis
```

### 2. Configure

```bash
cp .env.example .env
# Fill in:
#   TWILIO_ACCOUNT_SID / AUTH_TOKEN / PHONE_NUMBER
#   DEEPGRAM_API_KEY
#   ELEVENLABS_API_KEY  (+ ELEVENLABS_VOICE_ID for your custom voice)
#   ANTHROPIC_API_KEY
```

### 3. Expose publicly (ngrok)

```bash
ngrok http 8000
# Copy the https URL, set it as BASE_URL in .env
```

### 4. Configure Twilio

In your Twilio console, set the webhook for your phone number:
- **Voice → A call comes in → Webhook**: `https://your-ngrok-url.ngrok.io/calls/inbound`
- HTTP method: `POST`

### 5. Run

```bash
make dev
```

Call your Twilio number. Aria will answer!

### 6. Seed the knowledge base (optional)

```bash
make seed-kb
```

## Project Structure

```
app/
├── main.py               # FastAPI app + lifespan
├── config.py             # All settings (pydantic-settings)
├── api/
│   ├── calls.py          # Twilio webhooks (TwiML)
│   ├── websocket.py      # Twilio Media Streams WebSocket
│   └── admin.py          # Admin REST API
├── core/
│   ├── audio.py          # μ-law ↔ PCM, resampling, chunking
│   ├── vad.py            # Barge-in + end-of-turn detection
│   └── orchestrator.py   # Main call loop (STT → LLM → TTS)
├── services/
│   ├── stt.py            # Deepgram streaming STT
│   ├── tts.py            # ElevenLabs streaming TTS
│   ├── llm.py            # Claude streaming + tool use loop
│   └── telephony.py      # Twilio REST (outbound, hangup, transfer)
├── tools/
│   ├── registry.py       # Tool registration + dispatch
│   ├── calendar_tool.py  # Google Calendar (book / check availability)
│   ├── crm_tool.py       # HubSpot (lookup / update)
│   ├── knowledge_base.py # FAISS RAG search + ingestion
│   ├── transfer_tool.py  # Warm transfer + end call
│   └── call_control.py   # Send SMS
├── memory/
│   ├── session.py        # Redis — per-call state
│   └── history.py        # PostgreSQL — cross-call profiles
├── db/
│   ├── base.py           # SQLAlchemy async engine
│   └── models.py         # ORM models
└── models/
    ├── call.py           # CallSession, OutboundCallRequest
    └── conversation.py   # Message, ConversationTurn
```

## Admin API

```
GET  /admin/calls                  — list all call records
GET  /admin/calls/{sid}/turns      — conversation transcript
GET  /admin/callers                — caller profiles
GET  /admin/active-sessions        — live calls (from Redis)
POST /admin/knowledge-base/ingest  — upload a text file to KB
POST /admin/knowledge-base/ingest-text — ingest raw text
GET  /metrics                      — Prometheus metrics
GET  /docs                         — Swagger UI (debug mode only)
```

## Outbound Calls

```bash
curl -X POST http://localhost:8000/calls/make \
  -H "Content-Type: application/json" \
  -d '{"to_number": "+15551234567", "context": "Follow up on last week quote"}'
```

## Adding Tools

1. Create `app/tools/my_tool.py`
2. Decorate handler with `@ToolRegistry.register(...)`
3. Import the module in `app/tools/registry.py` → `_load_tools()`

Claude will automatically have access to the new tool on the next call.

## Latency Optimization

| Technique | Impact |
|---|---|
| Deepgram mulaw passthrough (no conversion) | ~20ms saved |
| `speech_final` endpointing (not VAD timer) | Faster turn detection |
| TTS flush on sentence boundaries (`.`, `!`, `?`) | First audio in ~300ms |
| ElevenLabs `eleven_turbo_v2_5` model | Lowest EL latency |
| Redis session (no DB on every frame) | ~5ms saved per turn |
| Single uvicorn worker (WebSocket state) | No cross-process issues |

## Barge-in / Interruption

When the caller speaks while the agent is talking:
1. `BargeInDetector` detects energy above threshold
2. TTS `asyncio.Task` is cancelled immediately
3. Twilio `clear` event flushes the audio buffer
4. STT continues capturing the new utterance

## Environment Variables

See [`.env.example`](.env.example) for the full list with descriptions.

## Tests

```bash
make test          # all tests
pytest tests/test_audio.py -v   # audio codec tests
pytest tests/test_vad.py -v     # VAD tests
pytest tests/test_api.py -v     # API tests
```

## Docker

```bash
make docker-up     # start Postgres + Redis
docker compose -f docker/docker-compose.yml up app   # full stack

# With observability (Prometheus + Grafana)
docker compose -f docker/docker-compose.yml --profile observability up
```

## License

MIT
