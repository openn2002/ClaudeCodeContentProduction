"""
Notion API wrapper.
All DB IDs and property names are exact-matched to the live schemas.
"""

import os
import requests
from datetime import datetime, date

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"

# Database IDs
DB_RESEARCH = "9abf1967-ffe8-4bc4-a2a4-b7bfe2a9f74f"
DB_IDEAS = "4a07179d-be0f-48fc-959d-da70809a10d8"
DB_SCRIPT_LIBRARY = "328e1b43-3099-80c0-8d2c-000bf61a8845"
DB_CONTENT_CALENDAR = "328e1b43-3099-80c1-82ce-000bb19649d3"
DB_WEEKLY_SCORECARD = "650e541d-a675-4348-8a8b-b024499471ac"


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
    resp.raise_for_status()
    return resp.json()


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
    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
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

def get_latest_research_row() -> dict | None:
    pages = query_database(
        DB_RESEARCH,
        sorts=[{"property": "Week", "direction": "descending"}],
    )
    return pages[0] if pages else None


# ---------------------------------------------------------------------------
# Convenience: get approved ideas not yet in Script Library
# ---------------------------------------------------------------------------

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
