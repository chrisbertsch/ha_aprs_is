"""Tests for the KISS framing and AX.25 UI codec (kiss.py)."""
import pytest

from custom_components.aprs_is.kiss import (
    FEND,
    FESC,
    TFEND,
    TFESC,
    _parse_callsign,
    decode_ax25_address,
    encode_ax25_address,
    encode_ax25_ui,
    encode_kiss_frame,
    parse_ax25_frame,
)


# ---------------------------------------------------------------------------
# _parse_callsign
# ---------------------------------------------------------------------------

class TestParseCallsign:
    def test_no_ssid(self):
        assert _parse_callsign("KE5YIM") == ("KE5YIM", 0)

    def test_with_ssid(self):
        assert _parse_callsign("KE5YIM-9") == ("KE5YIM", 9)

    def test_ssid_zero_explicit(self):
        assert _parse_callsign("KE5YIM-0") == ("KE5YIM", 0)

    def test_lowercase_normalised(self):
        assert _parse_callsign("ke5yim-3") == ("KE5YIM", 3)

    def test_invalid_ssid_falls_back_to_zero(self):
        assert _parse_callsign("KE5YIM-X") == ("KE5YIM", 0)

    def test_destination_no_ssid(self):
        assert _parse_callsign("APZHA") == ("APZHA", 0)

    def test_wide_digi(self):
        assert _parse_callsign("WIDE1-1") == ("WIDE1", 1)

    def test_nogate(self):
        # NOGATE has no SSID
        assert _parse_callsign("NOGATE") == ("NOGATE", 0)


# ---------------------------------------------------------------------------
# encode_ax25_address / decode_ax25_address
# ---------------------------------------------------------------------------

class TestAx25Address:
    def test_encode_is_7_bytes(self):
        assert len(encode_ax25_address("KE5YIM", 0, last=False)) == 7

    def test_chars_are_left_shifted(self):
        data = encode_ax25_address("KE5YIM", 0, last=False)
        assert data[0] == ord("K") << 1
        assert data[1] == ord("E") << 1

    def test_short_callsign_padded_with_spaces(self):
        data = encode_ax25_address("W1AB", 0, last=False)
        # bytes 4 and 5 should be space (0x20) shifted left → 0x40
        assert data[4] == 0x40
        assert data[5] == 0x40

    def test_last_bit_set_when_last_true(self):
        data = encode_ax25_address("KE5YIM", 0, last=True)
        assert data[6] & 0x01 == 1

    def test_last_bit_clear_when_last_false(self):
        data = encode_ax25_address("KE5YIM", 0, last=False)
        assert data[6] & 0x01 == 0

    def test_ssid_encoded_in_byte6(self):
        data = encode_ax25_address("KE5YIM", 9, last=False)
        ssid = (data[6] >> 1) & 0x0F
        assert ssid == 9

    def test_roundtrip_no_ssid(self):
        encoded = encode_ax25_address("KE5YIM", 0, last=True)
        call, ssid, is_last = decode_ax25_address(encoded)
        assert call == "KE5YIM"
        assert ssid == 0
        assert is_last is True

    def test_roundtrip_with_ssid(self):
        encoded = encode_ax25_address("W1ABC", 9, last=False)
        call, ssid, is_last = decode_ax25_address(encoded)
        assert call == "W1ABC"
        assert ssid == 9
        assert is_last is False

    def test_roundtrip_max_ssid(self):
        encoded = encode_ax25_address("KE5YIM", 15, last=True)
        call, ssid, is_last = decode_ax25_address(encoded)
        assert ssid == 15
        assert is_last is True

    def test_long_callsign_truncated_to_6(self):
        data = encode_ax25_address("TOOLONGCALL", 0, last=False)
        assert len(data) == 7
        call, _, _ = decode_ax25_address(data)
        assert call == "TOOLON"


# ---------------------------------------------------------------------------
# encode_ax25_ui
# ---------------------------------------------------------------------------

class TestEncodeAx25Ui:
    def _make_frame(self, src="KE5YIM-9", dst="APZHA", digis=None, info=b"test"):
        return encode_ax25_ui(src, dst, digis or [], info)

    def test_destination_first(self):
        frame = self._make_frame(src="KE5YIM", dst="APZHA")
        call, ssid, _ = decode_ax25_address(frame[:7])
        assert call == "APZHA"

    def test_source_second(self):
        frame = self._make_frame(src="KE5YIM", dst="APZHA")
        call, ssid, _ = decode_ax25_address(frame[7:14])
        assert call == "KE5YIM"
        assert ssid == 0

    def test_source_ssid_preserved(self):
        frame = self._make_frame(src="KE5YIM-9", dst="APZHA")
        _, ssid, _ = decode_ax25_address(frame[7:14])
        assert ssid == 9

    def test_no_digipeaters_source_is_last(self):
        frame = self._make_frame(digis=[])
        _, _, is_last = decode_ax25_address(frame[7:14])
        assert is_last is True

    def test_no_digipeaters_ctrl_pid_at_offset_14(self):
        frame = self._make_frame(digis=[])
        assert frame[14] == 0x03  # UI control
        assert frame[15] == 0xF0  # No-layer-3 PID

    def test_no_digipeaters_info_appended(self):
        frame = self._make_frame(digis=[], info=b"!hello")
        assert frame[16:] == b"!hello"

    def test_one_digipeater_source_not_last(self):
        frame = self._make_frame(digis=["WIDE1-1"])
        _, _, src_is_last = decode_ax25_address(frame[7:14])
        assert src_is_last is False

    def test_one_digipeater_digi_is_last(self):
        frame = self._make_frame(digis=["WIDE1-1"])
        call, ssid, is_last = decode_ax25_address(frame[14:21])
        assert call == "WIDE1"
        assert ssid == 1
        assert is_last is True

    def test_two_digipeaters_only_last_has_end_bit(self):
        frame = self._make_frame(digis=["WIDE1-1", "WIDE2-1"])
        _, _, d1_last = decode_ax25_address(frame[14:21])
        _, _, d2_last = decode_ax25_address(frame[21:28])
        assert d1_last is False
        assert d2_last is True

    def test_two_digipeaters_ctrl_at_correct_offset(self):
        frame = self._make_frame(digis=["WIDE1-1", "WIDE2-1"], info=b"data")
        # dest(7) + src(7) + digi1(7) + digi2(7) = 28
        assert frame[28] == 0x03
        assert frame[29] == 0xF0
        assert frame[30:] == b"data"

    def test_nogate_as_digipeater(self):
        frame = self._make_frame(digis=["WIDE1-1", "NOGATE"])
        call, ssid, is_last = decode_ax25_address(frame[21:28])
        assert call == "NOGATE"
        assert ssid == 0
        assert is_last is True

    def test_empty_info(self):
        frame = self._make_frame(digis=[], info=b"")
        # ctrl and pid present, nothing after
        assert frame[14] == 0x03
        assert frame[15] == 0xF0
        assert len(frame) == 16

    def test_aprs_info_payload(self):
        info = b"!3259.94N/09724.17W>Home Assistant"
        frame = self._make_frame(digis=["WIDE1-1", "WIDE2-1"], info=info)
        assert frame[30:] == info


# ---------------------------------------------------------------------------
# encode_kiss_frame
# ---------------------------------------------------------------------------

class TestEncodeKissFrame:
    def test_starts_and_ends_with_fend(self):
        frame = encode_kiss_frame(b"hello")
        assert frame[0] == FEND
        assert frame[-1] == FEND

    def test_type_byte_is_zero(self):
        frame = encode_kiss_frame(b"hello")
        assert frame[1] == 0x00

    def test_data_passes_through_unchanged(self):
        frame = encode_kiss_frame(b"hello")
        assert frame[2:-1] == b"hello"

    def test_fend_in_data_escaped(self):
        frame = encode_kiss_frame(bytes([FEND]))
        # FEND, 0x00, FESC, TFEND, FEND
        assert frame == bytes([FEND, 0x00, FESC, TFEND, FEND])

    def test_fesc_in_data_escaped(self):
        frame = encode_kiss_frame(bytes([FESC]))
        assert frame == bytes([FEND, 0x00, FESC, TFESC, FEND])

    def test_multiple_escapes(self):
        frame = encode_kiss_frame(bytes([FEND, FESC, 0x41]))
        # FEND, 0x00, FESC, TFEND, FESC, TFESC, 0x41, FEND
        assert frame == bytes([FEND, 0x00, FESC, TFEND, FESC, TFESC, 0x41, FEND])

    def test_empty_data(self):
        frame = encode_kiss_frame(b"")
        assert frame == bytes([FEND, 0x00, FEND])

    def test_normal_bytes_unmodified(self):
        data = bytes(range(0, 0xC0))  # all bytes below FEND
        frame = encode_kiss_frame(data)
        assert frame[2:-1] == data

    def test_high_bytes_not_special_pass_through(self):
        # 0xC1–0xDA and 0xDC–0xFF are not FEND or FESC — must not be escaped
        high = bytes(
            b for b in range(0xC1, 0x100) if b not in (0xC0, 0xDB)
        )
        frame = encode_kiss_frame(high)
        assert frame[2:-1] == high


# ---------------------------------------------------------------------------
# parse_ax25_frame
# ---------------------------------------------------------------------------

class TestParseAx25Frame:
    def _encode(self, src, dst, digis, info):
        return encode_ax25_ui(src, dst, digis, info)

    def test_roundtrip_no_digipeaters(self):
        raw = self._encode("KE5YIM-9", "APZHA", [], b"!test")
        result = parse_ax25_frame(raw)
        assert result is not None
        assert result["source"] == "KE5YIM-9"
        assert result["destination"] == "APZHA"
        assert result["digipeaters"] == []
        assert result["info"] == b"!test"

    def test_roundtrip_one_digipeater(self):
        raw = self._encode("KE5YIM-9", "APZHA", ["WIDE1-1"], b"data")
        result = parse_ax25_frame(raw)
        assert result["source"] == "KE5YIM-9"
        assert result["digipeaters"] == ["WIDE1-1"]

    def test_roundtrip_two_digipeaters(self):
        raw = self._encode("W1ABC", "APZHA", ["WIDE1-1", "WIDE2-1"], b"hello")
        result = parse_ax25_frame(raw)
        assert result["source"] == "W1ABC"
        assert result["digipeaters"] == ["WIDE1-1", "WIDE2-1"]
        assert result["info"] == b"hello"

    def test_nogate_in_path(self):
        raw = self._encode("KE5YIM-9", "APZHA", ["WIDE1-1", "NOGATE"], b"pos")
        result = parse_ax25_frame(raw)
        assert result["digipeaters"] == ["WIDE1-1", "NOGATE"]

    def test_destination_no_ssid(self):
        raw = self._encode("KE5YIM", "APZHA", [], b"x")
        result = parse_ax25_frame(raw)
        assert result["destination"] == "APZHA"

    def test_source_ssid_0_omitted(self):
        raw = self._encode("KE5YIM-0", "APZHA", [], b"x")
        result = parse_ax25_frame(raw)
        assert result["source"] == "KE5YIM"

    def test_aprs_info_payload_preserved(self):
        info = b"@011234z3259.94N/09724.17W_270/005g010t072h65b10152"
        raw = self._encode("KE5YIM-13", "APZHA", ["WIDE1-1"], info)
        result = parse_ax25_frame(raw)
        assert result["info"] == info

    def test_returns_none_when_too_short(self):
        assert parse_ax25_frame(b"\x00" * 10) is None

    def test_returns_none_on_empty(self):
        assert parse_ax25_frame(b"") is None

    def test_returns_none_on_non_ui_ctrl(self):
        raw = bytearray(self._encode("KE5YIM", "APZHA", [], b"x"))
        # ctrl byte is at offset 14 for no-digi frame; set to non-UI value
        raw[14] = 0x00
        assert parse_ax25_frame(bytes(raw)) is None

    def test_returns_none_on_wrong_pid(self):
        raw = bytearray(self._encode("KE5YIM", "APZHA", [], b"x"))
        raw[15] = 0x00
        assert parse_ax25_frame(bytes(raw)) is None

    def test_returns_none_when_end_of_address_never_set(self):
        # Build a frame but clear all end-of-address bits
        raw = bytearray(self._encode("KE5YIM", "APZHA", [], b"x"))
        raw[6]  &= 0xFE  # destination
        raw[13] &= 0xFE  # source
        assert parse_ax25_frame(bytes(raw)) is None

    def test_destination_with_nonzero_ssid_formatted(self):
        # encode_ax25_ui parses the destination SSID; parse_ax25_frame should
        # include it in the returned destination string
        raw = encode_ax25_ui("KE5YIM", "APZHA-1", [], b"x")
        result = parse_ax25_frame(raw)
        assert result is not None
        assert result["destination"] == "APZHA-1"

    def test_returns_none_when_ctrl_present_but_pid_missing(self):
        # Address block ends normally but only 1 byte remains (ctrl, no pid)
        raw = bytearray(self._encode("KE5YIM", "APZHA", [], b""))
        # frame is exactly 16 bytes; drop the last byte → 15 bytes,
        # so offset+2 (16) > len(data) (15)
        assert parse_ax25_frame(bytes(raw[:-1])) is None


# ---------------------------------------------------------------------------
# Full encode → KISS → unescape → parse round-trip
# ---------------------------------------------------------------------------

class TestFullRoundtrip:
    def _decode_kiss(self, frame: bytes) -> bytes:
        """Minimal KISS unescape (mirrors coordinator._handle_kiss_frame logic)."""
        assert frame[0] == FEND and frame[-1] == FEND
        raw = frame[1:-1]  # strip outer FENDs
        assert raw[0] == 0x00  # type byte
        data = bytearray()
        i = 1
        while i < len(raw):
            if raw[i] == FESC and i + 1 < len(raw):
                if raw[i + 1] == TFEND:
                    data.append(FEND)
                elif raw[i + 1] == TFESC:
                    data.append(FESC)
                i += 2
            else:
                data.append(raw[i])
                i += 1
        return bytes(data)

    def test_typical_aprs_position_packet(self):
        src = "KE5YIM-9"
        dst = "APZHA"
        digis = ["WIDE1-1", "WIDE2-1"]
        info = b"!3259.94N/09724.17W>Home Assistant"

        ax25 = encode_ax25_ui(src, dst, digis, info)
        kiss = encode_kiss_frame(ax25)
        recovered_ax25 = self._decode_kiss(kiss)
        result = parse_ax25_frame(recovered_ax25)

        assert result is not None
        assert result["source"] == src
        assert result["destination"] == dst
        assert result["digipeaters"] == digis
        assert result["info"] == info

    def test_packet_with_fend_byte_in_info(self):
        # Info containing 0xC0 must survive KISS escaping and unescaping
        info = bytes([0x21, FEND, 0x41])
        ax25 = encode_ax25_ui("W1ABC", "APZHA", [], info)
        kiss = encode_kiss_frame(ax25)
        recovered = self._decode_kiss(kiss)
        result = parse_ax25_frame(recovered)
        assert result["info"] == info

    def test_packet_with_fesc_byte_in_info(self):
        info = bytes([0x21, FESC, 0x41])
        ax25 = encode_ax25_ui("W1ABC", "APZHA", [], info)
        kiss = encode_kiss_frame(ax25)
        recovered = self._decode_kiss(kiss)
        result = parse_ax25_frame(recovered)
        assert result["info"] == info

    def test_nogate_path_roundtrip(self):
        ax25 = encode_ax25_ui("KE5YIM-9", "APZHA", ["WIDE1-1", "NOGATE"], b"!pos")
        kiss = encode_kiss_frame(ax25)
        recovered = self._decode_kiss(kiss)
        result = parse_ax25_frame(recovered)
        assert result["digipeaters"] == ["WIDE1-1", "NOGATE"]
