"""Tests for the BedJet climate entity."""

from __future__ import annotations

from custom_components.bedjet.pybedjet import BedJet
from homeassistant.components.climate import ATTR_CURRENT_TEMPERATURE, HVACMode
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import setup_integration


async def test_state_reflects_device(hass: HomeAssistant, bedjet: BedJet) -> None:
    """Test the climate entity reports the state read from the device."""
    entry = await setup_integration(hass, bedjet)

    entity = next(
        entity
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if entity.domain == "climate"
    )
    state = hass.states.get(entity.entity_id)

    assert state is not None
    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 30
    assert state.attributes[ATTR_TEMPERATURE] == 32
