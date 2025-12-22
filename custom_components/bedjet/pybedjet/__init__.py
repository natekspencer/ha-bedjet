"""BedJet device module."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from math import ceil

from bleak import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakError,
    establish_connection,
)

from .const import (
    BedJetButton,
    BedJetCommand,
    BedJetNotification,
    BioDataRequest,
    OperatingMode,
)

_LOGGER = logging.getLogger(__name__)

BEDJET_SERVICE_UUID = "00001000-bed0-0080-aa55-4265644a6574"
BEDJET_STATUS_UUID = "00002000-bed0-0080-aa55-4265644a6574"
BEDJET_NAME_UUID = "00002001-bed0-0080-aa55-4265644a6574"
BEDJET_SSID_UUID = "00002002-bed0-0080-aa55-4265644a6574"
BEDJET_PASSWD_UUID = "00002003-bed0-0080-aa55-4265644a6574"
BEDJET_COMMAND_UUID = "00002004-bed0-0080-aa55-4265644a6574"
BEDJET_BIODATA_UUID = "00002005-bed0-0080-aa55-4265644a6574"
BEDJET_BIODATA_FULL_UUID = "00002006-bed0-0080-aa55-4265644a6574"
CLIENT_CHARACTERISTIC_CONFIG = "00002902-0000-1000-8000-00805f9b34fb"

DISCONNECT_DELAY = 60

OPERATING_MODE_BUTTON_MAP = {
    OperatingMode.STANDBY: BedJetButton.OFF,
    OperatingMode.HEAT: BedJetButton.HEAT,
    OperatingMode.TURBO: BedJetButton.TURBO,
    OperatingMode.EXTENDED_HEAT: BedJetButton.EXTENDED_HEAT,
    OperatingMode.COOL: BedJetButton.COOL,
    OperatingMode.DRY: BedJetButton.DRY,
}

STALE_AFTER_SECONDS = 60


@dataclass(frozen=True)
class BedJetState:
    """BedJet state."""

    current_temperature: float = 0
    target_temperature: float = 0
    operating_mode: OperatingMode = OperatingMode.STANDBY
    runtime_remaining: timedelta = timedelta()
    maximum_runtime: timedelta = timedelta()
    turbo_time: timedelta = timedelta()
    fan_speed: int = 0

    minimum_temperature: float = 0
    maximum_temperature: float = 0
    ambient_temperature: float = 0


class BedJet:
    """BedJet class."""

    _firmware_version: str | None = None
    _biorhythm_names: list[str] | None = None
    _memory_names: list[str] | None = None
    _m1_name: str | None = None
    _m2_name: str | None = None
    _m3_name: str | None = None
    _shutdown_reason: int | None = None

    # status fields
    _device_status_data: bytearray | None = None
    _beeps_muted: bool | None = None
    _bio_sequence_step: int | None = None
    _connection_test_passed: bool | None = None
    _dual_zone: bool | None = None
    _led_enabled: bool | None = None
    _notification: BedJetNotification | None = None
    _units_setup: bool | None = None
    _update_phase: int | None = None

    # stale check
    _last_update: datetime | None = None

    def __init__(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData | None = None
    ) -> None:
        """Init the BedJet."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._operation_lock = asyncio.Lock()
        self._state = BedJetState()
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._auto_disconnect_timer: asyncio.TimerHandle | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._expected_disconnect = False
        self.loop = asyncio.get_running_loop()
        self._callbacks: list[Callable[[BedJetState], None]] = []
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
    def beeps_muted(self) -> bool | None:
        """Return `True` if beeps are muted."""
        return self._beeps_muted

    @property
    def biorhythm1_name(self) -> str | None:
        """Return the biorhythm 1 name."""
        if self._biorhythm_names and (name := self._biorhythm_names[0]):
            return name
        return None

    @property
    def biorhythm2_name(self) -> str | None:
        """Return the biorhythm 2 name."""
        if self._biorhythm_names and (name := self._biorhythm_names[1]):
            return name
        return None

    @property
    def biorhythm3_name(self) -> str | None:
        """Return the biorhythm 3 name."""
        if self._biorhythm_names and (name := self._biorhythm_names[2]):
            return name
        return None

    @property
    def bio_sequence_step(self) -> int | None:
        """Return the current bio sequence step."""
        return self._bio_sequence_step

    @property
    def connection_test_passed(self) -> bool | None:
        """Return if the connection test passed."""
        return self._connection_test_passed

    @property
    def dual_zone(self) -> bool | None:
        """Return `True` if part of a dual zone setup."""
        return self._dual_zone

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
    def led_enabled(self) -> bool | None:
        """Return if LED ring is enabled."""
        return self._led_enabled

    @property
    def m1_name(self) -> str | None:
        """Return the M1 memory name."""
        if self._memory_names and (name := self._memory_names[0]):
            return f"M1: {name}"
        return None

    @property
    def m2_name(self) -> str | None:
        """Return the M2 memory name."""
        if self._memory_names and (name := self._memory_names[1]):
            return f"M2: {name}"
        return None

    @property
    def m3_name(self) -> str | None:
        """Return the M3 memory name."""
        if self._memory_names and (name := self._memory_names[2]):
            return f"M3: {name}"
        return None

    @property
    def name(self) -> str:
        """Get the name of the device."""
        return self._name or self._ble_device.name or self._ble_device.address

    @property
    def name_and_address(self) -> str:
        """Get the name and address of the device."""
        return f"{self.name} ({self.address})"

    @property
    def notification(self) -> BedJetNotification | None:
        """Return the current notification."""
        return self._notification

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    @property
    def shutdown_reason(self) -> int | None:
        """Return the shutdown reason."""
        return self._shutdown_reason

    @property
    def state(self) -> BedJetState:
        """Return the current state."""
        return self._state

    @property
    def units_setup(self) -> bool | None:
        """Return `True` if units have been setup."""
        return self._units_setup

    @property
    def update_phase(self) -> int | None:
        """Return the update phase."""
        return self._update_phase

    async def set_clock(self, hour: int, minute: int) -> None:
        """Set the clock."""
        if not 0 <= hour <= 23:
            raise ValueError(f"Invalid hour: {hour} (range is [0, 23])")
        if not 0 <= minute <= 59:
            raise ValueError(f"Invalid minute: {minute} (range is [0, 59])")
        command = bytearray((BedJetCommand.SET_CLOCK, hour, minute))
        await self._send_command(command)

    async def set_fan_speed(self, fan_speed: int) -> None:
        """Set fan speed."""
        command = bytearray((BedJetCommand.SET_FAN, int(fan_speed / 5) - 1))
        await self._send_command(command)

    async def set_led(self, led: bool) -> None:
        """Set muted."""
        button = BedJetButton.LED_ON if led else BedJetButton.LED_OFF
        command = bytearray((BedJetCommand.BUTTON, button))
        await self._send_command(command)
        self._led_enabled = led
        self._fire_callbacks()

    async def set_muted(self, muted: bool) -> None:
        """Set muted."""
        button = BedJetButton.MUTE if muted else BedJetButton.UNMUTE
        command = bytearray((BedJetCommand.BUTTON, button))
        await self._send_command(command)
        self._beeps_muted = muted
        self._fire_callbacks()

    async def set_operating_mode(self, operating_mode: OperatingMode) -> None:
        """Set operating mode."""
        command = bytearray(
            (BedJetCommand.BUTTON, OPERATING_MODE_BUTTON_MAP[operating_mode])
        )
        await self._send_command(command)
        try:
            async with asyncio.timeout(1):
                while self.state.operating_mode != operating_mode:
                    await asyncio.sleep(0.1)
        except TimeoutError:
            _LOGGER.warning(
                "%s: Could not confirm if operating mode was set in 1 second",
                self.name_and_address,
            )

    async def set_runtime_remaining(self, hours: int = 0, minutes: int = 0) -> None:
        """Set runtime remaining."""
        if minutes >= 60:
            hours += int(minutes / 60)
            minutes = minutes % 60
        command = bytearray((BedJetCommand.SET_RUNTIME, hours, minutes))
        await self._send_command(command)

    async def set_temperature(self, temperature: float) -> None:
        """Set temperature."""
        command = bytearray((BedJetCommand.SET_TEMPERATURE, round(temperature * 2)))
        await self._send_command(command)

    async def update(self) -> None:
        """Update the BedJet."""
        _LOGGER.debug("%s: Updating", self.name_and_address)
        await self._ensure_connected()
        await self._read_device_status()
        await self._read_memory_names()
        await self._read_biorhythm_names()
        while self._state.current_temperature == 0:
            await asyncio.sleep(0.1)

    async def disconnect(self) -> None:
        """Disconnect from the BedJet."""
        _LOGGER.debug("%s: Disconnect", self.name_and_address)
        await self._execute_disconnect()

    def _fire_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._callbacks:
            callback(self._state)

    def register_callback(
        self, callback: Callable[[BedJetState], None]
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
                BEDJET_STATUS_UUID,
                self._notification_handler,
                cb={"notification_discriminator": self._notification_check_handler},
            )

            if self._device_status_data is None:
                await self._read_device_status()
            if not self._name:
                await self._read_device_name()
            if not self._firmware_version:
                await self._read_device_firmware()

    def _notification_check_handler(self, data: bytes) -> bool:
        """Verify notification data matches expected length."""
        return len(data) == 20

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle notification responses."""
        _LOGGER.debug(
            "%s: Notification received: %s", self.name_and_address, data.hex()
        )
        self._last_update = datetime.now(UTC)

        if len(data) != 20:
            _LOGGER.debug(
                "%s: Unexpected notification received: %s",
                self.name_and_address,
                data.hex(),
            )
            return

        hours_remaining = data[4]
        minutes_remaining = data[5]
        seconds_remaining = data[6]
        current_temperature = data[7] / 2  # Stored as Celsius * 2
        target_temperature = data[8] / 2  # Stored as Celsius * 2
        operating_mode = OperatingMode(data[9])
        fan_step = data[10]
        maximum_hours = data[11]
        maximum_minutes = data[12]
        minimum_temperature = data[13] / 2  # Stored as Celsius * 2
        maximum_temperature = data[14] / 2  # Stored as Celsius * 2
        turbo_time = int.from_bytes(data[15 : 15 + 2], byteorder="big")
        ambient_temperature = data[17] / 2  # Stored as Celsius * 2
        self._shutdown_reason = data[18]

        runtime_remaining = timedelta(
            hours=hours_remaining, minutes=minutes_remaining, seconds=seconds_remaining
        )
        maximum_runtime = timedelta(hours=maximum_hours, minutes=maximum_minutes)
        fan_speed = (fan_step + 1) * 5

        self._state = BedJetState(
            current_temperature,
            target_temperature,
            operating_mode,
            runtime_remaining,
            maximum_runtime,
            timedelta(seconds=turbo_time),
            fan_speed,
            minimum_temperature,
            maximum_temperature,
            ambient_temperature,
        )

        self._fire_callbacks()

    def _parse_bio_data_response(self, data: bytearray) -> None:
        """Parse bio data responses."""
        bio_type = data[0:1].hex()
        tag = data[1:2].hex()
        message = "Unknown bio data"

        def parse_text(data: bytearray, length: int | None = None, lead_bits: int = 0):
            if lead_bits:
                data = data[lead_bits:]
            if not length:
                if data[0] == 0:
                    return "Default"
                if data[0] == 1:
                    return None
                return data.split(b"\x00", 1)[0].decode()
            else:
                count = range(ceil(len(data) / length))
                return [parse_text(data[i * length : (i + 1) * length]) for i in count]

        if bio_type == "00":
            message = "Device name"
            self._name = parse_text(data, lead_bits=2)
        elif bio_type == "01":
            message = "Memory names"
            self._memory_names = parse_text(data, 16, 2)
        elif bio_type == "04":
            message = "Biorhythm names"
            self._biorhythm_names = parse_text(data, 16, 2)
        elif bio_type == "20":
            message = "Firmware"
            firmwares = parse_text(data, 16, 2)
            self._firmware_version = firmwares[0]

        _LOGGER.debug(
            "%s: %s (%s) received: %s (%s)",
            self.name_and_address,
            message,
            tag,
            data.hex(),
            data,
        )

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
                    await client.stop_notify(BEDJET_STATUS_UUID)
                except BleakError:
                    _LOGGER.debug(
                        "%s: Failed to stop notifications",
                        self.name_and_address,
                        exc_info=True,
                    )
                await client.disconnect()

    async def _read_device_name(self) -> None:
        """Read device name."""
        if self._client and self._client.is_connected:
            _LOGGER.debug("%s: Read device name", self.name_and_address)
            data = await self._client.read_gatt_char(BEDJET_NAME_UUID)
            if (name := data.decode()) != self.name:
                _LOGGER.debug(
                    "%s: Actual device name is %s", self.name_and_address, name
                )
                self._name = name

    async def _read_device_status(self) -> None:
        """Read device status."""
        if self._client and self._client.is_connected:
            _LOGGER.debug("%s: Read device status", self.name_and_address)
            data = await self._client.read_gatt_char(BEDJET_STATUS_UUID)
            self._last_update = datetime.now(UTC)

            if len(data) != 11:
                _LOGGER.debug(
                    "%s: Unexpected device status received: %s",
                    self.name_and_address,
                    data.hex(),
                )
                return

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
                # _ = data[0]  # unknown
                # _ = data[1]  # unknown
                _, _, _, _, _, _, self._dual_zone, _ = [
                    bool(data[2] >> x & 1) for x in range(7, -1, -1)
                ]
                # _ = data[3]  # unknown
                # _ = data[4]  # unknown
                # _ = data[5]  # unknown
                self._update_phase = data[6]
                (
                    _,
                    _,
                    self._connection_test_passed,
                    self._led_enabled,
                    _,
                    self._units_setup,
                    _,
                    self._beeps_muted,
                ) = [bool(data[7] >> x & 1) for x in range(7, -1, -1)]
                self._bio_sequence_step = data[8]
                self._notification = BedJetNotification(data[9])
                # _ = data[10]  # unknown

                self._fire_callbacks()

    async def _read_device_firmware(self) -> None:
        """Read device firmware."""
        tag = 0
        while not self._firmware_version and tag < 2:
            if self._client and self._client.is_connected:
                _LOGGER.debug("%s: Read device firmware", self.name_and_address)
                command = bytearray(
                    (BedJetCommand.GET_BIO, BioDataRequest.FIRMWARE_VERSIONS, tag)
                )
                await self._send_command(command)
                data = await self._client.read_gatt_char(BEDJET_BIODATA_FULL_UUID)
                self._parse_bio_data_response(data)
                tag += 1
        if not self._firmware_version:
            _LOGGER.debug("%s: Failed to read firmware", self.name_and_address)

    async def _read_biorhythm_names(self) -> None:
        """Read biorhythm preset names."""
        tag = 0
        while not self._biorhythm_names and tag < 2:
            if self._client and self._client.is_connected:
                _LOGGER.debug("%s: Read biorhythm names", self.name_and_address)
                command = bytearray(
                    (BedJetCommand.GET_BIO, BioDataRequest.BIORHYTHM_NAMES, tag)
                )
                await self._send_command(command)
                data = await self._client.read_gatt_char(BEDJET_BIODATA_FULL_UUID)
                self._parse_bio_data_response(data)
                tag += 1
        if not self._biorhythm_names:
            _LOGGER.debug("%s: Failed to read biorhythm names", self.name_and_address)

    async def _read_memory_names(self) -> None:
        """Read memory preset names."""
        tag = 0
        while not self._memory_names and tag < 2:
            if self._client and self._client.is_connected:
                _LOGGER.debug("%s: Read memory names", self.name_and_address)
                command = bytearray(
                    (BedJetCommand.GET_BIO, BioDataRequest.MEMORY_NAMES, tag)
                )
                await self._send_command(command)
                data = await self._client.read_gatt_char(BEDJET_BIODATA_FULL_UUID)
                self._parse_bio_data_response(data)
                tag += 1
        if not self._memory_names:
            _LOGGER.debug("%s: Failed to read memory names", self.name_and_address)

    async def _send_command(self, command: bytearray) -> None:
        """Send a command to the BedJet."""
        if self._client and self._client.is_connected:
            _LOGGER.debug(
                "%s: Sending command: %s", self.name_and_address, command.hex()
            )
            await self._client.write_gatt_char(BEDJET_COMMAND_UUID, command)

    async def _run_test_commands(self) -> None:
        """Run test commands."""
        if self._client and self._client.is_connected:
            tag = 0
            for bio_type in (
                BioDataRequest.BIORHYTHM_NAMES,
                BioDataRequest.DEVICE_NAME,
                BioDataRequest.FIRMWARE_VERSIONS,
                BioDataRequest.MEMORY_NAMES,
            ):
                tag += 1
                command = bytearray((BedJetCommand.GET_BIO, bio_type, tag))
                _LOGGER.debug(
                    "%s: Writing command value: %s",
                    self.name_and_address,
                    command.hex(),
                )
                await self._client.write_gatt_char(BEDJET_COMMAND_UUID, command, True)

                data = await self._client.read_gatt_char(BEDJET_BIODATA_FULL_UUID)
                self._parse_bio_data_response(data)
                _LOGGER.debug(
                    "%s: %s/%s, %s/%s, %s, %s",
                    self.name_and_address,
                    bio_type,
                    data[0],
                    tag,
                    data[1],
                    data[2:].hex(),
                    data[2:],
                )
