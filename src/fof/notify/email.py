"""Email push through Resend's HTTP API (free plan: 100 emails/day). Configured by environment variables:

RESEND_API_KEY   the API key (send-only scope)
FOF_EMAIL_TO     the inbox that receives the digests
FOF_EMAIL_FROM   sender; defaults to Resend's shared test sender, which can only mail the account owner
"""
from __future__ import annotations

import os

from ..ingest.http import post_json

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Fact or Fluke <onboarding@resend.dev>"


def send(subject: str, text: str, html: str | None = None) -> str:
    """Sends one email and returns Resend's message id."""
    key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("FOF_EMAIL_TO")
    if not key or not to:
        raise RuntimeError("RESEND_API_KEY and FOF_EMAIL_TO must be set")
    payload = {"from": os.environ.get("FOF_EMAIL_FROM", DEFAULT_FROM), "to": [to], "subject": subject, "text": text}
    if html:
        payload["html"] = html
    return post_json(RESEND_URL, payload, {"Authorization": f"Bearer {key}"}).get("id", "")
