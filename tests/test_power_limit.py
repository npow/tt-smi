# SPDX-FileCopyrightText: © 2026 Tenstorrent Inc.
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import Mock

import pytest

from tt_smi import constants
from tt_smi.backend import TTSMIBackend
from tt_smi.device_input import SmiDeviceInput, SmiDeviceTargetKind


def make_backend(devices, *, use_umd=True):
    backend = object.__new__(TTSMIBackend)
    backend.devices = devices
    backend.use_umd = use_umd
    return backend


def test_set_power_limit_umd_all_devices():
    devices = {0: Mock(), 1: Mock()}
    for device in devices.values():
        device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend(devices)
    backend.is_blackhole = Mock(return_value=True)

    changed = backend.set_power_limit(
        SmiDeviceInput(SmiDeviceTargetKind.ALL), 100
    )

    assert changed == [0, 1]
    for device in devices.values():
        device.arc_msg.assert_called_once_with(
            constants.TT_SMC_MSG_SET_TDP_LIMIT, args=[100, 0]
        )


def test_set_power_limit_luwen_uses_blackhole_arc_message():
    bh = Mock()
    bh.arc_msg.return_value = (0, 0)
    device = Mock()
    device.as_bh.return_value = bh
    backend = make_backend({0: device}, use_umd=False)
    backend.is_blackhole = Mock(return_value=True)

    backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 75)

    bh.arc_msg.assert_called_once_with(
        constants.TT_SMC_MSG_SET_TDP_LIMIT, arg0=75, arg1=0
    )


def test_set_power_limit_validates_all_architectures_before_writing():
    devices = {0: Mock(), 1: Mock()}
    backend = make_backend(devices)
    backend.is_blackhole = Mock(side_effect=lambda device_idx: device_idx == 0)

    with pytest.raises(ValueError, match="unsupported device.*1"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 100)

    devices[0].arc_msg.assert_not_called()


def test_set_power_limit_reports_firmware_rejection():
    device = Mock()
    device.arc_msg.return_value = (1, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)

    with pytest.raises(RuntimeError, match="Firmware rejected"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 500)


@pytest.mark.parametrize("watts", [49, 501])
def test_set_power_limit_rejects_out_of_range_value(watts):
    device = Mock()
    backend = make_backend({0: device})

    with pytest.raises(ValueError, match="between 50 and 500"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), watts)

    device.arc_msg.assert_not_called()


def test_resolve_device_input_reports_unknown_target():
    backend = make_backend({0: Mock()})

    with pytest.raises(ValueError, match="Device target.*9"):
        backend.resolve_device_input(
            SmiDeviceInput(SmiDeviceTargetKind.UMD_LOGICAL_ID, [9])
        )
