"""Fixtures for BedJet tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.bedjet.pybedjet import BedJet, OperatingMode, PowerLayer
from custom_components.bedjet.pybedjet.bedjet import BedJetState
from custom_components.bedjet.pybedjet.powerlayer import PowerLayerState

from . import service_info


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture(autouse=True)
def auto_mock_bluetooth(mock_bluetooth: None) -> None:
    """Keep Bluetooth from touching the host's adapters in all tests."""


def _complete_update(device: BedJet | PowerLayer, state: Any) -> None:
    """Apply a state to a device as if it had been read over Bluetooth."""
    device._state = state
    device._last_update = datetime.now(UTC)
    device._firmware_version = "1.0.0"
    device._fire_callbacks()


@pytest.fixture
def bedjet_state() -> BedJetState:
    """Return the state a BedJet reports when running in heat mode."""
    return BedJetState(
        current_temperature=30,
        target_temperature=32,
        operating_mode=OperatingMode.HEAT,
        runtime_remaining=timedelta(hours=1),
        maximum_runtime=timedelta(hours=4),
        turbo_time=timedelta(minutes=10),
        fan_speed=50,
        minimum_temperature=19,
        maximum_temperature=43,
        ambient_temperature=22,
    )


@pytest.fixture
async def bedjet(bedjet_state: BedJetState) -> Generator[BedJet]:
    """Return a BedJet that updates without a Bluetooth connection."""
    device = BedJet(service_info().device)

    async def update() -> None:
        _complete_update(device, bedjet_state)

    with (
        patch.object(device, "update", side_effect=update),
        patch.object(device, "disconnect", AsyncMock()),
    ):
        yield device


@pytest.fixture
async def powerlayer() -> Generator[PowerLayer]:
    """Return a PowerLayer that updates without a Bluetooth connection."""
    device = PowerLayer(service_info().device)
    state = PowerLayerState(head_angle=15, foot_angle=5)

    async def update() -> None:
        _complete_update(device, state)

    with (
        patch.object(device, "update", side_effect=update),
        patch.object(device, "disconnect", AsyncMock()),
    ):
        yield device
