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

# ISSC BedJet V2 UUIDs
BEDJET_V2_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
BEDJET_V2_STATUS_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
BEDJET_V2_COMMAND_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"

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

DEFAULT_TEMPERATURE_DELTA = 1.0
DEFAULT_TEMPERATURE_TIME = timedelta(seconds=15)


@dataclass
class TemperatureLimiter:
    """Limit how often a temperature value is allowed to change.

    This class suppresses small, rapid fluctuations ("jitter") from fast-reporting
    temperature sensors. A new temperature is accepted only if at least one of the
    following conditions is met:

    - The temperature changed by at least ``min_delta`` degrees.
    - At least ``min_time`` has passed since the last accepted update.

    If the incoming temperature is exactly the same as the current value, the
    internal timer is reset to prevent a forced update due only to elapsed time.
    """

    min_delta: float = DEFAULT_TEMPERATURE_DELTA
    min_time: timedelta = DEFAULT_TEMPERATURE_TIME

    temperature: float | None = None
    last_updated: datetime | None = None

    def update(self, temperature: float, now: datetime | None = None) -> float:
        """Process a new temperature reading and return the value to report.

        Args:
            temperature: The newly received temperature reading.
            now: Optional timestamp for the reading. If not provided, the current
                  UTC time will be used. Supplying this is useful for testing or when
                  multiple values should share the same timestamp.

        Returns:
            The temperature value that should be reported after applying the
            limiter rules. This will be either the new temperature (if accepted)
            or the previously accepted value (if suppressed).
        """
        if now is None:
            now = datetime.now(UTC)

        def _accept() -> float:
            self.temperature = temperature
            self.last_updated = now
            return temperature

        if self.last_updated is None or self.temperature is None:
            return _accept()

        if self.temperature == temperature:
            return _accept()  # reset timer to further reduce jitter

        if (
            abs(temperature - self.temperature) >= self.min_delta
            or (now - self.last_updated) >= self.min_time
        ):
            return _accept()

        return self.temperature


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

    # V2 Support Flag
    _is_v2: bool = False

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

        # temperature limiters
        self._current_temperature_limiter = TemperatureLimiter()
        self._ambient_temperature_limiter = TemperatureLimiter()

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
    def is_v2(self) -> bool:
        """Return True if connected to a V2 device."""
        return self._is_v2

    @property
    def model(self) -> str:
        """Return the model name based on the device version."""
        return "BedJet V2" if self.is_v2 else "BedJet 3"

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
        if self._is_v2:
            # V2 Protocol: SET_FAN (0x07)
            # Packet: 58 07 0E [MODE] [STEP] [TEMP] [HRS] [MIN] 00 [CHK]

            # 1. Determine Mode ID from current state
            mode_id = 0x02  # Default Heat
            if self.state.operating_mode == OperatingMode.TURBO:
                mode_id = 0x01
            elif self.state.operating_mode == OperatingMode.HEAT:
                mode_id = 0x02
            elif self.state.operating_mode == OperatingMode.COOL:
                mode_id = 0x03

            # 2. Calculate Fan Step
            step = int(fan_speed / 5)

            # 3. Handle Timer Preservation
            total_seconds = int(self.state.runtime_remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            # 4. Handle Temperature and Mute Flag
            temp_byte = round(self.state.target_temperature * 2)

            # If currently Muted, add 0x80 to bitmask to PRESERVE mute state
            if self.beeps_muted:
                temp_byte |= 0x80

            payload = bytearray(
                [0x07, 0x0E, mode_id, step, temp_byte, hours, minutes, 0x00]
            )
            await self._send_command(payload)
            return

        # Original V3 Command
        command = bytearray((BedJetCommand.SET_FAN, int(fan_speed / 5) - 1))
        await self._send_command(command)

    async def set_led(self, led: bool) -> None:
        """Set muted."""
        if self._is_v2:
            # V2 Protocol: CMD_SET_SETTINGS (0x11)
            # Settings Byte: Bit 0 = Mute, Bit 1 = LED Off
            settings_byte = 0x00

            # Preserve current Mute state
            if self.beeps_muted:
                settings_byte |= 0x01

            # Apply new LED state (Bit 1 is "Off")
            if not led:
                settings_byte |= 0x02

            await self._send_command(bytearray([0x02, 0x11, settings_byte]))
            self._led_enabled = led
            self._fire_callbacks()
            return

        # Original V3 Command
        button = BedJetButton.LED_ON if led else BedJetButton.LED_OFF
        command = bytearray((BedJetCommand.BUTTON, button))
        await self._send_command(command)
        self._led_enabled = led
        self._fire_callbacks()

    async def set_muted(self, muted: bool) -> None:
        """Set muted."""
        if self._is_v2:
            # V2 Protocol: CMD_SET_SETTINGS (0x11)
            # Settings Byte: Bit 0 = Mute, Bit 1 = LED Off
            settings_byte = 0x00

            # Apply new Mute state
            if muted:
                settings_byte |= 0x01

            # Preserve current LED state (Bit 1 is "Off")
            if self.led_enabled is False:
                settings_byte |= 0x02

            await self._send_command(bytearray([0x02, 0x11, settings_byte]))
            self._beeps_muted = muted
            self._fire_callbacks()
            return

        # Original V3 Command
        button = BedJetButton.MUTE if muted else BedJetButton.UNMUTE
        command = bytearray((BedJetCommand.BUTTON, button))
        await self._send_command(command)
        self._beeps_muted = muted
        self._fire_callbacks()

    async def set_operating_mode(self, operating_mode: OperatingMode) -> None:
        """Set operating mode."""
        if self._is_v2:
            # V2 Protocol: Button Events (0x02)
            target_btn = None
            if operating_mode == OperatingMode.TURBO:
                target_btn = 0x01
            elif operating_mode == OperatingMode.HEAT:
                target_btn = 0x02
            elif operating_mode == OperatingMode.COOL:
                target_btn = 0x03

            # Handle OFF (Standby)
            if operating_mode == OperatingMode.STANDBY:
                # Toggle current mode to turn off
                curr = self.state.operating_mode
                off_btn = None
                if curr == OperatingMode.TURBO:
                    off_btn = 0x01
                elif curr == OperatingMode.HEAT:
                    off_btn = 0x02
                elif curr == OperatingMode.COOL:
                    off_btn = 0x03

                if off_btn:
                    await self._send_command(bytearray([0x02, 0x01, off_btn]))
                    try:
                        async with asyncio.timeout(1):
                            while self.state.operating_mode != OperatingMode.STANDBY:
                                await asyncio.sleep(0.1)
                    except TimeoutError:
                        pass
                return

            # Handle ON (Mode Switch)
            if target_btn:
                # If already in mode, do nothing (unless it's Turbo, which we might want to refresh)
                if (
                    operating_mode != OperatingMode.TURBO
                    and self.state.operating_mode == operating_mode
                ):
                    return

                await self._send_command(bytearray([0x02, 0x01, target_btn]))
                try:
                    async with asyncio.timeout(1):
                        while self.state.operating_mode != operating_mode:
                            await asyncio.sleep(0.1)
                except TimeoutError:
                    pass
            return

        # Original V3 Command
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
        if self._is_v2:
            return  # V2 Runtime set via Fan/Mode commands, not standalone

        if minutes >= 60:
            hours += int(minutes / 60)
            minutes = minutes % 60
        command = bytearray((BedJetCommand.SET_RUNTIME, hours, minutes))
        await self._send_command(command)

    async def set_temperature(self, temperature: float) -> None:
        """Set temperature."""
        if self._is_v2:
            # V2 Protocol: CMD_SET_TEMP (0x02 0x07)
            temp_byte = round(temperature * 2)

            # Preserve Mute State
            if self.beeps_muted:
                temp_byte |= 0x80

            await self._send_command(bytearray([0x02, 0x07, temp_byte]))
            return

        # Original V3 Command
        command = bytearray((BedJetCommand.SET_TEMPERATURE, round(temperature * 2)))
        await self._send_command(command)

    async def update(self) -> None:
        """Update the BedJet."""
        _LOGGER.debug("%s: Updating", self.name_and_address)
        await self._ensure_connected()

        if not self._is_v2:
            await self._read_device_status()
            await self._read_memory_names()
            await self._read_biorhythm_names()

        try:
            async with asyncio.timeout(5.0):
                while self._state.current_temperature == 0:
                    await asyncio.sleep(0.1)
        except TimeoutError:
            pass

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

            # V2 Protocol Detection
            if client.services.get_characteristic(BEDJET_V2_STATUS_UUID):
                self._is_v2 = True
                status_uuid = BEDJET_V2_STATUS_UUID
                await asyncio.sleep(3.0)
                # V2 Init Packet (Wake Up)
                await client.write_gatt_char(
                    BEDJET_V2_COMMAND_UUID,
                    bytearray([0x58, 0x01, 0x0B, 0x9B]),
                    response=False,
                )
            else:
                self._is_v2 = False
                status_uuid = BEDJET_STATUS_UUID

            _LOGGER.debug("%s: Subscribe to notifications", self.name_and_address)

            for attempt in range(3):
                try:
                    await client.start_notify(
                        status_uuid,
                        self._notification_handler,
                        cb={
                            "notification_discriminator": self._notification_check_handler
                        },
                    )
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.0)

            if not self._is_v2:
                if self._device_status_data is None:
                    await self._read_device_status()
                if not self._name:
                    await self._read_device_name()
                if not self._firmware_version:
                    await self._read_device_firmware()
            else:
                self._name = "BedJet V2"
                self._firmware_version = "ISSC V2"

    def _notification_check_handler(self, data: bytes) -> bool:
        """Verify notification data matches expected length."""
        if self._is_v2:
            return len(data) == 14
        return len(data) == 20

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

        if self._is_v2:
            self._handle_v2_notification(data, _now)
            return

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
        current_temperature = self._current_temperature_limiter.update(
            data[7] / 2, _now
        )
        target_temperature = data[8] / 2
        operating_mode = OperatingMode(data[9])
        fan_step = data[10]
        maximum_hours = data[11]
        maximum_minutes = data[12]
        minimum_temperature = data[13] / 2
        maximum_temperature = data[14] / 2
        turbo_time = int.from_bytes(data[15 : 15 + 2], byteorder="big")
        ambient_temperature = self._ambient_temperature_limiter.update(
            data[17] / 2, _now
        )
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

    def _handle_v2_notification(self, data: bytearray, _now: datetime) -> None:
        """Handle ISSC V2 notification responses."""
        if len(data) != 14:
            return

        b4, b5 = data[4], data[5]
        operating_mode = OperatingMode.STANDBY
        fan_speed = 0

        # --- MODE & FAN DETECTION ---
        # 1. COOL: 97-116
        if 97 <= b4 <= 116:
            operating_mode = OperatingMode.COOL
            fan_speed = (b4 - 96) * 5
        # 2. HEAT: 65-84
        elif 65 <= b4 <= 84:
            operating_mode = OperatingMode.HEAT
            fan_speed = (b4 - 64) * 5
        # 3. TURBO: 33-52 (0x21-0x34)
        elif 33 <= b4 <= 52:
            operating_mode = OperatingMode.TURBO
            fan_speed = (b4 - 32) * 5
        # 4. OFF: 0x14 (20) or 0x0E (14) or Byte5=0
        elif b4 == 0x14 or b4 == 0x0E or b5 == 0x00:
            operating_mode = OperatingMode.STANDBY

        # --- TURBO FALLBACK ---
        if b5 in (0x01, 0x02, 0x03, 0x04) and operating_mode == OperatingMode.STANDBY:
            operating_mode = OperatingMode.TURBO
            fan_speed = 100

        # Retain Fan Speed if Off (prevents UI error)
        if operating_mode == OperatingMode.STANDBY:
            fan_speed = self._state.fan_speed
        else:
            if fan_speed > 0:
                fan_speed = int(round(fan_speed / 5.0) * 5)
                fan_speed = max(5, min(100, fan_speed))
            else:
                fan_speed = 5

        # --- TEMPERATURE ---
        def decode_temp_c(byte_val):
            raw_f = int(((byte_val & 0x7F) * 0.9) + 32)
            return (raw_f - 32) * 5 / 9

        current_temp_c = self._current_temperature_limiter.update(
            decode_temp_c(data[3]), _now
        )
        target_temp_c = decode_temp_c(data[7])

        # --- TURBO OVERRIDE (109F) ---
        if operating_mode == OperatingMode.TURBO:
            target_temp_c = 42.7

        hours = b5 >> 4
        sub_raw = ((b5 & 0x0F) << 8) | data[6]
        total_seconds = hours * 3600 + (sub_raw * 60 + 32) // 64
        runtime_remaining = timedelta(seconds=total_seconds)

        # --- STATUS FLAGS (Byte 8) ---
        self._beeps_muted = bool(data[8] & 0x80)
        self._led_enabled = not bool(data[3] & 0x80)

        turbo_time = max(0, 600 - data[11])

        self._state = BedJetState(
            current_temperature=current_temp_c,
            target_temperature=target_temp_c,
            operating_mode=operating_mode,
            runtime_remaining=runtime_remaining,
            maximum_runtime=timedelta(hours=10),
            turbo_time=timedelta(seconds=turbo_time),
            fan_speed=fan_speed,
            minimum_temperature=19.0,
            maximum_temperature=43.0,
            ambient_temperature=current_temp_c,
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
                    uuid = BEDJET_V2_STATUS_UUID if self._is_v2 else BEDJET_STATUS_UUID
                    await client.stop_notify(uuid)
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

            if self._is_v2:
                # WRAPPER: 0x58 + CMD + CHECKSUM
                v2_payload = bytearray([0x58]) + command
                total = sum(v2_payload) & 0xFF
                checksum = (0xFF - total) & 0xFF
                v2_payload.append(checksum)
                # Send V2 Packet
                await self._client.write_gatt_char(
                    BEDJET_V2_COMMAND_UUID, v2_payload, response=False
                )
            else:
                # Original V3 Command
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
