"""BedJet sensor entity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet, PowerLayer


@dataclass(frozen=True, kw_only=True)
class BedJetSensorEntityDescription(SensorEntityDescription):
    """BedJet sensor entity description."""

    value_fn: Callable[[BedJet | PowerLayer], Any]


SENSORS: dict[type[BedJet | PowerLayer], tuple[BedJetSensorEntityDescription, ...]] = {
    BedJet: (
        BedJetSensorEntityDescription(
            key="ambient_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            translation_key="ambient_temperature",
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda device: device.state.ambient_temperature,
        ),
        BedJetSensorEntityDescription(
            key="bio_sequence_step",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            translation_key="bio_sequence_step",
            value_fn=lambda device: device.bio_sequence_step,
        ),
        BedJetSensorEntityDescription(
            key="notification",
            device_class=SensorDeviceClass.ENUM,
            entity_category=EntityCategory.DIAGNOSTIC,
            options=[
                "none",
                "clean_filter",
                "update_available",
                "update_failed",
                "bio_fail_clock_not_set",
                "bio_fail_too_long",
            ],
            translation_key="notification",
            value_fn=(
                lambda device: (
                    notification.name.lower()
                    if (notification := device.notification)
                    else None
                )
            ),
        ),
        BedJetSensorEntityDescription(
            key="run_end_time",
            device_class=SensorDeviceClass.TIMESTAMP,
            translation_key="run_end_time",
            value_fn=lambda device: device.state.run_end_time,
        ),
        BedJetSensorEntityDescription(
            key="shutdown_reason",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            translation_key="shutdown_reason",
            value_fn=lambda device: device.shutdown_reason,
        ),
        BedJetSensorEntityDescription(
            key="turbo_time",
            device_class=SensorDeviceClass.DURATION,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            native_unit_of_measurement=UnitOfTime.SECONDS,
            suggested_unit_of_measurement=UnitOfTime.SECONDS,
            translation_key="turbo_time",
            value_fn=lambda device: device.state.turbo_time.total_seconds(),
        ),
        BedJetSensorEntityDescription(
            key="update_phase",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            translation_key="update_phase",
            value_fn=lambda device: device.update_phase,
        ),
    ),
    PowerLayer: (
        BedJetSensorEntityDescription(
            key="head_angle",
            translation_key="head_angle",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda device: device.state.head_angle,
        ),
        BedJetSensorEntityDescription(
            key="foot_angle",
            translation_key="foot_angle",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda device: device.state.foot_angle,
        ),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform for BedJet."""
    data = entry.runtime_data
    async_add_entities(
        BedJetSensorEntity(data.coordinator, data.device, entry.title, descriptor)
        for _type, descriptors in SENSORS.items()
        if isinstance(data.device, _type)
        for descriptor in descriptors
    )


class BedJetSensorEntity(BedJetEntity, SensorEntity):
    """Representation of BedJet device."""

    entity_description: BedJetSensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[None],
        device: BedJet | PowerLayer,
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
