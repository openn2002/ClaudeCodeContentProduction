#!/usr/bin/env python3
"""
migrate_scripts.py — One-off migration script.

Restructures all existing Script Library entries into the new 6-section format:
  Creative Direction, Hook (3 options), Script Outline (spoken content only),
  Key On-Screen Text, CTA, Caption

Writes the result as formatted Notion page body blocks so bold/italic/headings
render correctly. Spoken content is preserved word-for-word. Visual directions,
director's notes, production notes, and rationale commentary are stripped.

Usage:
  python migrate_scripts.py
"""

import sys
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

import anthropic
from lib.notion import append_blocks, markdown_to_blocks, DB_SCRIPT_LIBRARY

load_dotenv(override=True)

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"
MODEL = "claude-sonnet-4-6"


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def get_all_scripts():
    resp = requests.post(
        f"{BASE_URL}/databases/{DB_SCRIPT_LIBRARY}/query",
        headers=_headers(),
        json={},
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def get_prop_text(props, prop_name):
    rich_text = props.get(prop_name, {}).get("rich_text", [])
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def get_title(props):
    blocks = props.get("Name", {}).get("title", [])
    return "".join(b.get("plain_text", "") for b in blocks)


def clear_page_blocks(page_id):
    """Delete all existing blocks from a page."""
    url = f"{BASE_URL}/blocks/{page_id}/children"
    resp = requests.get(url, headers=_headers(), params={"page_size": 100})
    resp.raise_for_status()
    block_ids = [b["id"] for b in resp.json().get("results", [])]
    for bid in block_ids:
        del_resp = requests.delete(f"{BASE_URL}/blocks/{bid}", headers=_headers())
        if not del_resp.ok:
            print(f"    Warning: could not delete block {bid}")


SYSTEM_PROMPT = """You restructure existing video scripts into a clean 6-section format.

The 6 sections are:

## Creative Direction
2–3 sentences max. Who is filming, what's the setting, what's the overall vibe.
Keep it practical and simple — this is the brief for the person picking up a camera, not a director's shot list.
Factor in any team comments provided. Less is more here — avoid over-engineering it.

## Hook
Three hook options, labelled A, B, C. For each:
- **Option A:** One sentence describing the hook approach
- **Spoken line:** The exact opening words (copy these verbatim from the original)

## Script Outline
Scene-by-scene breakdown with rough timing (e.g. 0:00–0:10).
Include SPOKEN CONTENT ONLY — the exact words the talent says.
Do NOT include [Visual:], [Direction:], [Director's note:], [On-screen:], or any production instructions.
These belong in Creative Direction and Key On-Screen Text. Preserve all spoken words exactly.

## Key On-Screen Text
Bullet list of every text overlay in order. Keep each one short and clean.
Remove any notes, context, or rationale attached to items.

## CTA
1–3 sentences for the closing moment. Soft and community-focused by default.
Remove any notes about "why this works", algorithmic rationale, or platform-specific instructions.

## Caption
The social caption and hashtags only.
Strip out all production notes, editor's notes, citation notes, and rationale.
If multiple platform captions exist (TikTok, Instagram, Facebook), keep all of them — just remove the meta-commentary around them.

---

STRICT RULES:
- Preserve ALL spoken content word-for-word. Never change what is said.
- Creative Direction must be 2–3 sentences maximum.
- No meta-commentary, no rationale, no "why this works" explanations anywhere in the output.
- Output only the 6 sections with their ## headings. Nothing else.
"""


def restructure(title, hook, outline, on_screen, cta, caption, comments):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    user_msg = f"""Restructure this script. Title: {title}

TEAM COMMENTS (use to shape Creative Direction):
{comments.strip() if comments.strip() else "None"}

EXISTING HOOK:
{hook}

EXISTING SCRIPT OUTLINE:
{outline}

EXISTING KEY ON-SCREEN TEXT:
{on_screen}

EXISTING CTA:
{cta}

EXISTING CAPTION:
{caption}
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


def main():
    print("=== Script Migration Starting ===\n")
    scripts = get_all_scripts()
    print(f"Found {len(scripts)} scripts to process.\n")

    for i, script in enumerate(scripts, 1):
        props = script.get("properties", {})
        page_id = script["id"]
        title = get_title(props)

        print(f"[{i}/{len(scripts)}] {title}")

        hook = get_prop_text(props, "Hook")
        outline = get_prop_text(props, "Script Outline")
        on_screen = get_prop_text(props, "Key on-screen text callouts")
        cta = get_prop_text(props, "CTA")
        caption = get_prop_text(props, "Caption")
        comments = get_prop_text(props, "Comments")

        if not hook and not outline:
            print("  ⚠️  No content in properties — skipping.\n")
            continue

        print("  Restructuring via Claude...")
        new_content = restructure(title, hook, outline, on_screen, cta, caption, comments)

        print("  Clearing existing page body...")
        clear_page_blocks(page_id)

        print("  Writing new blocks to Notion...")
        blocks = markdown_to_blocks(new_content)
        if blocks:
            append_blocks(page_id, blocks)
            print(f"  ✓ {len(blocks)} blocks written.\n")
        else:
            print("  ⚠️  No blocks generated.\n")

    print("=== Migration Complete ===")


if __name__ == "__main__":
    main()
