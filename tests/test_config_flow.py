"""Tests for the BedJet config flow."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
import pytest

from custom_components.bedjet.const import DOMAIN
from custom_components.bedjet.pybedjet import BEDJET3_SERVICE_UUID
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import ADDRESS, NAME, MockConfigEntry, service_info


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip setting up the entry once the flow creates it."""
    with (
        patch(
            "custom_components.bedjet.async_setup_entry", return_value=True
        ) as setup_entry,
        patch("custom_components.bedjet.async_unload_entry", return_value=True),
    ):
        yield setup_entry


@pytest.fixture
def mock_determine_device() -> Generator[AsyncMock]:
    """Mock connecting to a device."""
    device = MagicMock(update=AsyncMock(), disconnect=AsyncMock())
    device.name = NAME
    with patch(
        "custom_components.bedjet.config_flow.determine_device", return_value=device
    ) as determine_device:
        yield determine_device


def _mock_discovered(*discovered: object):
    """Mock the devices Home Assistant has discovered."""
    return patch(
        "custom_components.bedjet.config_flow.async_discovered_service_info",
        return_value=list(discovered),
    )


@pytest.mark.usefixtures("mock_determine_device")
async def test_bluetooth_discovery(hass: HomeAssistant) -> None:
    """Test a discovered device can be confirmed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"{NAME} (EEFF)"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["result"].unique_id == ADDRESS


async def test_bluetooth_discovery_cannot_connect(
    hass: HomeAssistant, mock_determine_device: AsyncMock
) -> None:
    """Test discovery aborts when the device can't be reached."""
    mock_determine_device.side_effect = BleakError("failed")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_bluetooth_discovery_already_configured(hass: HomeAssistant) -> None:
    """Test discovery aborts for a device that is already set up."""
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_determine_device")
async def test_user_flow(hass: HomeAssistant) -> None:
    """Test picking a discovered device."""
    with _mock_discovered(service_info()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {CONF_ADDRESS: ADDRESS}


async def test_user_flow_only_lists_bedjets(hass: HomeAssistant) -> None:
    """Test devices that aren't a BedJet are left out."""
    by_uuid = service_info(
        "AA:BB:CC:DD:EE:01", "Bed", service_uuids=[BEDJET3_SERVICE_UUID]
    )
    other = service_info("AA:BB:CC:DD:EE:02", "Speaker")

    with _mock_discovered(service_info(), by_uuid, other):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert set(result["data_schema"].schema[CONF_ADDRESS].container) == {
        ADDRESS,
        by_uuid.address,
    }


async def test_user_flow_no_devices(hass: HomeAssistant) -> None:
    """Test the flow aborts when nothing has been discovered."""
    with _mock_discovered():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"
