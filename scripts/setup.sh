#!/usr/bin/env bash
set -euo pipefail

echo "==> Setting up AI Phone Agent"

# 1. Python virtualenv
if [ ! -d ".venv" ]; then
  python3.11 -m venv .venv
fi
source .venv/bin/activate

# 2. Install deps
pip install -e ".[dev]"

# 3. Create .env
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ".env created — fill in your API keys"
fi

# 4. Start infra (Docker)
if command -v docker &>/dev/null; then
  docker compose -f docker/docker-compose.yml up -d postgres redis
  echo "==> Waiting for Postgres..."
  sleep 3
fi

# 5. Run DB migrations (creates tables)
python -c "import asyncio; from app.db.base import init_db; asyncio.run(init_db())"

echo ""
echo "==> Done! Next steps:"
echo "  1. Edit .env with your Twilio / Deepgram / ElevenLabs / Anthropic keys"
echo "  2. Run: uvicorn app.main:app --reload"
echo "  3. Expose port 8000 via ngrok: ngrok http 8000"
echo "  4. Set BASE_URL in .env to your ngrok URL"
echo "  5. Point Twilio webhook to: \$BASE_URL/calls/inbound"
