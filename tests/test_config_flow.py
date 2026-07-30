"""Tests for the Waterbeep config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waterbeep.api import (
    WaterbeepAuthError,
    WaterbeepConnectionError,
    WaterbeepTwoFactorRequired,
)
from custom_components.waterbeep.config_flow import ConfigFlow, OptionsFlowHandler
from custom_components.waterbeep.const import (
    CONF_OTP_FROM_FILTER,
    CONF_OTP_RESEND_API_KEY,
    CONF_OTP_TO_FILTER,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

USER_INPUT = {CONF_USERNAME: "12345678", CONF_PASSWORD: "secret"}
CONTACTS = [{"id": "phone", "value": "PhoneVal"}, {"id": "email", "value": "EmailVal"}]


def _make_flow(hass: HomeAssistant) -> ConfigFlow:
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_USER}
    return flow


def _mock_2fa_client():
    """A patched WaterbeepClient whose login triggers a 2FA challenge."""
    instance = AsyncMock()
    instance.async_login = AsyncMock(side_effect=WaterbeepTwoFactorRequired(CONTACTS))
    instance.async_request_otp = AsyncMock()
    instance.async_submit_otp = AsyncMock()
    instance.close = AsyncMock()
    return instance


async def test_form_shown(hass: HomeAssistant) -> None:
    """The initial step shows the form with no errors."""
    flow = _make_flow(hass)
    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}


async def test_form_success(hass: HomeAssistant) -> None:
    """A valid login creates the entry."""
    flow = _make_flow(hass)

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
    ) as mock_client:
        instance = mock_client.return_value
        instance.async_login = AsyncMock()
        instance.close = AsyncMock()

        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Waterbeep (12345678)"
    assert result["data"] == USER_INPUT


async def test_form_invalid_auth(hass: HomeAssistant) -> None:
    """Bad credentials surface an invalid_auth error."""
    flow = _make_flow(hass)

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
    ) as mock_client:
        instance = mock_client.return_value
        instance.async_login = AsyncMock(side_effect=WaterbeepAuthError("bad"))
        instance.close = AsyncMock()

        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """A connection error surfaces cannot_connect."""
    flow = _make_flow(hass)

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
    ) as mock_client:
        instance = mock_client.return_value
        instance.async_login = AsyncMock(side_effect=WaterbeepConnectionError("down"))
        instance.close = AsyncMock()

        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_two_factor_full_flow(hass: HomeAssistant) -> None:
    """A 2FA challenge routes through contact + code steps to a created entry."""
    flow = _make_flow(hass)
    instance = _mock_2fa_client()

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
        return_value=instance,
    ):
        # Login is challenged -> contact picker shown.
        result = await flow.async_step_user(USER_INPUT)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "contact"

        # Pick SMS -> code entry shown, and Waterbeep was asked to send it.
        result = await flow.async_step_contact({"contact": "PhoneVal"})
        instance.async_request_otp.assert_awaited_once_with("PhoneVal")
        assert result["step_id"] == "otp"

        # Enter the code -> entry created.
        result = await flow.async_step_otp({"code": "123456"})

    instance.async_submit_otp.assert_awaited_once_with("123456")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT


async def test_otp_invalid_code_shows_error(hass: HomeAssistant) -> None:
    """A rejected code re-shows the OTP form with an error."""
    flow = _make_flow(hass)
    instance = _mock_2fa_client()
    instance.async_submit_otp = AsyncMock(side_effect=WaterbeepAuthError("bad"))

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
        return_value=instance,
    ):
        await flow.async_step_user(USER_INPUT)
        await flow.async_step_contact({"contact": "PhoneVal"})
        result = await flow.async_step_otp({"code": "000000"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp"
    assert result["errors"] == {"base": "invalid_otp"}


async def test_reauth_two_factor_flow(hass: HomeAssistant) -> None:
    """Reauth reuses the stored password and goes straight to the 2FA steps."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="12345678")
    entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}

    instance = _mock_2fa_client()

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=instance,
        ) as mock_client,
        patch.object(
            hass.config_entries, "async_reload", AsyncMock(return_value=True)
        ) as mock_reload,
    ):
        # No password prompt: the stored password is tried automatically and
        # the 2FA challenge routes straight to the contact picker.
        result = await flow.async_step_reauth(dict(entry.data))
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "contact"
        assert mock_client.call_args.kwargs["password"] == "secret"

        result = await flow.async_step_contact({"contact": "PhoneVal"})
        assert result["step_id"] == "otp"

        result = await flow.async_step_otp({"code": "123456"})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    mock_reload.assert_awaited_once_with(entry.entry_id)
    assert entry.data[CONF_PASSWORD] == "secret"


async def test_emailed_code_is_read_automatically(hass: HomeAssistant) -> None:
    """With a Resend inbox configured, the code step never faces the user."""
    flow = _make_flow(hass)
    instance = _mock_2fa_client()
    mailbox = AsyncMock()
    mailbox.async_wait_for_code = AsyncMock(return_value="123456")

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=instance,
        ),
        patch(
            "custom_components.waterbeep.config_flow.async_create_mailbox",
            return_value=mailbox,
        ),
    ):
        # One call: the challenge is raised, the email channel picked, the code
        # read and submitted, and the entry created — no step faces the user.
        result = await flow.async_step_user(
            {**USER_INPUT, CONF_OTP_RESEND_API_KEY: "re_abc"}
        )

    instance.async_request_otp.assert_awaited_once_with("EmailVal")
    instance.async_submit_otp.assert_awaited_once_with("123456")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OTP_RESEND_API_KEY] == "re_abc"


async def test_reauth_completes_without_any_prompt(hass: HomeAssistant) -> None:
    """A reauth from a failed poll must finish with nobody clicking anything.

    Regression: the contact picker used to be shown first, so an unattended
    reauth stalled on "choose where to send the code" — the exact case the
    feature exists to avoid.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**USER_INPUT, CONF_OTP_RESEND_API_KEY: "re_abc"},
        unique_id="12345678",
    )
    entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}

    instance = _mock_2fa_client()
    mailbox = AsyncMock()
    mailbox.async_wait_for_code = AsyncMock(return_value="123456")

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=instance,
        ),
        patch(
            "custom_components.waterbeep.config_flow.async_create_mailbox",
            return_value=mailbox,
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await flow.async_step_reauth(dict(entry.data))

    # The email channel was chosen for us, the code read, and the reauth closed.
    instance.async_request_otp.assert_awaited_once_with("EmailVal")
    instance.async_submit_otp.assert_awaited_once_with("123456")
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_contact_form_still_shown_without_a_mailbox(hass: HomeAssistant) -> None:
    """With the feature off the user is still asked where to send the code."""
    flow = _make_flow(hass)
    instance = _mock_2fa_client()

    with patch(
        "custom_components.waterbeep.config_flow.WaterbeepClient",
        return_value=instance,
    ):
        result = await flow.async_step_user(USER_INPUT)

    assert result["step_id"] == "contact"
    instance.async_request_otp.assert_not_awaited()


async def test_sms_only_challenge_still_shows_the_picker(hass: HomeAssistant) -> None:
    """No email channel means there is nothing the inbox could answer."""
    flow = _make_flow(hass)
    instance = AsyncMock()
    instance.async_login = AsyncMock(
        side_effect=WaterbeepTwoFactorRequired([{"id": "phone", "value": "PhoneVal"}])
    )
    instance.close = AsyncMock()
    mailbox = AsyncMock()

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=instance,
        ),
        patch(
            "custom_components.waterbeep.config_flow.async_create_mailbox",
            return_value=mailbox,
        ),
    ):
        result = await flow.async_step_user(
            {**USER_INPUT, CONF_OTP_RESEND_API_KEY: "re_abc"}
        )

    assert result["step_id"] == "contact"
    instance.async_request_otp.assert_not_awaited()


async def test_sms_channel_never_touches_the_inbox(hass: HomeAssistant) -> None:
    """A code sent by SMS is not going to show up in the Resend inbox.

    Only reachable by submitting the picker, so the pending challenge is set up
    directly rather than through the (now self-completing) login step.
    """
    flow = _make_flow(hass)
    flow._client = _mock_2fa_client()
    flow._contacts = CONTACTS
    mailbox = AsyncMock()

    with patch(
        "custom_components.waterbeep.config_flow.async_create_mailbox",
        return_value=mailbox,
    ):
        result = await flow.async_step_contact({"contact": "PhoneVal"})

    mailbox.async_wait_for_code.assert_not_awaited()
    assert result["step_id"] == "otp"


async def test_silent_inbox_falls_back_to_the_code_form(hass: HomeAssistant) -> None:
    """If nothing arrives in time the user is still asked for the code."""
    flow = _make_flow(hass)
    instance = _mock_2fa_client()
    mailbox = AsyncMock()
    mailbox.async_wait_for_code = AsyncMock(return_value=None)

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=instance,
        ),
        patch(
            "custom_components.waterbeep.config_flow.async_create_mailbox",
            return_value=mailbox,
        ),
    ):
        result = await flow.async_step_user(
            {**USER_INPUT, CONF_OTP_RESEND_API_KEY: "re_abc"}
        )

    # The code was requested by email, but nothing arrived — so ask for it.
    instance.async_request_otp.assert_awaited_once_with("EmailVal")
    instance.async_submit_otp.assert_not_awaited()
    assert result["step_id"] == "otp"


async def test_options_flow_edits_the_otp_settings(hass: HomeAssistant) -> None:
    """The Resend settings can be added, narrowed, and cleared after setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**USER_INPUT, CONF_OTP_RESEND_API_KEY: "re_old"},
        unique_id="12345678",
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["step_id"] == "init"

    result = await flow.async_step_init(
        {
            CONF_OTP_RESEND_API_KEY: "  re_new  ",
            CONF_OTP_FROM_FILTER: "aquamatrix.pt",
        }
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_OTP_RESEND_API_KEY: "re_new",
        CONF_OTP_FROM_FILTER: "aquamatrix.pt",
        # Empty values are stored so they can override the entry data.
        CONF_OTP_TO_FILTER: "",
    }


async def test_reauth_asks_password_only_when_rejected(hass: HomeAssistant) -> None:
    """The password form only appears when the stored password fails."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="12345678")
    entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}

    rejected = AsyncMock()
    rejected.async_login = AsyncMock(side_effect=WaterbeepAuthError("bad"))
    rejected.close = AsyncMock()

    with (
        patch(
            "custom_components.waterbeep.config_flow.WaterbeepClient",
            return_value=rejected,
        ),
        patch.object(
            hass.config_entries, "async_reload", AsyncMock(return_value=True)
        ) as mock_reload,
    ):
        # Stored password rejected -> password form with the error shown.
        result = await flow.async_step_reauth(dict(entry.data))
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "invalid_auth"}

        # A working password then completes the reauth (no 2FA challenge).
        rejected.async_login = AsyncMock()
        result = await flow.async_step_reauth_confirm({CONF_PASSWORD: "newpass"})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    mock_reload.assert_awaited_once_with(entry.entry_id)
    assert entry.data[CONF_PASSWORD] == "newpass"
