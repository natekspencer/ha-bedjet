"""Tests for BedJet setup and unload."""

from __future__ import annotations

from unittest.mock import patch

from bleak.exc import BleakError

from custom_components.bedjet.const import DOMAIN
from custom_components.bedjet.pybedjet import BedJet, PowerLayer
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import ADDRESS, NAME, MockConfigEntry, service_info, setup_integration


def _config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a config entry that has not been set up."""
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_and_unload_bedjet(hass: HomeAssistant, bedjet: BedJet) -> None:
    """Test a BedJet sets up all of its platforms and unloads cleanly."""
    entry = await setup_integration(hass, bedjet)
    assert entry.state is ConfigEntryState.LOADED

    domains = {
        entity.domain
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    }
    assert domains == {
        "binary_sensor",
        "button",
        "climate",
        "fan",
        "number",
        "sensor",
        "switch",
    }

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    bedjet.disconnect.assert_awaited()


async def test_setup_powerlayer(hass: HomeAssistant, powerlayer: PowerLayer) -> None:
    """Test a PowerLayer only sets up the platforms it supports."""
    entry = await setup_integration(hass, powerlayer)
    assert entry.state is ConfigEntryState.LOADED

    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {entity.domain for entity in entries} == {"button", "sensor"}

    head_angle = next(
        entity.entity_id for entity in entries if entity.translation_key == "head_angle"
    )
    state = hass.states.get(head_angle)
    assert state is not None
    assert state.state not in (STATE_UNAVAILABLE, "unknown")
    assert float(state.state) == 15


async def test_setup_retries_when_device_not_found(hass: HomeAssistant) -> None:
    """Test setup is retried while the device hasn't been seen."""
    entry = _config_entry(hass)

    with patch(
        "custom_components.bedjet.bluetooth.async_last_service_info",
        return_value=None,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_connection_fails(hass: HomeAssistant) -> None:
    """Test setup is retried when the device can't be reached."""
    entry = _config_entry(hass)

    with (
        patch(
            "custom_components.bedjet.bluetooth.async_last_service_info",
            return_value=service_info(),
        ),
        patch(
            "custom_components.bedjet.determine_device",
            side_effect=BleakError("failed"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_device_type_unknown(hass: HomeAssistant) -> None:
    """Test setup is retried when the device type can't be determined."""
    entry = _config_entry(hass)

    with (
        patch(
            "custom_components.bedjet.bluetooth.async_last_service_info",
            return_value=service_info(),
        ),
        patch("custom_components.bedjet.determine_device", return_value=None),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
