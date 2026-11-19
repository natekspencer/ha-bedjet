"""Tests for the BedJet buttons."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.bedjet.pybedjet import PowerLayer
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import setup_integration


@pytest.mark.parametrize(
    ("translation_key", "code"),
    [
        ("head_massage_on", 0x14),
        ("foot_massage_on", 0x15),
        ("massage_off", 0x16),
        ("save_m1", 0x28),
        ("save_m2", 0x29),
        ("save_m3", 0x2A),
    ],
)
async def test_powerlayer_button_sends_code(
    hass: HomeAssistant, powerlayer: PowerLayer, translation_key: str, code: int
) -> None:
    """Test pressing a PowerLayer button writes its button code."""
    entry = await setup_integration(hass, powerlayer)
    entity_id = next(
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if entity.translation_key == translation_key
    )

    with (
        patch.object(powerlayer, "_ensure_connected", AsyncMock()),
        patch.object(powerlayer, "_send_command", AsyncMock()) as send_command,
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )

    send_command.assert_awaited_once_with(bytearray((0x01, code)))
