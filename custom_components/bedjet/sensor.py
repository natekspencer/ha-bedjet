"""BedJet sensor entity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform for BedJet."""
    data = entry.runtime_data
    async_add_entities(
        [
            BedJetSensorEntity(data.coordinator, data.device, entry.title, descriptor)
            for descriptor in SENSORS
        ]
    )


@dataclass(frozen=True, kw_only=True)
class BedJetSensorEntityDescription(SensorEntityDescription):
    """BedJet sensor entity description."""

    value_fn: Callable[[BedJet], Any]


SENSORS = (
    BedJetSensorEntityDescription(
        key="ambient_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        translation_key="ambient_temperature",
        value_fn=lambda device: device._state.ambient_temperature,
    ),
    BedJetSensorEntityDescription(
        key="runtime_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        translation_key="runtime_remaining",
        value_fn=lambda device: device._state.runtime_remaining.total_seconds(),
    ),
)


class BedJetSensorEntity(BedJetEntity, SensorEntity):
    """Representation of BedJet device."""

    entity_description: BedJetSensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[None],
        device: BedJet,
        name: str,
        entity_description: BedJetSensorEntityDescription,
    ) -> None:
        """Initialize a BedJet sensor entity."""
        self.entity_description = entity_description
        self._attr_unique_id = f"{device.address}_{entity_description.key}"
        super().__init__(coordinator, device, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        self._attr_native_value = self.entity_description.value_fn(self._device)
