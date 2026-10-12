"""Midea lan E1 message."""

from midealan.const import DeviceType
from midealan.message import (
    ListTypes,
    MessageBody,
    MessageRequest,
    MessageResponse,
    MessageType,
)

BRIGTH_BYTE = 24
STORAGE_REMAINING_BYTE = 18
HUMIDITY_BYTE = 33
CONTROL_BODY_LENGTH = 37  # 38 bytes with the body type, as in Midea's Lua

WORK_STATUS_POWER_OFF = 0x00
WORK_STATUS_CANCEL = 0x01
WORK_STATUS_ORDER = 0x02
WORK_STATUS_WORK = 0x03
WORK_STATUS_CANCEL_ORDER = 0x04

# Work command offsets, after the body type byte
WORK_DELAY_HOURS_INDEX = 6
WORK_DELAY_MINUTES_INDEX = 7
WORK_DOOR_AUTO_OPEN_INDEX = 12

# Status reply offsets and flags
DOOR_AUTO_OPEN_FLAG = 0x40
DELAY_HOURS_BYTE = 7
DELAY_MINUTES_BYTE = 8


class MessageE1Base(MessageRequest):
    """E1 message base."""

    def __init__(
        self,
        protocol_version: int,
        message_type: MessageType,
        body_type: ListTypes,
    ) -> None:
        """Initialize E1 message base."""
        super().__init__(
            device_type=DeviceType.E1,
            protocol_version=protocol_version,
            message_type=message_type,
            body_type=body_type,
        )

    @property
    def _body(self) -> bytearray:
        raise NotImplementedError


class MessagePower(MessageE1Base):
    """E1 message power."""

    def __init__(self, protocol_version: int) -> None:
        """Initialize E1 message power."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.set,
            body_type=ListTypes.X08,
        )
        self.power = False

    @property
    def _body(self) -> bytearray:
        power = 0x01 if self.power else 0x00
        return bytearray([power, 0x00, 0x00, 0x00])


class MessageWork(MessageE1Base):
    """E1 message work.

    Layout from Midea's T_0000_E1_7600002B_2024042301.lua: byte 1 work status,
    byte 2 mode, bytes 7-8 delay (hours, minutes) when ordering, byte 13 door
    auto-open.
    """

    def __init__(self, protocol_version: int) -> None:
        """Initialize E1 message work."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.set,
            body_type=ListTypes.X08,
        )
        self.work_status = WORK_STATUS_WORK
        self.mode = 0
        self.delay_minutes = 0
        self.door_auto_open = False

    @property
    def _body(self) -> bytearray:
        body = bytearray(CONTROL_BODY_LENGTH)
        body[0] = self.work_status
        body[1] = self.mode
        if self.work_status == WORK_STATUS_ORDER:
            (
                body[WORK_DELAY_HOURS_INDEX],
                body[WORK_DELAY_MINUTES_INDEX],
            ) = divmod(self.delay_minutes, 60)
        body[WORK_DOOR_AUTO_OPEN_INDEX] = 0x01 if self.door_auto_open else 0x00
        return body


class MessageLock(MessageE1Base):
    """E1 message lock."""

    def __init__(self, protocol_version: int) -> None:
        """Initialize E1 message lock."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.set,
            body_type=ListTypes.X83,
        )
        self.lock = False

    @property
    def _body(self) -> bytearray:
        lock = 0x03 if self.lock else 0x04
        return bytearray([lock]) + bytearray([0x00] * 36)


class MessageStorage(MessageE1Base):
    """E1 message storage."""

    def __init__(self, protocol_version: int) -> None:
        """Initialize E1 message storage."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.set,
            body_type=ListTypes.X81,
        )
        self.storage = False

    @property
    def _body(self) -> bytearray:
        storage = 0x01 if self.storage else 0x00
        return (
            bytearray([0x00, 0x00, 0x00, storage])
            + bytearray([0xFF] * 6)
            + bytearray([0x00] * 27)
        )


class MessageQuery(MessageE1Base):
    """E1 message query."""

    def __init__(self, protocol_version: int) -> None:
        """Initialize E1 message query."""
        super().__init__(
            protocol_version=protocol_version,
            message_type=MessageType.query,
            body_type=ListTypes.X00,
        )

    @property
    def _body(self) -> bytearray:
        return bytearray([])


class E1GeneralMessageBody(MessageBody):
    """E1 message general body."""

    def __init__(self, body: bytearray) -> None:
        """Initialize E1 message general body."""
        super().__init__(body)
        self.power = body[1] > 0
        self.status = body[1]
        self.mode = body[2]
        self.additional = body[3]
        self.door = (body[5] & 0x01) == 0  # 0 - open, 1 - close
        self.rinse_aid = (body[5] & 0x02) > 0  # 0 - enough, 1 - shortage
        self.salt = (body[5] & 0x04) > 0  # 0 - enough, 1 - shortage
        start_pause = (body[5] & 0x08) > 0  # operator
        if start_pause:
            self.start = True
        elif self.status in [2, 3]:
            self.start = False
        self.lack_bright = (body[5] & 0x02) > 0
        self.lack_softwater = (body[5] & 0x04) > 0
        self.diyflag = (body[4] & 0x08) > 0
        self.child_lock = (body[5] & 0x10) > 0
        self.uv = (body[4] & 0x2) > 0
        self.door_auto_open = (body[4] & DOOR_AUTO_OPEN_FLAG) > 0
        # Delay left until a delayed start, only meaningful in status Delay
        self.delay_remaining = (
            body[DELAY_HOURS_BYTE] * 60 + body[DELAY_MINUTES_BYTE]
            if self.status == WORK_STATUS_ORDER
            else 0
        )
        self.dry = (body[4] & 0x10) > 0
        self.dry_status = (body[4] & 0x20) > 0
        self.storage = (body[5] & 0x20) > 0  # airswitch
        self.storage_status = (body[5] & 0x40) > 0  # airstatus
        self.time_remaining = body[6]
        if len(body) > HUMIDITY_BYTE:
            _left_time_high = body[32]
            if _left_time_high:
                self.time_remaining = _left_time_high * 256 + self.time_remaining
        self.progress = body[9]  # washStage
        self.storage_set_time = (  # airSetTime    Hour
            body[17] if len(body) > STORAGE_REMAINING_BYTE else False
        )
        self.storage_remaining = (  # airLeftTime    Hour
            body[18] if len(body) > STORAGE_REMAINING_BYTE else False
        )
        self.temperature = body[11]
        self.humidity = body[33] if len(body) > HUMIDITY_BYTE else None
        self.doorswitch = (body[5] & 0x01) > 0
        self.dryswitch = (body[5] & 0x10) > 0
        self.drystatus = (body[5] & 0x20) > 0
        self.waterswitch = (body[4] & 0x04) > 0
        self.water_lack = (body[5] & 0x80) > 0
        self.dry_step_switch = (body[4] & 0x01) > 0
        self.uv_switch = (body[4] & 0x02) > 0
        self.error_code = body[10]
        self.softwater = body[13]
        self.wrong_operation = body[16]
        self.bright = body[24] if len(body) > BRIGTH_BYTE else None


class MessageE1Response(MessageResponse):
    """E1 message response."""

    def __init__(self, message: bytes) -> None:
        """Initialize E1 message response."""
        super().__init__(bytearray(message))
        if (
            self.message_type == MessageType.set
            and 0 <= self.body_type <= ListTypes.X07
        ) or (
            self.message_type in [MessageType.query, MessageType.notify1]
            and self.body_type == 0
        ):
            self.set_body(E1GeneralMessageBody(super().body))
        self.set_attr()
