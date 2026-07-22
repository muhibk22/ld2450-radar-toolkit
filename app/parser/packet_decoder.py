"""
Packet Decoder supporting both Binary LD2450 Frames and ASCII Serial Stream Text Lines.
"""

import struct
import time
import re
from typing import List, Dict
from ..models.target import Target
from ..models.packet import Packet
from ..config import MAX_TARGETS, FRAME_HEADER, FRAME_FOOTER

class PacketDecoder:
    """
    Decodes binary LD2450 protocol frames OR ASCII text stream lines into Target and Packet objects.
    """

    ASCII_REGEX = re.compile(
        r"Target\s+(\d+)\s*\|\s*Valid:\s*(\d+)\s*\|\s*X:\s*(-?\d+)\s*mm\s*\|\s*Y:\s*(-?\d+)\s*mm\s*\|\s*Speed:\s*(-?\d+)\s*(?:cm/s|mm/s)\s*\|\s*Resolution:\s*(\d+)",
        re.IGNORECASE
    )

    def __init__(self):
        self.sequence_counter = 0

    @staticmethod
    def _decode_ld2450_int16(val: int) -> float:
        is_negative = bool(val & 0x8000)
        magnitude = val & 0x7FFF
        return -float(magnitude) if is_negative else float(magnitude)

    def decode(self, raw_frame: bytes) -> Packet:
        self.sequence_counter += 1
        now = time.time()

        # Check if ASCII target text line
        if raw_frame.startswith(b"Target "):
            return self._decode_ascii_line(raw_frame, now)

        # Binary Frame Decoder
        return self._decode_binary_frame(raw_frame, now)

    def _decode_ascii_line(self, raw_frame: bytes, now: float) -> Packet:
        text = raw_frame.decode("utf-8", errors="ignore").strip()
        match = self.ASCII_REGEX.search(text)
        targets: List[Target] = []

        if match:
            t_id = int(match.group(1)) - 1  # 1-indexed to 0-indexed (Slot 0, 1, 2)
            t_valid = int(match.group(2)) == 1
            t_x = float(match.group(3))
            t_y = float(match.group(4))
            t_speed = float(match.group(5)) * 10.0  # cm/s to mm/s
            t_res = float(match.group(6))

            target = Target(
                id=f"Target {t_id}",
                raw_id=t_id,
                x=t_x,
                y=t_y,
                speed=t_speed,
                distance_resolution=t_res,
                valid=t_valid
            )
            targets.append(target)

            return Packet(
                sequence_id=self.sequence_counter,
                timestamp=now,
                raw_bytes=raw_frame,
                payload_bytes=raw_frame,
                targets=targets,
                header_valid=True,
                footer_valid=True,
                valid=True,
                unknown_bytes={"ASCII Log": text}
            )

        return Packet(
            sequence_id=self.sequence_counter,
            timestamp=now,
            raw_bytes=raw_frame,
            valid=False,
            corrupt_reason="Invalid ASCII text format"
        )

    def _decode_binary_frame(self, raw_frame: bytes, now: float) -> Packet:
        targets: List[Target] = []

        header_valid = raw_frame.startswith(FRAME_HEADER) or raw_frame.startswith(bytes([0xAA, 0xFF]))
        footer_valid = raw_frame.endswith(FRAME_FOOTER) or len(raw_frame) >= 14

        if len(raw_frame) < 14:
            return Packet(
                sequence_id=self.sequence_counter,
                timestamp=now,
                raw_bytes=raw_frame,
                header_valid=header_valid,
                footer_valid=footer_valid,
                valid=False,
                corrupt_reason="Frame boundary check failed or invalid length"
            )

        payload = raw_frame[4:-2] if len(raw_frame) >= 6 else raw_frame

        # Decode up to 3 targets if payload permits
        for i in range(MAX_TARGETS):
            offset = i * 8
            if offset + 8 > len(payload):
                break

            x_raw, y_raw, speed_raw, dist_res_raw = struct.unpack_from("<HHHH", payload, offset)

            # LD2450 Protocol Decoding:
            # X coordinate: Bit 15 is sign bit (0 = Right +X, 1 = Left -X)
            x_mm = -float(x_raw & 0x7FFF) if (x_raw & 0x8000) else float(x_raw & 0x7FFF)

            # Y coordinate: Depth distance ahead in front of radar (ALWAYS POSITIVE +Y)
            y_mm = float(y_raw & 0x7FFF)

            # Speed: Bit 15 is sign bit (0 = approaching, 1 = receding), unit cm/s -> mm/s
            speed_mms = (-float(speed_raw & 0x7FFF) if (speed_raw & 0x8000) else float(speed_raw & 0x7FFF)) * 10.0

            # Target is valid ONLY if Distance Resolution (RCS) > 0 and Depth Y >= 200 mm (0.2m)
            # HARDWARE LIMITS: We strictly filter targets outside maximum physical bounds (8m, 10m/s).
            # Wall socket power supplies inject noise into the RF front-end, causing the LD2450 to
            # hallucinate "ghost" targets at 30+ meters moving at 100+ m/s. This filter drops them instantly.
            is_valid = (
                (dist_res_raw > 0) and 
                (200.0 <= y_mm <= 8000.0) and 
                (abs(x_mm) <= 8000.0) and 
                (abs(speed_mms) <= 10000.0)
            )

            target = Target(
                id=f"Target {i}",
                raw_id=i,
                x=x_mm,
                y=y_mm,
                speed=speed_mms,
                distance_resolution=float(dist_res_raw),
                valid=is_valid
            )
            targets.append(target)

        unknown_bytes_map: Dict[str, str] = {}
        for idx, b in enumerate(raw_frame):
            if idx not in range(4, 28) and idx not in (0, 1, 2, 3, len(raw_frame)-2, len(raw_frame)-1):
                unknown_bytes_map[f"Unknown Byte {idx}"] = f"0x{b:02X}"

        return Packet(
            sequence_id=self.sequence_counter,
            timestamp=now,
            raw_bytes=raw_frame,
            payload_bytes=payload,
            targets=targets,
            header_valid=header_valid,
            footer_valid=footer_valid,
            valid=True,
            unknown_bytes=unknown_bytes_map
        )
