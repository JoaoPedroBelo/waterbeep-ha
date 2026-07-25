"""Tests for the automatic two-factor code retrieval from a Resend inbox.

Payload shapes mirror Resend's documented ``GET /emails/receiving`` (list) and
``GET /emails/receiving/{id}`` (single message) responses.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from unittest.mock import patch

import aiohttp
from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from custom_components.waterbeep.const import (
    CONF_OTP_FROM_FILTER,
    CONF_OTP_RESEND_API_KEY,
    CONF_OTP_TO_FILTER,
    RESEND_API_BASE,
    RESEND_LIST_LIMIT,
    RESEND_RECEIVING_PATH,
)
from custom_components.waterbeep.otp_mailbox import (
    OtpMailboxConfig,
    OtpMailboxError,
    ResendOtpMailbox,
    async_create_mailbox,
    extract_otp_code,
    html_to_text,
)

API_KEY = "re_testkey"
LIST_URL = f"{RESEND_API_BASE}{RESEND_RECEIVING_PATH}?limit={RESEND_LIST_LIMIT}"


def _detail_url(email_id: str) -> str:
    return f"{RESEND_API_BASE}{RESEND_RECEIVING_PATH}/{email_id}"


def _stamp(moment: datetime) -> str:
    """Format a datetime the way Resend does (ISO 8601, ``Z`` suffix)."""
    return moment.isoformat().replace("+00:00", "Z")


def _meta(
    email_id: str,
    received: datetime,
    sender: str = "noreply@aquamatrix.pt",
    to: str = "waterbeep@inbound.example.pt",
) -> dict:
    """Build one entry of the list-received-emails payload."""
    return {
        "id": email_id,
        "from": sender,
        "to": [to],
        "subject": "Waterbeep",
        "created_at": _stamp(received),
    }


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """A session owned by the test.

    Deliberately not Home Assistant's shared session, which outlives the test.
    Nothing here needs it — the client takes any session.

    The explicit ``ThreadedResolver`` matters: with ``aiodns`` installed (a Home
    Assistant dependency) aiohttp defaults to ``AsyncResolver``, whose pycares
    channel starts a daemon thread that survives the test and trips
    ``pytest_homeassistant_custom_component``'s lingering-thread check. No DNS
    ever happens here anyway — ``aioresponses`` intercepts every request.
    """
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as client:
        yield client


def _mailbox(session: aiohttp.ClientSession, **extra) -> ResendOtpMailbox:
    """Build a mailbox with the same config path the coordinator uses."""
    config = OtpMailboxConfig.from_config({CONF_OTP_RESEND_API_KEY: API_KEY, **extra})
    assert config is not None
    return ResendOtpMailbox(session, config)


# --- Code extraction -------------------------------------------------------


def test_extract_prefers_the_keyword_anchored_code() -> None:
    """A number introduced by "código" beats an unrelated earlier number."""
    body = "Fatura 998877 emitida. O seu codigo de verificacao e 123456. Obrigado."
    assert extract_otp_code(body) == "123456"


def test_extract_accepts_a_portuguese_accented_keyword() -> None:
    """The keyword pattern matches the accented Portuguese wording."""
    assert extract_otp_code("O seu código é: 654321") == "654321"


def test_extract_falls_back_to_a_standalone_group() -> None:
    """With no keyword at all, a lone 6-digit group is still accepted."""
    assert extract_otp_code("Waterbeep\n\n456789\n\nAquamatrix") == "456789"


def test_extract_scans_the_subject_first() -> None:
    """The subject is the most trustworthy place for the code."""
    assert extract_otp_code("Codigo 111222", "no code in the body here") == "111222"


def test_extract_ignores_longer_digit_runs() -> None:
    """A 9-digit reference is not a 6-digit code."""
    assert extract_otp_code("Referencia 123456789 para pagamento") is None


def test_extract_returns_none_without_any_code() -> None:
    """Unrelated mail yields nothing rather than a wrong guess."""
    assert extract_otp_code("Newsletter", None, "") is None


def test_extract_ignores_digits_inside_urls_and_addresses() -> None:
    """Regression: a real Gmail forwarding-confirmation mail yielded a fake code.

    Trimmed from an actual message received in the Resend inbox. It contains no
    code at all, but ``answer.py?answer=184973`` satisfied the bare 6-digit
    fallback until URLs and addresses were scrubbed out first.
    """
    body = (
        "user@example.com has requested to automatically forward mail to\n"
        "your email address waterbeep@inbound.example.pt.\n\n"
        "To learn more about why you might have received this message, please\n"
        "visit: http://support.google.com/mail/bin/answer.py?answer=184973.\n"
    )
    assert extract_otp_code("Gmail Forwarding Confirmation", body) is None


def test_extract_still_finds_a_code_next_to_a_url() -> None:
    """Scrubbing removes the noise, not the code."""
    body = "Codigo: 246813\nDetalhes em https://www.aquamatrix.pt/waterbeep/999999"
    assert extract_otp_code(body) == "246813"


def test_html_to_text_drops_style_blocks() -> None:
    """Digits inside CSS must not be mistaken for the code."""
    html = (
        "<html><head><style>.a{width:100000px;color:#123456}</style></head>"
        "<body><p>O seu c&oacute;digo &eacute; <b>202531</b></p></body></html>"
    )
    text = html_to_text(html)
    assert "width" not in text
    assert extract_otp_code(text) == "202531"


# --- Configuration ---------------------------------------------------------


def test_config_disabled_without_an_api_key() -> None:
    """No key (or a cleared one) means the feature is off."""
    assert OtpMailboxConfig.from_config({}) is None
    assert OtpMailboxConfig.from_config({CONF_OTP_RESEND_API_KEY: "   "}) is None


def test_config_normalises_filters() -> None:
    """Filters are trimmed and lower-cased for substring matching."""
    config = OtpMailboxConfig.from_config(
        {
            CONF_OTP_RESEND_API_KEY: f"  {API_KEY} ",
            CONF_OTP_FROM_FILTER: " Aquamatrix.PT ",
            CONF_OTP_TO_FILTER: "",
        }
    )
    assert config is not None
    assert config.api_key == API_KEY
    assert config.from_filter == "aquamatrix.pt"
    assert config.to_filter == ""


def test_config_matches_from_and_to() -> None:
    """Both filters are optional and applied as substrings."""
    config = OtpMailboxConfig(
        api_key=API_KEY, from_filter="aquamatrix.pt", to_filter="waterbeep@"
    )
    assert config.matches(
        {"from": "NoReply@Aquamatrix.pt", "to": ["waterbeep@inbound.example.pt"]}
    )
    assert not config.matches({"from": "spam@example.com", "to": ["waterbeep@x.pt"]})
    assert not config.matches({"from": "x@aquamatrix.pt", "to": ["other@x.pt"]})
    # No filters configured: anything in the dedicated inbox is fair game.
    assert OtpMailboxConfig(api_key=API_KEY).matches({"from": "a@b.c", "to": []})


# --- Inbox polling ---------------------------------------------------------


async def test_fetch_code_reads_the_newest_matching_mail(
    session: aiohttp.ClientSession,
) -> None:
    """The most recent inbound mail wins, whatever order Resend lists them in."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        mocked.get(
            LIST_URL,
            payload={
                "data": [
                    _meta("old", since + timedelta(seconds=5)),
                    _meta("new", since + timedelta(seconds=40)),
                ]
            },
        )
        mocked.get(
            _detail_url("new"),
            payload={"subject": "Waterbeep", "text": "O seu código é 424242"},
        )
        code = await mailbox.async_fetch_code(since)

    assert code == "424242"


async def test_fetch_code_ignores_mail_older_than_the_request(
    session: aiohttp.ClientSession,
) -> None:
    """A previous attempt's code can never be replayed."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        # Well outside the clock-skew leeway.
        mocked.get(
            LIST_URL,
            payload={"data": [_meta("stale", since - timedelta(minutes=30))]},
        )
        code = await mailbox.async_fetch_code(since)

    # The body was never fetched, so the stale mail was rejected on metadata.
    assert code is None


async def test_fetch_code_applies_the_sender_filter(
    session: aiohttp.ClientSession,
) -> None:
    """Mail from another sender is skipped when a from-filter is set."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session, otp_from_filter="aquamatrix.pt")

    with aioresponses() as mocked:
        mocked.get(
            LIST_URL,
            payload={
                "data": [
                    _meta("spam", since + timedelta(seconds=5), sender="ad@shop.com")
                ]
            },
        )
        code = await mailbox.async_fetch_code(since)

    assert code is None


async def test_fetch_code_does_not_reinspect_a_seen_mail(
    session: aiohttp.ClientSession,
) -> None:
    """A mail without a code is fetched once, not on every poll."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session)
    payload = {"data": [_meta("plain", since + timedelta(seconds=5))]}

    with aioresponses() as mocked:
        mocked.get(LIST_URL, payload=payload)
        mocked.get(_detail_url("plain"), payload={"text": "nothing useful here"})
        assert await mailbox.async_fetch_code(since) is None

        # Second pass: only the list is served. A repeat body fetch would raise.
        mocked.get(LIST_URL, payload=payload)
        assert await mailbox.async_fetch_code(since) is None


async def test_wait_for_code_gives_up_after_the_timeout(
    session: aiohttp.ClientSession,
) -> None:
    """An empty inbox returns None instead of blocking the poll forever."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        mocked.get(LIST_URL, payload={"data": []})
        code = await mailbox.async_wait_for_code(since, timeout=0, interval=0)

    assert code is None


async def test_wait_for_code_returns_the_code(session: aiohttp.ClientSession) -> None:
    """The happy path: the forwarded mail is there and carries the code."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        mocked.get(LIST_URL, payload={"data": [_meta("m1", since)]})
        mocked.get(
            _detail_url("m1"),
            payload={
                "subject": "Waterbeep",
                "text": None,
                "html": "<p>Código de verificação: <b>135790</b></p>",
            },
        )
        code = await mailbox.async_wait_for_code(since, timeout=5, interval=0)

    assert code == "135790"


async def test_wait_for_code_keeps_polling_until_the_mail_lands(
    session: aiohttp.ClientSession,
) -> None:
    """Forwarding takes a moment, so an empty first poll is not a failure."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        mocked.get(LIST_URL, payload={"data": []})
        mocked.get(LIST_URL, payload={"data": [_meta("late", since)]})
        mocked.get(_detail_url("late"), payload={"text": "Codigo: 987654"})
        code = await mailbox.async_wait_for_code(since, timeout=30, interval=0)

    assert code == "987654"


async def test_unparseable_payloads_are_ignored(session: aiohttp.ClientSession) -> None:
    """A malformed list or timestamp must not raise, just yield no code."""
    since = dt_util.utcnow()
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        mocked.get(LIST_URL, payload={"object": "list"})  # no "data" key at all
        assert await mailbox.async_fetch_code(since) is None

        mocked.get(
            LIST_URL,
            payload={"data": ["not-an-object", {"id": "x", "created_at": "nonsense"}]},
        )
        assert await mailbox.async_fetch_code(since) is None


async def test_server_error_raises(session: aiohttp.ClientSession) -> None:
    """A Resend outage is reported so the caller can fall back to the prompt."""
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        mocked.get(LIST_URL, status=500)
        with pytest.raises(OtpMailboxError, match="500"):
            await mailbox.async_fetch_code(dt_util.utcnow())


async def test_rejected_api_key_raises(session: aiohttp.ClientSession) -> None:
    """A bad key is reported, not silently treated as an empty inbox."""
    mailbox = _mailbox(session)

    with aioresponses() as mocked:
        mocked.get(LIST_URL, status=401)
        with pytest.raises(OtpMailboxError, match="401"):
            await mailbox.async_fetch_code(dt_util.utcnow())


async def test_create_mailbox_honours_the_api_key(hass: HomeAssistant) -> None:
    """The factory the coordinator and config flow call, wired to HA's session.

    HA's shared session is patched out: actually creating it leaves a thread
    behind that trips the lingering-thread check at teardown.
    """
    with patch(
        "custom_components.waterbeep.otp_mailbox.async_get_clientsession"
    ) as mock_session:
        # No key: the feature is off and HA's session is never even touched.
        assert async_create_mailbox(hass, {}) is None
        mock_session.assert_not_called()

        mailbox = async_create_mailbox(hass, {CONF_OTP_RESEND_API_KEY: API_KEY})

    assert isinstance(mailbox, ResendOtpMailbox)
    mock_session.assert_called_once_with(hass)
