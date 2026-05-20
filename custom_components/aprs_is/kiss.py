"""KISS TNC framing and AX.25 UI frame encode/decode — no third-party dependencies."""
from __future__ import annotations

# KISS special bytes
FEND  = 0xC0  # frame delimiter
FESC  = 0xDB  # escape character
TFEND = 0xDC  # FEND within data (follows FESC)
TFESC = 0xDD  # FESC within data (follows FESC)

# AX.25 UI frame constants
_AX25_CTRL_UI = 0x03
_AX25_PID_NO_L3 = 0xF0


def _parse_callsign(callsign: str) -> tuple[str, int]:
    """Split 'CALL-N' into ('CALL', N). SSID defaults to 0."""
    parts = callsign.upper().split("-", 1)
    try:
        ssid = int(parts[1]) if len(parts) == 2 else 0
    except ValueError:
        ssid = 0
    return parts[0], ssid


def encode_ax25_address(callsign: str, ssid: int, last: bool) -> bytes:
    """Encode a single AX.25 address field (7 bytes)."""
    call = callsign.upper()[:6].ljust(6)
    data = bytearray(ord(c) << 1 for c in call)
    data.append(0x60 | ((ssid & 0x0F) << 1) | (0x01 if last else 0x00))
    return bytes(data)


def decode_ax25_address(data: bytes) -> tuple[str, int, bool]:
    """Decode a 7-byte AX.25 address. Returns (callsign, ssid, is_last)."""
    call = "".join(chr(b >> 1) for b in data[:6]).strip()
    ssid_byte = data[6]
    ssid = (ssid_byte >> 1) & 0x0F
    is_last = bool(ssid_byte & 0x01)
    return call, ssid, is_last


def encode_ax25_ui(
    source: str,
    destination: str,
    digipeaters: list[str],
    info: bytes,
) -> bytes:
    """Build an AX.25 UI frame for APRS."""
    dst_call, dst_ssid = _parse_callsign(destination)
    src_call, src_ssid = _parse_callsign(source)

    frame = bytearray()
    frame += encode_ax25_address(dst_call, dst_ssid, last=False)

    if digipeaters:
        frame += encode_ax25_address(src_call, src_ssid, last=False)
        for i, digi in enumerate(digipeaters):
            digi_call, digi_ssid = _parse_callsign(digi)
            frame += encode_ax25_address(digi_call, digi_ssid, last=(i == len(digipeaters) - 1))
    else:
        frame += encode_ax25_address(src_call, src_ssid, last=True)

    frame.append(_AX25_CTRL_UI)
    frame.append(_AX25_PID_NO_L3)
    frame += info
    return bytes(frame)


def encode_kiss_frame(ax25_bytes: bytes) -> bytes:
    """Wrap AX.25 bytes in a KISS data frame (port 0)."""
    escaped = bytearray()
    for b in ax25_bytes:
        if b == FEND:
            escaped += bytes([FESC, TFEND])
        elif b == FESC:
            escaped += bytes([FESC, TFESC])
        else:
            escaped.append(b)
    return bytes([FEND, 0x00]) + bytes(escaped) + bytes([FEND])


def parse_ax25_frame(data: bytes) -> dict | None:
    """Parse raw AX.25 bytes into address + info fields.

    Returns {"source", "destination", "digipeaters", "info"} or None on error.
    Only accepts UI frames (ctrl=0x03) with APRS PID (0xF0).
    """
    if len(data) < 16:  # 2 addresses min + ctrl + pid
        return None

    try:
        addresses: list[tuple[str, int]] = []
        offset = 0
        while offset + 7 <= len(data):
            call, ssid, is_last = decode_ax25_address(data[offset:offset + 7])
            addresses.append((call, ssid))
            offset += 7
            if is_last:
                break
        else:
            return None  # end-of-address bit never set

        if len(addresses) < 2:
            return None

        if offset + 2 > len(data):
            return None

        ctrl = data[offset]
        pid  = data[offset + 1]
        if ctrl != _AX25_CTRL_UI or pid != _AX25_PID_NO_L3:
            return None

        info = data[offset + 2:]

        dst_call, dst_ssid = addresses[0]
        src_call, src_ssid = addresses[1]
        destination = f"{dst_call}-{dst_ssid}" if dst_ssid else dst_call
        source      = f"{src_call}-{src_ssid}" if src_ssid else src_call
        digipeaters = [
            f"{c}-{s}" if s else c for c, s in addresses[2:]
        ]

        return {
            "source":      source,
            "destination": destination,
            "digipeaters": digipeaters,
            "info":        info,
        }
    except Exception:
        return None
