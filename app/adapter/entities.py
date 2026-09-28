"""Adapter entities defining the data contract between Manager and Adapter layers."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserRecordEntity:
    """Storage entity representing an available user in UserAdapter."""
    user_id: str
    created_at: str  # ISO 8601 UTC timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert user record to dictionary."""
        return asdict(self)


@dataclass
class RoomMembershipRecordEntity:
    """Storage entity representing a user's membership in a chat room."""
    room_id: str
    user_id: str
    joined_at: str  # ISO 8601 UTC timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert membership record to dictionary."""
        return asdict(self)


@dataclass
class MessageRecordEntity:
    """Storage entity representing a message posted in a chat room."""
    room_id: str
    user_id: str
    content: str
    timestamp: str  # ISO 8601 UTC timestamp
    id: Optional[int] = None  # Assigned by ChatAdapter upon persistence

    def to_dict(self) -> Dict[str, Any]:
        """Convert message record to dictionary."""
        return asdict(self)


@dataclass
class ChatRoomRecordEntity:
    """Storage aggregate entity representing a chat room, its members, and messages."""
    room_id: str
    created_at: str  # ISO 8601 UTC timestamp
    # Key: user_id -> RoomMembershipRecordEntity for O(1) membership checks
    memberships: Dict[str, RoomMembershipRecordEntity] = field(default_factory=dict)
    # Ordered message history
    messages: List[MessageRecordEntity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert chat room aggregate to dictionary."""
        return {
            "room_id": self.room_id,
            "created_at": self.created_at,
            "memberships": {uid: m.to_dict() for uid, m in self.memberships.items()},
            "messages": [msg.to_dict() for msg in self.messages],
        }


@dataclass
class GreetingRecordEntity:
    """Storage/persistence entity for greeting records in the adapter."""
    name: str
    salutation: str
    message: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert adapter entity to dictionary."""
        return asdict(self)
