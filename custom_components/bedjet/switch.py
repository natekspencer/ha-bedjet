"""BedJet switch entity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet


@dataclass(frozen=True, kw_only=True)
class BedJetSwitchEntityDescription(SwitchEntityDescription):
    """BedJet switch entity description."""

    toggle_fn: Callable[[BedJet, bool], Any]
    value_fn: Callable[[BedJet], Any]


SWITCHES = (
    BedJetSwitchEntityDescription(
        key="enable_led",
        entity_category=EntityCategory.CONFIG,
        translation_key="enable_led",
        toggle_fn=lambda device, muted: device.set_led(muted),
        value_fn=lambda device: device.led_enabled,
    ),
    BedJetSwitchEntityDescription(
        key="mute_beeps",
        entity_category=EntityCategory.CONFIG,
        translation_key="mute_beeps",
        toggle_fn=lambda device, muted: device.set_muted(muted),
        value_fn=lambda device: device.beeps_muted,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform for BedJet."""
    data = entry.runtime_data
    async_add_entities(
        BedJetSwitchEntity(data.coordinator, data.device, entry.title, descriptor)
        for descriptor in SWITCHES
    )


class BedJetSwitchEntity(BedJetEntity, SwitchEntity):
    """Representation of BedJet device."""

    entity_description: BedJetSwitchEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[None],
        device: BedJet,
        name: str,
        entity_description: BedJetSwitchEntityDescription,
    ) -> None:
        """Initialize a BedJet switch entity."""
        self.entity_description = entity_description
        self._attr_unique_id = f"{device.address}_{entity_description.key}"
        super().__init__(coordinator, device, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        self._attr_is_on = self.entity_description.value_fn(self._device)

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        await self.entity_description.toggle_fn(self._device, False)

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        await self.entity_description.toggle_fn(self._device, True)
