"""Phase 2: Canva MCP build from approved DesignSpec."""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic
from anthropic import APIError, APIStatusError
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from canva_agent.config import (
    CANVA_MCP_URL,
    MCP_BETA,
    get_api_key,
    get_canva_token,
    resolve_model,
)
from pathlib import Path

from canva_agent.phase1_analyze import spec_to_json
from canva_agent.schemas import DesignSpec

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
console = Console()
DESIGN_URL_RE = re.compile(r"https?://(?:www\.)?canva\.com/design/[^\s\"'<>]+", re.I)


def _load_system_prompt() -> str:
    return (PROMPTS_DIR / "phase2_system.md").read_text(encoding="utf-8")


def _mcp_config(token: str) -> tuple[list[dict], list[dict]]:
    servers = [
        {
            "type": "url",
            "url": CANVA_MCP_URL,
            "name": "canva",
            "authorization_token": token,
        }
    ]
    tools = [{"type": "mcp_toolset", "mcp_server_name": "canva"}]
    return servers, tools


def _extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(DESIGN_URL_RE.findall(text)))


def _format_block(block: Any) -> str | None:
    if getattr(block, "type", None) == "text":
        return block.text
    if getattr(block, "type", None) == "tool_use":
        return f"[tool] {block.name}({json.dumps(block.input)[:200]}...)"
    return None


def _run_stream(
    client: anthropic.Anthropic,
    model_id: str,
    system: str,
    user_content: str,
    token: str,
) -> tuple[str, list[str]]:
    servers, tools = _mcp_config(token)
    collected_text: list[str] = []
    design_urls: list[str] = []
    status = Text("Connecting to Canva MCP...", style="cyan")

    with Live(status, console=console, refresh_per_second=8) as live:
        with client.beta.messages.stream(
            model=model_id,
            max_tokens=16384,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            mcp_servers=servers,
            tools=tools,
            betas=[MCP_BETA],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        collected_text.append(delta.text)
                        live.update(Text("".join(collected_text)[-500:], style="dim"))
                elif event.type == "content_block_start":
                    block = event.content_block
                    line = _format_block(block)
                    if line:
                        collected_text.append(line + "\n")

        final = stream.get_final_message()
        for block in final.content:
            line = _format_block(block)
            if line:
                collected_text.append(line + "\n")
            if getattr(block, "type", None) == "text":
                design_urls.extend(_extract_urls(block.text))

    full_text = "".join(collected_text)
    design_urls = list(dict.fromkeys(design_urls + _extract_urls(full_text)))
    return full_text, design_urls


def build_design(spec: DesignSpec, model: str = "sonnet", feedback: str = "") -> list[str]:
    """Run Phase 2 MCP build. Returns design URLs found."""
    model_id = resolve_model(model)
    system = _load_system_prompt()
    spec_json = spec_to_json(spec)

    user_content = f"Build this design in Canva using the spec:\n\n{spec_json}"
    if feedback.strip():
        user_content = f"Refine the design with this feedback: {feedback.strip()}\n\nSpec:\n{spec_json}"

    client = anthropic.Anthropic(api_key=get_api_key())
    token = get_canva_token()

    try:
        _, urls = _run_stream(client, model_id, system, user_content, token)
    except APIStatusError as e:
        if e.status_code == 401:
            raise RuntimeError(
                "Canva authentication failed (401). Your CANVA_ACCESS_TOKEN may be "
                "expired (~4 hours). See README.md → Getting your Canva access token."
            ) from e
        if e.status_code == 429:
            raise RuntimeError("Rate limit hit. Wait and try again.") from e
        raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
    except APIError as e:
        raise RuntimeError(f"API error: {e}") from e

    if urls:
        console.print("\n[bold green]Design ready:[/bold green]")
        for url in urls:
            console.print(f"  {url}")
    else:
        console.print(
            Panel(
                "Build finished but no canva.com/design URL was detected in the response. "
                "Check Canva directly or try tweak with more specific feedback.",
                title="No URL found",
                border_style="yellow",
            )
        )
    return urls


def smoke_test_mcp() -> None:
    """Minimal MCP connectivity check."""
    model_id = resolve_model("sonnet")
    client = anthropic.Anthropic(api_key=get_api_key())
    token = get_canva_token()
    servers, tools = _mcp_config(token)

    console.print("[cyan]Testing Canva MCP connection...[/cyan]")
    try:
        response = client.beta.messages.create(
            model=model_id,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": "List the Canva MCP tools you have access to. Reply briefly.",
                }
            ],
            mcp_servers=servers,
            tools=tools,
            betas=[MCP_BETA],
        )
        for block in response.content:
            if block.type == "text":
                console.print(block.text)
        console.print("[green]MCP smoke test OK[/green]")
    except APIStatusError as e:
        if e.status_code == 401:
            raise RuntimeError(
                "Canva token invalid or expired. See README.md → Getting your Canva access token."
            ) from e
        raise
