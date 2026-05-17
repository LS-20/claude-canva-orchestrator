# canva-design-agent

A command-line tool that separates design recreation into two phases: Claude analyzes your reference image into a structured JSON spec (Phase 1), you approve or refine it, then Claude builds the design in Canva via MCP (Phase 2). This avoids the low-fidelity single-shot approach of the stock connector.

## Quickstart

1. Clone this repo and `cd` into it.
2. Ensure Python 3.11+ (`python3 --version`).
3. Install: `uv sync` or `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`
4. Copy `.env.example` to `.env` and add your keys (see Setup below).
5. Run: `python -m canva_agent run --image ./your-reference.jpg`

## Setup

**Python 3.11+** required.

```bash
# With uv (recommended)
uv sync

# Or with pip
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Copy the example env file and fill in real values:

```bash
cp .env.example .env
```

Edit `.env` — never commit this file.

## Getting your Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com).
2. Create or copy an API key.
3. Paste it in `.env` as `ANTHROPIC_API_KEY=sk-ant-...`

## Getting your Canva access token

Canva MCP requires **per-user OAuth** — not a service account. Tokens expire after roughly **4 hours**; you will need to refresh and re-paste into `.env`.

1. Read [Canva MCP server setup](https://www.canva.dev/docs/connect/canva-mcp-server-setup/).
2. Complete the OAuth flow for your Canva account (via Claude Desktop, Cursor MCP settings, or Canva's developer docs).
3. Copy the access token into `.env` as `CANVA_ACCESS_TOKEN=...`
4. Test connectivity: `python -c "from canva_agent.phase2_build import smoke_test_mcp; smoke_test_mcp()"`

If you get 401 errors, your token likely expired — generate a new one.

Troubleshooting: [Canva MCP troubleshooting](https://www.canva.dev/docs/mcp/troubleshooting/)

## Usage examples

```bash
# Interactive prompts for image path and notes
python -m canva_agent run --image ./planner.jpg

# Choose models per phase
python -m canva_agent run --image ./planner.jpg --analysis-model opus --build-model sonnet

# Load prior saved specs as Phase 1 context
python -m canva_agent run --image ./planner.jpg --memory

# Save a full session transcript (secrets redacted)
python -m canva_agent run --image ./planner.jpg --log-session
```

**Review loop commands:** `approve`, `edit`, `revise <feedback>`, `restart`, `save`, `quit`

**Post-build commands:** `tweak <feedback>`, `done`

## Customizing the prompts

Edit the markdown files — no code changes needed:

- `canva_agent/prompts/phase1_system.md` — vision analysis instructions
- `canva_agent/prompts/phase2_system.md` — Canva build instructions

## Cost estimates

Approximate cost per API call (assumes ~2k input + ~1.5k output tokens):

| Analysis model | Build model | Est. per run (both phases) |
|----------------|-------------|----------------------------|
| haiku          | haiku       | ~$0.01                     |
| sonnet         | sonnet      | ~$0.03                     |
| opus           | sonnet      | ~$0.05                     |
| opus           | opus        | ~$0.07                     |

Actual cost depends on image complexity and MCP tool usage.

## Troubleshooting

| Error | Fix |
|-------|-----|
| Missing `.env` | Run `cp .env.example .env` and fill in keys |
| Invalid Anthropic API key (401) | Check key at console.anthropic.com |
| Canva token invalid (401) | Token expired (~4h); re-authenticate and update `.env` |
| JSON parse failed | Try `revise` or `restart`; check `phase1_system.md` |
| Rate limit (429) | Wait and retry |
| Image not found | Use absolute or correct relative path |

## Security warning

**DO NOT commit `.env` to git.** It contains your Anthropic API key and Canva token. Only `.env.example` (with placeholders) belongs in the repo. If you accidentally commit secrets, rotate them immediately at [console.anthropic.com](https://console.anthropic.com) and regenerate your Canva token.
