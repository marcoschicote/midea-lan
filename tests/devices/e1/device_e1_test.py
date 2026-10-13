"""Test E1 device."""

from unittest.mock import patch

import pytest

from midealan.const import ProtocolVersion
from midealan.devices.e1 import DeviceAttributes, MideaE1Device
from midealan.devices.e1.message import (
    MessageLock,
    MessagePower,
    MessageQuery,
    MessageStorage,
    MessageWork,
)
from midealan.exceptions import ValueWrongType
from midealan.message import MessageType


class TestMideaE1Device:
    """Test E1 device."""

    device: MideaE1Device

    @pytest.fixture(autouse=True)
    def _setup_device(self) -> None:
        """Set up E1 device."""
        self.device = MideaE1Device(
            name="Test Device",
            device_id=1,
            ip_address="192.168.1.100",
            port=6444,
            token="AA",
            key="BB",
            device_protocol=ProtocolVersion.V3,
            model="test_model",
            subtype=1,
            customize="test_customize",
        )

    def test_modes(self) -> None:
        """Test work modes are exposed without allowing mutation."""
        modes = self.device.modes
        assert modes[0x04] == "eco_wash"
        modes[0x04] = "Changed"
        assert self.device.modes[0x04] == "eco_wash"

    def test_build_query(self) -> None:
        """Test build query."""
        queries = self.device.build_query()
        assert len(queries) == 1
        assert isinstance(queries[0], MessageQuery)

    def test_set_work_mode(self) -> None:
        """Test setting a supported work mode."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_work_mode(0x04)

        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.mode == 0x04

    def test_set_work_mode_rejects_unknown_mode(self) -> None:
        """Test setting an unknown work mode."""
        with pytest.raises(ValueWrongType, match="Unsupported work mode"):
            self.device.set_work_mode(0x11)

    def test_start_work(self) -> None:
        """Test starting the currently selected work mode."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.start_work()

        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.mode == 0x04

    def test_start_work_door_auto_open(self) -> None:
        """Test starting with door auto-open."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.start_work(door_auto_open=True)

        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.door_auto_open is True

    def test_cancel_work(self) -> None:
        """Test cancelling the running program keeps the current mode."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.cancel_work()

        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.body == bytearray.fromhex("080104".ljust(76, "0"))

    def test_set_delayed_start(self) -> None:
        """Test a delayed start sends status order with the delay."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_delayed_start(0x04, 60, door_auto_open=True)

        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.body == bytearray.fromhex(
            "0802040000000001000000000001".ljust(76, "0"),
        )

    @pytest.mark.parametrize("minutes", [0, -1, 24 * 60 + 1])
    def test_set_delayed_start_rejects_delay(self, minutes: int) -> None:
        """Test a delayed start rejects out of range delays."""
        with pytest.raises(ValueWrongType, match="Delay must be"):
            self.device.set_delayed_start(0x04, minutes)

    def test_set_delayed_start_rejects_unknown_mode(self) -> None:
        """Test a delayed start rejects an unknown work mode."""
        with pytest.raises(ValueWrongType, match="Unsupported work mode"):
            self.device.set_delayed_start(0x11, 60)

    def test_set_delayed_start_rejects_neutral_mode(self) -> None:
        """Test a delayed start needs a work mode."""
        with pytest.raises(ValueWrongType, match="No work mode selected"):
            self.device.set_delayed_start(0x00, 60)

    def test_cancel_delayed_start(self) -> None:
        """Test cancelling a delayed start."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.cancel_delayed_start()

        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.body == bytearray.fromhex("080404".ljust(76, "0"))

    @pytest.mark.parametrize("mode", [None, 0, "neutral_gear"])
    def test_start_work_requires_selected_mode(self, mode: str | int | None) -> None:
        """Test starting requires a non-neutral selected mode."""
        self.device._attributes[DeviceAttributes.mode] = mode
        with pytest.raises(ValueWrongType, match="No work mode selected"):
            self.device.start_work()

    def test_start_work_rejects_invalid_mode_type(self) -> None:
        """Test starting rejects an invalid stored mode."""
        self.device._attributes[DeviceAttributes.mode] = 4
        with pytest.raises(ValueWrongType, match="Invalid work mode"):
            self.device.start_work()

    @staticmethod
    def _message(message_type: MessageType, body: bytearray) -> bytes:
        header = bytearray(
            [0xAA, *([0x00] * 7), ProtocolVersion.V1, message_type],
        )
        crc = bytearray([0x00])
        return bytes(header + body + crc)

    def test_process_message_maps_status_progress_and_mode(self) -> None:
        """Test process message maps status, progress and mode via lookup tables."""
        body = bytearray(40)
        body[1] = 0x03  # status Running
        body[2] = 0x04  # mode ECO Wash
        body[9] = 0x03  # progress Rinse
        new_status = self.device.process_message(
            self._message(MessageType.query, body),
        )
        assert self.device.attributes[DeviceAttributes.status] == "running"
        assert self.device.attributes[DeviceAttributes.mode] == "eco_wash"
        assert self.device.attributes[DeviceAttributes.progress] == "rinse"
        assert new_status[DeviceAttributes.status.value] == "running"

    def test_process_message_unknown_status_mode_and_progress(self) -> None:
        """Test process message returns None for unmapped lookup values."""
        body = bytearray(40)
        body[1] = 0xFF  # unknown status
        body[2] = 0xFF  # unknown mode
        body[9] = 0xFF  # out-of-range progress
        self.device.process_message(self._message(MessageType.query, body))
        assert self.device.attributes[DeviceAttributes.status] is None
        assert self.device.attributes[DeviceAttributes.mode] is None
        assert self.device.attributes[DeviceAttributes.progress] is None

    def test_process_message_unhandled_message_type(self) -> None:
        """Test process message ignores unhandled message/body type combinations."""
        body = bytearray(40)
        new_status = self.device.process_message(
            self._message(MessageType.notify2, body),
        )
        assert new_status == {}

    def test_set_attribute_rejects_non_bool(self) -> None:
        """Test set attribute rejects non-bool values."""
        with pytest.raises(ValueWrongType, match="Expected bool"):
            self.device.set_attribute(DeviceAttributes.power.value, "on")

    def test_set_attribute_power(self) -> None:
        """Test set attribute power sends a power message."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.power.value, True)
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessagePower)
        assert message.power is True

    def test_set_attribute_child_lock(self) -> None:
        """Test set attribute child lock sends a lock message."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.child_lock.value, True)
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageLock)
        assert message.lock is True

    def test_set_attribute_storage(self) -> None:
        """Test set attribute storage sends a storage message."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.storage.value, True)
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageStorage)
        assert message.storage is True

    def test_set_attribute_unknown_attribute_is_noop(self) -> None:
        """Test set attribute with an unsupported attribute sends nothing."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.uv.value, True)
        mock_build_send.assert_not_called()

    def test_set_attribute_mode_starts_program(self) -> None:
        """Test writing mode through set_attribute starts the program."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.mode.value, "eco_wash")
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.work_status == 0x03
        assert message.mode == 0x04

    def test_set_attribute_mode_by_code(self) -> None:
        """Test writing a mode code through set_attribute."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.mode.value, 0x04)
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.mode == 0x04

    def test_set_attribute_status_cancel(self) -> None:
        """Test writing status cancel through set_attribute."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.status.value, "cancel")
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.body == bytearray.fromhex("080104".ljust(76, "0"))

    def test_set_attribute_status_running_starts_work(self) -> None:
        """Test status running/work starts the selected program."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.status.value, "running")
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.work_status == 0x03
        assert message.mode == 0x04

    def test_set_attribute_status_order_uses_stored_delay(self) -> None:
        """Test status order sends a delayed start with the stored delay."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        self.device._attributes[DeviceAttributes.delay_minutes] = 60
        self.device._attributes[DeviceAttributes.door_auto_open] = True
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.status.value, "order")
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.body == bytearray.fromhex(
            "0802040000000001000000000001".ljust(76, "0"),
        )

    def test_set_attribute_status_cancel_order(self) -> None:
        """Test status cancel_order cancels a pending delayed start."""
        self.device._attributes[DeviceAttributes.mode] = "eco_wash"
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.status.value, "cancel_order")
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.body == bytearray.fromhex("080404".ljust(76, "0"))

    def test_set_attribute_status_unknown(self) -> None:
        """Test an unknown status trigger is rejected."""
        with pytest.raises(ValueWrongType, match="Unsupported status"):
            self.device.set_attribute(DeviceAttributes.status.value, "spin")

    def test_set_attribute_delay_minutes_stores_value(self) -> None:
        """Test delay_minutes is stored and reused by a later order."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.delay_minutes.value, 90)
        mock_build_send.assert_not_called()
        assert self.device.attributes[DeviceAttributes.delay_minutes.value] == 90

    def test_set_attribute_delay_minutes_rejects_out_of_range(self) -> None:
        """Test delay_minutes rejects out of range values."""
        with pytest.raises(ValueWrongType, match="Delay must be"):
            self.device.set_attribute(DeviceAttributes.delay_minutes.value, 0)

    def test_set_attribute_door_auto_open_stores_value(self) -> None:
        """Test door_auto_open is stored without sending a message."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_attribute(DeviceAttributes.door_auto_open.value, True)
        mock_build_send.assert_not_called()
        assert self.device.attributes[DeviceAttributes.door_auto_open.value] is True

    def test_set_work_mode_by_name(self) -> None:
        """Test set_work_mode accepts a mode name."""
        with patch.object(self.device, "build_send") as mock_build_send:
            self.device.set_work_mode("eco_wash")
        message = mock_build_send.call_args.args[0]
        assert isinstance(message, MessageWork)
        assert message.mode == 0x04

    def test_set_work_mode_rejects_unknown_name(self) -> None:
        """Test set_work_mode rejects an unknown mode name."""
        with pytest.raises(ValueWrongType, match="Unsupported work mode"):
            self.device.set_work_mode("spin")
