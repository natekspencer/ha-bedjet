"""BedJet constants."""

from __future__ import annotations

from enum import Enum, IntEnum


class BedJetNotification(Enum):
    """BedJet notification."""

    NONE = 0
    """No notification pending"""
    CLEAN_FILTER = 1
    """Clean Filter: please check BedJet air filter and clean if necessary"""
    UPDATE_AVAILABLE = 2
    """Firmware Update: a newer version of firmware is available"""
    UPDATE_FAILED = 3
    """Firmware Update: unable to connect to the firmware update server"""
    BIO_FAIL_CLOCK_NOT_SET = 4
    """The specified sequence cannot be run because the clock is not set"""
    BIO_FAIL_TOO_LONG = 5
    """The specified sequence cannot be run because it contains steps 
    that would be too long running from the current time"""


class OperatingMode(IntEnum):
    """Operating mode."""

    STANDBY = 0  # off
    HEAT = 1  # limited to 4 hours
    TURBO = 2  # high heat, limited time
    EXTENDED_HEAT = 3  # limited to 10 hours
    COOL = 4  # actually "Fan only"
    DRY = 5  # high speed, no heat
    WAIT = 6  # a step during a biorhythm program


class BedJetButton(IntEnum):
    """BedJet buttons."""

    OFF = 0x1
    COOL = 0x2
    HEAT = 0x3
    TURBO = 0x4
    DRY = 0x5
    EXTENDED_HEAT = 0x6

    M1 = 0x20
    M2 = 0x21
    M3 = 0x22

    DEBUG_ON = 0x40
    DEBUG_OFF = 0x41
    CONNECTION_TEST = 0x42
    UPDATE_FIRMWARE = 0x43
    NOTIFY_ACK = 0x52

    BIORHYTHM_1 = 0x80
    BIORHYTHM_2 = 0x81
    BIORHYTHM_3 = 0x82


class BedJetCommand(IntEnum):
    """BedJet commands."""

    BUTTON = 0x1
    SET_RUNTIME = 0x2
    SET_TEMPERATURE = 0x3
    SET_STEP = 0x4
    SET_HACKS = 0x5
    STATUS = 0x6
    SET_FAN = 0x7
    SET_CLOCK = 0x8

    SET_BIO = 0x40
    GET_BIO = 0x41


class BioDataRequest(IntEnum):
    """BedJet bio data request."""

    DEVICE_NAME = 0
    MEMORY_NAMES = 1
    BIORHYTHM_NAMES = 4
    FIRMWARE_VERSIONS = 32
