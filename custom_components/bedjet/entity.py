"""BedJet device entity."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .pybedjet import BedJet


class BedJetEntity(CoordinatorEntity[DataUpdateCoordinator[None]]):
    """Representation of a BedJet device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DataUpdateCoordinator[None], device: BedJet, name: str
    ) -> None:
        """Initialize a BedJet entity."""
        super().__init__(coordinator)
        self._device = device
        
        # Determine model name based on connection type
        model_name = "BedJet V2" if device.is_v2 else "BedJet 3"

        self._attr_device_info = DeviceInfo(
            name=name,
            manufacturer="BedJet",
            model=model_name,
            sw_version=device.firmware_version,
            connections={(dr.CONNECTION_BLUETOOTH, device.address)},
        )
        self._async_update_attrs()

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle data update."""
        self._async_update_attrs()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            self._device.register_callback(self._handle_coordinator_update)
        )
        return await super().async_added_to_hass()
