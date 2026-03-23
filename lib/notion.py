"""
Notion API wrapper.
All DB IDs and property names are exact-matched to the live schemas.
"""

import os
import requests
from datetime import datetime, date
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"

# Database IDs — page IDs from Notion URLs (used by REST API)
DB_RESEARCH = "e3acb755-1822-4972-bc6d-afd43bdeb0ac"
DB_IDEAS = "f10f7723-3b07-40bb-b102-a0f61c0c7cc7"
DB_SCRIPT_LIBRARY = "328e1b43-3099-80f7-8757-c81031ad79df"
DB_CONTENT_CALENDAR = "328e1b43-3099-80b9-b663-ec69cbb84088"
DB_WEEKLY_SCORECARD = "73cc6247-1de2-4c16-987b-661fb05e32e1"


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def query_database(db_id: str, filter_obj: dict = None, sorts: list = None) -> list:
    """Return all pages from a database, handling pagination."""
    url = f"{BASE_URL}/databases/{db_id}/query"
    payload = {}
    if filter_obj:
        payload["filter"] = filter_obj
    if sorts:
        payload["sorts"] = sorts

    pages = []
    has_more = True
    cursor = None
    while has_more:
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(url, headers=_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")
    return pages


def get_page(page_id: str) -> dict:
    resp = requests.get(f"{BASE_URL}/pages/{page_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def create_page(db_id: str, properties: dict, children: list = None) -> dict:
    payload = {
        "parent": {"database_id": db_id},
        "properties": properties,
    }
    if children:
        payload["children"] = children
    resp = requests.post(f"{BASE_URL}/pages", headers=_headers(), json=payload)
    if not resp.ok:
        print(f"[notion] create_page error {resp.status_code}: {resp.text[:2000]}")
    resp.raise_for_status()
    return resp.json()


def get_page_text(page_id: str) -> str:
    """Fetch all block content from a page and return as plain text."""
    url = f"{BASE_URL}/blocks/{page_id}/children"
    lines = []
    has_more = True
    cursor = None
    while has_more:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = requests.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        for block in data.get("results", []):
            block_type = block.get("type", "")
            content = block.get(block_type, {})
            rich_text = content.get("rich_text", [])
            text = "".join(rt.get("plain_text", "") for rt in rich_text)
            if text:
                lines.append(text)
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")
    return "\n".join(lines)


def append_blocks(page_id: str, blocks: list) -> None:
    """Append content blocks to a page in batches of 100 (Notion API limit)."""
    url = f"{BASE_URL}/blocks/{page_id}/children"
    for i in range(0, len(blocks), 100):
        batch = blocks[i:i + 100]
        resp = requests.patch(url, headers=_headers(), json={"children": batch})
        if not resp.ok:
            print(f"[notion] append_blocks error {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()


def update_page(page_id: str, properties: dict) -> dict:
    resp = requests.patch(
        f"{BASE_URL}/pages/{page_id}",
        headers=_headers(),
        json={"properties": properties},
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Property builders — matches the exact schema types from each DB
# ---------------------------------------------------------------------------

def prop_title(text: str) -> dict:
    return {"title": [{"text": {"content": text}}]}


def prop_rich_text(text: str) -> dict:
    # Notion rich_text blocks have a 2000 char limit per block; chunk if needed
    chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks]}


def prop_select(value: str) -> dict:
    return {"select": {"name": value}}


def prop_multi_select(values: list) -> dict:
    return {"multi_select": [{"name": v} for v in values]}


def prop_checkbox(value: bool) -> dict:
    return {"checkbox": value}


def prop_number(value: float) -> dict:
    return {"number": value}


def prop_date(start: str, end: str = None) -> dict:
    """start/end as ISO-8601 date strings (YYYY-MM-DD)."""
    d = {"start": start}
    if end:
        d["end"] = end
    return {"date": d}


def prop_relation(page_urls: list) -> dict:
    """page_urls: list of Notion page URLs or IDs."""
    ids = []
    for u in page_urls:
        # Extract ID from URL if needed
        pid = u.split("/")[-1].split("?")[0]
        # Remove dashes if already UUID-formatted
        ids.append({"id": pid})
    return {"relation": ids}


# ---------------------------------------------------------------------------
# Convenience: get latest Research row
# ---------------------------------------------------------------------------

def get_latest_analysis() -> Optional[dict]:
    """Get the most recent Competitor Analysis row from the Research DB."""
    pages = query_database(
        DB_RESEARCH,
        filter_obj={"property": "Type", "select": {"equals": "Competitor Analysis"}},
        sorts=[{"property": "Content Week", "direction": "descending"}],
    )
    return pages[0] if pages else None


def get_latest_performance_insights() -> Optional[str]:
    """Get the most recent Performance Analysis report text from the Research DB."""
    pages = query_database(
        DB_RESEARCH,
        filter_obj={"property": "Type", "select": {"equals": "Performance Analysis"}},
        sorts=[{"property": "Content Week", "direction": "descending"}],
    )
    if not pages:
        return None
    return get_page_text(pages[0]["id"])


def get_all_live_posts() -> list:
    """
    Query Content Calendar for all posts with Status=Live.
    Returns structured list for performance analysis — name, platform, pillar, views, clicks.
    Only includes posts that have views recorded (i.e. metrics have been collected).
    """
    pages = query_database(
        DB_CONTENT_CALENDAR,
        filter_obj={"property": "Status", "status": {"equals": "Live"}},
        sorts=[{"property": "Publish Date", "direction": "descending"}],
    )
    posts = []
    for page in pages:
        props = page.get("properties", {})

        title_arr = props.get("Name", {}).get("title", [])
        name = title_arr[0].get("plain_text", "") if title_arr else ""

        views = props.get("Views", {}).get("number") or 0
        link_clicks = props.get("Link Clicks", {}).get("number") or 0

        platform_ms = props.get("Platform", {}).get("multi_select", [])
        platforms = [p.get("name", "") for p in platform_ms]

        pillar_sel = props.get("Pillar", {}).get("select") or {}
        pillar = pillar_sel.get("name", "")

        pub_date = props.get("Publish Date", {}).get("date") or {}
        published_at = pub_date.get("start", "")

        # Only include posts that have had metrics collected
        if name and views > 0:
            posts.append({
                "name": name,
                "platforms": platforms,
                "pillar": pillar,
                "views": views,
                "link_clicks": link_clicks,
                "published_at": published_at,
            })

    return posts


def get_latest_research_row() -> Optional[dict]:
    pages = query_database(
        DB_RESEARCH,
        filter_obj={"property": "Type", "select": {"equals": "Research"}},
        sorts=[{"property": "Content Week", "direction": "descending"}],
    )
    return pages[0] if pages else None


# ---------------------------------------------------------------------------
# Convenience: get approved ideas not yet in Script Library
# ---------------------------------------------------------------------------

def _parse_inline(text: str) -> list:
    """Convert inline markdown (bold, italic, code) to Notion rich_text annotation format."""
    import re
    rich_text = []
    pattern = r'(\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`|([^*`\n]+))'
    for match in re.finditer(pattern, text):
        bold_italic = match.group(2)
        bold = match.group(3)
        italic = match.group(4)
        code = match.group(5)
        plain = match.group(6)
        if bold_italic:
            rich_text.append({"type": "text", "text": {"content": bold_italic},
                               "annotations": {"bold": True, "italic": True}})
        elif bold:
            rich_text.append({"type": "text", "text": {"content": bold},
                               "annotations": {"bold": True}})
        elif italic:
            rich_text.append({"type": "text", "text": {"content": italic},
                               "annotations": {"italic": True}})
        elif code:
            rich_text.append({"type": "text", "text": {"content": code},
                               "annotations": {"code": True}})
        elif plain:
            rich_text.append({"type": "text", "text": {"content": plain}})
    return rich_text if rich_text else [{"type": "text", "text": {"content": text}}]


def markdown_to_blocks(text: str) -> list:
    """
    Convert a markdown string to a list of Notion API block objects.
    Supports: ## headings, ### headings, bullet lists, numbered lists,
    blockquotes, dividers, bold/italic inline, and plain paragraphs.
    """
    import re
    blocks = []
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        if s.startswith('### '):
            blocks.append({"object": "block", "type": "heading_3",
                            "heading_3": {"rich_text": _parse_inline(s[4:])}})
        elif s.startswith('## '):
            blocks.append({"object": "block", "type": "heading_2",
                            "heading_2": {"rich_text": _parse_inline(s[3:])}})
        elif s.startswith('# '):
            blocks.append({"object": "block", "type": "heading_1",
                            "heading_1": {"rich_text": _parse_inline(s[2:])}})
        elif s in ('---', '***', '___'):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif s.startswith('- ') or s.startswith('* '):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": _parse_inline(s[2:])}})
        elif re.match(r'^\d+\.\s', s):
            content = re.sub(r'^\d+\.\s', '', s)
            blocks.append({"object": "block", "type": "numbered_list_item",
                            "numbered_list_item": {"rich_text": _parse_inline(content)}})
        elif s.startswith('> '):
            blocks.append({"object": "block", "type": "quote",
                            "quote": {"rich_text": _parse_inline(s[2:])}})
        else:
            blocks.append({"object": "block", "type": "paragraph",
                            "paragraph": {"rich_text": _parse_inline(s)}})
    return blocks


def get_approved_ideas() -> list:
    return query_database(
        DB_IDEAS,
        filter_obj={"property": "Status", "select": {"equals": "Approved"}},
    )


# ---------------------------------------------------------------------------
# Convenience: get current week Scorecard row (by Date range containing today)
# ---------------------------------------------------------------------------

def get_or_create_scorecard_row(week_start: str, week_end: str, week_label: str) -> dict:
    """Find a scorecard row for the given week or create one."""
    pages = query_database(DB_WEEKLY_SCORECARD)
    for page in pages:
        date_prop = page["properties"].get("Date", {}).get("date")
        if date_prop and date_prop.get("start") == week_start:
            return page

    # Create new row
    return create_page(
        DB_WEEKLY_SCORECARD,
        {
            "Week": prop_title(week_label),
            "Date": prop_date(week_start, week_end),
        },
    )
