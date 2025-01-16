"""BedJet button entity."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import now

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform for BedJet."""
    data = entry.runtime_data
    async_add_entities([BedJetButtonEntity(data.coordinator, data.device, entry.title)])


class BedJetButtonEntity(BedJetEntity, ButtonEntity):
    """Representation of BedJet device."""

    _attr_translation_key = "sync_clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: DataUpdateCoordinator[None], device: BedJet, name: str
    ) -> None:
        """Initialize a BedJet button entity."""
        self._attr_unique_id = f"{device.address}_sync_clock"
        super().__init__(coordinator, device, name)

    async def async_press(self) -> None:
        """Handle the button press."""
        _now = now()
        await self._device.set_clock(_now.hour, _now.minute)
