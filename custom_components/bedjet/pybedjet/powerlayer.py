"""BedJet PowerLayer device."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging

from bleak import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakError,
    establish_connection,
)

from .const import PowerLayerButton, PowerLayerCommand

_LOGGER = logging.getLogger(__name__)

POWERLAYER_LOCAL_NAME = "BEDJET_BF"
POWERLAYER_SERVICE_UUID = "00001000-bed0-0080-aa55-4265644a6574"
POWERLAYER_UUID = "00001001-bed0-0080-aa55-4265644a6574"
POWERLAYER_NAME_UUID = "00002001-bed0-0080-aa55-4265644a6574"
POWERLAYER_SSID_UUID = "00002002-bed0-0080-aa55-4265644a6574"
POWERLAYER_PASSWORD_UUID = "00002003-bed0-0080-aa55-4265644a6574"
# POWERLAYER_UNKNOWN_UUID = "00002005-bed0-0080-aa55-4265644a6574"
POWERLAYER_STATUS_UUID = "00002006-bed0-0080-aa55-4265644a6574"
POWERLAYER_COMMAND_UUID = "00002007-bed0-0080-aa55-4265644a6574"
# POWERLAYER_UNKNOWN2_UUID = "00002008-bed0-0080-aa55-4265644a6574"

# POWERLAYER_NOTIFICATION_LENGTH = 20
POWERLAYER_NOTIFICATION_MIN_LENGTH = 16  # head and foot angles end at byte 16
# POWERLAYER_STATUS_LENGTH = 11

DISCONNECT_DELAY = 60
STALE_AFTER_SECONDS = 60


@dataclass(frozen=True)
class PowerLayerState:
    """PowerLayer state."""

    head_angle: float = 0
    foot_angle: float = 0
    head_massage_on: bool = False
    foot_massage_on: bool = False
    massage_intensity: int = 0
    massage_program: str | None = None
    child_lock: bool = False


class PowerLayer:
    """PowerLayer class."""

    _firmware_version: str | None = None

    # status fields
    _device_status_data: bytearray | None = None

    # stale check
    _last_update: datetime | None = None

    def __init__(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData | None = None
    ) -> None:
        """Init the PowerLayer."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._operation_lock = asyncio.Lock()
        self._state = PowerLayerState()
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._auto_disconnect_timer: asyncio.TimerHandle | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._expected_disconnect = False
        self.loop = asyncio.get_running_loop()
        self._callbacks: list[Callable[[PowerLayerState], None]] = []
        self._resolve_protocol_event = asyncio.Event()
        self._name: str | None = None

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Set the ble device."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        _LOGGER.debug("%s: RSSI=%s", self.name_and_address, self.rssi)

    @property
    def address(self) -> str:
        """Return the address."""
        return self._ble_device.address

    @property
    def model(self) -> str:
        """Return the model name based on the device version."""
        return "PowerLayer"

    @property
    def firmware_version(self) -> str | None:
        """Return the firmware version."""
        return self._firmware_version

    @property
    def is_data_stale(self) -> bool:
        """Return `True` if the data should be considered stale based on last update."""
        return (
            self._last_update is None
            or (datetime.now(UTC) - self._last_update).total_seconds()
            > STALE_AFTER_SECONDS
        )

    @property
    def name(self) -> str:
        """Get the name of the device."""
        return self._name or self._ble_device.name or self._ble_device.address

    @property
    def name_and_address(self) -> str:
        """Get the name and address of the device."""
        return f"{self.name} ({self.address})"

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    @property
    def state(self) -> PowerLayerState:
        """Return the current state."""
        return self._state

    async def send_button(self, button: PowerLayerButton) -> None:
        """Set LED."""
        command = bytearray((PowerLayerCommand.BUTTON, button))
        await self._send_command(command)
        self._fire_callbacks()

    async def update(self) -> None:
        """Update the PowerLayer."""
        _LOGGER.debug("%s: Updating", self.name_and_address)
        await self._ensure_connected()

        await self._read_device_status()

        try:
            async with asyncio.timeout(5.0):
                while self._device_status_data is None:
                    await asyncio.sleep(0.1)
        except TimeoutError:
            pass

    async def disconnect(self) -> None:
        """Disconnect from the PowerLayer."""
        _LOGGER.debug("%s: Disconnect", self.name_and_address)
        await self._execute_disconnect()

    def _fire_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._callbacks:
            callback(self._state)

    def register_callback(
        self, callback: Callable[[PowerLayerState], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when the state changes."""

        def unregister_callback() -> None:
            self._callbacks.remove(callback)

        self._callbacks.append(callback)
        return unregister_callback

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete",
                self.name_and_address,
            )
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        async with self._connect_lock:
            # Check again while holding the lock
            if self._client and self._client.is_connected:
                self._reset_disconnect_timer()
                return
            _LOGGER.debug("%s: Connecting", self.name_and_address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                self._disconnected,
                use_services_cache=True,
                ble_device_callback=lambda: self._ble_device,
            )
            _LOGGER.debug("%s: Connected", self.name_and_address)

            self._client = client
            self._reset_disconnect_timer()

            _LOGGER.debug("%s: Subscribe to notifications", self.name_and_address)

            await client.start_notify(
                POWERLAYER_STATUS_UUID,
                self._notification_handler,
                cb={"notification_discriminator": self._notification_check_handler},
            )

            if self._device_status_data is None:
                await self._read_device_status()
            if not self._name:
                await self._read_device_name()
            # if not self._firmware_version:
            #     await self._read_device_firmware()

    def _notification_check_handler(self, data: bytes) -> bool:
        """Verify notification data matches expected length."""
        # TODO: Figure out notification length
        return len(data) >= POWERLAYER_NOTIFICATION_MIN_LENGTH

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle notification responses.

        Temperatures are reported in degrees Celsius * 2.
        """
        _LOGGER.debug(
            "%s: Notification received: %s", self.name_and_address, data.hex()
        )
        self._last_update = _now = datetime.now(UTC)

        # TODO: Figure out notification length
        # if len(data) != POWERLAYER_NOTIFICATION_LENGTH:
        #     _LOGGER.debug(
        #         "%s: Unexpected notification received: %s",
        #         self.name_and_address,
        #         data.hex(),
        #     )
        #     return

        head_angle = (int.from_bytes(data[12:14], "big") - 78) / 46.25 + 1.0
        foot_angle = int.from_bytes(data[14:16], "big") / 37.043

        self._state = PowerLayerState(
            head_angle=head_angle,
            foot_angle=foot_angle,
        )

        self._fire_callbacks()

    def _reset_disconnect_timer(self) -> None:
        """Reset disconnect timer."""
        if self._auto_disconnect_timer:
            self._auto_disconnect_timer.cancel()
        self._expected_disconnect = False
        self._auto_disconnect_timer = self.loop.call_later(
            DISCONNECT_DELAY, self._auto_disconnect
        )

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        if self._expected_disconnect:
            _LOGGER.debug("%s: Disconnected from device", self.name_and_address)
            return
        _LOGGER.warning("%s: Device unexpectedly disconnected", self.name_and_address)

    def _auto_disconnect(self) -> None:
        """Disconnect from device automatically."""
        self._auto_disconnect_timer = None
        asyncio.create_task(self._execute_timed_disconnect())

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        _LOGGER.debug(
            "%s: Disconnecting after timeout of %s",
            self.name_and_address,
            DISCONNECT_DELAY,
        )
        await self._execute_disconnect()

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        if self._auto_disconnect_timer:
            self._auto_disconnect_timer.cancel()
        async with self._connect_lock:
            client = self._client
            self._expected_disconnect = True
            self._client = None
            if client and client.is_connected:
                try:
                    await client.stop_notify(POWERLAYER_STATUS_UUID)
                except BleakError:
                    _LOGGER.debug(
                        "%s: Failed to stop notifications",
                        self.name_and_address,
                        exc_info=True,
                    )
                await client.disconnect()

    async def _read_device_name(self) -> None:
        """Read device name PowerLayer."""
        if self._client and self._client.is_connected:
            _LOGGER.debug("%s: Read device name", self.name_and_address)
            data = await self._client.read_gatt_char(POWERLAYER_NAME_UUID)
            if (name := data.decode()) != self.name:
                _LOGGER.debug(
                    "%s: Actual device name is %s", self.name_and_address, name
                )
                self._name = name

    async def _read_device_status(self) -> None:
        """Read device status."""
        if self._client and self._client.is_connected:
            _LOGGER.debug("%s: Read device status", self.name_and_address)
            data = await self._client.read_gatt_char(POWERLAYER_STATUS_UUID)
            self._last_update = datetime.now(UTC)

            # TODO: Determine status length
            # if len(data) != POWERLAYER_STATUS_LENGTH:
            #     _LOGGER.debug(
            #         "%s: Unexpected device status received: %s",
            #         self.name_and_address,
            #         data.hex(),
            #     )
            #     return

            _LOGGER.debug(
                "%s: Received device status: %s", self.name_and_address, data.hex()
            )
            if (old_data := self._device_status_data) != data:
                _LOGGER.debug(
                    "%s: Device status updated: %s -> %s",
                    self.name_and_address,
                    old_data.hex() if old_data else None,
                    data.hex(),
                )
                self._device_status_data = data
                # TODO: Determine status parsing

                self._fire_callbacks()

    async def _send_command(self, command: bytearray) -> None:
        """Send a command to the PowerLayer."""
        if self._client and self._client.is_connected:
            _LOGGER.debug(
                "%s: Sending command: %s", self.name_and_address, command.hex()
            )

            await self._client.write_gatt_char(POWERLAYER_COMMAND_UUID, command)
