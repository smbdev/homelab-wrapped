"""Email digests, sent through the user's own SMTP server.

Plain-text email built from a story spec. Redaction doesn't apply here: the
digest goes to the user's own inbox via their own server, like the local web
view (§6 governs *exports*, which are share-bound).
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from wrapped.core.config import EmailConfig


def render_digest(story: dict[str, Any]) -> tuple[str, str]:
    """Turn a story spec into ``(subject, plain-text body)``.

    Args:
        story: A story spec as produced by :func:`wrapped.core.story.build_story`.

    Returns:
        Subject line and body. Cards render as headline plus optional sub-line;
        list cards include their ranked items.
    """
    label = story["period"]["label"]
    lines = [label, "=" * len(label), ""]
    for card in story["cards"]:
        lines.append(f"• {card['headline']}")
        for item in card.get("items", []):
            lines.append(f"    {item['label']} — {item['value']}")
        if card.get("sub"):
            lines.append(f"  {card['sub']}")
        lines.append("")
    lines.append("— Homelab Wrapped, from your own server")
    return f"Homelab Wrapped: {label}", "\n".join(lines)


def send_digest(email: EmailConfig, subject: str, body: str) -> None:
    """Send a digest through the configured SMTP server.

    Uses STARTTLS by default and logs in only when a username is configured,
    so unauthenticated LAN relays work too.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email.from_addr
    msg["To"] = email.to
    msg.set_content(body)
    with smtplib.SMTP(email.smtp_host, email.smtp_port, timeout=30) as smtp:
        if email.starttls:
            smtp.starttls()
        if email.username:
            smtp.login(email.username, email.password or "")
        smtp.send_message(msg)
