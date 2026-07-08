"""HTTP client for the Waterbeep (Aquamatrix) service.

Waterbeep has no public API. This client drives the same endpoints the web
dashboard uses at https://www.aquamatrix.pt/waterbeep/.

Auth model (ASP.NET Core):
  1. GET  /waterbeep/Account/Login          -> sets the antiforgery cookie and
                                               embeds a hidden
                                               ``__RequestVerificationToken``
                                               in the HTML.
  2. POST /waterbeep/Account/Login          -> form body with ``UserCode``,
                                               ``Password`` and the scraped
                                               token. On success the server
                                               sets the auth session cookie and
                                               redirects to the dashboard.
  3. GET  <dashboard page>                   -> scrape a fresh token for AJAX.
  4. POST /waterbeep/Dashboard/Get*          -> AJAX calls that return JSON,
                                               requiring the token in the body
                                               and ``X-Requested-With`` header.

The cookie jar is owned by this client (never the shared HA session) so the
authenticated session is isolated to this integration.

See docs/API.md for the captured requests this client is based on.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from .const import BASE_URL

_LOGGER = logging.getLogger(__name__)

# Endpoints (relative to BASE_URL). Verified live against the waterbeep tenant.
LOGIN_PATH = "/waterbeep/Account/Login"
DASHBOARD_LANDING = "/waterbeep/Dashboard/Modalities"
SEVEN_DAYS_PATH = "/waterbeep/Dashboard/GetLastSevenDaysChart"
THIRTY_DAYS_PATH = "/waterbeep/Dashboard/GetLastThirtyDaysChart"
MONTHLY_PATH = "/waterbeep/Dashboard/GetLastConsumptionReadingsChart"
CAPITATION_PATH = "/waterbeep/Dashboard/GetCapitationConsumption"

# Two-factor auth (risk-based; triggered by a new IP / expired trust window).
# On a challenge the login POST lands on TwoFactorAuth instead of the dashboard.
# The web app then POSTs SubmitContact (sends the OTP to email/SMS) and SubmitOTP
# (submits the 6-digit code); both return JSON ``{"succeeded": bool, ...}``.
TWO_FACTOR_PATH = "/waterbeep/Account/TwoFactorAuth"
SUBMIT_CONTACT_PATH = "/waterbeep/Account/SubmitContact"
SUBMIT_OTP_PATH = "/waterbeep/Account/SubmitOTP"

# Browser-like headers. The site is picky about a plausible User-Agent.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) "
    "Gecko/20100101 Firefox/152.0"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 30  # seconds

# Extract the ASP.NET Core antiforgery token from a rendered page. Attribute
# order varies, so match both orderings of name/value.
_TOKEN_RE = re.compile(
    r'name="__RequestVerificationToken"[^>]*value="([^"]+)"'
    r'|value="([^"]+)"[^>]*name="__RequestVerificationToken"'
)

# Match a single ``<input ... name="ContactType" ...>`` radio on the 2FA page.
_CONTACT_TAG_RE = re.compile(r'<input\b[^>]*\bname="ContactType"[^>]*>')


def _scrape_hidden(html: str, field: str) -> str | None:
    """Scrape the ``value`` of a hidden ``<input name="field">`` (any attr order)."""
    pattern = re.compile(
        rf'name="{re.escape(field)}"[^>]*value="([^"]*)"'
        rf'|value="([^"]*)"[^>]*name="{re.escape(field)}"'
    )
    match = pattern.search(html)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _scrape_contacts(html: str) -> list[dict[str, str]]:
    """Parse the 2FA page's ``ContactType`` radios into ``{"id", "value"}`` dicts.

    The radio ``value`` is what ``SubmitContact`` expects; the ``id`` (``email`` /
    ``phone``) tells us the delivery channel for labelling. Parsed live rather
    than hardcoded because the values are server-rendered per session.
    """
    contacts: list[dict[str, str]] = []
    for tag in _CONTACT_TAG_RE.findall(html):
        value_match = re.search(r'\bvalue="([^"]*)"', tag)
        if not value_match:
            continue
        id_match = re.search(r'\bid="([^"]*)"', tag)
        contacts.append(
            {"id": id_match.group(1) if id_match else "", "value": value_match.group(1)}
        )
    return contacts


class WaterbeepError(Exception):
    """Base error for the Waterbeep client."""


class WaterbeepAuthError(WaterbeepError):
    """Raised when authentication fails (bad UserCode/Password or expired session)."""


class WaterbeepConnectionError(WaterbeepError):
    """Raised when the Waterbeep service cannot be reached."""


class WaterbeepTwoFactorRequired(WaterbeepError):
    """Raised when Waterbeep challenges the login with a two-factor OTP.

    Carries the available ``contacts`` (delivery channels) parsed from the 2FA
    page. The client keeps its session open so the caller can drive
    ``async_request_otp`` and ``async_submit_otp`` to complete the challenge.
    """

    def __init__(self, contacts: list[dict[str, str]]) -> None:
        """Store the parsed delivery-channel options."""
        super().__init__("Two-factor verification required")
        self.contacts = contacts


class WaterbeepClient:
    """Minimal client that logs into Waterbeep and pulls dashboard data."""

    def __init__(self, user_code: str, password: str, inhabitants: int = 2) -> None:
        """Store credentials. The session is created lazily in ``async_login``."""
        self._user_code = user_code
        self._password = password
        self._inhabitants = inhabitants
        self._session: aiohttp.ClientSession | None = None
        self._logged_in = False
        # Antiforgery token scraped from the post-login landing page; reused as
        # the body token for AJAX calls (verified live).
        self._token: str | None = None
        # Pending two-factor challenge state (set when a login is intercepted by
        # 2FA; consumed by async_request_otp / async_submit_otp).
        self._tfa_token: str | None = None
        self._tfa_entity: str | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create the private cookie-backed session on first use."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=_DEFAULT_HEADERS,
                cookie_jar=aiohttp.CookieJar(),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying session (call on unload)."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        self._logged_in = False
        self._token = None
        self._tfa_token = None
        self._tfa_entity = None

    async def _get_verification_token(self, path: str) -> str:
        """GET a page and scrape its ``__RequestVerificationToken``."""
        session = await self._ensure_session()
        url = f"{BASE_URL}{path}"
        try:
            async with session.get(url) as resp:
                html = await resp.text()
        except aiohttp.ClientError as err:
            raise WaterbeepConnectionError(f"Failed to load {path}: {err}") from err

        match = _TOKEN_RE.search(html)
        if not match:
            raise WaterbeepAuthError(f"No __RequestVerificationToken found on {path}")
        return match.group(1) or match.group(2)

    async def async_login(self) -> None:
        """Authenticate against Waterbeep. Raises on failure."""
        session = await self._ensure_session()

        # 1. Fetch the login page for a fresh antiforgery token + cookie.
        token = await self._get_verification_token(LOGIN_PATH)

        # 2. POST credentials.
        payload = {
            "UserCode": self._user_code,
            "Password": self._password,
            "__RequestVerificationToken": token,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Upgrade-Insecure-Requests": "1",
        }
        url = f"{BASE_URL}{LOGIN_PATH}"
        try:
            async with session.post(url, data=payload, headers=headers) as resp:
                final_url = str(resp.url)
                body = await resp.text()
        except aiohttp.ClientError as err:
            raise WaterbeepConnectionError(f"Login request failed: {err}") from err

        # Risk-based 2FA: a correct UserCode/Password but an untrusted IP lands
        # on the TwoFactorAuth page instead of the dashboard. Parse the pending
        # challenge and hand the delivery-channel options to the caller.
        if TWO_FACTOR_PATH in final_url or 'id="tfaForm"' in body:
            tfa_token = _scrape_hidden(body, "Token")
            tfa_entity = _scrape_hidden(body, "EntityCode")
            contacts = _scrape_contacts(body)
            if not tfa_token or not tfa_entity or not contacts:
                raise WaterbeepAuthError(
                    "Two-factor challenge page missing expected fields"
                )
            self._tfa_token = tfa_token
            self._tfa_entity = tfa_entity
            _LOGGER.debug("Waterbeep requires 2FA for %s", self._user_code)
            raise WaterbeepTwoFactorRequired(contacts)

        # A successful login redirects away from the login page (verified: it
        # lands on /waterbeep/Dashboard/Modalities). A failed login re-renders
        # the login form (still on Account/Login).
        if "Account/Login" in final_url or LOGIN_PATH in final_url:
            raise WaterbeepAuthError("Login rejected - check UserCode and Password")

        # The landing page embeds the antiforgery token used as the body token
        # for subsequent AJAX calls (verified live). Capture it here.
        match = _TOKEN_RE.search(body)
        if not match:
            raise WaterbeepAuthError(
                "Logged in but no antiforgery token on the landing page"
            )
        self._token = match.group(1) or match.group(2)
        self._logged_in = True
        _LOGGER.debug("Waterbeep login successful for %s", self._user_code)

    async def _post_2fa(self, path: str, payload: dict[str, str]) -> dict[str, Any]:
        """POST a 2FA handshake endpoint (SubmitContact/SubmitOTP) and return JSON.

        Mirrors the web app's ``$.ajax`` call: form-encoded body plus the
        ``X-Requested-With`` header. Responses are JSON ``{"succeeded": bool}``.
        """
        session = await self._ensure_session()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
        }
        url = f"{BASE_URL}{path}"
        try:
            async with session.post(url, data=payload, headers=headers) as resp:
                resp.raise_for_status()
                result: dict[str, Any] = await resp.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            raise WaterbeepConnectionError(
                f"{path} returned HTTP {err.status}"
            ) from err
        except aiohttp.ClientError as err:
            raise WaterbeepConnectionError(f"{path} request failed: {err}") from err
        return result

    async def async_request_otp(self, contact_value: str) -> None:
        """Ask Waterbeep to send the OTP to the chosen delivery channel.

        ``contact_value`` is the ``value`` of one of the ``contacts`` handed to
        the caller via ``WaterbeepTwoFactorRequired``.
        """
        if not self._tfa_token or not self._tfa_entity:
            raise WaterbeepAuthError("No pending two-factor challenge")
        result = await self._post_2fa(
            SUBMIT_CONTACT_PATH,
            {
                "Token": self._tfa_token,
                "EntityCode": self._tfa_entity,
                "ContactType": contact_value,
            },
        )
        if not result.get("succeeded"):
            raise WaterbeepAuthError("Waterbeep refused to send the verification code")

    async def async_submit_otp(self, code: str) -> None:
        """Submit the OTP code to clear the challenge and trust this session/IP.

        On success the session (and its source IP) becomes trusted; we scrape a
        fresh AJAX token so the client is immediately usable for data calls.
        """
        if not self._tfa_token or not self._tfa_entity:
            raise WaterbeepAuthError("No pending two-factor challenge")
        result = await self._post_2fa(
            SUBMIT_OTP_PATH,
            {
                "Token": self._tfa_token,
                "EntityCode": self._tfa_entity,
                "OTPCode": code.strip(),
            },
        )
        if not result.get("succeeded"):
            raise WaterbeepAuthError("Invalid or expired verification code")
        self._tfa_token = None
        self._tfa_entity = None
        self._token = await self._get_verification_token(DASHBOARD_LANDING)
        self._logged_in = True
        _LOGGER.debug("Waterbeep 2FA cleared for %s", self._user_code)

    async def _post_endpoint(
        self, path: str, extra: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """POST an antiforgery-protected dashboard endpoint and return JSON.

        The token goes in the request body with an ``X-Requested-With`` header;
        no header token or cookie pairing is required (verified live). A session
        that has expired serves the HTML login page instead of JSON, which we
        translate to ``WaterbeepAuthError`` so the caller can re-login.
        """
        session = await self._ensure_session()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
        }
        payload = {"__RequestVerificationToken": self._token or ""}
        if extra:
            payload.update(extra)
        url = f"{BASE_URL}{path}"
        try:
            async with session.post(url, data=payload, headers=headers) as resp:
                if resp.status in {401, 403}:
                    raise WaterbeepAuthError(f"{path} returned {resp.status}")
                resp.raise_for_status()
                if "json" not in resp.headers.get("Content-Type", ""):
                    raise WaterbeepAuthError(
                        f"{path} returned non-JSON (session likely expired)"
                    )
                result: dict[str, Any] = await resp.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            raise WaterbeepConnectionError(
                f"{path} returned HTTP {err.status}"
            ) from err
        except aiohttp.ClientError as err:
            raise WaterbeepConnectionError(f"{path} request failed: {err}") from err
        return result

    async def _fetch_all(self) -> dict[str, Any]:
        """Fetch every dashboard endpoint used by the integration."""
        return {
            "thirty_days": await self._post_endpoint(THIRTY_DAYS_PATH),
            "seven_days": await self._post_endpoint(SEVEN_DAYS_PATH),
            "monthly": await self._post_endpoint(MONTHLY_PATH),
            "capitation": await self._post_endpoint(
                CAPITATION_PATH,
                {"numberOfInhabitants": str(self._inhabitants)},
            ),
        }

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch all dashboard data, logging in first if needed.

        Retries once after a fresh login if the session appears expired.
        """
        if not self._logged_in:
            await self.async_login()

        try:
            return await self._fetch_all()
        except WaterbeepAuthError:
            _LOGGER.debug("Session expired, re-authenticating")
            self._logged_in = False
            self._token = None
            await self.async_login()
            return await self._fetch_all()
