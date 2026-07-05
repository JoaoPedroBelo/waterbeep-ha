"""Tests for the Waterbeep API client (network-free units)."""

from custom_components.waterbeep.api import _TOKEN_RE, WaterbeepClient


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
