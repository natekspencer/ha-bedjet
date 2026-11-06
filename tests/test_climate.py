"""Tests for the BedJet climate entity."""

from __future__ import annotations

from custom_components.bedjet.pybedjet import BedJet
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_PRESET_MODES,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from . import MockConfigEntry, setup_integration


def _climate_state(hass: HomeAssistant, entry: MockConfigEntry) -> State:
    """Return the state of the climate entity."""
    entity = next(
        entity
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if entity.domain == "climate"
    )
    state = hass.states.get(entity.entity_id)
    assert state is not None
    return state


async def test_state_reflects_device(hass: HomeAssistant, bedjet: BedJet) -> None:
    """Test the climate entity reports the state read from the device."""
    entry = await setup_integration(hass, bedjet)

    state = _climate_state(hass, entry)

    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 30
    assert state.attributes[ATTR_TEMPERATURE] == 32


async def test_named_presets(hass: HomeAssistant, bedjet: BedJet) -> None:
    """Test only the memory and biorhythm slots with a name become presets."""
    bedjet._memory_names = ["Nap", "", ""]
    bedjet._biorhythm_names = ["Sleep", "", ""]

    entry = await setup_integration(hass, bedjet)

    presets = _climate_state(hass, entry).attributes[ATTR_PRESET_MODES]

    assert bedjet.m1_name in presets
    assert bedjet.biorhythm1_name in presets
    assert bedjet.m2_name is None
    assert bedjet.biorhythm2_name is None
    assert None not in presets
