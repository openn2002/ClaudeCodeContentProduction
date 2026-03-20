"""
Slack webhook wrapper.
Two channels: #content-pipeline and #organic-growth.
"""

import os
import requests

WEBHOOK_CONTENT_PIPELINE = os.getenv("SLACK_WEBHOOK_CONTENT_PIPELINE")
WEBHOOK_ORGANIC_GROWTH = os.getenv("SLACK_WEBHOOK_ORGANIC_GROWTH")


def _send(webhook_url: str, text: str, blocks: list = None):
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    resp = requests.post(webhook_url, json=payload)
    resp.raise_for_status()


def notify_content_pipeline(text: str, blocks: list = None):
    """Post to #content-pipeline."""
    _send(WEBHOOK_CONTENT_PIPELINE, text, blocks)


def notify_organic_growth(text: str, blocks: list = None):
    """Post to #organic-growth."""
    _send(WEBHOOK_ORGANIC_GROWTH, text, blocks)


# ---------------------------------------------------------------------------
# Reusable block builders
# ---------------------------------------------------------------------------

def section_block(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def divider_block() -> dict:
    return {"type": "divider"}


def button_block(text: str, url: str) -> dict:
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": text},
                "url": url,
            }
        ],
    }
