"""BedJet fan entity."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import BedJetData
from .const import DOMAIN
from .entity import BedJetEntity
from .pybedjet import BedJet, OperatingMode

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the fan platform for BedJet."""
    data: BedJetData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BedJetFanEntity(data.coordinator, data.device, entry.title)])


class BedJetFanEntity(BedJetEntity, FanEntity):
    """Representation of BedJet device."""

    _attr_name = None
    _attr_speed_count = 20
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.TURN_ON
    )

    def __init__(
        self, coordinator: DataUpdateCoordinator[None], device: BedJet, name: str
    ) -> None:
        """Initialize a BedJet fan entity."""
        self._attr_unique_id = f"{device.address}_fan"
        super().__init__(coordinator, device, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        device = self._device
        state = device._state
        is_on = state.operating_mode != OperatingMode.STANDBY
        self._attr_is_on = is_on
        self._attr_percentage = state.fan_speed if is_on else 0

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            return await self.async_turn_off()
        await self.async_turn_on(percentage=percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self._device.set_operating_mode(OperatingMode.STANDBY)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if self._device._state.operating_mode == OperatingMode.STANDBY:
            await self._device.set_operating_mode(OperatingMode.COOL)
        if percentage:
            await self._device.set_fan_speed(percentage)
