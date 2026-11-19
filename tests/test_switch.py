"""Tests for the BedJet switches."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.bedjet.pybedjet import PowerLayer
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import setup_integration


def _entity_id(hass: HomeAssistant, config_entry_id: str, translation_key: str) -> str:
    """Return the entity ID for a translation key."""
    return next(
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), config_entry_id
        )
        if entity.translation_key == translation_key
    )


@pytest.mark.parametrize(
    ("translation_key", "on_code"),
    [("head_massage", 0x14), ("foot_massage", 0x15)],
)
async def test_powerlayer_massage_switch(
    hass: HomeAssistant, powerlayer: PowerLayer, translation_key: str, on_code: int
) -> None:
    """Test a massage switch sends its codes and keeps an unknown, assumed state."""
    entry = await setup_integration(hass, powerlayer)
    entity_id = _entity_id(hass, entry.entry_id, translation_key)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_ASSUMED_STATE] is True

    with (
        patch.object(powerlayer, "_ensure_connected", AsyncMock()),
        patch.object(powerlayer, "_send_command", AsyncMock()) as send_command,
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
        send_command.assert_awaited_once_with(bytearray((0x01, on_code)))
        assert hass.states.get(entity_id).state == STATE_UNKNOWN

        send_command.reset_mock()
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
        send_command.assert_awaited_once_with(bytearray((0x01, 0x16)))
        assert hass.states.get(entity_id).state == STATE_UNKNOWN
