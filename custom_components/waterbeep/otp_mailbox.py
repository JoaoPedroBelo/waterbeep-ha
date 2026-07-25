"""Read the Waterbeep two-factor code back from a Resend inbound mailbox.

Optional, opt-in. Waterbeep can deliver its one-time code by email; when the
user forwards that mail to a `Resend <https://resend.com>`_ inbound address,
this module reads the code out of it so the challenge clears with nobody
touching the Home Assistant UI::

    Waterbeep --(OTP mail)--> user mailbox --(forwarding rule)--> Resend inbound
                                                                       |
              HA polls GET /emails/receiving  <-------------------------+

Two Resend endpoints are used, both ``GET`` and bearer-authenticated:

``/emails/receiving``
    Recent inbound mail, metadata only (``id``, ``from``, ``to``, ``subject``,
    ``created_at``).
``/emails/receiving/{id}``
    The full message (``text``, ``html``, ``headers``).

Resend's ``email.received`` webhook is deliberately *not* used: it would require
Home Assistant to be reachable from the internet, whereas the list endpoint keeps
this a pure cloud-polling integration like the rest of the component.

Resend network logic lives here rather than in ``api.py``, which owns the
Waterbeep session and its private cookie jar. The coordinator and config flow
still never talk HTTP directly — they drive this client.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
import logging
import re
from time import monotonic
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    CONF_OTP_FROM_FILTER,
    CONF_OTP_RESEND_API_KEY,
    CONF_OTP_TO_FILTER,
    OTP_CLOCK_SKEW,
    OTP_CODE_LENGTH,
    OTP_POLL_INTERVAL,
    OTP_WAIT_TIMEOUT,
    RESEND_API_BASE,
    RESEND_LIST_LIMIT,
    RESEND_RECEIVING_PATH,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30  # seconds

# Strip non-visible markup before scanning an HTML body: CSS/JS blocks are full
# of digits that would otherwise look like candidate codes.
_HTML_BLOCK_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Digits inside a URL or an address are never the code, but they do satisfy the
# fallback pattern below — verified against a real Gmail forwarding-confirmation
# mail, where ``support.google.com/…/answer.py?answer=184973`` was picked up as a
# code. Both shapes are removed before anything is scanned.
_NOISE_RE = re.compile(r"https?://\S+|www\.\S+|\S*@\S+", re.IGNORECASE)

# Preferred match: a code introduced by a word that means "code" (PT or EN).
# ``\D`` spans the words and punctuation between the two ("o seu código de
# verificação é: 123456"), bounded so a keyword cannot claim a distant number.
_KEYWORD_CODE_RE = re.compile(
    rf"(?:c[oó]digo|code|otp|pin|verifica\w*)\D{{0,40}}?(\d{{{OTP_CODE_LENGTH}}})",
    re.IGNORECASE,
)
# Fallback: any standalone group of exactly OTP_CODE_LENGTH digits.
_BARE_CODE_RE = re.compile(rf"(?<!\d)(\d{{{OTP_CODE_LENGTH}}})(?!\d)")


class OtpMailboxError(Exception):
    """Raised when the Resend inbox cannot be read."""


def html_to_text(html: str) -> str:
    """Flatten an HTML body into scannable plain text."""
    text = _HTML_BLOCK_RE.sub(" ", html)
    text = _HTML_TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", unescape(text)).strip()


def scrub(text: str) -> str:
    """Drop URLs and addresses, whose digits are never the code."""
    return _NOISE_RE.sub(" ", text)


def extract_otp_code(*parts: str | None) -> str | None:
    """Pull the one-time code out of ``parts``, in order of trust.

    Runs the keyword-anchored pattern across every part first, so "o seu código
    é 123456" wins over an unrelated number that happens to appear earlier in
    the same mail (an order total, a reference). Only if no part yields a
    keyword match does it fall back to the first standalone 6-digit group —
    which is why URLs and addresses are scrubbed out first.
    """
    candidates = [scrub(part) for part in parts if part]
    for pattern in (_KEYWORD_CODE_RE, _BARE_CODE_RE):
        for candidate in candidates:
            match = pattern.search(candidate)
            if match:
                return match.group(1)
    return None


@dataclass(frozen=True)
class OtpMailboxConfig:
    """Resolved settings for the automatic code retrieval."""

    api_key: str
    from_filter: str = ""
    to_filter: str = ""

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> OtpMailboxConfig | None:
        """Build from merged config-entry data+options, or ``None`` when off.

        The feature is opt-in: no API key means no automatic retrieval, and an
        API key cleared through the options flow disables it again.
        """
        api_key = str(config.get(CONF_OTP_RESEND_API_KEY) or "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            from_filter=str(config.get(CONF_OTP_FROM_FILTER) or "").strip().lower(),
            to_filter=str(config.get(CONF_OTP_TO_FILTER) or "").strip().lower(),
        )

    def matches(self, email: Mapping[str, Any]) -> bool:
        """Check an inbound mail's ``from``/``to`` against the configured filters."""
        if self.from_filter and self.from_filter not in _joined(email.get("from")):
            return False
        return not (self.to_filter and self.to_filter not in _joined(email.get("to")))


@callback
def async_create_mailbox(
    hass: HomeAssistant, config: Mapping[str, Any]
) -> ResendOtpMailbox | None:
    """Build a mailbox from a config mapping, or ``None`` when not configured."""
    mailbox_config = OtpMailboxConfig.from_config(config)
    if mailbox_config is None:
        return None
    return ResendOtpMailbox(async_get_clientsession(hass), mailbox_config)


class ResendOtpMailbox:
    """Poll a Resend inbound mailbox for a freshly issued Waterbeep OTP."""

    def __init__(
        self, session: aiohttp.ClientSession, config: OtpMailboxConfig
    ) -> None:
        """Store the shared HA session (no cookies involved) and the settings."""
        self._session = session
        self._config = config
        # Message IDs already inspected, so repeated polls only fetch new mail.
        self._seen: set[str] = set()

    async def async_wait_for_code(
        self,
        since: datetime,
        *,
        timeout: float = OTP_WAIT_TIMEOUT,
        interval: float = OTP_POLL_INTERVAL,
    ) -> str | None:
        """Wait for the forwarded code mail and return the code, or ``None``.

        ``since`` is the moment Waterbeep was asked to send the code; anything
        older is ignored so a previous attempt's code can never be replayed.
        Returns ``None`` when nothing usable arrived before ``timeout``.
        """
        deadline = monotonic() + timeout
        while True:
            code = await self.async_fetch_code(since)
            if code is not None:
                return code
            if monotonic() + interval >= deadline:
                _LOGGER.debug(
                    "No Waterbeep code mail in the Resend inbox after %ss", timeout
                )
                return None
            await asyncio.sleep(interval)

    async def async_fetch_code(self, since: datetime) -> str | None:
        """Inspect the inbox once and return a code if one is already there."""
        cutoff = since - timedelta(seconds=OTP_CLOCK_SKEW)
        for email in await self._async_list_candidates(cutoff):
            email_id = str(email["id"])
            self._seen.add(email_id)
            full = await self._async_get(email_id)
            code = extract_otp_code(
                full.get("subject"),
                full.get("text"),
                html_to_text(full.get("html") or ""),
            )
            if code is not None:
                _LOGGER.debug("Found a Waterbeep code in inbound mail %s", email_id)
                return code
            _LOGGER.debug(
                "Inbound mail %s carries no %s-digit code", email_id, OTP_CODE_LENGTH
            )
        return None

    async def _async_list_candidates(self, cutoff: datetime) -> list[dict[str, Any]]:
        """List not-yet-inspected inbound mail newer than ``cutoff``, newest first."""
        payload = await self._async_request(
            RESEND_RECEIVING_PATH, {"limit": str(RESEND_LIST_LIMIT)}
        )
        raw = payload.get("data")
        if not isinstance(raw, list):
            return []

        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for email in raw:
            if not isinstance(email, dict) or not email.get("id"):
                continue
            if str(email["id"]) in self._seen:
                continue
            received = dt_util.parse_datetime(str(email.get("created_at") or ""))
            if received is None or received < cutoff:
                continue
            if not self._config.matches(email):
                continue
            candidates.append((received, email))

        # Resend does not document the list order, so sort explicitly: the most
        # recent mail carries the most recent code.
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [email for _, email in candidates]

    async def _async_get(self, email_id: str) -> dict[str, Any]:
        """Retrieve one inbound mail in full (body + headers)."""
        return await self._async_request(f"{RESEND_RECEIVING_PATH}/{email_id}")

    async def _async_request(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """GET a Resend endpoint and return its JSON body."""
        url = f"{RESEND_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Accept": "application/json",
        }
        try:
            async with self._session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in {401, 403}:
                    raise OtpMailboxError(
                        f"Resend rejected the API key (HTTP {resp.status})"
                    )
                resp.raise_for_status()
                result: dict[str, Any] = await resp.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            raise OtpMailboxError(f"{path} returned HTTP {err.status}") from err
        except aiohttp.ClientError as err:
            raise OtpMailboxError(f"{path} request failed: {err}") from err
        except TimeoutError as err:
            raise OtpMailboxError(f"{path} timed out") from err
        if not isinstance(result, dict):
            raise OtpMailboxError(f"{path} returned an unexpected payload")
        return result


def _joined(value: Any) -> str:
    """Lower-case a Resend address field (``str`` or list of ``str``)."""
    if isinstance(value, list):
        return " ".join(str(item) for item in value).lower()
    return str(value or "").lower()
