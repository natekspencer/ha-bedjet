"""BedJet climate entity."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.unit_conversion import TemperatureConverter

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet, BedJetButton, BedJetCommand, OperatingMode

_LOGGER = logging.getLogger(__name__)

DISCOVERY_INTERVAL = 60  # seconds

OPERATING_MODE_MAP = {
    OperatingMode.COOL: HVACMode.COOL,
    OperatingMode.DRY: HVACMode.DRY,
    OperatingMode.HEAT: HVACMode.HEAT,
    OperatingMode.EXTENDED_HEAT: HVACMode.HEAT,
    OperatingMode.STANDBY: HVACMode.OFF,
    OperatingMode.TURBO: HVACMode.HEAT,
    OperatingMode.WAIT: HVACMode.OFF,
}
OPERATING_MODE_PRESET_MAP = {
    OperatingMode.EXTENDED_HEAT: "Extended Heat",
    OperatingMode.TURBO: "Turbo",
}

HVAC_MODE_MAP = {
    # HVACMode.AUTO
    HVACMode.COOL: OperatingMode.COOL,
    HVACMode.DRY: OperatingMode.DRY,
    HVACMode.FAN_ONLY: OperatingMode.COOL,
    HVACMode.HEAT: OperatingMode.HEAT,
    # HVACMode.HEAT_COOL:OperatingMode.
    HVACMode.OFF: OperatingMode.STANDBY,
}

PRESET_MODE_MAP = {
    "Turbo": BedJetButton.TURBO,
    "Extended Heat": BedJetButton.EXTENDED_HEAT,
    # "M1": BedJetButton.M1,
    # "M2": BedJetButton.M2,
    # "M3": BedJetButton.M3,
    # "Biorhythm 1": BedJetButton.BIORHYTHM_1,
    # "Biorhythm 2": BedJetButton.BIORHYTHM_2,
    # "Biorhythm 3": BedJetButton.BIORHYTHM_3,
}

MEMORY_PRESETS = (BedJetButton.M1, BedJetButton.M2, BedJetButton.M3)
BIORHYTHM_PRESETS = (
    BedJetButton.BIORHYTHM_1,
    BedJetButton.BIORHYTHM_2,
    BedJetButton.BIORHYTHM_3,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform for BedJet."""
    data = entry.runtime_data
    async_add_entities(
        [BedJetClimateEntity(data.coordinator, data.device, entry.title)]
    )


class BedJetClimateEntity(BedJetEntity, ClimateEntity):
    """Representation of BedJet device."""

    _attr_fan_modes = [f"{speed}%" for speed in (range(5, 101, 5))]
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
    ]
    _attr_name = None
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self, coordinator: DataUpdateCoordinator[None], device: BedJet, name: str
    ) -> None:
        """Initialize a BedJet climate entity."""
        self._attr_unique_id = device.address
        self._max_temp_actual = 0.0
        self._min_temp_actual = 0.0

        self._bedjet_max_temp = (
            TemperatureConverter.convert(  # maximum per bedjet 3 manual
                109, UnitOfTemperature.FAHRENHEIT, self.temperature_unit
            )
        )
        self._bedjet_min_temp = (
            TemperatureConverter.convert(  # minimum per bedjet 3 manual
                66, UnitOfTemperature.FAHRENHEIT, self.temperature_unit
            )
        )

        super().__init__(coordinator, device, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        device = self._device
        state = device.state
        self._attr_current_temperature = state.current_temperature
        self._attr_fan_mode = f"{state.fan_speed}%"
        self._attr_hvac_mode = OPERATING_MODE_MAP[state.operating_mode]
        # Set min/max temp to the full range of bedjet temps to allow HA call to set_temperature to also set hvac state.
        # Per-mode temp ranges validated manually below
        self._max_temp_actual = state.maximum_temperature
        self._min_temp_actual = state.minimum_temperature
        self._attr_max_temp = max(
            state.maximum_temperature, self._bedjet_max_temp, self.max_temp
        )
        self._attr_min_temp = min(
            state.minimum_temperature, self._bedjet_min_temp, self.min_temp
        )
        self._attr_preset_mode = OPERATING_MODE_PRESET_MAP.get(state.operating_mode)
        self._attr_preset_modes = (
            list(PRESET_MODE_MAP.keys())
            + [
                name
                for name in (device.m1_name, device.m2_name, device.m3_name)
                if name
            ]
            + [
                name
                for name in (
                    device.biorhythm1_name,
                    device.biorhythm2_name,
                    device.biorhythm3_name,
                )
                if name
            ]
        )
        self._attr_target_temperature = state.target_temperature

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        await self._device.set_fan_speed(int(fan_mode.replace("%", "")))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        await self._device.set_operating_mode(HVAC_MODE_MAP[hvac_mode])

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if not (button := PRESET_MODE_MAP.get(preset_mode)):
            device = self._device
            if preset_mode == device.m1_name:
                button = BedJetButton.M1
            elif preset_mode == device.m2_name:
                button = BedJetButton.M2
            elif preset_mode == device.m3_name:
                button = BedJetButton.M3
            elif preset_mode == device.biorhythm1_name:
                button = BedJetButton.BIORHYTHM_1
            elif preset_mode == device.biorhythm2_name:
                button = BedJetButton.BIORHYTHM_2
            elif preset_mode == device.biorhythm3_name:
                button = BedJetButton.BIORHYTHM_3
            else:
                raise ValueError(f"{preset_mode} is not a valid preset for {self.name}")
        await self._device._send_command(bytearray((BedJetCommand.BUTTON, button)))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""

        if ATTR_HVAC_MODE in kwargs:
            _LOGGER.debug(
                f"Call to set temperature includes update to bedjet mode: {kwargs[ATTR_HVAC_MODE]}"
            )
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])
            # Wait to pick up the new min/max temp
            await self.async_update_ha_state(force_refresh=True)

        # Changing the bedjet mode changes the valid temp range.
        # HA evaluates min/max temp _before_ calling this method though...
        # So, to process the command to change the mode + temperature at the same time,
        # we set the HA-visible min/max temp to the full bedjet temp range (regardless of mode)
        # and validate the temperature against the _actual_ ranges here, after setting the mode above
        temp = kwargs.get(ATTR_TEMPERATURE)

        _LOGGER.debug(
            "Check valid temperature %d %s (%d %s) in actual bedjet range for mode %s: range %d %s - %d %s",
            temp,
            self.temperature_unit,
            temp,
            self.hass.config.units.temperature_unit,
            str(self.hvac_mode),
            self._min_temp_actual,
            self.temperature_unit,
            self._max_temp_actual,
            self.temperature_unit,
        )
        if temp < self._min_temp_actual or temp > self._max_temp_actual:
            raise ServiceValidationError(
                translation_domain=CLIMATE_DOMAIN,
                translation_key="temp_out_of_range",
                translation_placeholders={
                    "check_temp": str(temp),
                    "min_temp": str(self._min_temp_actual),
                    "max_temp": str(self._max_temp_actual),
                },
            )

        await self._device.set_temperature(temp)
