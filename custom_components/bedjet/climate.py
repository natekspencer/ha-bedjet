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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
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
    "None": BedJetButton.HEAT,
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
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate platform for BedJet."""
    data = entry.runtime_data
    async_add_entities(
        [BedJetClimateEntity(data.coordinator, data.device, entry.title)]
    )


def temperature_to_mode(temperature: float):
    as_fahrenheit = TemperatureConverter.convert(
        temperature, UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT
    )
    if as_fahrenheit <= 78:
        return OperatingMode.COOL
    if as_fahrenheit <= 87:
        return OperatingMode.DRY
    return OperatingMode.HEAT


class BedJetClimateEntity(BedJetEntity, ClimateEntity):
    """Representation of BedJet device."""

    _attr_fan_modes = [f"{speed}%" for speed in (range(5, 101, 5))]
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

        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.AUTO,
        ]
        if not device.is_v2:
            self._attr_hvac_modes.append(HVACMode.DRY)

        super().__init__(coordinator, device, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        device = self._device
        state = device.state
        self._attr_current_temperature = state.current_temperature
        self._attr_fan_mode = f"{state.fan_speed}%"

        # Only update hass-displayed mode if:
        if (
            getattr(self, "_attr_hvac_mode", None) != HVACMode.AUTO  # Not in auto mode
            or state.operating_mode == OperatingMode.STANDBY  # Bedjet turned itself off
        ):
            self._attr_hvac_mode = OPERATING_MODE_MAP[state.operating_mode]

        self._max_temp_actual = state.maximum_temperature
        self._min_temp_actual = state.minimum_temperature

        if self._attr_hvac_mode == HVACMode.AUTO:
            # Set min/max temp to the full range of bedjet temps to allow HA call to set_temperature to also set hvac state.
            # Per-mode temp ranges validated manually below
            self._attr_max_temp = max(
                state.maximum_temperature, self._bedjet_max_temp, self.max_temp
            )
            self._attr_min_temp = min(
                state.minimum_temperature, self._bedjet_min_temp, self.min_temp
            )
        else:
            self._attr_max_temp = self._max_temp_actual
            self._attr_min_temp = self._min_temp_actual

        # DYNAMIC V2 PRESETS: Filter out unsupported items
        base_presets = list(PRESET_MODE_MAP.keys())
        if device.is_v2:
            if "Extended Heat" in base_presets:
                base_presets.remove("Extended Heat")
        else:
            if "None" in base_presets:
                base_presets.remove("None")

        self._attr_preset_mode = OPERATING_MODE_PRESET_MAP.get(state.operating_mode)

        # "None" included to revert from Turbo to Heat mode
        if device.is_v2 and self._attr_preset_mode is None:
            self._attr_preset_mode = "None"

        self._attr_preset_modes = (
            base_presets
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
        if self._device.is_v2 and hvac_mode == HVACMode.DRY:
            _LOGGER.warning("Dry Mode is not supported on BedJet V2")
            return

        if hvac_mode == HVACMode.AUTO:
            cur_temp = self.current_temperature
            target_mode = (
                temperature_to_mode(cur_temp) if cur_temp else OperatingMode.COOL
            )
        else:
            target_mode = HVAC_MODE_MAP[hvac_mode]

        await self._device.set_operating_mode(target_mode)
        self._attr_hvac_mode = hvac_mode

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        device = self._device

        if device.is_v2:
            if preset_mode == "Extended Heat":
                _LOGGER.warning("Extended Heat is not supported on BedJet V2")
                return

            if preset_mode == "Turbo":
                await device.set_operating_mode(OperatingMode.TURBO)
                return

            if preset_mode == "None":
                if device.state.operating_mode == OperatingMode.TURBO:
                    await device.set_operating_mode(OperatingMode.HEAT)
                return

        if not (button := PRESET_MODE_MAP.get(preset_mode)):
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
            new_mode = kwargs[ATTR_HVAC_MODE]
            if new_mode == HVACMode.AUTO:
                # if the new mode is auto we'll handle it automatically below, just need to set the climate mode state here
                self._attr_hvac_mode = new_mode
            else:
                _LOGGER.debug(
                    f"Call to set temperature includes update to bedjet mode: {new_mode}"
                )
                await self.async_set_hvac_mode(new_mode)
                # Wait to pick up the new min/max temp
                await self.async_update_ha_state(force_refresh=True)

        temp = kwargs.get(ATTR_TEMPERATURE)

        if self._attr_hvac_mode == HVACMode.AUTO:
            # Check if we need to change the bedjet mode to allow this temperature
            target_mode = temperature_to_mode(temp)
            if target_mode != self._device.state.operating_mode:
                _LOGGER.debug(
                    f"Automatically moving bedjet mode from %s to %s to accomodate temperature %.1f %s",
                    self._device.state.operating_mode.name,
                    target_mode.name,
                    temp,
                    self.temperature_unit,
                )
                await self._device.set_operating_mode(target_mode)
                await self.async_update_ha_state(force_refresh=True)

            # Changing the bedjet mode changes the valid temp range.
            # HA evaluates min/max temp _before_ calling this method though...
            # we set the HA-visible min/max temp to the full bedjet temp range in auto-mode
            # and validate the temperature against the _actual_ ranges here,
            # after setting the effective operating mode above

            _LOGGER.debug(
                "Check valid temperature %.1f %s (%.1f %s) in actual bedjet range for mode %s: range %.1f %s - %.1f %s",
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
