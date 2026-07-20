"""Tests for the Waterbeep API client (network-free units).

The 2FA handshake is driven through a lightweight fake session so no real
``aiohttp`` connector/resolver threads are created (which would trip Home
Assistant's lingering-thread teardown guard).
"""

import pytest

from custom_components.waterbeep.api import (
    _TOKEN_RE,
    WaterbeepAuthError,
    WaterbeepClient,
    WaterbeepTwoFactorRequired,
    _scrape_contacts,
    _scrape_hidden,
)

# A trimmed-down TwoFactorAuth challenge page (attribute order matches the live
# site: value before name for the hidden fields).
TFA_PAGE = """
<form id="tfaForm">
  <input name="__RequestVerificationToken" type="hidden" value="TFA_AF_TOK" />
  <input type="hidden" value="TFA_TOKEN_123" id="tokenFa" name="Token">
  <input type="hidden" value="ENTITY_456" id="entityFa" name="EntityCode">
  <input class="form-check-input" type="radio" id="email" value="EmailVal" checked name="ContactType">
  <input class="form-check-input" type="radio" id="phone" value="PhoneVal" name="ContactType">
</form>
"""

# A second challenge page with a *different* Token, to prove a refresh re-scrapes
# fresh challenge state (the live session binding that avoids the HTTP 500).
TFA_PAGE_2 = TFA_PAGE.replace("TFA_TOKEN_123", "TFA_TOKEN_999")

LOGIN_PAGE = (
    '<form id="login-form"><input name="__RequestVerificationToken" '
    'type="hidden" value="LOGIN_TOK" /></form>'
)
DASHBOARD_PAGE = (
    '<input name="__RequestVerificationToken" type="hidden" value="AJAX_TOK" />'
)


class _FakeResponse:
    """Minimal aiohttp-style response usable as an async context manager."""

    def __init__(
        self,
        *,
        text: str = "",
        json: dict | None = None,
        status: int = 200,
        url: str = "",
    ) -> None:
        self._text = text
        self._json = json
        self.status = status
        self.url = url
        self.headers: dict[str, str] = {}

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def text(self) -> str:
        return self._text

    async def json(self, content_type: str | None = None) -> dict:
        return self._json or {}

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise AssertionError("unexpected error status in test")


class _FakeSession:
    """Serves queued ``_FakeResponse`` objects in call order per HTTP method."""

    def __init__(self, gets: list, posts: list) -> None:
        self._gets = list(gets)
        self._posts = list(posts)
        self.closed = False
        # Records ``(url, data, headers)`` for every POST so tests can assert
        # what was actually sent on the wire.
        self.post_calls: list[tuple[str, dict | None, dict | None]] = []

    def get(self, url):
        return self._gets.pop(0)

    def post(self, url, data=None, headers=None):
        self.post_calls.append((url, data, headers))
        return self._posts.pop(0)

    async def close(self) -> None:
        self.closed = True


def _client_with(gets: list, posts: list) -> WaterbeepClient:
    client = WaterbeepClient("12345678", "secret")
    client._session = _FakeSession(gets, posts)
    return client


class TestTokenRegex:
    """The antiforgery token scraper must handle attribute ordering."""

    def test_name_before_value(self):
        html = (
            '<input name="__RequestVerificationToken" type="hidden" '
            'value="CfDJ8ABC123" />'
        )
        match = _TOKEN_RE.search(html)
        assert match is not None
        assert (match.group(1) or match.group(2)) == "CfDJ8ABC123"

    def test_value_before_name(self):
        html = (
            '<input type="hidden" value="CfDJ8XYZ789" '
            'name="__RequestVerificationToken" />'
        )
        match = _TOKEN_RE.search(html)
        assert match is not None
        assert (match.group(1) or match.group(2)) == "CfDJ8XYZ789"

    def test_missing_token(self):
        assert _TOKEN_RE.search("<html><body>no token here</body></html>") is None


class TestClientState:
    """Basic client lifecycle without touching the network."""

    def test_starts_logged_out(self):
        client = WaterbeepClient("12345678", "secret")
        assert client._logged_in is False
        assert client._session is None


class TestTwoFactorParsing:
    """The 2FA page scrapers must survive attribute ordering (network-free)."""

    def test_scrape_hidden_value_before_name(self):
        assert _scrape_hidden(TFA_PAGE, "Token") == "TFA_TOKEN_123"
        assert _scrape_hidden(TFA_PAGE, "EntityCode") == "ENTITY_456"

    def test_scrape_antiforgery_name_before_value(self):
        assert _scrape_hidden(TFA_PAGE, "__RequestVerificationToken") == "TFA_AF_TOK"

    def test_scrape_hidden_missing(self):
        assert _scrape_hidden(TFA_PAGE, "Nope") is None

    def test_scrape_contacts(self):
        contacts = _scrape_contacts(TFA_PAGE)
        assert contacts == [
            {"id": "email", "value": "EmailVal"},
            {"id": "phone", "value": "PhoneVal"},
        ]


class TestTwoFactorFlow:
    """End-to-end 2FA handshake against a fake session."""

    async def test_login_raises_two_factor_with_contacts(self):
        client = _client_with(
            gets=[_FakeResponse(text=LOGIN_PAGE)],
            posts=[_FakeResponse(text=TFA_PAGE, url="https://x/Account/TwoFactorAuth")],
        )

        with pytest.raises(WaterbeepTwoFactorRequired) as excinfo:
            await client.async_login()

        assert [c["id"] for c in excinfo.value.contacts] == ["email", "phone"]
        assert client._tfa_token == "TFA_TOKEN_123"
        assert client._tfa_entity == "ENTITY_456"
        assert client._tfa_antiforgery == "TFA_AF_TOK"
        assert client._logged_in is False

    async def test_request_and_submit_otp_completes_login(self):
        client = _client_with(
            gets=[_FakeResponse(text=LOGIN_PAGE), _FakeResponse(text=DASHBOARD_PAGE)],
            posts=[
                _FakeResponse(text=TFA_PAGE, url="https://x/Account/TwoFactorAuth"),
                _FakeResponse(json={"succeeded": True}),
                _FakeResponse(json={"succeeded": True, "redirectUrl": "/x"}),
            ],
        )

        with pytest.raises(WaterbeepTwoFactorRequired):
            await client.async_login()
        await client.async_request_otp("PhoneVal")
        await client.async_submit_otp("123456")

        assert client._logged_in is True
        assert client._token == "AJAX_TOK"
        assert client._tfa_token is None

        # The antiforgery token must ride along with both 2FA handshakes,
        # matching the rest of the site (omitting it yields HTTP 400).
        contact_data = client._session.post_calls[1][1]
        otp_data = client._session.post_calls[2][1]
        assert contact_data["__RequestVerificationToken"] == "TFA_AF_TOK"
        assert contact_data["ContactType"] == "PhoneVal"
        assert otp_data["__RequestVerificationToken"] == "TFA_AF_TOK"
        assert otp_data["OTPCode"] == "123456"

    async def test_refresh_challenge_reissues_token(self):
        # The initial login challenge goes stale; refreshing must re-login and
        # re-scrape a fresh Token (bound to a live session) without surfacing
        # the WaterbeepTwoFactorRequired to the caller.
        client = _client_with(
            gets=[_FakeResponse(text=LOGIN_PAGE), _FakeResponse(text=LOGIN_PAGE)],
            posts=[
                _FakeResponse(text=TFA_PAGE, url="https://x/Account/TwoFactorAuth"),
                _FakeResponse(text=TFA_PAGE_2, url="https://x/Account/TwoFactorAuth"),
            ],
        )

        with pytest.raises(WaterbeepTwoFactorRequired):
            await client.async_login()
        assert client._tfa_token == "TFA_TOKEN_123"

        await client.async_refresh_challenge()  # swallows the 2FA raise
        assert client._tfa_token == "TFA_TOKEN_999"
        assert client._tfa_entity == "ENTITY_456"
        assert client._logged_in is False

    async def test_submit_otp_rejects_bad_code(self):
        client = _client_with(
            gets=[_FakeResponse(text=LOGIN_PAGE)],
            posts=[
                _FakeResponse(text=TFA_PAGE, url="https://x/Account/TwoFactorAuth"),
                _FakeResponse(json={"succeeded": False}),
            ],
        )

        with pytest.raises(WaterbeepTwoFactorRequired):
            await client.async_login()
        with pytest.raises(WaterbeepAuthError):
            await client.async_submit_otp("000000")

        assert client._logged_in is False
