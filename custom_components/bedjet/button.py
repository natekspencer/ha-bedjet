"""BedJet button entity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import now

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet, PowerLayer, PowerLayerButton

_LOGGER = logging.getLogger(__name__)


async def set_clock(bedjet: BedJet) -> None:
    """Handle the button press."""
    _now = now()
    await bedjet.set_clock(_now.hour, _now.minute)


@dataclass(frozen=True, kw_only=True)
class BedJetButtonEntityDescription(ButtonEntityDescription):
    """BedJet binary sensor entity description."""

    press_fn: Callable[[BedJet | PowerLayer], Any]


BUTTONS: dict[type[BedJet | PowerLayer], tuple[BedJetButtonEntityDescription, ...]] = {
    BedJet: (
        BedJetButtonEntityDescription(
            key="sync_clock",
            translation_key="sync_clock",
            entity_category=EntityCategory.CONFIG,
            press_fn=set_clock,
        ),
    ),
}
BUTTONS[PowerLayer] = tuple(
    BedJetButtonEntityDescription(
        key=button.name.lower(),
        translation_key=button.name.lower(),
        press_fn=lambda powerlayer, btn=button: powerlayer.send_button(btn),
    )
    for button in PowerLayerButton
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform for BedJet."""
    data = entry.runtime_data
    async_add_entities(
        [
            BedJetButtonEntity(data.coordinator, data.device, entry.title, description)
            for _type, descriptions in BUTTONS.items()
            if isinstance(data.device, _type)
            for description in descriptions
        ]
    )


class BedJetButtonEntity(BedJetEntity, ButtonEntity):
    """Representation of BedJet device."""

    entity_description: BedJetButtonEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[None],
        device: BedJet | PowerLayer,
        name: str,
        entity_description: BedJetButtonEntityDescription,
    ) -> None:
        """Initialize a BedJet button entity."""
        self.entity_description = entity_description
        self._attr_unique_id = f"{device.address}_{entity_description.key}"
        super().__init__(coordinator, device, name)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.entity_description.press_fn(self._device)
