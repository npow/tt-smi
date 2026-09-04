# SPDX-FileCopyrightText: © 2026 Tenstorrent Inc.
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import Mock, call
from types import SimpleNamespace

import pytest

from tt_smi import constants
from tt_smi.backend import TTSMIBackend
from tt_smi.device_input import SmiDeviceInput, SmiDeviceTargetKind
from tt_smi.tt_smi import tt_smi_main


def make_backend(devices, *, use_umd=True):
    backend = object.__new__(TTSMIBackend)
    backend.devices = devices
    backend.use_umd = use_umd
    backend.get_runtime_power_status = Mock(
        return_value=constants.RUNTIME_POWER_OPERATIONAL
    )
    return backend


def test_set_power_limit_umd_all_devices():
    devices = {0: Mock(), 1: Mock()}
    for device in devices.values():
        device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend(devices)
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_board_power_limit = Mock(return_value=100)

    changed = backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 100)

    assert changed == [0, 1]
    for device in devices.values():
        device.arc_msg.assert_called_once_with(
            constants.TT_SMC_MSG_SET_BOARD_POWER_LIMIT, args=[100, 0]
        )


def test_set_power_limit_luwen_uses_blackhole_arc_message():
    bh = Mock()
    bh.arc_msg_buf.return_value = [0, 0, 0, 0, 0, 0, 0, 0]
    device = Mock()
    device.as_bh.return_value = bh
    backend = make_backend({0: device}, use_umd=False)
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_board_power_limit = Mock(return_value=75)

    backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 75)

    bh.arc_msg_buf.assert_called_once_with(
        [constants.TT_SMC_MSG_SET_BOARD_POWER_LIMIT, 75, 0, 0, 0, 0, 0, 0]
    )


def test_set_power_limit_luwen_reports_firmware_rejection():
    bh = Mock()
    bh.arc_msg_buf.return_value = [1, 0, 0, 0, 0, 0, 0, 0]
    device = Mock()
    device.as_bh.return_value = bh
    backend = make_backend({0: device}, use_umd=False)
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_board_power_limit = Mock(return_value=300)

    with pytest.raises(RuntimeError, match="Firmware rejected"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 151)


def test_set_power_limit_validates_all_architectures_before_writing():
    devices = {0: Mock(), 1: Mock()}
    backend = make_backend(devices)
    backend.is_blackhole = Mock(side_effect=lambda device_idx: device_idx == 0)

    with pytest.raises(ValueError, match="unsupported device.*1"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 100)

    devices[0].arc_msg.assert_not_called()


def test_set_power_limit_preflights_all_readbacks_before_writing():
    devices = {0: Mock(), 1: Mock()}
    backend = make_backend(devices)
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_board_power_limit = Mock(
        side_effect=[300, RuntimeError("telemetry unavailable")]
    )

    with pytest.raises(RuntimeError, match="telemetry unavailable"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 100)

    devices[0].arc_msg.assert_not_called()
    devices[1].arc_msg.assert_not_called()


def test_set_power_limit_reports_firmware_rejection():
    device = Mock()
    device.arc_msg.return_value = (1, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)

    with pytest.raises(RuntimeError, match="Firmware rejected"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 151)


def test_set_power_limit_rejects_false_success_when_readback_is_unchanged():
    device = Mock()
    device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_board_power_limit = Mock(return_value=150)

    with pytest.raises(RuntimeError, match="did not apply.*remains 150 W"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 151)


def test_set_power_limit_leaves_upper_bound_validation_to_firmware():
    device = Mock()
    device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_board_power_limit = Mock(return_value=501)

    backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 501)

    device.arc_msg.assert_called_once_with(
        constants.TT_SMC_MSG_SET_BOARD_POWER_LIMIT, args=[501, 0]
    )


def test_set_power_limit_rejects_value_below_firmware_minimum():
    device = Mock()
    backend = make_backend({0: device})

    with pytest.raises(ValueError, match="at least 50.*board-specific"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 49)

    device.arc_msg.assert_not_called()


def test_set_aiclk_limit_umd_uses_host_fmax_message():
    device = Mock()
    device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_aiclk_limit = Mock(return_value=1100)

    changed = backend.set_aiclk_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 1100)

    assert changed == [0]
    device.arc_msg.assert_called_once_with(
        constants.TT_SMC_MSG_SET_ASIC_HOST_FMAX, args=[1100, 0]
    )


def test_luwen_aiclk_readback_uses_raw_telemetry_tag():
    bh = Mock()
    bh.axi_read32.side_effect = [0x1000, 975]
    device = Mock()
    device.as_bh.return_value = bh
    backend = make_backend({0: device}, use_umd=False)

    assert backend.get_runtime_aiclk_limit(0) == 975
    assert bh.axi_read32.call_args_list == [
        call(constants.BH_TELEMETRY_DATA_REG_ADDR),
        call(0x1000 + constants.TAG_HOST_AICLK_LIMIT * 4),
    ]


def test_luwen_runtime_power_status_uses_raw_telemetry_tag():
    bh = Mock()
    bh.axi_read32.side_effect = [0x1000, constants.RUNTIME_POWER_OPERATIONAL]
    device = Mock()
    device.as_bh.return_value = bh
    backend = make_backend({0: device}, use_umd=False)

    status = TTSMIBackend.get_runtime_power_status(backend, 0)

    assert status == constants.RUNTIME_POWER_OPERATIONAL
    assert bh.axi_read32.call_args_list == [
        call(constants.BH_TELEMETRY_DATA_REG_ADDR),
        call(0x1000 + constants.TAG_RUNTIME_POWER_STATUS * 4),
    ]


def test_aiclk_limit_rejects_unsigned_adjacent_memory_before_write():
    device = Mock()
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_aiclk_limit = Mock(return_value=1350)
    backend.get_runtime_power_status = Mock(return_value=0x0000000E)

    with pytest.raises(RuntimeError, match="ABI is unavailable or incompatible"):
        backend.set_aiclk_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 1350)

    device.arc_msg.assert_not_called()


def test_power_limit_rejects_false_success_without_strict_policy():
    device = Mock()
    device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_board_power_limit = Mock(return_value=300)
    backend.get_runtime_power_status = Mock(
        return_value=constants.RUNTIME_POWER_STATUS_ABI_VALUE
    )

    with pytest.raises(RuntimeError, match="not strict, fresh, and ready"):
        backend.set_power_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 300)

    device.arc_msg.assert_called_once_with(
        constants.TT_SMC_MSG_SET_BOARD_POWER_LIMIT, args=[300, 0]
    )


def test_runtime_power_status_rejects_reserved_bit():
    backend = make_backend({0: Mock()})
    backend.get_runtime_power_status = Mock(
        return_value=constants.RUNTIME_POWER_OPERATIONAL
        | constants.RUNTIME_POWER_STATUS_RESERVED_MASK
    )

    with pytest.raises(RuntimeError, match="malformed"):
        backend.require_runtime_power_policy(0)


def test_set_aiclk_limit_zero_restores_default():
    device = Mock()
    device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_aiclk_limit = Mock(return_value=0)

    backend.set_aiclk_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 0)

    device.arc_msg.assert_called_once_with(
        constants.TT_SMC_MSG_SET_ASIC_HOST_FMAX, args=[0, 1]
    )


def test_set_aiclk_limit_rejects_false_success():
    device = Mock()
    device.arc_msg.return_value = (0, 0, 0)
    backend = make_backend({0: device})
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_aiclk_limit = Mock(return_value=1200)

    with pytest.raises(RuntimeError, match="did not apply.*remains 1200 MHz"):
        backend.set_aiclk_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 1100)


def test_set_aiclk_limit_luwen_uses_host_fmax_message():
    bh = Mock()
    bh.arc_msg_buf.return_value = [0, 0, 0, 0, 0, 0, 0, 0]
    device = Mock()
    device.as_bh.return_value = bh
    backend = make_backend({0: device}, use_umd=False)
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_aiclk_limit = Mock(return_value=1000)

    backend.set_aiclk_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 1000)

    bh.arc_msg_buf.assert_called_once_with(
        [constants.TT_SMC_MSG_SET_ASIC_HOST_FMAX, 1000, 0, 0, 0, 0, 0, 0]
    )


def test_set_aiclk_limit_luwen_fails_hard_without_readback_telemetry():
    bh = Mock()
    bh.arc_msg_buf.return_value = [0, 0, 0, 0, 0, 0, 0, 0]
    device = Mock()
    device.as_bh.return_value = bh
    backend = make_backend({0: device}, use_umd=False)
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_aiclk_limit = Mock(
        side_effect=RuntimeError("telemetry is unavailable")
    )

    with pytest.raises(RuntimeError, match="telemetry is unavailable"):
        backend.set_aiclk_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 850)

    bh.arc_msg_buf.assert_not_called()


def test_set_aiclk_limit_preflights_all_readbacks_before_writing():
    devices = {0: Mock(), 1: Mock()}
    backend = make_backend(devices)
    backend.is_blackhole = Mock(return_value=True)
    backend.get_runtime_aiclk_limit = Mock(
        side_effect=[850, RuntimeError("telemetry unavailable")]
    )

    with pytest.raises(RuntimeError, match="telemetry unavailable"):
        backend.set_aiclk_limit(SmiDeviceInput(SmiDeviceTargetKind.ALL), 900)

    devices[0].arc_msg.assert_not_called()
    devices[1].arc_msg.assert_not_called()


def test_combined_cli_applies_power_policy_before_aiclk():
    backend = Mock()
    backend.set_power_limit.return_value = [0]
    backend.set_aiclk_limit.return_value = [0]
    calls = Mock()
    calls.attach_mock(backend.set_power_limit, "power")
    calls.attach_mock(backend.set_aiclk_limit, "aiclk")
    args = SimpleNamespace(power_limit=300, aiclk_limit=1350, device=None)

    with pytest.raises(SystemExit) as exit_info:
        tt_smi_main(backend, args)

    assert exit_info.value.code == 0
    assert calls.method_calls == [
        call.power(SmiDeviceInput(SmiDeviceTargetKind.ALL), 300),
        call.aiclk(SmiDeviceInput(SmiDeviceTargetKind.ALL), 1350),
    ]


def test_resolve_device_input_reports_unknown_target():
    backend = make_backend({0: Mock()})

    with pytest.raises(ValueError, match="Device target.*9"):
        backend.resolve_device_input(
            SmiDeviceInput(SmiDeviceTargetKind.UMD_LOGICAL_ID, [9])
        )
