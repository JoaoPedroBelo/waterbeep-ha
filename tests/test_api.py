"""Tests for the Waterbeep API client (network-free units)."""

from aioresponses import aioresponses
import pytest

from custom_components.waterbeep.api import (
    _TOKEN_RE,
    BASE_URL,
    DASHBOARD_LANDING,
    LOGIN_PATH,
    SUBMIT_CONTACT_PATH,
    SUBMIT_OTP_PATH,
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
  <input type="hidden" value="TFA_TOKEN_123" id="tokenFa" name="Token">
  <input type="hidden" value="ENTITY_456" id="entityFa" name="EntityCode">
  <input class="form-check-input" type="radio" id="email" value="EmailVal" checked name="ContactType">
  <input class="form-check-input" type="radio" id="phone" value="PhoneVal" name="ContactType">
</form>
"""

LOGIN_PAGE = (
    '<form id="login-form"><input name="__RequestVerificationToken" '
    'type="hidden" value="LOGIN_TOK" /></form>'
)
DASHBOARD_PAGE = (
    '<input name="__RequestVerificationToken" type="hidden" value="AJAX_TOK" />'
)


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

    def test_scrape_hidden_missing(self):
        assert _scrape_hidden(TFA_PAGE, "Nope") is None

    def test_scrape_contacts(self):
        contacts = _scrape_contacts(TFA_PAGE)
        assert contacts == [
            {"id": "email", "value": "EmailVal"},
            {"id": "phone", "value": "PhoneVal"},
        ]


class TestTwoFactorFlow:
    """End-to-end 2FA handshake against mocked HTTP."""

    async def test_login_raises_two_factor_with_contacts(self):
        client = WaterbeepClient("12345678", "secret")
        with aioresponses() as mocked:
            mocked.get(f"{BASE_URL}{LOGIN_PATH}", status=200, body=LOGIN_PAGE)
            mocked.post(f"{BASE_URL}{LOGIN_PATH}", status=200, body=TFA_PAGE)

            with pytest.raises(WaterbeepTwoFactorRequired) as excinfo:
                await client.async_login()

        assert [c["id"] for c in excinfo.value.contacts] == ["email", "phone"]
        assert client._tfa_token == "TFA_TOKEN_123"
        assert client._tfa_entity == "ENTITY_456"
        assert client._logged_in is False
        await client.close()

    async def test_request_and_submit_otp_completes_login(self):
        client = WaterbeepClient("12345678", "secret")
        with aioresponses() as mocked:
            mocked.get(f"{BASE_URL}{LOGIN_PATH}", status=200, body=LOGIN_PAGE)
            mocked.post(f"{BASE_URL}{LOGIN_PATH}", status=200, body=TFA_PAGE)
            with pytest.raises(WaterbeepTwoFactorRequired):
                await client.async_login()

            mocked.post(
                f"{BASE_URL}{SUBMIT_CONTACT_PATH}",
                status=200,
                payload={"succeeded": True},
            )
            await client.async_request_otp("PhoneVal")

            mocked.post(
                f"{BASE_URL}{SUBMIT_OTP_PATH}",
                status=200,
                payload={"succeeded": True, "redirectUrl": DASHBOARD_LANDING},
            )
            mocked.get(
                f"{BASE_URL}{DASHBOARD_LANDING}", status=200, body=DASHBOARD_PAGE
            )
            await client.async_submit_otp("123456")

        assert client._logged_in is True
        assert client._token == "AJAX_TOK"
        assert client._tfa_token is None
        await client.close()

    async def test_submit_otp_rejects_bad_code(self):
        client = WaterbeepClient("12345678", "secret")
        with aioresponses() as mocked:
            mocked.get(f"{BASE_URL}{LOGIN_PATH}", status=200, body=LOGIN_PAGE)
            mocked.post(f"{BASE_URL}{LOGIN_PATH}", status=200, body=TFA_PAGE)
            with pytest.raises(WaterbeepTwoFactorRequired):
                await client.async_login()

            mocked.post(
                f"{BASE_URL}{SUBMIT_OTP_PATH}",
                status=200,
                payload={"succeeded": False},
            )
            with pytest.raises(WaterbeepAuthError):
                await client.async_submit_otp("000000")

        assert client._logged_in is False
        await client.close()
