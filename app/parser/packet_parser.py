"""
Stream Synchronizer and Live Packet Parser for LD2450 Protocol Explorer.
Supports Dual Modes:
1. Binary LD2450 Frames (AA FF 03 00 ... 55 CC)
2. ASCII Text Stream (Target %d | Valid: %d | X: %d mm | Y: %d mm ...)
"""

import time
import re
from typing import List, Tuple
from ..config import FRAME_HEADER, FRAME_FOOTER
from ..utils.logger import setup_logger

logger = setup_logger("packet_parser")

KNOWN_HEADERS = [
    bytes([0xAA, 0xFF, 0x03, 0x00]),  # 3-target reporting frame (30B)
    bytes([0xAA, 0xFF, 0x02, 0x00]),  # 2-target reporting frame (22B)
    bytes([0xAA, 0xFF, 0x01, 0x00]),  # 1-target reporting frame (14B)
    bytes([0xFD, 0xFC, 0xFB, 0xFA]),  # Config/Command response header
    bytes([0xAA, 0xFF]),              # Generic 2-byte AA FF prefix
]

class PacketParser:
    """
    Dual-mode stream parser handling both raw binary protocol frames and ASCII text streams.
    """

    def __init__(self):
        self.buffer = bytearray()
        self.total_packets_received = 0
        self.corrupt_packets = 0
        self.dropped_packets = 0
        self.sync_failures = 0
        
        self._last_stats_time = time.time()
        self._packets_in_interval = 0
        self.packets_per_second = 0.0

        self._in_unaligned_state = False
        self._unaligned_bytes_since_log = 0

    def parse_stream(self, data: bytes) -> Tuple[List[bytes], bytes]:
        """
        Processes incoming byte stream and extracts binary frames or ASCII text packet lines.
        Returns (frames, unaligned_bytes).
        """
        self.buffer.extend(data)
        frames: List[bytes] = []
        unaligned_bytes = bytearray()

        while len(self.buffer) > 0:
            # Check for ASCII text stream first (lines starting with 'Target ' or '---')
            if b"Target " in self.buffer or b"----" in self.buffer:
                ascii_frames, consumed = self._extract_ascii_lines(self.buffer)
                if ascii_frames:
                    frames.extend(ascii_frames)
                    self.total_packets_received += len(ascii_frames)
                    self._packets_in_interval += len(ascii_frames)
                    self.buffer = self.buffer[consumed:]
                    self._in_unaligned_state = False
                    continue

            # Check for Binary header match
            if len(self.buffer) >= 4:
                header_index, matched_hdr = self._find_header(self.buffer)

                if header_index == -1:
                    # No binary header found and no complete ASCII lines
                    if len(self.buffer) > 256:
                        discarded_len = len(self.buffer) - 128
                        unaligned = self.buffer[:discarded_len]
                        unaligned_bytes.extend(unaligned)
                        self.dropped_packets += len(unaligned)
                        self.buffer = self.buffer[discarded_len:]
                    break

                if header_index > 0:
                    # Noise bytes before binary header
                    noise = self.buffer[:header_index]
                    unaligned_bytes.extend(noise)
                    self.sync_failures += 1
                    self.dropped_packets += header_index
                    self.buffer = self.buffer[header_index:]

                extracted_frame, bytes_consumed = self._extract_binary_frame(self.buffer)

                if extracted_frame is not None:
                    frames.append(extracted_frame)
                    self.total_packets_received += 1
                    self._packets_in_interval += 1
                    self._in_unaligned_state = False
                    self.buffer = self.buffer[bytes_consumed:]
                elif bytes_consumed > 0:
                    self.corrupt_packets += 1
                    self.buffer = self.buffer[bytes_consumed:]
                else:
                    break
            else:
                break

        # Calculate live Packets/sec
        now = time.time()
        elapsed = now - self._last_stats_time
        if elapsed >= 1.0:
            self.packets_per_second = self._packets_in_interval / elapsed
            self._packets_in_interval = 0
            self._last_stats_time = now

        return frames, bytes(unaligned_bytes)

    def _extract_ascii_lines(self, buf: bytearray) -> Tuple[List[bytes], int]:
        """Extracts complete ASCII target text lines up to newline."""
        frames: List[bytes] = []
        consumed = 0

        while True:
            newline_idx = buf.find(b"\n", consumed)
            if newline_idx == -1:
                break
            
            line = bytes(buf[consumed:newline_idx+1]).strip()
            line_len = (newline_idx + 1) - consumed

            if line.startswith(b"Target ") or line.startswith(b"---"):
                if line.startswith(b"Target "):
                    frames.append(line)
                consumed = newline_idx + 1
            else:
                # Non-target line
                consumed = newline_idx + 1

        return frames, consumed

    def _find_header(self, buf: bytearray) -> Tuple[int, bytes | None]:
        best_idx = -1
        best_hdr = None
        for hdr in KNOWN_HEADERS:
            idx = buf.find(hdr)
            if idx != -1:
                if best_idx == -1 or idx < best_idx:
                    best_idx = idx
                    best_hdr = hdr
        return best_idx, best_hdr

    def _extract_binary_frame(self, buf: bytearray) -> Tuple[bytes | None, int]:
        if buf.startswith(bytes([0xAA, 0xFF, 0x03, 0x00])):
            if len(buf) < 30:
                return None, 0
            if buf[28:30] == FRAME_FOOTER:
                return bytes(buf[:30]), 30
            return None, 4

        elif buf.startswith(bytes([0xAA, 0xFF, 0x02, 0x00])):
            if len(buf) < 22:
                return None, 0
            if buf[20:22] == FRAME_FOOTER:
                return bytes(buf[:22]), 22
            return None, 4

        elif buf.startswith(bytes([0xAA, 0xFF, 0x01, 0x00])):
            if len(buf) < 14:
                return None, 0
            if buf[12:14] == FRAME_FOOTER:
                return bytes(buf[:14]), 14
            return None, 4

        elif buf.startswith(bytes([0xAA, 0xFF])):
            footer_idx = buf.find(FRAME_FOOTER, 4)
            if footer_idx != -1 and footer_idx + 2 <= 64:
                frame_len = footer_idx + 2
                if len(buf) >= frame_len:
                    return bytes(buf[:frame_len]), frame_len
            if len(buf) >= 64:
                return None, 2
            return None, 0

        return None, 1

    def get_statistics(self) -> dict:
        return {
            "packets_total": self.total_packets_received,
            "packets_per_sec": round(self.packets_per_second, 1),
            "corrupt_packets": self.corrupt_packets,
            "dropped_packets": self.dropped_packets,
            "sync_failures": self.sync_failures,
        }
