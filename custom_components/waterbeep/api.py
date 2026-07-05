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
SEVEN_DAYS_PATH = "/waterbeep/Dashboard/GetLastSevenDaysChart"
THIRTY_DAYS_PATH = "/waterbeep/Dashboard/GetLastThirtyDaysChart"
MONTHLY_PATH = "/waterbeep/Dashboard/GetLastConsumptionReadingsChart"
CAPITATION_PATH = "/waterbeep/Dashboard/GetCapitationConsumption"

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


class WaterbeepError(Exception):
    """Base error for the Waterbeep client."""


class WaterbeepAuthError(WaterbeepError):
    """Raised when authentication fails (bad UserCode/Password or expired session)."""


class WaterbeepConnectionError(WaterbeepError):
    """Raised when the Waterbeep service cannot be reached."""


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
