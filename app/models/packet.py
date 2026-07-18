"""
Packet Data Model for LD2450 Protocol Explorer.
"""

from dataclasses import dataclass, field
import time
from typing import List, Dict
from .target import Target

@dataclass
class Packet:
    """
    Represents a raw and decoded LD2450 protocol packet.
    """
    sequence_id: int
    timestamp: float = field(default_factory=time.time)
    raw_bytes: bytes = b""
    payload_bytes: bytes = b""
    targets: List[Target] = field(default_factory=list)
    header_valid: bool = True
    footer_valid: bool = True
    valid: bool = True
    corrupt_reason: str = ""
    
    # Map of unknown byte index -> hex string value (e.g. {"Unknown Byte 28": "0x00"})
    unknown_bytes: Dict[str, str] = field(default_factory=dict)

    @property
    def hex_string(self) -> str:
        """Formatted space-separated HEX string representation of raw packet."""
        return " ".join(f"{b:02X}" for b in self.raw_bytes)

    @property
    def size_bytes(self) -> int:
        return len(self.raw_bytes)
