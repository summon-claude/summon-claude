"""Provider abstractions for chat platforms."""

from .base import ChannelRef, ChatProvider, MessageRef
from .slack import SlackChatProvider

__all__ = ["ChannelRef", "ChatProvider", "MessageRef", "SlackChatProvider"]
