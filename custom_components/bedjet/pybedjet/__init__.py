"""BedJet module."""

from __future__ import annotations

import logging

from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTCharacteristic, BleakGATTServiceCollection
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .bedjet import (
    BEDJET2_SERVICE_UUID,
    BEDJET3_SERVICE_UUID,
    BedJet,
    BedJetButton,
    BedJetCommand,
    BedJetState,
    OperatingMode,
)
from .powerlayer import (
    POWERLAYER_SERVICE_UUID,
    POWERLAYER_UUID,
    PowerLayer,
    PowerLayerButton,
    PowerLayerState,
)

__all__ = [
    "BEDJET2_SERVICE_UUID",
    "BEDJET3_SERVICE_UUID",
    "POWERLAYER_SERVICE_UUID",
    "BedJet",
    "BedJetButton",
    "BedJetCommand",
    "BedJetState",
    "OperatingMode",
    "PowerLayer",
    "PowerLayerButton",
    "PowerLayerState",
]

_LOGGER = logging.getLogger(__name__)


def _get_service_info(services: BleakGATTServiceCollection) -> str:
    details = {
        "Services": services.services,
        "Characteristics": services.characteristics,
        "Descriptors": services.descriptors,
    }
    return "".join(
        f"\n  {key}:{''.join(f'\n    {s}{f" {s.properties}" if isinstance(s, BleakGATTCharacteristic) else ""}' for s in value.values())}"
        for key, value in details.items()
    )


async def determine_device(device: BLEDevice) -> BedJet | PowerLayer | None:
    """Determine device type."""

    async with await establish_connection(
        BleakClientWithServiceCache,
        device,
        device.name or "BedJet",
        use_services_cache=True,
    ) as client:
        _LOGGER.debug(
            "%s (%s):%s",
            device.name,
            device.address,
            _get_service_info(client.services),
        )

        if client.services.get_service(BEDJET3_SERVICE_UUID):
            _LOGGER.debug(
                "%s (%s): Setting up BedJet 3 device", device.name, device.address
            )
            return BedJet(device)
        if client.services.get_service(BEDJET2_SERVICE_UUID):
            _LOGGER.debug(
                "%s (%s): Setting up BedJet V2 device", device.name, device.address
            )
            return BedJet(device)
        if client.services.get_service(POWERLAYER_UUID):
            _LOGGER.debug(
                "%s (%s): Setting up PowerLayer device", device.name, device.address
            )
            return PowerLayer(device)
    return None
