"""BedJet number entity."""

from __future__ import annotations

import logging
from math import ceil

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import BedJetData
from .const import DOMAIN
from .entity import BedJetEntity
from .pybedjet import BedJet

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform for BedJet."""
    data: BedJetData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BedJetNumberEntity(data.coordinator, data.device, entry.title)])


class BedJetNumberEntity(BedJetEntity, NumberEntity):
    """Representation of BedJet device."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_translation_key = "runtime_remaining"

    def __init__(
        self, coordinator: DataUpdateCoordinator[None], device: BedJet, name: str
    ) -> None:
        """Initialize a BedJet fan entity."""
        self._attr_unique_id = f"{device.address}_runtime_remaining"
        super().__init__(coordinator, device, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        device = self._device
        state = device._state
        self._attr_native_max_value = state.maximum_runtime.total_seconds() / 60
        self._attr_native_value = ceil(state.runtime_remaining.total_seconds() / 60)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self._device.set_runtime_remaining(minutes=int(value))
