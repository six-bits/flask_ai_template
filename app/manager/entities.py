"""Domain entities defining the Service <-> Manager contract for the Chat Service."""

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass
class JoinRoomRequestEntity:
    """Request entity to join a room."""
    room_id: str
    user_id: str


@dataclass
class JoinRoomResponseEntity:
    """Response entity after joining a room."""
    room_id: str
    user_id: str
    status: str = "joined"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SendMessageRequestEntity:
    """Request entity to send a message."""
    room_id: str
    user_id: str
    content: str


@dataclass
class MessageResponseEntity:
    """Response entity for a message."""
    id: int
    room_id: str
    user_id: str
    content: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GetMessagesRequestEntity:
    """Request entity to retrieve messages from a room."""
    room_id: str
    user_id: str


@dataclass
class LeaveRoomRequestEntity:
    """Request entity to leave a room."""
    room_id: str
    user_id: str


@dataclass
class LeaveRoomResponseEntity:
    """Response entity after leaving a room."""
    room_id: str
    user_id: str
    status: str = "left"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
