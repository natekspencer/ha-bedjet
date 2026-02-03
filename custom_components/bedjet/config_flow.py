"""Config flow for BedJet integration."""

from __future__ import annotations

import logging
from typing import Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS
from bluetooth_data_tools import human_readable_name
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN
from .pybedjet import BedJet

_LOGGER = logging.getLogger(__name__)

LOCAL_NAMES = {"BEDJET_V3"}
# NEW: Define V2 UUID so we can discover it
BEDJET_V2_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"


async def connect_bedjet(device: BLEDevice) -> tuple[bool, str]:
    """Connect to a BedJet and return return status and success or error."""
    bedjet = BedJet(device)
    try:
        await bedjet.update()
    except BLEAK_EXCEPTIONS:
        return (False, "cannot_connect")
    except Exception:
        _LOGGER.exception("Unexpected error")
        return (False, "unknown")
    finally:
        await bedjet.disconnect()
    return (True, bedjet.name)


class BedjetDeviceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BedJet."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Discovered BT device: %s", discovery_info)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        success, name = await connect_bedjet(discovery_info.device)
        if not success:
            return self.async_abort(reason=name)

        name = human_readable_name(name, discovery_info.name, discovery_info.address)
        self.context["title_placeholders"] = {"name": name}
        self._discovery_info = discovery_info

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self.context["title_placeholders"]["name"],
                data={CONF_ADDRESS: self._discovery_info.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=self.context["title_placeholders"],
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            # local_name = discovery_info.name
            await self.async_set_unique_id(
                discovery_info.address, raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            success, name = await connect_bedjet(discovery_info.device)
            if success:
                return self.async_create_entry(
                    title=name,
                    data={CONF_ADDRESS: discovery_info.address},
                )
            errors["base"] = name

        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids()
            for discovery in async_discovered_service_info(self.hass):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                    # MODIFIED: Logic extended to allow V2 UUIDs through
                    or (
                        not any(discovery.name.startswith(local_name) for local_name in LOCAL_NAMES)
                        and BEDJET_V2_SERVICE_UUID not in discovery.service_uuids
                    )
                ):
                    continue
                self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        service_info.address: (
                            f"{service_info.name} ({service_info.address})"
                        )
                        for service_info in self._discovered_devices.values()
                    }
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
