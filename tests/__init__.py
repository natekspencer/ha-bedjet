"""Tests for the BedJet integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from custom_components.bedjet.const import DOMAIN
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

try:
    from pytest_homeassistant.common import MockConfigEntry
except ImportError:  # Home Assistant < 2026.11
    from pytest_homeassistant_custom_component.common import MockConfigEntry

ADDRESS = "AA:BB:CC:DD:EE:FF"
NAME = "BEDJET_V3"


def service_info(
    address: str = ADDRESS, name: str = NAME, service_uuids: list[str] | None = None
) -> Any:
    """Return a stand-in for the service info of a discovered device."""
    return SimpleNamespace(
        address=address,
        name=name,
        service_uuids=service_uuids or [],
        device=SimpleNamespace(address=address, name=name),
        advertisement=None,
        rssi=-60,
    )


async def setup_integration(hass: HomeAssistant, device: Any) -> MockConfigEntry:
    """Set up the BedJet integration with the given device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.bedjet.bluetooth.async_last_service_info",
            return_value=service_info(),
        ),
        patch("custom_components.bedjet.determine_device", return_value=device),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry
