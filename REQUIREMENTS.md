# Project Requirements: `canva-design-agent`

## 1. Project Overview

**What this is:** A command-line agentic orchestration layer that sits between Claude and the Canva MCP server. It implements a strict two-phase pipeline:

1. **Phase 1 — Vision Analysis:** Claude examines a reference image (e.g., a digital planner mockup the user wants to recreate) and produces a structured JSON design spec listing every element it detects — typography, colors, layout, components, copy, imagery type, composition notes, and required Canva stock asset queries.
2. **Phase 2 — Canva Build:** Using the approved spec from Phase 1, Claude calls the Canva MCP server to generate the actual design with high fidelity to the reference.

**Why this exists:** The stock Claude + Canva connector tries to do analysis and design generation in a single shot, which produces vague, low-fidelity results when recreating reference images. This tool separates the two phases and adds a mandatory human approval gate between them, giving the user precise control over the design brief before any Canva resources are spent.

**End user:** A solo Etsy seller / designer who wants to recreate or iterate on reference mockups (digital planners, templates, social posts, etc.) using AI-assisted Canva generation, with full control over the design direction.

---

## 2. Tech Stack & Versions

- **Language:** Python 3.11+
- **Package manager:** `uv` (preferred) or `pip` with `venv`
- **Core dependencies:**
  - `anthropic` (official Anthropic Python SDK — latest)
  - `python-dotenv` (env var loading)
  - `rich` (terminal UI / colored output / nice prompts)
  - `pydantic` (validate the JSON design spec schema)
  - `click` or `typer` (CLI argument parsing — pick one, prefer `typer`)
- **No web framework, no database.** Everything is CLI + local JSON files.

---

## 3. Security & Secrets Handling (CRITICAL — user is a beginner)

The user has an Anthropic API key and will eventually have Canva auth credentials. These must NEVER be hardcoded or committed to git.

**Required implementation:**

1. Create a `.env.example` file in the repo root with placeholder values (this IS committed to git):
   ```
   ANTHROPIC_API_KEY=sk-ant-your-key-here
   CANVA_ACCESS_TOKEN=your-canva-oauth-token-here
   ```
2. Create a `.gitignore` that excludes (at minimum):
   ```
   .env
   .venv/
   __pycache__/
   *.pyc
   .DS_Store
   /sessions/
   /saved_specs/
   ```
3. On first run, if `.env` is missing, the CLI must:
   - Print a clear, friendly error explaining what to do
   - Offer to create `.env` from `.env.example` interactively
   - Exit cleanly without crashing
4. Use `python-dotenv` to load `.env` at startup
5. NEVER print the API key to the terminal, NEVER log it, NEVER include it in any saved files
6. Add a section in the README explicitly warning the user not to commit `.env` and explaining how `.env.example` works

---

## 4. The Two-Phase Pipeline (Core Logic)

### Phase 1: Vision Analysis

**Input:** A local image file path (the user's reference image) plus optional user notes describing intent.

**Process:**
1. Load the image, convert to base64
2. Call the Anthropic API with:
   - The image
   - A carefully-crafted system prompt (see §6) that instructs Claude to act as a senior design analyst and output ONLY a structured JSON design spec
   - The user's intent notes
   - Configurable model (see §5)
3. Parse the JSON response into a Pydantic schema (see §7) — if parsing fails, retry once with a "fix your JSON" follow-up; if it fails again, surface the raw response to the user
4. Pretty-print the spec in the terminal using `rich` (formatted tables, syntax-highlighted JSON)

**Mandatory approval gate:**
After printing the spec, the CLI enters a conversational review loop. The user can:
- `approve` → proceed to Phase 2
- `edit` → open the spec in `$EDITOR` (or fall back to nano) for manual JSON editing, then re-validate
- `revise <feedback>` → send the spec + the user's natural-language feedback back to Claude for a revised version
- `restart` → re-analyze the original image with new notes
- `save` → save spec to `./saved_specs/<timestamp>-<slug>.json` for later reuse
- `quit` → exit cleanly without proceeding

**Phase 2 must NEVER run automatically.** It only runs after explicit `approve`.

### Phase 2: Canva Build

**Input:** The approved JSON design spec.

**Process:**
1. Call the Anthropic API again with:
   - A system prompt that instructs Claude to translate the spec into Canva MCP tool calls
   - The full spec as context
   - The Canva MCP server attached via `mcp_servers` parameter
   - Configurable model (see §5)
2. Stream tool calls and Canva responses back to the terminal as they happen (use `rich` for live updates)
3. When Canva returns design URLs, print them clearly
4. After completion, offer the user a follow-up loop:
   - `tweak <feedback>` → ask Claude to refine via further MCP calls
   - `done` → exit

---

## 5. Configurable Models Per Run

The user wants to choose the model for each phase independently per run. Support these CLI flags:

```bash
python -m canva_agent run --image ./planner.jpg \
  --analysis-model opus \
  --build-model sonnet
```

**Allowed values** (map shortnames to full model IDs internally):
| Shortname | Full model ID            | Notes                                                |
|-----------|--------------------------|------------------------------------------------------|
| `haiku`   | `claude-haiku-4-5`       | Cheapest; OK for simple images                       |
| `sonnet`  | `claude-sonnet-4-6`      | Balanced default                                     |
| `opus`    | `claude-opus-4-7`        | Best vision quality; recommended for analysis phase  |

**Defaults if flags omitted:** `--analysis-model sonnet --build-model sonnet`.

Print the chosen models and approximate per-call cost estimate at startup so the user understands what they're about to spend. Pricing (per 1M tokens, USD):
- Haiku 4.5: $1 input / $5 output
- Sonnet 4.6: $3 input / $15 output
- Opus 4.7: $5 input / $25 output

---

## 6. System Prompts (Critical — Write These Carefully)

### Phase 1 (Vision Analysis) System Prompt

The system prompt for Phase 1 must:
- Frame Claude as a senior design analyst whose only job is observation, not creation
- Instruct it to output ONLY valid JSON matching the schema in §7 — no preamble, no markdown fences, no commentary
- Enumerate EVERY element it detects: typography (font family guess, size, weight, color), color palette (with hex codes), layout (grid, alignment, spacing), components (boxes, dividers, icons, illustrations), copy (verbatim text), imagery (style, subject, mood — for Canva stock search), composition (focal point, hierarchy, whitespace usage)
- For each visual element that would need a Canva stock asset, generate a precise search query (e.g., `"minimalist line icon coffee cup"`) in a dedicated `stock_asset_queries` field
- Note any uncertainty explicitly in a `notes` field rather than guessing

### Phase 2 (Canva Build) System Prompt

The system prompt for Phase 2 must:
- Frame Claude as a Canva execution agent
- Instruct it to use the spec as ground truth and call Canva MCP tools to realize it
- Tell it to search Canva stock using the `stock_asset_queries` from the spec before composing
- Tell it to match typography, colors, and layout to the spec as closely as Canva's tools allow
- Tell it to surface any Canva limitations (e.g., font unavailable) honestly rather than silently substituting

Both prompts should live in a `prompts/` directory as separate `.md` files so the user can edit them without touching code.

---

## 7. Design Spec Schema (Pydantic)

Define this schema in `schemas.py`. The Phase 1 output must conform to it:

```python
from pydantic import BaseModel
from typing import Literal

class Color(BaseModel):
    hex: str
    role: str  # e.g., "primary", "accent", "background"

class TypographyElement(BaseModel):
    text: str
    font_family_guess: str
    size_estimate: str  # e.g., "large heading", "body", "caption"
    weight: Literal["light", "regular", "medium", "bold"]
    color_hex: str

class StockAssetQuery(BaseModel):
    purpose: str  # where it goes in the design
    canva_search_query: str
    style_notes: str

class LayoutNote(BaseModel):
    grid: str  # e.g., "2-column", "centered single column"
    alignment: str
    spacing_density: Literal["tight", "balanced", "airy"]
    focal_point: str

class DesignSpec(BaseModel):
    design_type: str  # e.g., "digital planner cover", "instagram post"
    dimensions_estimate: str
    mood: str
    color_palette: list[Color]
    typography: list[TypographyElement]
    components: list[str]  # bullet list of structural elements
    stock_asset_queries: list[StockAssetQuery]
    layout: LayoutNote
    composition_notes: str
    uncertainties: list[str]
```

---

## 8. CLI Interaction Model (Claude Code-like)

The user wants a conversational REPL feel similar to Claude Code. Structure:

```
$ python -m canva_agent
Welcome to canva-design-agent.
Reference image path? > ./planner.jpg
Brief notes about your intent? > Want an Etsy-style minimal digital planner cover, neutral tones
[Analyzing with claude-sonnet-4-6... estimated cost: ~$0.02]

[spec is printed in a formatted view]

What would you like to do? (approve / edit / revise <feedback> / restart / save / quit)
> revise the typography looks too bold, try lighter weights
[Revising with claude-sonnet-4-6...]
[updated spec is printed]

> approve
[Building with claude-sonnet-4-6 via Canva MCP...]
[live tool-call stream]

Design ready: https://canva.com/design/...
What next? (tweak <feedback> / done)
> done
Bye.
```

Use `rich.prompt.Prompt` for input and `rich.console.Console` for output. Use `rich.markdown.Markdown` and `rich.json.JSON` for nicely formatted spec display.

---

## 9. Output Management

The user does NOT want disk usage to grow uncontrollably.

- **Default behavior:** print everything to terminal, save nothing
- **Opt-in saves only:**
  - `save` command in the review loop → writes the spec JSON to `./saved_specs/`
  - `--log-session` CLI flag → writes a full session transcript (input image path reference, prompts, responses, final design URLs) to `./sessions/<timestamp>.md`
- Both directories are git-ignored
- Never auto-save images, never copy the reference image into the project directory

---

## 10. Optional Session Memory

Add a `--memory` flag that, when set, loads past saved specs from `./saved_specs/` and passes a compact summary of them as additional context to Phase 1. Default off. When on, print a one-line note like `Loaded 3 prior specs as context.`

---

## 11. Canva MCP Integration — Important Caveats

**This is the hardest part of the project and the user is a beginner, so document it well.**

The Anthropic Messages API supports remote MCP servers via the `mcp_servers` parameter (currently in beta — may require the `anthropic-beta: mcp-client-2025-04-04` header; verify against current docs at https://docs.claude.com).

Canva's MCP server URL is `https://mcp.canva.com/mcp` and it requires OAuth authentication. The user must obtain an access token from Canva. The two viable paths:

**Path A (preferred — simpler for the user):**
1. The user authenticates once via Canva's developer portal and obtains a long-lived access token
2. Token goes in `.env` as `CANVA_ACCESS_TOKEN`
3. Pass it in the `mcp_servers` config under the `authorization_token` field

**Path B (more robust — implement if Path A token expires often):**
1. Implement the full OAuth 2.0 device-code flow in `auth.py`
2. Cache the refresh token in `.env` and auto-refresh on expiry

**For the v1 of this project, implement Path A.** Add a `README` section titled "Getting your Canva token" that links to Canva's MCP/OAuth setup docs and walks through it step by step. If the token is missing or invalid, fail with a clear error message pointing to that README section.

When constructing the MCP config in the API call:

```python
mcp_servers=[{
    "type": "url",
    "url": "https://mcp.canva.com/mcp",
    "name": "canva",
    "authorization_token": os.environ["CANVA_ACCESS_TOKEN"]
}]
```

---

## 12. File Structure

```
canva-design-agent/
├── .env.example
├── .gitignore
├── README.md
├── REQUIREMENTS.md          # this file
├── pyproject.toml           # or requirements.txt
├── canva_agent/
│   ├── __init__.py
│   ├── __main__.py          # entrypoint: `python -m canva_agent`
│   ├── cli.py               # typer commands & REPL loop
│   ├── phase1_analyze.py    # vision analysis logic
│   ├── phase2_build.py      # Canva MCP build logic
│   ├── schemas.py           # Pydantic models
│   ├── config.py            # env loading, model shortname mapping, pricing
│   └── prompts/
│       ├── phase1_system.md
│       └── phase2_system.md
├── saved_specs/             # gitignored, created at runtime
└── sessions/                # gitignored, created at runtime
```

---

## 13. Error Handling Requirements

- All API calls wrapped in try/except with friendly, actionable error messages
- Specifically handle: missing `.env`, invalid Anthropic API key (401), invalid Canva token (401 from MCP), rate limits (429), network errors, malformed JSON from Claude, image file not found or unsupported format
- Never crash with a raw stack trace in the user's face — catch at the top level and print a clean error with a hint
- For the Phase 1 JSON parse, retry once automatically before surfacing the failure

---

## 14. README Requirements

The README must include, in this order:

1. One-paragraph description of what the tool does
2. **Quickstart** (5 numbered steps max from clone to first run)
3. **Setup**
   - Python 3.11+ check
   - `uv sync` or `pip install -r requirements.txt`
   - Copy `.env.example` to `.env` and fill in keys
4. **Getting your Anthropic API key** (link to console.anthropic.com)
5. **Getting your Canva access token** (detailed steps)
6. **Usage examples** (3-4 example commands covering common cases)
7. **Customizing the prompts** (point to `prompts/` directory)
8. **Cost estimates** (table of approximate cost per run by model combo)
9. **Troubleshooting** (3-5 common errors and fixes)
10. **Security warning** — DO NOT commit `.env`

---

## 15. Build Order for Cursor

Tackle in this exact order to keep each step testable:

1. Project scaffolding: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md` skeleton, directory structure
2. `config.py` — env loading, model shortname mapping, pricing table
3. `schemas.py` — Pydantic models
4. `prompts/phase1_system.md` — write the analysis system prompt
5. `phase1_analyze.py` — image → base64 → API call → JSON parse → spec object. Test this standalone with a sample image.
6. `cli.py` — Typer command + the REPL review loop with `rich`. At this point the user can analyze + review + revise specs (Phase 2 not wired yet).
7. `prompts/phase2_system.md` — write the build system prompt
8. `phase2_build.py` — MCP-enabled API call with streaming tool calls. Verify Canva token works first with a minimal hello-world call.
9. Wire Phase 2 into the REPL behind the `approve` command.
10. `--memory` flag, `--log-session` flag, polish.
11. Fill out the full README.
12. Test end-to-end with a real reference image.

---

## 16. Out of Scope (v1)

- Web UI
- Multi-user / accounts
- Storing reference images in the repo
- Automated A/B generation of multiple design variants (could be v2)
- Direct Etsy publishing integration
- Anything beyond the Anthropic + Canva integration

---

## 17. Definition of Done

The project is done when:
- `python -m canva_agent run --image <path>` runs end-to-end without crashing
- Phase 1 produces a valid `DesignSpec` JSON for a digital planner reference image
- The review loop allows `approve` / `edit` / `revise` / `save` / `quit` and each works
- Phase 2, after approval, successfully calls Canva MCP and returns at least one design URL
- `.env` handling is bulletproof — no key ever leaks to terminal, logs, or saved files
- The README is complete and a stranger could clone + run the project in under 10 minutes
