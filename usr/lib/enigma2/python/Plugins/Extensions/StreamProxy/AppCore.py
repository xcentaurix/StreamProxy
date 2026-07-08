# -*- coding: utf-8 -*-
# AppCoreSC - No cache version optimized for Enigma2
from .StreamProxyLog import enhanced_log as _enhanced_log
from urllib.parse import urlparse, urljoin, unquote, quote
import requests
import re
import time
import hashlib
import os
import json
import random
import threading

VERBOSE_LOGS = os.environ.get(
    'STREAMPROXY_VERBOSE',
    '0').lower() in (
        '1',
        'true',
        'yes',
    'on')
_HOT_LOG_TAGS = set(['proxy_ts'])


def enhanced_log(msg, level="INFO", tag="AppCore"):
    """Light filter to avoid excessive I/O on hot paths in Enigma2."""
    if not VERBOSE_LOGS:
        if level == "DEBUG":
            return
        if tag in _HOT_LOG_TAGS and level == "INFO":
            return
    return _enhanced_log(msg, level, tag)


# Import LiveTV extractor for powerset domains
try:
    from .extractor.livetv_extractor import process_powerset_url, is_powerset_domain
    LIVETV_AVAILABLE = True
    enhanced_log("LiveTV extractor available", "INFO", "AppCore")
except ImportError as e:
    LIVETV_AVAILABLE = False

    def process_powerset_url(*args, **kwargs):
        return None

    def is_powerset_domain(*args, **kwargs):
        return False
    enhanced_log(
        "LiveTV extractor not available: %s" % e,
        "WARNING",
        "AppCore")

# Cryptography library handling for Enigma2
AES_AVAILABLE = False
AES_MODULE = None
try:
    from Crypto.Cipher import AES as CryptoAES
    AES_MODULE = CryptoAES
    AES_AVAILABLE = True
    enhanced_log("Crypto.Cipher.AES available", "INFO", "AppCore")
except ImportError:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        AES_MODULE = "cryptography"
        AES_AVAILABLE = True
        enhanced_log("cryptography available", "INFO", "AppCore")
    except ImportError:
        AES_AVAILABLE = False

        class Cipher:
            pass

        class algorithms:
            pass

        class modes:
            pass

        def default_backend():
            return None
        enhanced_log(
            "No AES library available - decryption disabled",
            "WARNING",
            "AppCore")

# =====================================================================
# EXTERNAL PROXY INTEGRATION - COMPLETE
# =====================================================================
# Import external proxy
try:
    from .external_proxy import (
        is_proxy_esterno_attivo,
        resolve_via_proxy_esterno,
        fetch_segment_via_proxy_esterno,
        register_cdn_domain,
        is_cdn_daddy_url,
        is_url_del_proxy_esterno,
        build_external_segment_url,
        build_external_key_url,
    )
    EXTERNAL_PROXY_AVAILABLE = True
    enhanced_log("External proxy available", "INFO", "AppCore")
except ImportError:
    EXTERNAL_PROXY_AVAILABLE = False

    def is_proxy_esterno_attivo():
        return False

    def resolve_via_proxy_esterno(*args, **kwargs):
        return None

    def fetch_segment_via_proxy_esterno(*args, **kwargs):
        return None

    def register_cdn_domain(*args, **kwargs):
        return

    def is_cdn_daddy_url(*args, **kwargs):
        return False
    enhanced_log("External proxy not available", "WARNING", "AppCore")

    def is_url_del_proxy_esterno(*args, **kwargs):
        return False

    def build_external_segment_url(*args, **kwargs):
        return None

    def build_external_key_url(*args, **kwargs):
        return None

# External proxy domain cache
EXTERNAL_PROXY_DOMAINS = set()
# =====================================================================


def convert_fmp4_to_ts(fmp4_content, stream_id=None):
    """OPTIMIZED SOLUTION: Intelligent fMP4 handling for Enigma2

    For Freeshot, send fMP4 directly without conversion to avoid A/V issues.
    TS conversion is used only when strictly necessary.
    """
    try:
        if len(fmp4_content) < 8:
            enhanced_log(
                "[FMP4_CONVERT] Segment too small, using fallback",
                "WARNING",
                "proxy_ts")
            # Fallback: empty but valid TS segment
            return b'\x47\x1F\xFF\x10' + b'\xFF' * 184

        # Check content format
        if len(fmp4_content) > 0 and fmp4_content[0] == 0x47:
            enhanced_log(
                "[FMP4_CONVERT] Content already in TS format",
                "INFO",
                "proxy_ts")
            return fmp4_content

        # Verify fMP4 header
        if len(fmp4_content) >= 8:
            header_type = fmp4_content[4:8]
            if header_type not in [b'ftyp', b'styp', b'moof', b'mdat']:
                enhanced_log(
                    "[FMP4_CONVERT] Unrecognised header: %s, trying anyway" %
                    header_type, "WARNING", "proxy_ts")

        enhanced_log(
            "[FMP4_CONVERT] Processing %d bytes of fMP4" % len(fmp4_content),
            "DEBUG",
            "proxy_ts")

        # For Freeshot, ALWAYS send fMP4 directly
        # Modern Enigma2 handles fMP4 natively better than TS conversion
        if stream_id and stream_id in STREAM_KEY_INFO:
            stream_info = STREAM_KEY_INFO[stream_id]

            if stream_info.get('is_freeshot', False):
                enhanced_log(
                    "[FMP4_DIRECT] Freeshot: direct fMP4 delivery (optimal for Enigma2)",
                    "INFO",
                    "proxy_ts")

                enhanced_log(
                    "[FMP4_DIRECT] Size: %d bytes" % len(fmp4_content),
                    "DEBUG",
                    "proxy_ts"
                )

                return fmp4_content

        # Mandatory init segment for video
        init_data = b''
        if stream_id and stream_id in STREAM_KEY_INFO:
            init_segment = STREAM_KEY_INFO[stream_id].get('init_segment')

            if init_segment:
                enhanced_log(
                    "[FMP4_CONVERT] Using init segment: %d bytes" %
                    len(init_segment), "DEBUG", "proxy_ts")
                init_data = init_segment
            else:
                enhanced_log(
                    "[FMP4_CONVERT] Missing init segment for stream %s" %
                    stream_id, "WARNING", "proxy_ts")

        ts_packets = []

        # Standard TS packet size
        TS_PAYLOAD_SIZE = 184  # 188 - 4 byte header

        # Optimised PIDs for Enigma2
        PMT_PID = 0x1000
        VIDEO_PID = 0x0100
        AUDIO_PID = 0x0101
        PCR_PID = VIDEO_PID  # PCR always from video

        # PAT optimised for Enigma2
        pat_payload = bytes([
            0x00,  # table_id (PAT)
            0xB0, 0x0D,  # section_syntax_indicator + section_length
            0x00, 0x01,  # transport_stream_id
            0xC1,  # version_number + current_next_indicator
            0x00, 0x00,  # section_number + last_section_number
            0x00, 0x01,  # program_number (1)
            (PMT_PID >> 8) | 0xE0, PMT_PID & 0xFF,  # program_map_PID
            # CRC32 correct for Enigma2
            0x2A, 0xB1, 0x04, 0xB2
        ])

        pat_padded = pat_payload + b'\xFF' * \
            (TS_PAYLOAD_SIZE - len(pat_payload))
        pat_header = bytes([0x47, 0x40, 0x00, 0x10])  # PAT with PUSI=1
        pat_packet = pat_header + pat_padded
        ts_packets.append(pat_packet)

        # PMT with correct stream_type for Enigma2
        pmt_payload = bytes([
            0x02,  # table_id (PMT)
            0xB0, 0x17,  # section_syntax_indicator + section_length
            0x00, 0x01,  # program_number
            0xC1,  # version_number + current_next_indicator
            0x00, 0x00,  # section_number + last_section_number
            (PCR_PID >> 8) | 0xE0, PCR_PID & 0xFF,  # PCR_PID (video)
            0xF0, 0x00,  # program_info_length (0)
            # Video stream H.264 AVC
            0x1B,  # stream_type (H.264/AVC) - Enigma2 compatible
            (VIDEO_PID >> 8) | 0xE0, VIDEO_PID & 0xFF,  # elementary_PID
            0xF0, 0x00,  # ES_info_length (0)
            # Audio stream AAC
            0x0F,  # stream_type (AAC ADTS) - Enigma2 compatible
            (AUDIO_PID >> 8) | 0xE0, AUDIO_PID & 0xFF,  # elementary_PID
            0xF0, 0x00,  # ES_info_length (0)
            # CRC32 correct
            0x2F, 0x44, 0xB9, 0x9B
        ])

        pmt_padded = pmt_payload + b'\xFF' * \
            (TS_PAYLOAD_SIZE - len(pmt_payload))
        pmt_header = bytes([0x47, 0x50, 0x00, 0x10])  # PMT with PUSI=1
        pmt_packet = pmt_header + pmt_padded
        ts_packets.append(pmt_packet)

        enhanced_log(
            "[FMP4_CONVERT] Added PAT/PMT optimised for Enigma2",
            "DEBUG",
            "proxy_ts")

        # Combine init + payload for full video metadata
        if init_data:
            # Init segment MUST be processed for correct video metadata
            payload_data = init_data + fmp4_content
            enhanced_log(
                "[FMP4_CONVERT] Combined init (%d) + payload (%d) = %d bytes" %
                (len(init_data), len(fmp4_content), len(payload_data)), "DEBUG", "proxy_ts")
        else:
            # Without init segment, video may not work
            payload_data = fmp4_content
            enhanced_log(
                "[FMP4_CONVERT] WARNING: No init segment - video may not work!",
                "WARNING",
                "proxy_ts")

        base_timestamp = int(time.time() *
                             90000) & 0x1FFFFFFFF  # 33-bit timestamp

        video_continuity = 2  # Start from 2 (after PAT and PMT)
        audio_continuity = 0
        pcr_base = base_timestamp
        # Process data in chunks optimised for Enigma2
        pos = 0
        packet_num = 0

        while pos < len(payload_data):
            if packet_num == 0:
                # First packet with PES header
                pts = (base_timestamp + packet_num * 3600) & 0x1FFFFFFFF

                pts_bytes = [
                    0x21 | ((pts >> 29) & 0x0E),
                    (pts >> 22) & 0xFF,
                    0x01 | ((pts >> 14) & 0xFE),
                    (pts >> 7) & 0xFF,
                    0x01 | ((pts << 1) & 0xFE)
                ]

                pes_header = bytes([
                    0x00, 0x00, 0x01, 0xE0,
                    0x00, 0x00,
                    0x84, 0x80, 0x05
                ] + pts_bytes)

                # Available space for data
                adaptation_field_length = 7
                available_space = TS_PAYLOAD_SIZE - \
                    adaptation_field_length - len(pes_header)
                chunk = payload_data[pos:pos + available_space]

                # Adaptation field with PCR
                adaptation_field = bytes([
                    adaptation_field_length - 1,
                    0x10,
                    (pcr_base >> 25) & 0xFF,
                    (pcr_base >> 17) & 0xFF,
                    (pcr_base >> 9) & 0xFF,
                    (pcr_base >> 1) & 0xFF,
                    ((pcr_base & 0x01) << 7) | 0x7E,
                    0x00
                ])

                packet_payload = pes_header + chunk
                if len(packet_payload) < TS_PAYLOAD_SIZE - \
                        adaptation_field_length:
                    packet_payload += b'\xFF' * (
                        TS_PAYLOAD_SIZE - adaptation_field_length - len(packet_payload))

                ts_header = bytes([
                    0x47,
                    0x40 | ((VIDEO_PID >> 8) & 0x1F),
                    VIDEO_PID & 0xFF,
                    0x30 | (video_continuity & 0x0F)
                ])

                ts_packet = ts_header + adaptation_field + packet_payload
                pos += len(chunk)
            else:
                # Subsequent packets
                chunk = payload_data[pos:pos + TS_PAYLOAD_SIZE]

                if len(chunk) < TS_PAYLOAD_SIZE:
                    chunk += b'\xFF' * (TS_PAYLOAD_SIZE - len(chunk))

                ts_header = bytes([
                    0x47,
                    (VIDEO_PID >> 8) & 0x1F,
                    VIDEO_PID & 0xFF,
                    0x10 | (video_continuity & 0x0F)
                ])

                ts_packet = ts_header + chunk
                pos += TS_PAYLOAD_SIZE

            ts_packets.append(ts_packet)
            video_continuity = (video_continuity + 1) % 16
            packet_num += 1

        # Add synthetic AAC audio packets for A/V compatibility
        # Enigma2 expects both video and audio to work correctly
        for audio_frame in range(3):  # 3 audio frames per segment
            # Audio AAC PES header
            # 1920 = 90000/46.875 (AAC frame duration)
            audio_pts = (base_timestamp + audio_frame * 1920) & 0x1FFFFFFFF

            audio_pts_bytes = [
                0x21 | ((audio_pts >> 29) & 0x0E),
                (audio_pts >> 22) & 0xFF,
                0x01 | ((audio_pts >> 14) & 0xFE),
                (audio_pts >> 7) & 0xFF,
                0x01 | ((audio_pts << 1) & 0xFE)
            ]

            # Silent AAC frame (7 bytes ADTS header + 1 byte payload)
            aac_frame = bytes([
                0xFF, 0xF1,  # ADTS sync + profile
                0x50, 0x80,  # sampling freq + channel config
                0x23, 0xFC,  # frame length + buffer fullness
                0x00, 0x00   # payload (silent)
            ])

            audio_pes_header = bytes([
                0x00, 0x00, 0x01, 0xC0,  # PES start code + stream_id (audio)
                0x00, 0x00,  # PES_packet_length (0 = unbounded)
                0x84, 0x80, 0x05  # PES flags + header length
            ] + audio_pts_bytes)

            # Combine PES header with AAC frame
            audio_payload = audio_pes_header + aac_frame

            # Padding if needed
            if len(audio_payload) < TS_PAYLOAD_SIZE:
                audio_payload = audio_payload + b'\xFF' * \
                    (TS_PAYLOAD_SIZE - len(audio_payload))

            # TS header for audio
            audio_ts_header = bytes([
                0x47,  # sync_byte
                0x40 | ((AUDIO_PID >> 8) & 0x1F),  # PUSI=1 + PID high
                AUDIO_PID & 0xFF,  # PID low
                0x10 | (audio_continuity & 0x0F)  # payload_only + continuity
            ])

            audio_ts_packet = audio_ts_header + audio_payload[:TS_PAYLOAD_SIZE]
            ts_packets.append(audio_ts_packet)
            audio_continuity = (audio_continuity + 1) % 16

        # Combine all TS packets
        ts_stream = b''.join(ts_packets)

        enhanced_log(
            "[FMP4_CONVERT] Created %d TS packets (%d bytes)" % (
                len(ts_packets),
                len(ts_stream)
            ),
            "INFO",
            "proxy_ts"
        )

        enhanced_log(
            "[FMP4_CONVERT] Structure: PAT + PMT + %d video + PCR" % (
                len(ts_packets) - 5
            ),
            "DEBUG",
            "proxy_ts"
        )
        # Verify sync byte
        if ts_stream and ts_stream[0] == 0x47:
            enhanced_log(
                "[FMP4_CONVERT] Valid TS stream (sync byte 0x47)",
                "DEBUG",
                "proxy_ts"
            )
        else:
            enhanced_log(
                "[FMP4_CONVERT] ERROR: Invalid TS stream!",
                "ERROR",
                "proxy_ts"
            )

        enhanced_log(
            "[FMP4_CONVERT] Conversion completed: %d TS bytes" %
            len(ts_stream), "INFO", "proxy_ts")

        return ts_stream

    except Exception as e:
        enhanced_log(
            "[FMP4_CONVERT] Conversion error: %s" % e,
            "ERROR",
            "proxy_ts")
        # Complete and valid TS stream for Enigma2
        try:
            # Complete PAT
            pat = (
                bytes([0x47, 0x40, 0x00, 0x10, 0x00])
                + bytes([
                    0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00,
                    0x00, 0x01, 0xF0, 0x00, 0x2A, 0xB1, 0x04, 0xB2
                ])
                + b'\xFF' * 167
            )

            # Complete PMT with video + audio
            pmt = (
                bytes([0x47, 0x50, 0x00, 0x10, 0x02])
                + bytes([
                    0x00, 0xB0, 0x17, 0x00, 0x01, 0xC1, 0x00, 0x00,
                    0xE1, 0x00, 0xF0, 0x00
                ])
                + bytes([
                    0x1B, 0xE1, 0x00, 0xF0, 0x00, 0x0F, 0xE1, 0x01,
                    0xF0, 0x00, 0x2F, 0x44, 0xB9, 0x9B
                ])
                + b'\xFF' * 163
            )

            # Video packet with full PES header and PTS
            pes_header = bytes([0x00,
                                0x00,
                                0x01,
                                0xE0,
                                0x00,
                                0x00,
                                0x84,
                                0x80,
                                0x05,
                                0x21,
                                0x00,
                                0x01,
                                0x00,
                                0x01])
            video_payload = pes_header + b'\xFF' * (184 - len(pes_header))
            video = bytes([0x47, 0x41, 0x00, 0x10]) + video_payload

            # Synthetic AAC audio packet
            audio_pes = bytes([0x00, 0x00, 0x01, 0xC0, 0x00, 0x00,
                               0x84, 0x80, 0x05, 0x21, 0x00, 0x01, 0x00, 0x01])
            audio_payload = audio_pes + b'\xFF' * (184 - len(audio_pes))
            audio = bytes([0x47, 0x41, 0x01, 0x10]) + audio_payload

            fallback_ts = pat + pmt + video + audio
            enhanced_log(
                "[FMP4_CONVERT] Complete TS fallback generated: %d bytes" %
                len(fallback_ts), "INFO", "proxy_ts")
            return fallback_ts
        except Exception as fallback_error:
            # Emergency fallback
            emergency_ts = b'\x47\x1F\xFF\x10' + b'\xFF' * 184

            enhanced_log(
                "[FMP4_CONVERT] Complete TS fallback error: %s" %
                fallback_error, "WARNING", "proxy_ts")

            enhanced_log(
                "[FMP4_CONVERT] Emergency fallback: %d bytes" %
                len(emergency_ts), "WARNING", "proxy_ts")

            return emergency_ts


def is_valid_ts_payload(data, packets_to_check=5):
    """Light MPEG-TS validation: sync byte 0x47 on multiple 188-byte packets."""
    if not data or len(data) < 188 or data[0] != 0x47:
        return False
    packet_count = min(packets_to_check, len(data) // 188)
    if packet_count <= 0:
        return False
    for packet_index in range(packet_count):
        if data[packet_index * 188] != 0x47:
            return False
    return True


def make_fallback_ts_segment(packet_count=3):
    """Generate a small valid TS segment to send when an encrypted segment is unusable."""
    pat = bytes([
        0x47, 0x40, 0x00, 0x10, 0x00,
        0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00,
        0x00, 0x01, 0xF0, 0x00, 0x2A, 0xB1, 0x04, 0xB2
    ]) + b'\xFF' * 167
    null_packet = b'\x47\x1F\xFF\x10' + b'\xFF' * 184
    return pat + (null_packet * max(0, packet_count - 1))


def get_non_ts_content_type(url, content=None):
    """Identify HLS non-video resources that should not pass through TS decryption."""
    url_lower = (url or "").lower().split("?", 1)[0]
    if url_lower.endswith(".vtt") or url_lower.endswith(".webvtt"):
        return "text/vtt"
    if url_lower.endswith(".srt"):
        return "application/x-subrip"
    if url_lower.endswith(".ttml") or url_lower.endswith(
            ".dfxp") or url_lower.endswith(".xml"):
        return "application/ttml+xml"

    if content:
        sample = content[:64].lstrip()
        if sample.startswith(b"WEBVTT"):
            return "text/vtt"
        if sample.startswith((b"<?xml", b"<tt ")):
            return "application/ttml+xml"

    return None


def is_subtitle_resource(url):
    """Identify subtitle playlists/segments that should not be treated as TS."""
    url_lower = (url or "").lower().split("?", 1)[0]
    subtitle_extensions = (".vtt", ".webvtt", ".srt", ".ttml", ".dfxp")
    subtitle_markers = ("/subtitle/", "/subtitles/", "/subs/")
    return url_lower.endswith(subtitle_extensions) or any(
        marker in url_lower for marker in subtitle_markers)


def is_subtitle_media_tag(line):
    """Identify HLS EXT-X-MEDIA tags dedicated to subtitles."""
    line_upper = (line or "").upper()
    return line_upper.startswith(
        "#EXT-X-MEDIA") and "TYPE=SUBTITLES" in line_upper


def decrypt_ts_if_needed(ts_content, stream_id, headers, segment_url=None):
    """AES-128 decryption with detailed logging for DLHD debugging"""
    enhanced_log(
        "[DECRYPT_TS] === START DECRYPTION for stream %s ===" % stream_id,
        "INFO",
        "AppCore")

    if not AES_AVAILABLE:
        enhanced_log("[DECRYPT_TS] AES not available", "ERROR", "AppCore")
        return ts_content

    if len(ts_content) == 0:
        enhanced_log("[DECRYPT_TS] Empty content", "ERROR", "AppCore")
        return ts_content

    non_ts_content_type = get_non_ts_content_type(segment_url, ts_content)
    if non_ts_content_type:
        enhanced_log(
            "[DECRYPT_TS] Non-TS resource detected (%s), skipping decryption" %
            non_ts_content_type, "INFO", "AppCore")
        return ts_content

    if len(ts_content) % 16 != 0:
        enhanced_log(
            "[DECRYPT_TS] Length %d not multiple of 16, incomplete/unaligned segment" %
            len(ts_content), "WARNING", "AppCore")
        return make_fallback_ts_segment()

    # Log first byte for debugging
    enhanced_log(
        "[DECRYPT_TS] Content first byte: 0x%02x" % ts_content[0],
        "INFO",
        "AppCore")

    try:
        stream_info = STREAM_KEY_INFO.get(stream_id, {})
        if not stream_info:
            enhanced_log(
                "[DECRYPT_TS] Stream info not found for %s" % stream_id,
                "ERROR",
                "AppCore")
            return ts_content

        enhanced_log(
            "[DECRYPT_TS] Stream info found for %s" % stream_id,
            "INFO",
            "AppCore")

        # Get AES key
        aes_key = get_aes_key_for_stream(stream_id, headers, segment_url)
        if not aes_key:
            enhanced_log(
                "[DECRYPT_TS] AES key not available",
                "ERROR",
                "AppCore")
            return ts_content

        enhanced_log(
            "[DECRYPT_TS] AES key obtained: %d bytes" % len(aes_key),
            "INFO",
            "AppCore")

        # Use IV from stream info
        iv = stream_info.get('iv', b'\x00' * 16)
        if isinstance(iv, str):
            try:
                iv_str = iv.replace('0x', '') if iv.startswith('0x') else iv
                iv = bytes.fromhex(iv_str)
                enhanced_log(
                    "[DECRYPT_TS] IV converted from hex: %s" % iv.hex(),
                    "DEBUG",
                    "AppCore")
            except Exception as iv_error:
                iv = iv.encode('latin-1')
                enhanced_log(
                    "[DECRYPT_TS] IV not hex, using latin-1 bytes: %s" %
                    iv_error, "DEBUG", "AppCore")
                enhanced_log(
                    "[DECRYPT_TS] IV converted from string: %s" % iv.hex(),
                    "DEBUG",
                    "AppCore")

        # Ensure IV is 16 bytes
        if len(iv) != 16:
            iv = (iv + b'\x00' * 16)[:16]
            enhanced_log(
                "[DECRYPT_TS] IV adjusted to 16 bytes: %s" % iv.hex(),
                "WARNING",
                "AppCore")

        enhanced_log(
            "[DECRYPT_TS] Final IV: %s" % iv.hex(),
            "DEBUG",
            "AppCore")
        enhanced_log(
            "[DECRYPT_TS] Key: %s" % aes_key.hex(),
            "DEBUG",
            "AppCore")

        # Decryption
        enhanced_log(
            "[DECRYPT_TS] Starting AES-128-CBC decryption",
            "INFO",
            "AppCore")

        if AES_MODULE == "cryptography":
            cipher = Cipher(
                algorithms.AES(aes_key),
                modes.CBC(iv),
                backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(ts_content) + decryptor.finalize()
        else:
            cipher = AES_MODULE.new(aes_key, AES_MODULE.MODE_CBC, iv)
            decrypted = cipher.decrypt(ts_content)

        enhanced_log(
            "[DECRYPT_TS] Decryption completed: %d bytes" % len(decrypted),
            "INFO",
            "AppCore")

        # Remove PKCS7 padding
        if len(decrypted) > 0:
            padding_length = decrypted[-1]
            enhanced_log(
                "[DECRYPT_TS] Last byte (padding): 0x%02x" % padding_length,
                "DEBUG",
                "AppCore")

            if 0 < padding_length <= 16:
                if all(
                        b == padding_length for b in decrypted[-padding_length:]):
                    decrypted = decrypted[:-padding_length]
                    enhanced_log(
                        "[DECRYPT_TS] PKCS7 padding removed: %d bytes" %
                        padding_length, "INFO", "AppCore")
                else:
                    enhanced_log(
                        "[DECRYPT_TS] Invalid padding, keeping original content",
                        "WARNING",
                        "AppCore")
            else:
                enhanced_log(
                    "[DECRYPT_TS] Padding out of range, no removal",
                    "WARNING",
                    "AppCore")

        # Verify final sync byte
        if len(decrypted) > 0:
            enhanced_log(
                "[DECRYPT_TS] First byte after decryption: 0x%02x" %
                decrypted[0], "INFO", "AppCore")

            if is_valid_ts_payload(decrypted):
                enhanced_log(
                    "[DECRYPT_TS] === DECRYPTION SUCCESSFUL (sync byte 0x47) ===",
                    "INFO",
                    "AppCore")
                return decrypted
            else:
                enhanced_log(
                    "[DECRYPT_TS] Sync byte invalid after decryption: 0x%02x" %
                    decrypted[0], "WARNING", "AppCore")
                # Try without removing padding
                if AES_MODULE == "cryptography":
                    cipher = Cipher(
                        algorithms.AES(aes_key),
                        modes.CBC(iv),
                        backend=default_backend())
                    decryptor = cipher.decryptor()
                    decrypted_no_padding = decryptor.update(
                        ts_content) + decryptor.finalize()
                else:
                    cipher = AES_MODULE.new(aes_key, AES_MODULE.MODE_CBC, iv)
                    decrypted_no_padding = cipher.decrypt(ts_content)

                if len(decrypted_no_padding) > 0 and is_valid_ts_payload(
                        decrypted_no_padding):
                    enhanced_log(
                        "[DECRYPT_TS] === DECRYPTION SUCCESSFUL (without padding removal) ===",
                        "INFO",
                        "AppCore")
                    return decrypted_no_padding
                else:
                    enhanced_log(
                        "[DECRYPT_TS] Decryption failed, returning original content",
                        "ERROR",
                        "AppCore")
                    return make_fallback_ts_segment()
        else:
            enhanced_log(
                "[DECRYPT_TS] Decrypted content empty",
                "ERROR",
                "AppCore")
            return make_fallback_ts_segment()

    except Exception as e:
        enhanced_log(
            "[DECRYPT_TS] === ERROR DURING DECRYPTION: %s: %s ===" % (
                type(e).__name__, str(e)),
            "ERROR",
            "AppCore")
        import traceback
        enhanced_log(
            "[DECRYPT_TS] Stack trace: %s" % traceback.format_exc(),
            "ERROR",
            "AppCore")
        return make_fallback_ts_segment()


enhanced_log("AppCoreSC - Initialization", "INFO", "AppCore")

# Import separate extractors
try:
    from .extractor.dlhd_extractor import DLHDExtractor
    dlhd_extractor = DLHDExtractor()
    DLHD_AVAILABLE = True
    # Keep reference to DLHD session for AES key downloads
    DLHD_SESSION = dlhd_extractor.session if hasattr(
        dlhd_extractor, 'session') else None
    enhanced_log("DLHD extractor available", "INFO", "AppCore")
except ImportError as e:
    DLHD_AVAILABLE = False
    DLHD_SESSION = None

    class DLHDExtractor:
        def is_daddylive_link(self, url):
            return False

        def extract_stream(self, url):
            return None
    dlhd_extractor = DLHDExtractor()
    enhanced_log(
        "DLHD extractor not available: %s" % e,
        "WARNING",
        "AppCore")

try:
    from .extractor.vavoo_extractor import vavoo_extractor, is_vavoo_link
    VAVOO_AVAILABLE = True
    enhanced_log("Vavoo extractor available", "INFO", "AppCore")
except ImportError as e:
    VAVOO_AVAILABLE = False

    def vavoo_extractor(*args, **kwargs):
        return None

    def is_vavoo_link(*args, **kwargs):
        return False
    enhanced_log(
        "Vavoo extractor not available: %s" % e,
        "WARNING",
        "AppCore")

try:
    from .extractor.vix_extractor import vix_extractor
    VIX_AVAILABLE = True
    enhanced_log("VixCloud extractor available", "INFO", "AppCore")
except ImportError as e:
    VIX_AVAILABLE = False

    class vix_extractor:
        @staticmethod
        def extract(url):
            return None
    enhanced_log(
        "VixCloud extractor not available: %s" % e,
        "WARNING",
        "AppCore")

# TVTap is now handled via WMS Manager and ServiceMonitor


def get_dlhd_session():
    if DLHD_AVAILABLE and dlhd_extractor and hasattr(
            dlhd_extractor, 'session'):
        return dlhd_extractor.session

    # If DLHD session not available, try external proxy
    if EXTERNAL_PROXY_AVAILABLE and is_proxy_esterno_attivo():
        # Return a dummy session that uses external proxy
        class ExternalProxySession:
            def get(self, url, headers=None, timeout=8, verify=False):
                from .external_proxy import resolve_via_proxy_esterno
                result = resolve_via_proxy_esterno(url, headers)
                if result and result.get("resolved_url"):
                    # Simulate response
                    return requests.get(
                        result["resolved_url"],
                        headers=headers,
                        timeout=timeout)
                return None
        return ExternalProxySession()
    return None


TVTAP_AVAILABLE = True
enhanced_log("TVTap handled via WMS Manager", "INFO", "AppCore")

# Sportsonline extractor
try:
    from .extractor.sportonline_extractor import extract_sportonline, is_sportonline_link
    SPORTONLINE_AVAILABLE = True
    enhanced_log("Sportsonline extractor available", "INFO", "AppCore")
except ImportError as e:
    SPORTONLINE_AVAILABLE = False

    def extract_sportonline(*args, **kwargs):
        return None

    def is_sportonline_link(*args, **kwargs):
        return False
    enhanced_log(
        "Sportsonline extractor not available: %s" % e,
        "WARNING",
        "AppCore")

# Sport99 / CDNLiveTV extractor
try:
    from .extractor.sport99_extractor import extract_sport99, is_sport99_link
    SPORT99_AVAILABLE = True
    enhanced_log("Sport99 extractor available", "INFO", "AppCore")
except ImportError as e:
    SPORT99_AVAILABLE = False

    def extract_sport99(*args, **kwargs):
        return None

    def is_sport99_link(*args, **kwargs):
        return False
    enhanced_log(
        "Sport99 extractor not available: %s" % e,
        "WARNING",
        "AppCore")

# Freeshot extractor
try:
    from .extractor.freeshot_extractor import freeshot_extractor, is_freeshot_link
    FREESHOT_AVAILABLE = True
    enhanced_log("Freeshot extractor available", "INFO", "AppCore")
except ImportError as e:
    FREESHOT_AVAILABLE = False

    def is_freeshot_link(*args, **kwargs):
        return False

    class freeshot_extractor:
        @staticmethod
        def extract(url):
            return None
    enhanced_log(
        "Freeshot extractor not available: %s" % e,
        "WARNING",
        "AppCore")

# Maxstream extractor
try:
    from .extractor.maxstream_extractor import MaxstreamExtractor, is_maxstream_link
    maxstream_extractor = MaxstreamExtractor()
    MAXSTREAM_AVAILABLE = True
    enhanced_log("Maxstream extractor available", "INFO", "AppCore")
except ImportError as e:
    MAXSTREAM_AVAILABLE = False

    def is_maxstream_link(*args, **kwargs):
        return False

    class MaxstreamExtractor:
        def extract(self, url, **kwargs):
            return None
    maxstream_extractor = MaxstreamExtractor()
    enhanced_log(
        "Maxstream extractor not available: %s" % e,
        "WARNING",
        "AppCore")

# Mixdrop extractor
MIXDROP_DOMAINS = (
    'mixdrop.co',
    'mixdrop.vip',
    'm1xdrop.net',
    'm1xdrop.bz',
    'mixdrop.ch',
    'mixdrop.ps',
    'mixdrop.ag',
    'mxcontent.net')
try:
    try:
        from .extractor.mixdrop_extractor import MixdropExtractor, is_mixdrop_link
    except ImportError:
        from extractor.mixdrop_extractor import MixdropExtractor, is_mixdrop_link
    mixdrop_extractor = MixdropExtractor()
    MIXDROP_AVAILABLE = True
    enhanced_log("Mixdrop extractor available", "INFO", "AppCore")
except ImportError as e:
    MIXDROP_AVAILABLE = False

    def is_mixdrop_link(*args, **kwargs):
        url = args[0] if args else ""
        return any(domain in (url or "").lower() for domain in MIXDROP_DOMAINS)

    class MixdropExtractor:
        def extract(self, url, **kwargs):
            return None
    mixdrop_extractor = MixdropExtractor()
    enhanced_log(
        "Mixdrop extractor not available: %s" % e,
        "WARNING",
        "AppCore")

# Optimised configuration for Enigma2
VERIFY_SSL = False
REQUEST_TIMEOUT = 15  # Increased timeout for slow connections


# Dummy caches for ServiceMonitor compatibility
def is_direct_media_url(url):
    """Identify direct non-HLS video URLs."""
    url_path = (url or "").lower().split("?", 1)[0]
    return url_path.endswith((".mp4", ".mkv", ".webm", ".flv", ".mov", ".avi"))


class DummyCache:
    def clear(self):
        pass

    def get(self, key):
        return None

    def put(self, key, value):
        return True


M3U8_CACHE = DummyCache()
TS_CACHE = DummyCache()
KEY_CACHE = DummyCache()
RESOLVED_LINKS_CACHE = DummyCache()
VAVOO_M3U8_PREFETCH_CACHE = {}
VAVOO_FINAL_M3U8_CACHE = {}

# --- General Configuration ---
# VERIFY_SSL = os.environ.get('VERIFY_SSL', 'false').lower() not in ('false', '0', 'no')
# if not VERIFY_SSL:
#     app.logger.warning("ATTENTION: SSL certificate verification is DISABLED. This may expose security risks.")
#     import urllib3
#     urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Increased timeout to handle large TS segments
# Optimised configuration for Enigma2
try:
    REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', '15'))
except (ValueError, TypeError):
    REQUEST_TIMEOUT = 15

enhanced_log(
    "Request timeout set to %d seconds." % REQUEST_TIMEOUT,
    "INFO",
    "AppCore")

# Simplified configurations for Enigma2 (Keep-Alive disabled)
try:
    KEEP_ALIVE_TIMEOUT = int(os.environ.get('KEEP_ALIVE_TIMEOUT', '60'))
    MAX_KEEP_ALIVE_REQUESTS = int(
        os.environ.get(
            'MAX_KEEP_ALIVE_REQUESTS',
            '100'))
    POOL_CONNECTIONS = int(os.environ.get('POOL_CONNECTIONS', '5'))
    POOL_MAXSIZE = int(os.environ.get('POOL_MAXSIZE', '10'))
    enhanced_log(
        "Keep-Alive configured: timeout=%ds, max_requests=%d" % (
            KEEP_ALIVE_TIMEOUT, MAX_KEEP_ALIVE_REQUESTS),
        "INFO",
        "AppCore")

except (ValueError, TypeError):
    KEEP_ALIVE_TIMEOUT = 60
    MAX_KEEP_ALIVE_REQUESTS = 100
    POOL_CONNECTIONS = 5
    POOL_MAXSIZE = 10
enhanced_log(
    "Keep-Alive disabled: timeout=%ds, max_requests=%d" % (
        KEEP_ALIVE_TIMEOUT, MAX_KEEP_ALIVE_REQUESTS),
    "INFO",
    "AppCore")

# Global session pool for persistent connections
SESSION_POOL = {}
SESSION_MAX_AGE = 300
SESSION_MAX_REQUESTS = 100
try:
    from threading import Lock
    SESSION_LOCK = Lock()
except ImportError:
    class DummyLock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def acquire(self):
            pass

        def release(self):
            pass
    SESSION_LOCK = DummyLock()


def make_enigma2_request(url, headers=None, timeout=None, **kwargs):
    """HTTP request optimised for Enigma2 with automatic retry and improved error handling"""
    default_headers = {
        'Accept': '*/*',
        'Connection': 'close'
    }

    # Only if no User-Agent is set, use default
    if not headers or not headers.get('User-Agent'):
        default_headers['User-Agent'] = 'Enigma2-StreamProxy/1.2'

    if headers:
        default_headers.update(headers)

    timeout = timeout or REQUEST_TIMEOUT
    retry_codes = [429, 500, 502, 503, 504]

    # For Freeshot, use more aggressive timeouts
    is_freeshot_url = 'lovecdn.ru' in url.lower()
    if is_freeshot_url:
        timeout = min(timeout, 4)  # Max 4 seconds for Freeshot
        max_attempts = 2  # Only 2 attempts for speed
    else:
        max_attempts = 3

    response = None
    for attempt in range(max_attempts):
        try:
            response = requests.get(
                url,
                headers=default_headers,
                timeout=timeout,
                verify=VERIFY_SSL,
                stream=kwargs.get('stream', False),
                allow_redirects=kwargs.get('allow_redirects', True)
            )
            if response.status_code not in retry_codes:
                return response
            if attempt < max_attempts - 1:
                sleep_time = 0.2 if is_freeshot_url else 0.5
                time.sleep(sleep_time * (attempt + 1))
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_attempts - 1:
                sleep_time = 0.1 if is_freeshot_url else 0.3
                time.sleep(sleep_time * (attempt + 1))
                continue
            if is_freeshot_url:
                enhanced_log("[FREESHOT_TIMEOUT] Timeout after %d attempts: %s" % (
                    max_attempts, url[-50:]), "WARNING", "AppCore")
            else:
                enhanced_log(
                    "Request error after %d attempts: %s" %
                    (max_attempts, e), "ERROR", "AppCore")
            raise
        except requests.exceptions.HTTPError as e:
            # For specific HTTP errors, do not retry
            enhanced_log("HTTP error: %s" % e, "ERROR", "AppCore")
            raise
        except Exception as e:
            enhanced_log("Request error: %s" % e, "ERROR", "AppCore")
            raise
    return response


def get_enigma2_timeout(url):
    """Optimised timeouts for Enigma2"""
    url_lower = url.lower()

    if 'kiko2.ru' in url_lower:
        return 8 if '.ts' in url_lower else 10
    elif 'vavoo' in url_lower:
        return 4 if '.ts' in url_lower else 6
    elif any(d in url_lower for d in ['daddylive', 'daddy', 'dlhd']):
        return 6 if '.ts' in url_lower else 8
    elif any(d in url_lower for d in ['vix', 'vixsrc', 'vixcloud']):
        return 8 if '.ts' in url_lower else 12
    else:
        return 5 if '.ts' in url_lower else 8


# Compatibility for existing code that uses vavoo_resolver
if VAVOO_AVAILABLE:
    from .extractor.vavoo_extractor import vavoo_resolver
else:
    class DummyVavooResolver:
        def resolve_vavoo_link(self, link):
            return None

        def clear_vavoo_cache(self, x=None):
            pass
    vavoo_resolver = DummyVavooResolver()


def extract_custom_headers_from_url(url):
    """Extract custom headers from URL (format: #Header=Value&Header2=Value2)"""
    if not url or '#' not in url:
        return url, {}

    try:
        # Split URL and fragment
        url_parts = url.split('#', 1)
        clean_url = url_parts[0]
        fragment = url_parts[1] if len(url_parts) > 1 else ''

        if not fragment:
            return url, {}

        # Extract headers from fragment
        headers = {}
        for param in fragment.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                # Decode and normalise
                key = unquote(key).strip()
                value = unquote(value).strip()
                headers[key] = value
                enhanced_log("[CUSTOM_HEADER] Extracted: %s = %s..." % (
                    key, value[:50]), "DEBUG", "AppCore")

        return clean_url, headers
    except Exception as e:
        enhanced_log(
            "[CUSTOM_HEADER] Extraction error: %s" % e,
            "ERROR",
            "AppCore")
        return url, {}


def resolve_m3u8_link(url, headers=None, **kwargs):
    """
    Resolve DaddyLive URL with multi-endpoint and detailed debug logging.
    Handles full flow: extraction → validation → AES key
    """
    enhanced_log(
        "[RESOLVE_START] Starting URL resolution: %s..." % url[:100],
        "INFO",
        "AppCore")

    if not url:
        enhanced_log("[RESOLVE_ERROR] URL not provided", "ERROR", "AppCore")
        return {"resolved_url": None, "headers": {}}

    # Extract custom headers from URL (Origin, Referer, User-Agent)
    clean_url, custom_headers = extract_custom_headers_from_url(url)
    if custom_headers:
        enhanced_log(
            "[CUSTOM_HEADERS] Extracted %d custom headers" %
            len(custom_headers), "INFO", "AppCore")
        url = clean_url  # Use clean URL without fragment

    current_headers = headers.copy() if headers else {}
    current_headers.update(custom_headers)
    enhanced_log(
        "[RESOLVE_HEADERS] Initial headers: %d elements" %
        len(current_headers), "DEBUG", "AppCore")

    # =====================================================================
    # EXTERNAL PROXY: Check before any extractor
    # =====================================================================
    if EXTERNAL_PROXY_AVAILABLE and is_proxy_esterno_attivo():
        enhanced_log(
            "External proxy active, delegating resolve",
            "INFO",
            "AppCore")
        external_result = resolve_via_proxy_esterno(clean_url, current_headers)
        if external_result and external_result.get("resolved_url"):
            enhanced_log("URL resolved by external proxy", "INFO", "AppCore")
            return {
                "resolved_url": external_result["resolved_url"],
                "headers": {**current_headers, **external_result.get("headers", {})},
                "m3u8_content": external_result.get("m3u8_content")
            }
    # =====================================================================

    # 1. Extract header from URL
    enhanced_log(
        "[RESOLVE_STEP1] Starting header extraction from URL",
        "INFO",
        "AppCore")
    clean_url = url
    extracted_headers = {}

    if '&h_' in url or '%26h_' in url:
        enhanced_log(
            "[RESOLVE_HEADERS] Detected header parameters in URL",
            "INFO",
            "AppCore")
        temp_url = url

        if 'vavoo.to' in temp_url.lower() and '%26' in temp_url:
            temp_url = temp_url.replace('%26', '&')
            enhanced_log(
                "[RESOLVE_HEADERS] Replaced %26 with & for Vavoo",
                "DEBUG",
                "AppCore")

        if '%26h_' in temp_url:
            temp_url = unquote(unquote(temp_url))
            enhanced_log(
                "[RESOLVE_HEADERS] Double unquote applied",
                "DEBUG",
                "AppCore")

        url_parts = temp_url.split('&h_', 1)
        clean_url = url_parts[0]
        header_params = '&h_' + url_parts[1]
        enhanced_log(
            "[RESOLVE_HEADERS] Clean URL: %s..." % clean_url[:50],
            "DEBUG",
            "AppCore")
        enhanced_log("[RESOLVE_HEADERS] Header parameters: %s..." %
                     header_params[:100], "DEBUG", "AppCore")

        for param in header_params.split('&'):
            if param.startswith('h_'):
                try:
                    key_value = param[2:].split('=', 1)
                    if len(key_value) == 2:
                        key = unquote(key_value[0]).replace('_', '-')
                        value = unquote(key_value[1])
                        extracted_headers[key] = value
                        enhanced_log("[RESOLVE_HEADERS] Extracted header: %s = %s..." % (
                            key, value[:20]), "DEBUG", "AppCore")
                except Exception as e:
                    enhanced_log(
                        "[RESOLVE_HEADERS] Error extracting %s: %s" %
                        (param, e), "ERROR", "AppCore")

    final_headers = {**current_headers, **extracted_headers}
    enhanced_log(
        "[RESOLVE_STEP1] Final headers: %d elements" % len(final_headers),
        "INFO",
        "AppCore")

    # 2. Check URL type with separate extractors
    enhanced_log("[RESOLVE_STEP2] Checking URL type", "INFO", "AppCore")

    # Check Sport99 / CDNLiveTV - domain specific before generic matchers
    if SPORT99_AVAILABLE and is_sport99_link(clean_url):
        enhanced_log(
            "[RESOLVE_SPORT99] Detected Sport99/CDNLiveTV link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            resolved_sport99 = extract_sport99(clean_url, final_headers)
            if resolved_sport99 and resolved_sport99.get("resolved_url"):
                enhanced_log(
                    "[RESOLVE_SPORT99] Sport99 resolved successfully",
                    "INFO",
                    "AppCore")
                sport99_headers = resolved_sport99.get(
                    "headers") or resolved_sport99.get("request_headers") or {}
                combined_headers = {**final_headers, **sport99_headers}
                result = {
                    "resolved_url": resolved_sport99["resolved_url"],
                    "headers": combined_headers,
                    "mediaflow_endpoint": resolved_sport99.get("mediaflow_endpoint")}
                if resolved_sport99.get("m3u8_content"):
                    result["m3u8_content"] = resolved_sport99["m3u8_content"]
                return result
            else:
                enhanced_log(
                    "[RESOLVE_SPORT99] Sport99 resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_SPORT99] Sport99 resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check PowerSet (LiveTV), after more specific domains
    if LIVETV_AVAILABLE and is_powerset_domain(clean_url):
        enhanced_log(
            "[RESOLVE_POWERSET] Detected powerset domain: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            resolved_powerset = process_powerset_url(clean_url, final_headers)
            if resolved_powerset and resolved_powerset.get("resolved_url"):
                enhanced_log(
                    "[RESOLVE_POWERSET] PowerSet resolved successfully",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **
                                    resolved_powerset.get("headers", {})}
                return {
                    "resolved_url": resolved_powerset["resolved_url"],
                    "headers": combined_headers,
                    "mediaflow_endpoint": resolved_powerset.get("mediaflow_endpoint"),
                    "query_params": resolved_powerset.get(
                        "query_params",
                        {})}
            else:
                enhanced_log(
                    "[RESOLVE_POWERSET] PowerSet resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_POWERSET] PowerSet resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check DaddyLive/DLHD with separate extractor
    if DLHD_AVAILABLE and dlhd_extractor.is_daddylive_link(clean_url):
        enhanced_log(
            "[RESOLVE_DLHD] Detected DaddyLive/DLHD link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        enhanced_log(
            "[DLHD_FLOW] === START DADDYLIVE EXTRACTION FLOW ===",
            "INFO",
            "AppCore")
        try:
            resolved_dlhd = dlhd_extractor.extract_stream(clean_url)
            if resolved_dlhd and resolved_dlhd.get("destination_url"):
                enhanced_log(
                    "[DLHD_FLOW] === FLOW COMPLETED SUCCESSFULLY ===",
                    "INFO",
                    "AppCore")
                enhanced_log(
                    "[DLHD_FLOW] Final URL: %s" %
                    resolved_dlhd['destination_url'],
                    "INFO",
                    "AppCore")

                combined_headers = {**final_headers, **
                                    resolved_dlhd.get("request_headers", {})}

                enhanced_log(
                    "[DLHD_FLOW] Combined headers: %s" % list(
                        combined_headers.keys()),
                    "DEBUG",
                    "AppCore")

                result = {
                    "resolved_url": resolved_dlhd["destination_url"],
                    "headers": combined_headers}
                if resolved_dlhd.get("captured_manifest"):
                    result["m3u8_content"] = resolved_dlhd["captured_manifest"]
                return result
            else:
                enhanced_log(
                    "[DLHD_FLOW] === FLOW FAILED - NO URL ===",
                    "ERROR",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[DLHD_FLOW] === FLOW FAILED - ERROR: %s ===" % e,
                "ERROR",
                "AppCore")
            import traceback
            enhanced_log(
                "[DLHD_FLOW] Traceback: %s" % traceback.format_exc(),
                "DEBUG",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check VixCloud with separate extractor
    if VIX_AVAILABLE and any(vix_domain in clean_url.lower()
                             for vix_domain in ['vix', 'vixcloud', 'vixsrc']):
        enhanced_log(
            "[RESOLVE_VIX] Detected VixCloud link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            resolved_vix = vix_extractor.extract(clean_url)
            if resolved_vix and (resolved_vix.get(
                    "resolved_url") or resolved_vix.get("m3u8_content")):
                enhanced_log(
                    "[RESOLVE_VIX] VixCloud resolved successfully",
                    "INFO",
                    "AppCore")
                resolved_vix["headers"] = {
                    **final_headers, **resolved_vix.get("headers", {})}
                return resolved_vix
            else:
                enhanced_log(
                    "[RESOLVE_VIX] VixCloud resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_VIX] VixCloud resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check Vavoo with separate extractor
    if VAVOO_AVAILABLE and is_vavoo_link(clean_url):
        enhanced_log(
            "[RESOLVE_VAVOO] Detected Vavoo link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            resolved_vavoo = vavoo_extractor.extract(clean_url, final_headers)
            if resolved_vavoo and resolved_vavoo.get("resolved_url"):
                enhanced_log(
                    "[RESOLVE_VAVOO] Vavoo resolved successfully",
                    "INFO",
                    "AppCore")
                return resolved_vavoo
            else:
                enhanced_log(
                    "[RESOLVE_VAVOO] Vavoo resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_VAVOO] Vavoo resolver error: %s" % e,
                "ERROR",
                "AppCore")
            # FALLBACK: If Vavoo fails, return a user-friendly error M3U8
            if "timeout" in str(e).lower() or "connection" in str(e).lower():
                enhanced_log(
                    "[RESOLVE_VAVOO] Timeout/connection - returning fallback",
                    "WARNING",
                    "AppCore")
                return {
                    "resolved_url": None,
                    "headers": final_headers,
                    "m3u8_content": "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-ENDLIST\n# Vavoo server temporarily unavailable\n"
                }
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check Sportsonline
    if SPORTONLINE_AVAILABLE and is_sportonline_link(clean_url):
        enhanced_log(
            "[RESOLVE_SPORTONLINE] Detected Sportsonline link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            resolved_sport = extract_sportonline(clean_url)
            if resolved_sport and resolved_sport.get("resolved_url"):
                enhanced_log(
                    "[RESOLVE_SPORTONLINE] Sportsonline resolved successfully",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **
                                    resolved_sport.get("headers", {})}
                return {
                    "resolved_url": resolved_sport["resolved_url"],
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "[RESOLVE_SPORTONLINE] Sportsonline resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_SPORTONLINE] Sportsonline resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check Freeshot
    if FREESHOT_AVAILABLE and is_freeshot_link(clean_url):
        enhanced_log(
            "[RESOLVE_FREESHOT] Detected Freeshot link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            resolved_freeshot = freeshot_extractor.extract(clean_url)
            if resolved_freeshot and resolved_freeshot.get("resolved_url"):
                enhanced_log(
                    "[RESOLVE_FREESHOT] Freeshot resolved successfully",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **
                                    resolved_freeshot.get("headers", {})}
                return {
                    "resolved_url": resolved_freeshot["resolved_url"],
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "[RESOLVE_FREESHOT] Freeshot resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_FREESHOT] Freeshot resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check Maxstream
    if MAXSTREAM_AVAILABLE and is_maxstream_link(clean_url):
        enhanced_log(
            "[RESOLVE_MAXSTREAM] Detected Maxstream link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            season = kwargs.get('season')
            episode = kwargs.get('episode')
            resolved_maxstream = maxstream_extractor.extract(
                clean_url, season=season, episode=episode)
            if resolved_maxstream and resolved_maxstream.get("resolved_url"):
                enhanced_log(
                    "[RESOLVE_MAXSTREAM] Maxstream resolved successfully",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **
                                    resolved_maxstream.get("headers", {})}
                return {
                    "resolved_url": resolved_maxstream["resolved_url"],
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "[RESOLVE_MAXSTREAM] Maxstream resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_MAXSTREAM] Maxstream resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Check Mixdrop
    if MIXDROP_AVAILABLE and (is_mixdrop_link(clean_url) or any(
            domain in clean_url.lower() for domain in MIXDROP_DOMAINS)):
        enhanced_log(
            "[RESOLVE_MIXDROP] Detected Mixdrop link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            resolved_mixdrop = mixdrop_extractor.extract(clean_url)
            mixdrop_url = resolved_mixdrop.get("resolved_url") or resolved_mixdrop.get(
                "destination_url") if resolved_mixdrop else None
            mixdrop_headers = resolved_mixdrop.get("headers") or resolved_mixdrop.get(
                "request_headers") if resolved_mixdrop else {}
            if resolved_mixdrop and mixdrop_url:
                enhanced_log(
                    "[RESOLVE_MIXDROP] Mixdrop resolved successfully",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **mixdrop_headers}
                return {
                    "resolved_url": mixdrop_url,
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "[RESOLVE_MIXDROP] Mixdrop resolver returned None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                "[RESOLVE_MIXDROP] Mixdrop resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Direct TVTap check
    if TVTAP_AVAILABLE and any(
        pattern in clean_url.lower() for pattern in [
            'tvtap',
            'rocktalk.net',
            'taptube.net',
            'authsign=',
            'stream.mardio.link']):
        enhanced_log(
            "[RESOLVE_TVTAP] Detected TVTap link: %s..." % clean_url[:50],
            "INFO",
            "AppCore")
        try:
            # TVTap is handled directly, return clean URL
            return {
                "resolved_url": clean_url,
                "headers": final_headers,
                "tvtap_info": {"direct_stream": True}
            }
        except Exception as e:
            enhanced_log(
                "[RESOLVE_TVTAP] TVTap resolver error: %s" % e,
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Generic URL - passthrough
    enhanced_log(
        "[RESOLVE_PASSTHROUGH] Generic URL, passthrough",
        "INFO",
        "AppCore")
    return {"resolved_url": clean_url, "headers": final_headers}


def get_dynamic_timeout(url, base_timeout=REQUEST_TIMEOUT):
    """Calculate dynamic timeout optimised for channel change speed."""
    url_lower = url.lower()

    if '.ts' in url_lower:
        if any(d in url_lower for d in ['kiko2.ru', 'daddylive', 'daddy']):
            return 6
        elif any(d in url_lower for d in ['vavoo', 'shouurvki7jtfax', 'ngolpdkyoctjcddxshli469r']):
            return 8
        else:
            return 6
    elif '.m3u8' in url_lower:
        if any(d in url_lower for d in ['kiko2.ru', 'daddylive', 'daddy']):
            return 8
        elif any(d in url_lower for d in ['vavoo', 'shouurvki7jtfax', 'ngolpdkyoctjcddxshli469r']):
            return 10
        else:
            return 8
    else:
        if any(
            d in url_lower for d in [
                'vavoo',
                'shouurvki7jtfax',
                'ngolpdkyoctjcddxshli469r']):
            return 8
        else:
            return 6


def _get_vavoo_prefetch_entry(m3u_url, wait_timeout=0, consume=True):
    if not m3u_url or 'vavoo' not in m3u_url.lower():
        return None

    stream_id = get_stream_id_from_url(m3u_url)
    entry = VAVOO_M3U8_PREFETCH_CACHE.get(stream_id)
    if not entry:
        return None

    if entry.get('in_progress') and wait_timeout:
        event = entry.get('event')
        if event:
            enhanced_log(
                "[VAVOO_PREFETCH] Waiting for prefetch for %s up to %ds" %
                (stream_id, wait_timeout), "INFO", "AppCore")
            event.wait(wait_timeout)
            entry = VAVOO_M3U8_PREFETCH_CACHE.get(stream_id)
            if not entry:
                return None

    if entry.get('in_progress'):
        enhanced_log(
            "[VAVOO_PREFETCH] Prefetch still in progress for %s" % stream_id,
            "DEBUG",
            "AppCore")
        return None

    if time.time() - entry.get('timestamp', 0) > 45:
        VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
        return None

    content = entry.get('m3u8_content') or ''
    resolved_url = entry.get('resolved_url') or ''
    if content and not content.lstrip().startswith('#EXTM3U'):
        VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
        return None
    if not content and not resolved_url:
        VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
        return None

    enhanced_log(
        "[VAVOO_PREFETCH] M3U8 from prefetch for stream %s" % stream_id,
        "INFO",
        "AppCore")
    if consume:
        return VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
    return entry.copy()


def _clear_vavoo_resolved_url_cache(reason=""):
    """Clear only resolved Vavoo CDN URLs, preserving signature/session if possible."""
    if not VAVOO_AVAILABLE:
        return
    try:
        cache = getattr(vavoo_extractor, "_url_cache", None)
        if isinstance(cache, dict):
            cache.clear()
            enhanced_log(
                "[VAVOO] Resolved URL cache cleared%s" %
                (': ' + reason if reason else ''), "INFO", "AppCore")
        elif hasattr(vavoo_extractor, "clear_cache"):
            vavoo_extractor.clear_cache()
            enhanced_log(
                "[VAVOO] Extractor cache cleared%s" %
                (': ' + reason if reason else ''), "INFO", "AppCore")
    except Exception as exc:
        enhanced_log(
            "[VAVOO] Error clearing URL cache: %s" % exc,
            "DEBUG",
            "AppCore")


def prefetch_vavoo_m3u8(m3u_url, headers=None):
    """Start background Vavoo resolution before Enigma2 requests the M3U8.

    For Vavoo, prefetch prepares only the CDN URL. The playlist is downloaded
    by the real request, avoiding two parallel CDN downloads at channel change.
    """
    if not m3u_url or 'vavoo' not in m3u_url.lower():
        return False

    stream_id = get_stream_id_from_url(m3u_url)
    existing = VAVOO_M3U8_PREFETCH_CACHE.get(stream_id)
    if existing and time.time() - existing.get('timestamp', 0) < 20:
        enhanced_log(
            "[VAVOO_PREFETCH] Prefetch already available/in progress for %s" %
            stream_id, "DEBUG", "AppCore")
        return True

    event = threading.Event()
    VAVOO_M3U8_PREFETCH_CACHE[stream_id] = {
        'in_progress': True,
        'timestamp': time.time(),
        'event': event}

    def _worker():
        try:
            enhanced_log(
                "[VAVOO_PREFETCH] Starting prefetch for %s" % stream_id,
                "INFO",
                "AppCore")
            result = resolve_m3u8_link(m3u_url, headers or {})
            final_url = result.get("resolved_url")
            m3u_content = result.get("m3u8_content", "")
            result_headers = result.get("headers", {}).copy()

            if final_url:
                VAVOO_M3U8_PREFETCH_CACHE[stream_id] = {
                    'timestamp': time.time(),
                    'resolved_url': final_url,
                    'headers': result_headers,
                    'm3u8_content': m3u_content if m3u_content.lstrip().startswith('#EXTM3U') else '',
                    'event': event,
                }
                enhanced_log(
                    "[VAVOO_PREFETCH] M3U8 ready for %s: %d characters" %
                    (stream_id, len(m3u_content)), "INFO", "AppCore")
            else:
                VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
                enhanced_log(
                    "[VAVOO_PREFETCH] Invalid content for %s" % stream_id,
                    "WARNING",
                    "AppCore")
        except Exception as exc:
            VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
            _clear_vavoo_resolved_url_cache("prefetch failed")
            enhanced_log(
                "[VAVOO_PREFETCH] Failed for %s: %s" % (stream_id, exc),
                "WARNING",
                "AppCore")
        finally:
            event.set()

    threading.Thread(target=_worker, daemon=True).start()
    return True


def wait_vavoo_prefetch(m3u_url, timeout=0):
    """Return the Vavoo prefetch result, waiting briefly if it is in progress."""
    return _get_vavoo_prefetch_entry(
        m3u_url, wait_timeout=timeout, consume=False)


def _vavoo_playlist_header_variants(headers):
    clean_headers = {}
    for key, value in (headers or {}).items():
        if key.lower().startswith("x-easyproxy-"):
            continue
        clean_headers[key] = value

    variants = [clean_headers]
    variants.append({
        "User-Agent": "MediaHubMX/2",
        "Accept": "*/*",
        "Referer": "https://vavoo.to/",
        "Origin": "https://vavoo.to",
    })
    variants.append({
        "User-Agent": "VAVOO/2.6",
        "Accept": "*/*",
    })
    return variants


def _is_vavoo_cdn_url(url):
    url_lower = (url or "").lower()
    return any(d in url_lower for d in [
        "ngolpdkyoctjcddxshli469r",
        "shouurvki7jtfax",
    ])


def _fetch_vavoo_playlist(url, headers, timeout):
    request_headers = {}
    for key, value in (headers or {}).items():
        if key.lower().startswith("x-easyproxy-"):
            continue
        request_headers[key] = value

    enhanced_log(
        "[VAVOO] Downloading playlist with fresh session",
        "INFO",
        "AppCore")
    session = create_robust_session()
    try:
        return session.get(
            url,
            headers=request_headers if request_headers else None,
            timeout=timeout,
            verify=VERIFY_SSL,
            allow_redirects=True
        )
    finally:
        try:
            session.close()
        except Exception:
            pass


def get_proxy_for_url(url):
    config = config_manager.load_config()
    no_proxy_domains = [
        d.strip() for d in config.get(
            'NO_PROXY_DOMAINS',
            '').split(',') if d.strip()]

    # Check if it is a DaddyLive URL
    is_daddylive = (
        'kiko2.ru' in url.lower() or
        re.search(r'stream-\d+', url.lower()) is not None or
        'thedaddy.dad' in url.lower() or
        'daddylive' in url.lower()
    )

    # Check if it is Mixdrop (requires proxy for IP)
    is_mixdrop = 'mxcontent.net' in url.lower() or 'mixdrop' in url.lower()
    is_vavoo = any(d in url.lower() for d in [
        'vavoo.to',
        'ngolpdkyoctjcddxshli469r',
        'shouurvki7jtfax'
    ])

    if is_vavoo:
        proxy_pool = PROXY_LIST or DADDY_PROXY_LIST
        if proxy_pool:
            chosen_proxy = random.choice(proxy_pool)
            enhanced_log(
                "[VAVOO_PROXY] Using proxy for CDN/resolve Vavoo",
                "INFO",
                "AppCore")
            return {'http': chosen_proxy, 'https': chosen_proxy}

    # If DaddyLive or Mixdrop, use specific proxies
    if is_daddylive or is_mixdrop:
        daddy_proxies = get_daddy_proxy_list()
        if daddy_proxies:
            chosen_proxy = random.choice(daddy_proxies)
            return {'http': chosen_proxy, 'https': chosen_proxy}

    # Otherwise use general proxies
    if not PROXY_LIST:
        return None

    try:
        parsed_url = urlparse(url)
        if any(domain in parsed_url.netloc for domain in no_proxy_domains):
            return None
    except Exception:
        pass

    chosen_proxy = random.choice(PROXY_LIST)
    return {'http': chosen_proxy, 'https': chosen_proxy}


def extract_channel_id(url):
    """Extract channel ID from various URL formats"""
    match_premium = re.search(r'/premium(\d+)/mono\.m3u8$', url)
    if match_premium:
        return match_premium.group(1)

    match_player = re.search(
        r'/(?:watch|stream|cast|player)/stream-(\d+)\.php', url)
    if match_player:
        return match_player.group(1)

    return None


def refresh_freeshot_token(channel_name, old_token):
    """Automatic refresh of expired Freeshot token - OPTIMISED"""
    try:
        if not FREESHOT_AVAILABLE:
            return None

        enhanced_log(
            "[FREESHOT_REFRESH] Refreshing token for channel: %s" %
            channel_name, "INFO", "AppCore")

        # Map of common Freeshot channels
        channel_mapping = {
            'SkySport24IT': 'sky-sport-24-it',
            'SkySportUnoIT': 'sky-sport-uno-it',
            'SkySportDueIT': 'sky-sport-due-it',
            'SkySportCalcioIT': 'sky-sport-calcio-it',
            'SkySportArenaIT': 'sky-sport-arena-it',
            'SkySportMaxIT': 'sky-sport-max-it'
        }

        # Find Freeshot channel name
        freeshot_channel = channel_mapping.get(channel_name)
        if not freeshot_channel:
            # Improved fallback: automatic conversion
            freeshot_channel = channel_name.lower()
            freeshot_channel = freeshot_channel.replace('sky', 'sky-')
            freeshot_channel = freeshot_channel.replace('sport', 'sport-')
            freeshot_channel = freeshot_channel.replace('24', '-24')
            freeshot_channel = freeshot_channel.replace('it', '-it')
            freeshot_channel = freeshot_channel.replace('--', '-')
            if not freeshot_channel.endswith('-it'):
                freeshot_channel += '-it'

        # Use generic channel ID for Sky Sport 24
        channel_id = '383' if 'sport-24' in freeshot_channel else '26'

        # Extract stream from Freeshot with new token
        freeshot_url = "https://www.freeshot.live/live-tv/%s/%s" % (
            freeshot_channel, channel_id)
        enhanced_log(
            "[FREESHOT_REFRESH] Attempting refresh: %s" % freeshot_url,
            "DEBUG",
            "AppCore")

        fresh_result = freeshot_extractor.extract(freeshot_url)
        if fresh_result and fresh_result.get('resolved_url'):
            fresh_url = fresh_result['resolved_url']

            # Extract the new token
            token_match = re.search(r'token=([^&]+)', fresh_url)
            if token_match:
                new_token = token_match.group(1)
                enhanced_log(
                    "[FREESHOT_REFRESH] New token obtained: %s..." % new_token[:20],
                    "INFO",
                    "AppCore")
                return new_token
            else:
                enhanced_log(
                    "[FREESHOT_REFRESH] Token not found in URL",
                    "WARNING",
                    "AppCore")
                return None
        else:
            enhanced_log(
                "[FREESHOT_REFRESH] Extractor failed",
                "ERROR",
                "AppCore")
            return None

    except Exception as e:
        enhanced_log(
            "[FREESHOT_REFRESH] Token refresh error: %s" % e,
            "ERROR",
            "AppCore")
        return None


def get_stream_id_from_url(url):
    """
    Generate deterministic Stream ID per channel to avoid conflicts.

    Original problem: each resolution generated a random UUID → different stream_id
    for the same channel → Enigma2 cannot find cache → playback stops.

    SOLUTION: Use channel hash for a coherent Stream ID for the same channel.
    """
    import hashlib

    # For DaddyLive, use channel ID as base
    if 'daddyhd.com' in url or 'daddylive' in url:
        channel_match = re.search(r'[?&]id=(\d+)', url)
        if channel_match:
            channel_id = channel_match.group(1)
            stream_id = hashlib.sha256(
                ("daddy_%s" % channel_id).encode()).hexdigest()[:12]
            enhanced_log(
                "[STREAM_ID] Deterministic stream ID for DaddyLive channel %s: %s" %
                (channel_id, stream_id), "INFO", "AppCore")
            return stream_id

    # For VIX, use stable IDs instead of full URL (token/rendition change
    # often)
    if 'vixsrc.to/tv/' in url or 'vixcloud.co/tv/' in url:
        tv_match = re.search(r'/tv/(\d+)(?:/(\d+))?(?:/(\d+))?', url)
        if tv_match:
            tv_key = "_".join([part for part in tv_match.groups() if part])
            stream_id = hashlib.sha256(
                ("vix_tv_%s" % tv_key).encode()).hexdigest()[:12]
            enhanced_log(
                "[STREAM_ID] Deterministic stream ID for VIX tv %s: %s" %
                (tv_key, stream_id), "INFO", "AppCore")
            return stream_id

    # For VIX, use playlist ID as base (covers vixsrc.to, vixcloud.co,
    # calpezz8.space, etc.)
    playlist_match = re.search(r'/playlist/(\d+)', url)
    if playlist_match and any(
        d in url.lower() for d in [
            'vixsrc',
            'vixcloud',
            'calpezz',
            'vix-content']):
        playlist_id = playlist_match.group(1)
        stream_id = hashlib.sha256(
            ("vix_%s" % playlist_id).encode()).hexdigest()[:12]
        enhanced_log(
            "[STREAM_ID] Deterministic stream ID for VIX playlist %s: %s" %
            (playlist_id, stream_id), "INFO", "AppCore")
        return stream_id

    # For Freeshot, use channel name as base
    if 'lovecdn.ru' in url:
        channel_match = re.search(r'lovecdn\.ru/([^/]+)/', url)
        if channel_match:
            channel_name = channel_match.group(1)
            stream_id = hashlib.sha256(
                ("freeshot_%s" % channel_name).encode()).hexdigest()[:12]
            enhanced_log(
                "[STREAM_ID] Deterministic stream ID for Freeshot %s: %s" %
                (channel_name, stream_id), "INFO", "AppCore")
            return stream_id

    # For VAVOO, extract channel ID
    if 'vavoo' in url.lower():
        channel_match = re.search(r'[?&]id=([^&]+)', url)
        if channel_match:
            channel_id = channel_match.group(1)
            stream_id = hashlib.sha256(
                ("vavoo_%s" % channel_id).encode()).hexdigest()[:12]
            enhanced_log(
                "[STREAM_ID] Deterministic stream ID for Vavoo %s: %s" %
                (channel_id, stream_id), "INFO", "AppCore")
            return stream_id

    # For other URLs, use the URL itself as base (less ideal, but stable)
    stream_id = hashlib.sha256(url.encode()).hexdigest()[:12]
    enhanced_log(
        "[STREAM_ID] Generic deterministic stream ID: %s" % stream_id,
        "INFO",
        "AppCore")
    return stream_id


def is_daddy_domain(url):
    """Check if URL belongs to daddy domains for detailed logging"""
    if not url:
        return False
    url_lower = url.lower()
    return any(d in url_lower for d in [
        'kiko2.ru', 'giokko.ru', 'daddylive', 'daddy', 'dlhd', 'thedaddy.dad',
        'chevy.', 'tigertestxtg.sbs', 'soyspace.cyou'
    ])


def detect_m3u_type(content):
    """Detect if it is an M3U (IPTV list) or M3U8 (HLS stream)"""
    if "#EXTM3U" in content and "#EXTINF" in content:
        return "m3u8"
    return "m3u"


def replace_key_uri(line, headers_query):
    """Replace AES-128 key URI with proxy"""
    match = re.search(r'URI="([^"]+)"', line)
    if match:
        key_url = match.group(1)
        proxied_key_url = "http://127.0.0.1:7860/proxy/key?url=%s&%s" % (
            quote(key_url), headers_query)
        return line.replace(key_url, proxied_key_url)
    return line


def get_proxy_with_fallback(url, max_retries=3):
    """Get a proxy with automatic fallback in case of error"""
    if not PROXY_LIST:
        return None

    for attempt in range(max_retries):
        try:
            proxy_config = get_proxy_for_url(url)
            if proxy_config:
                return proxy_config
        except Exception:
            continue

    return None


# Simplified Route Registry
class RouteRegistry:
    def __init__(self):
        self.routes = {}

    def route(self, name):
        def decorator(func):
            self.routes[name] = func
            return func

        return decorator

    def dispatch(self, name, *args, **kwargs):
        enhanced_log(
            "[DEBUG] dispatch %s: args=%s, kwargs=%s" % (name, args, kwargs),
            "DEBUG",
            "AppCore")

        if name in self.routes:
            return self.routes[name](**kwargs)
        raise ValueError("Route '%s' not found" % name)


route_registry = RouteRegistry()


# MPD proxy for DASH
@route_registry.route('/proxy/mpd')
def proxy_mpd(request=None, **kwargs):
    """MPD proxy - Enigma2 does not support DASH natively"""
    mpd_url = kwargs.get('url', '').strip()
    enhanced_log(
        "[MPD] Enigma2 does not support DASH: %s..." % mpd_url[:100],
        "WARNING",
        "AppCore")

    m3u8_content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-ENDLIST\n"
        "# Stream MPD/DASH not supported by Enigma2\n"
    )
    return {
        'content': m3u8_content.encode(),
        'status': 200,
        'content_type': 'application/vnd.apple.mpegurl'
    }


# M3U proxy WITHOUT CACHE
@route_registry.route('/proxy/m3u')
def proxy_m3u(request=None, **kwargs):
    """M3U proxy WITHOUT CACHE - Direct results"""
    enhanced_log("Proxy M3U", "INFO", "AppCore")

    m3u_url = kwargs.get('url', '').strip()
    m3u_url = unquote(m3u_url)
    enhanced_log("[DEBUG] Received URL: %s" % m3u_url, "DEBUG", "AppCore")

    if not m3u_url:
        enhanced_log("[DEBUG] Empty URL!", "ERROR", "AppCore")

        return {
            'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }

    try:
        # Extract custom headers from parameters (User-Agent, h_Referer,
        # etc.)
        custom_headers = {
            unquote(key[2:]).replace("_", "-"): unquote(value).strip()
            for key, value in kwargs.items()
            if key.lower().startswith("h_")
        }
        if custom_headers:
            enhanced_log(
                "[PROXY_M3U] Extracted custom headers: %s" % list(
                    custom_headers.keys()),
                "DEBUG",
                "AppCore")

        # =====================================================================
        # EXTERNAL PROXY: Complete delegation
        # =====================================================================
        if EXTERNAL_PROXY_AVAILABLE and is_proxy_esterno_attivo():
            enhanced_log("Delegating to external proxy", "INFO", "AppCore")
            external_result = resolve_via_proxy_esterno(
                m3u_url, custom_headers)
            if external_result and external_result.get("m3u8_content"):
                enhanced_log(
                    "M3U8 obtained from external proxy",
                    "INFO",
                    "AppCore")
                return {
                    'content': external_result["m3u8_content"].encode(),
                    'status': 200,
                    'content_type': 'application/vnd.apple.mpegurl'
                }
            elif external_result and external_result.get("resolved_url"):
                enhanced_log(
                    "Using resolved URL from external proxy",
                    "INFO",
                    "AppCore")
                m3u_url = external_result["resolved_url"]
                if external_result.get("headers"):
                    custom_headers.update(external_result["headers"])
        # =====================================================================

        # Extract dlhd_masked parameter from request (will be updated after
        # resolve)
        dlhd_masked_param = kwargs.get('dlhd_masked', '0') == '1'
        enhanced_log(
            "[DLHD_MASKED] Initial dlhd_masked parameter: %s" %
            dlhd_masked_param, "DEBUG", "AppCore")

        # Deterministic stream ID avoids accidental clearance
        current_stream_id = get_stream_id_from_url(m3u_url)
        is_vavoo_request = 'vavoo' in m3u_url.lower()
        if is_vavoo_request:
            cached_m3u8 = VAVOO_FINAL_M3U8_CACHE.get(current_stream_id)
            if cached_m3u8:
                cached_content = cached_m3u8.get('content')
                cached_age = time.time() - cached_m3u8.get('timestamp', 0)
                if cached_content and cached_m3u8.get(
                        'in_progress') and cached_age < 60:
                    enhanced_log(
                        "[VAVOO_M3U8_CACHE] Refresh already in progress, reusing last valid playlist (%ds)" %
                        cached_age, "INFO", "AppCore")
                    return {
                        'content': cached_content,
                        'status': 200,
                        'content_type': 'application/vnd.apple.mpegurl'
                    }
                if cached_content and cached_age < 6:
                    enhanced_log(
                        "[VAVOO_M3U8_CACHE] Recent playlist from cache (%ds)" %
                        cached_age, "INFO", "AppCore")
                    return {
                        'content': cached_content,
                        'status': 200,
                        'content_type': 'application/vnd.apple.mpegurl'
                    }

            VAVOO_FINAL_M3U8_CACHE[current_stream_id] = {
                'content': cached_m3u8.get('content') if cached_m3u8 else None,
                'timestamp': cached_m3u8.get(
                    'timestamp',
                    0) if cached_m3u8 else 0,
                'in_progress': True,
                'started': time.time(),
            }
        prefetched_result = _get_vavoo_prefetch_entry(
            m3u_url, wait_timeout=2 if is_vavoo_request else 0)

        # Check if it is an automatic refresh of the same channel
        # IMPROVED: Use stream_id to identify if it is the same channel
        is_same_channel = current_stream_id in STREAM_KEY_INFO

        # For multi-track providers (VixCloud etc.), also check if any existing
        # stream shares the same base playlist ID to avoid wiping sibling
        # tracks
        if not is_same_channel and STREAM_KEY_INFO:
            playlist_match = re.search(r'/playlist/(\d+)', m3u_url)
            if playlist_match:
                playlist_id = playlist_match.group(1)
                is_same_channel = any(
                    info.get('playlist_id') == playlist_id
                    for info in STREAM_KEY_INFO.values()
                )
                if is_same_channel:
                    enhanced_log(
                        "[CACHE_REUSE] Same playlist session (%s), keeping existing streams" %
                        playlist_id, "INFO", "AppCore")

        if not is_same_channel:
            # Channel change, clear cache to avoid conflicts
            clear_stream_cache()
            enhanced_log(
                "[CACHE_CLEAR] Cache cleared for channel change. New stream_id: %s" %
                current_stream_id, "INFO", "AppCore")
        else:
            # If same channel, reuse cache but update timestamp
            enhanced_log(
                "[CACHE_REUSE] Same channel (stream_id: %s), reusing cache" %
                current_stream_id, "INFO", "AppCore")
            # Intelligent JWT token expiry check for DaddyLive
            if 'daddyhd.com' in m3u_url or 'daddylive' in m3u_url:
                try:
                    stream_info = STREAM_KEY_INFO[current_stream_id]
                    headers = stream_info.get('headers', {})
                    auth_header = headers.get('Authorization', '')

                    if auth_header.startswith('Bearer '):
                        token = auth_header[7:]
                        try:
                            import jwt
                            decoded = jwt.decode(
                                token, options={
                                    "verify_signature": False})
                            exp_time = decoded.get('exp', 0)
                            current_time = time.time()
                            remaining_time = exp_time - current_time

                            # Refresh only if less than 2 minutes remain to
                            # expiry
                            if remaining_time < 120:
                                enhanced_log(
                                    "[TOKEN_REFRESH] Token expires in %ds, refresh needed" %
                                    int(remaining_time), "INFO", "AppCore")

                                # Invalidate DLHD cache for this channel
                                if DLHD_AVAILABLE and dlhd_extractor:
                                    try:
                                        channel_match = re.search(
                                            r'[?&]id=(\d+)', m3u_url)
                                        if channel_match:
                                            channel_id = channel_match.group(1)
                                            if hasattr(
                                                    dlhd_extractor, 'cache') and channel_id in dlhd_extractor.cache:
                                                del dlhd_extractor.cache[channel_id]
                                                enhanced_log(
                                                    "[DLHD_CACHE] Cache invalidated for channel %s" %
                                                    channel_id, "INFO", "AppCore")
                                    except Exception as cache_error:
                                        enhanced_log(
                                            "[DLHD_CACHE] Cache invalidation error: %s" %
                                            cache_error, "DEBUG", "AppCore")

                                # Remove stream to force new download
                                del STREAM_KEY_INFO[current_stream_id]
                                keys_to_remove = [
                                    k for k in AES_KEY_CACHE.keys() if k.startswith(current_stream_id)]
                                for k in keys_to_remove:
                                    del AES_KEY_CACHE[k]
                                is_same_channel = False  # Force new download
                                enhanced_log(
                                    "[CACHE_INVALIDATED] Cache invalidated for token refresh", "INFO", "AppCore")
                            else:
                                enhanced_log(
                                    "[TOKEN_VALID] Token valid for %ds" %
                                    int(remaining_time), "DEBUG", "AppCore")
                        except ImportError:
                            enhanced_log(
                                "[TOKEN_CHECK] PyJWT not available, using time fallback",
                                "WARNING",
                                "AppCore")
                            # Fallback: refresh every 4 minutes if PyJWT not
                            # available
                            last_used = stream_info.get('last_used', 0)
                            if time.time() - last_used > 240:
                                enhanced_log(
                                    "[FALLBACK_REFRESH] Fallback refresh after 4 minutes", "INFO", "AppCore")
                                del STREAM_KEY_INFO[current_stream_id]
                                is_same_channel = False
                        except Exception as e:
                            enhanced_log(
                                "[TOKEN_CHECK] Token check error: %s" % e,
                                "WARNING",
                                "AppCore")
                except Exception as e:
                    enhanced_log(
                        "[TOKEN_CHECK] Token control error: %s" % e,
                        "WARNING",
                        "AppCore")

        enhanced_log(
            "[DEBUG] Calling resolve_m3u8_link directly",
            "DEBUG",
            "AppCore")
        if prefetched_result:
            enhanced_log(
                "[VAVOO_PREFETCH] Using pre-resolved result",
                "INFO",
                "AppCore")
            result = prefetched_result
            if custom_headers:
                result["headers"] = {
                    **result.get("headers", {}), **custom_headers}
        else:
            result = resolve_m3u8_link(m3u_url, custom_headers)
        enhanced_log(
            "[DEBUG] Resolve result: %s" % result,
            "DEBUG",
            "AppCore")

        if not result.get("resolved_url") and not result.get("m3u8_content"):
            return {
                'content': "Error: Unable to resolve URL to a valid M3U8.".encode(),
                'status': 500,
                'content_type': 'text/plain'}

        final_url = result.get("resolved_url")

        # Automatically detect masked DLHD segments AFTER obtaining final_url
        is_dlhd_domain = final_url and is_daddy_domain(final_url)
        dlhd_masked = kwargs.get(
            'dlhd_masked',
            '0') == '1' or is_dlhd_domain or is_daddy_domain(m3u_url)
        enhanced_log(
            "[DLHD_MASKED] dlhd_masked parameter: %s (auto-detected: %s)" %
            (dlhd_masked, is_dlhd_domain), "INFO", "AppCore")

        # Initialize m3u_content before use
        m3u_content = result.get("m3u8_content", "")
        current_headers_for_proxy = result.get("headers", {}).copy()
        current_headers_for_proxy.update(custom_headers or {})

        if final_url and is_direct_media_url(final_url):
            headers_query = "&".join(["h_%s=%s" % (quote(k), quote(
                v)) for k, v in current_headers_for_proxy.items()])
            media_stream_id = get_stream_id_from_url(m3u_url)
            encoded_media_url = quote(final_url, safe='')
            proxy_media_url = "http://127.0.0.1:7860/proxy/ts?url=%s&fmp4=1&stream_id=%s" % (
                encoded_media_url, media_stream_id)
            if headers_query:
                proxy_media_url += "&%s" % headers_query
            enhanced_log(
                "[DIRECT_MEDIA] Direct URL resolved, generating playlist wrapper: %s..." % final_url[:80],
                "INFO",
                "AppCore")
            return {
                'content': b'',
                'status': 302,
                'content_type': 'video/mp4',
                'redirect_url': proxy_media_url
            }

        # If the resolver (e.g. Vix) hasn't already provided the content,
        # download it
        if not m3u_content:
            # Reduced timeouts for Enigma2
            timeout_to_use = 6 if 'kiko2.ru' in final_url else get_dynamic_timeout(
                final_url)
            enhanced_log(
                "[M3U8_TIMEOUT] Optimised timeout: %ds" % timeout_to_use,
                "DEBUG",
                "AppCore")

            # Use proxy for Mixdrop
            proxy_config = get_proxy_for_url(final_url)
            proxy_url = proxy_config['http'] if proxy_config else None

            if VAVOO_AVAILABLE and is_vavoo_link(
                    m3u_url) and _is_vavoo_cdn_url(final_url):
                m3u_response = _fetch_vavoo_playlist(
                    final_url, current_headers_for_proxy, timeout_to_use)
            else:
                m3u_response = make_persistent_request(
                    final_url,
                    headers=current_headers_for_proxy,
                    timeout=timeout_to_use,
                    proxy_url=proxy_url,
                    allow_redirects=True
                )
            if (
                m3u_response.status_code == 403
                and VAVOO_AVAILABLE
                and is_vavoo_link(m3u_url)
            ):
                enhanced_log(
                    "[VAVOO] 403 on resolved CDN URL, clearing cache and retrying once",
                    "WARNING",
                    "AppCore")
                _clear_vavoo_resolved_url_cache("403 playlist")
                result = resolve_m3u8_link(m3u_url, custom_headers)
                final_url = result.get("resolved_url")
                m3u_content = result.get("m3u8_content", "")
                current_headers_for_proxy = result.get("headers", {}).copy()
                current_headers_for_proxy.update(custom_headers or {})
                if not m3u_content and final_url:
                    timeout_to_use = get_dynamic_timeout(final_url)
                    proxy_config = get_proxy_for_url(final_url)
                    proxy_url = proxy_config['http'] if proxy_config else None
                    if _is_vavoo_cdn_url(final_url):
                        m3u_response = _fetch_vavoo_playlist(
                            final_url, current_headers_for_proxy, timeout_to_use)
                    else:
                        m3u_response = make_persistent_request(
                            final_url,
                            headers=current_headers_for_proxy,
                            timeout=timeout_to_use,
                            proxy_url=proxy_url,
                            allow_redirects=True
                        )
            if (
                m3u_response.status_code == 403
                and VAVOO_AVAILABLE
                and is_vavoo_link(m3u_url)
                and final_url
            ):
                enhanced_log(
                    "[VAVOO] Persistent 403, trying header variants",
                    "WARNING",
                    "AppCore")
                for variant_headers in _vavoo_playlist_header_variants(
                        current_headers_for_proxy):
                    if _is_vavoo_cdn_url(final_url):
                        m3u_response = _fetch_vavoo_playlist(
                            final_url, variant_headers, timeout_to_use)
                    else:
                        m3u_response = make_persistent_request(
                            final_url,
                            headers=variant_headers,
                            timeout=timeout_to_use,
                            proxy_url=proxy_url,
                            allow_redirects=True
                        )
                    if m3u_response.status_code != 403:
                        current_headers_for_proxy = variant_headers
                        enhanced_log(
                            "[VAVOO] CDN playlist accepted with headers: %s" %
                            list(
                                variant_headers.keys()),
                            "INFO",
                            "AppCore")
                        break
            if not m3u_content:
                m3u_response.raise_for_status()
                m3u_content = m3u_response.text
                final_url = m3u_response.url  # Update with final URL after redirects

            # VALIDATION: Verify it is a valid M3U8
            if not m3u_content.strip().startswith('#EXTM3U'):
                enhanced_log(
                    "[M3U8_VALIDATION] Content is not a valid M3U8 (probably HTML)",
                    "ERROR",
                    "AppCore")
                enhanced_log(
                    "[M3U8_VALIDATION] First 200 characters: %s" % m3u_content[:200],
                    "DEBUG",
                    "AppCore")
                return {
                    'content': "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-ENDLIST\n# Error: URL does not return valid M3U8\n".encode(),
                    'status': 200,
                    'content_type': 'application/vnd.apple.mpegurl'}
        else:
            enhanced_log(
                "[proxy_m3u] Using pre-processed M3U8 content from resolver.",
                "INFO",
                "AppCore")

        enhanced_log(
            "[M3U8_CONTENT] M3U8 content received (%d characters):" %
            len(m3u_content), "DEBUG", "AppCore")
        enhanced_log(
            "[M3U8_CONTENT] First 500 characters: %s" % m3u_content[:500],
            "DEBUG",
            "AppCore")

        parsed_url = urlparse(final_url)
        base_url = "%s://%s%s/" % (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path.rsplit('/', 1)[0]
        )

        # CRITICAL: Create query string with headers from resolution
        headers_query = "&".join(["h_%s=%s" % (quote(k), quote(
            v)) for k, v in current_headers_for_proxy.items()])
        stream_id = get_stream_id_from_url(m3u_url)

        # CRITICAL: Save stream information for TS segments
        extract_key_info_from_m3u8(
            m3u_content.splitlines(),
            stream_id,
            base_url,
            current_headers_for_proxy,
            result)

        # Always save basic stream info even without AES key
        playlist_id_match = re.search(r'/playlist/(\d+)', m3u_url)
        playlist_id_val = playlist_id_match.group(
            1) if playlist_id_match else None
        if stream_id not in STREAM_KEY_INFO:
            STREAM_KEY_INFO[stream_id] = {
                'headers': current_headers_for_proxy or {},
                'base_url': base_url,
                'is_daddy': is_daddy_domain(final_url),
                'is_freeshot': 'lovecdn.ru' in final_url.lower(),
                'playlist_id': playlist_id_val,
            }
            enhanced_log(
                "[STREAM_INFO] Saved base info for stream %s" % stream_id,
                "DEBUG",
                "AppCore")
        else:
            # CRITICAL UPDATE: Update headers if stream already exists
            existing_headers = STREAM_KEY_INFO[stream_id].get('headers', {})
            existing_headers.update(current_headers_for_proxy or {})
            STREAM_KEY_INFO[stream_id]['headers'] = existing_headers
            enhanced_log(
                "[STREAM_INFO] Updated headers for existing stream %s" %
                stream_id, "DEBUG", "AppCore")
            enhanced_log(
                "[STREAM_INFO] Saved headers: %s" % list(
                    existing_headers.keys()),
                "DEBUG",
                "AppCore")

        # Clean expired segments more frequently
        if random.randint(
                1, 5) == 1:  # 20% probability for more frequent cleaning
            cleanup_expired_segments()

        modified_m3u8 = []
        aes_key_line = None  # Save the AES key line for DLHD

        # =====================================================================
        # EXTERNAL PROXY: rewrite segments to point to external proxy
        # When active, the external proxy handles decrypt/conversion entirely.
        # We only rewrite segment and key URLs; all other M3U8 tags are kept.
        # =====================================================================
        use_ext_proxy_segments = (
            EXTERNAL_PROXY_AVAILABLE
            and is_proxy_esterno_attivo()
            and bool(build_external_segment_url('http://x'))
        )
        if use_ext_proxy_segments:
            enhanced_log(
                "[EXT_PROXY_M3U8] Rewriting segments to external proxy",
                "INFO", "AppCore")
            ext_rewritten = []
            for line in m3u_content.splitlines():
                line = line.strip()
                if line.startswith("#EXT-X-KEY") and 'AES-128' in line:
                    uri_match = re.search(r'URI="([^"]+)"', line)
                    if uri_match:
                        raw_key_url = urljoin(base_url, uri_match.group(1))
                        ext_key_url = build_external_key_url(raw_key_url)
                        if ext_key_url:
                            line = line.replace(
                                uri_match.group(1), ext_key_url)
                    ext_rewritten.append(line)
                elif line.startswith("#EXT-X-MAP") and 'URI="' in line:
                    uri_match = re.search(r'URI="([^"]+)"', line)
                    if uri_match:
                        init_url = urljoin(base_url, uri_match.group(1))
                        ext_init_url = build_external_segment_url(init_url)
                        if ext_init_url:
                            line = line.replace(
                                uri_match.group(1), ext_init_url)
                    ext_rewritten.append(line)
                elif line.startswith("#EXT-X-MEDIA") and 'URI="' in line:
                    if is_subtitle_media_tag(line):
                        continue
                    uri_match = re.search(r'URI="([^"]+)"', line)
                    if uri_match:
                        media_url = urljoin(base_url, uri_match.group(1))
                        if not is_subtitle_resource(media_url):
                            ext_media_url = build_external_segment_url(
                                media_url)
                            if ext_media_url:
                                line = line.replace(
                                    uri_match.group(1), ext_media_url)
                    ext_rewritten.append(line)
                elif line and not line.startswith('#'):
                    segment_url = urljoin(base_url, line)
                    if is_subtitle_resource(segment_url):
                        continue
                    if '.m3u8' in segment_url.lower() or 'playlist' in segment_url.lower():
                        ext_seg_url = build_external_segment_url(segment_url)
                        ext_rewritten.append(ext_seg_url or segment_url)
                    else:
                        ext_seg_url = build_external_segment_url(segment_url)
                        ext_rewritten.append(ext_seg_url or segment_url)
                else:
                    ext_rewritten.append(line)
            final_m3u8 = "\n".join(ext_rewritten) + "\n"
            enhanced_log(
                "[EXT_PROXY_M3U8] Rewrite done (%d lines)" %
                len(ext_rewritten), "INFO", "AppCore")
            return {
                'content': final_m3u8.encode(),
                'status': 200,
                'content_type': 'application/vnd.apple.mpegurl'
            }
        # =====================================================================

        for line in m3u_content.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-KEY") and 'AES-128' in line:
                # For DLHD, keep the AES key in M3U8
                if is_daddy_domain(final_url) or is_daddy_domain(m3u_url):
                    uri_match = re.search(r'URI="([^"]+)"', line)
                    if uri_match:
                        key_url = urljoin(base_url, uri_match.group(1))
                        proxy_key_url = "http://127.0.0.1:7860/proxy/key?url=%s&%s" % (
                            quote(key_url), headers_query)
                        aes_key_line = line.replace(
                            uri_match.group(1), proxy_key_url)
                        enhanced_log(
                            "[DLHD_KEY] AES key kept in M3U8: %s" % key_url[-30:],
                            "INFO",
                            "AppCore")
                continue
            elif line.startswith("#EXT-X-MAP") and 'URI="' in line:
                # OPTIMISED SOLUTION: For fMP4, keep EXT-X-MAP for native
                # compatibility
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    init_url = urljoin(base_url, uri_match.group(1))
                    enhanced_log(
                        "[INIT_MAP] Init segment URL: %s" % init_url,
                        "INFO",
                        "AppCore")

                    # Ensure STREAM_KEY_INFO exists
                    if stream_id not in STREAM_KEY_INFO:
                        STREAM_KEY_INFO[stream_id] = {
                            'headers': current_headers_for_proxy or {},
                            'base_url': base_url,
                            'is_daddy': is_daddy_domain(final_url),
                            'is_freeshot': 'lovecdn.ru' in final_url.lower()
                        }

                    # NEW APPROACH: For Freeshot, keep EXT-X-MAP in M3U8
                    # Modern Enigma2 can handle init segment automatically
                    if STREAM_KEY_INFO[stream_id].get('is_freeshot', False):
                        # Transform URI to proxy to maintain headers
                        if headers_query:
                            proxy_init_url = "http://127.0.0.1:7860/proxy/ts?url=%s&fmp4=1&stream_id=%s&%s" % (
                                quote(init_url), stream_id, headers_query)
                        else:
                            proxy_init_url = "http://127.0.0.1:7860/proxy/ts?url=%s&fmp4=1&stream_id=%s" % (
                                quote(init_url), stream_id)

                        # Replace original URI with proxy
                        line = line.replace(uri_match.group(1), proxy_init_url)
                        enhanced_log(
                            "[INIT_MAP] EXT-X-MAP kept with proxy for Freeshot",
                            "INFO",
                            "AppCore")
                        modified_m3u8.append(line)
                        continue
                    else:
                        # For other providers, download and save init segment
                        # (original behaviour)
                        try:
                            init_response = make_persistent_request(
                                init_url,
                                headers=current_headers_for_proxy,
                                timeout=8
                            )
                            init_response.raise_for_status()
                            init_content = init_response.content

                            if len(init_content) >= 8:
                                STREAM_KEY_INFO[stream_id]['init_segment'] = init_content
                                STREAM_KEY_INFO[stream_id]['init_timestamp'] = time.time(
                                )
                                enhanced_log(
                                    "[INIT_DOWNLOAD] Init segment saved: %d bytes" %
                                    len(init_content), "INFO", "AppCore")

                            # Remove EXT-X-MAP for compatibility
                            enhanced_log(
                                "[INIT_SKIP] Removed EXT-X-MAP for Enigma2 compatibility", "INFO", "AppCore")
                            continue

                        except Exception as e:
                            enhanced_log(
                                "[INIT_DOWNLOAD] Init download error: %s" %
                                e, "ERROR", "AppCore")
                            # Remove EXT-X-MAP even on error
                            continue
                else:
                    enhanced_log(
                        "[INIT_SKIP] EXT-X-MAP without valid URI",
                        "WARNING",
                        "AppCore")
                    continue
            elif line.startswith("#EXT-X-MEDIA") and 'URI="' in line:
                if is_subtitle_media_tag(line):
                    enhanced_log(
                        "[SUBTITLE_SKIP] Subtitle track removed from M3U8 to avoid VTT requests via TS",
                        "INFO",
                        "AppCore")
                    continue

                # Transform audio/subtitle URI to proxy URL
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    media_url = uri_match.group(1)
                    media_url = urljoin(base_url, media_url)
                    if is_subtitle_resource(media_url):
                        enhanced_log(
                            "[SUBTITLE_SKIP] Subtitle playlist removed: %s" % media_url[-60:],
                            "INFO",
                            "AppCore")
                        continue
                    if headers_query:
                        proxy_media_url = "http://127.0.0.1:7860/proxy/m3u?url=%s&%s" % (
                            quote(media_url), headers_query)
                    else:
                        proxy_media_url = "http://127.0.0.1:7860/proxy/m3u?url=%s" % quote(
                            media_url)
                    line = line.replace(uri_match.group(1), proxy_media_url)
                modified_m3u8.append(line)
            elif line and not line.startswith("#"):
                segment_url = urljoin(base_url, line)
                segment_url_lower = segment_url.lower()

                if is_subtitle_resource(segment_url):
                    enhanced_log(
                        "[SUBTITLE_SKIP] Subtitle segment discarded: %s" %
                        line, "INFO", "AppCore")
                    continue

                # Improved validation for DLHD segments
                is_dlhd_domain = is_daddy_domain(
                    segment_url_lower) or dlhd_masked

                if is_dlhd_domain:
                    # For DLHD, keep ALL segments from DLHD domains (even encoded ones)
                    # Only discard real images, fonts, CSS/JS
                    if any(
                        ext in segment_url_lower for ext in [
                            '.png',
                            '.jpg',
                            '.gif',
                            '.svg',
                            '.xml',
                            '.json',
                            '.woff',
                            '.ttf',
                            '.ico',
                            '.css',
                            '.js']):
                        enhanced_log(
                            "[SEGMENT_SKIP] Non-video segment discarded (DLHD): %s" %
                            line, "WARNING", "AppCore")
                        continue
                    # Accept ALL other segments from DLHD domains (including
                    # encoded ones)
                    enhanced_log(
                        "[DLHD_SEGMENT] DLHD segment accepted: %s..." % line[:50],
                        "DEBUG",
                        "AppCore")
                else:
                    # For other providers, discard .html/.css/.js/.txt normally
                    if any(
                        ext in segment_url_lower for ext in [
                            '.js',
                            '.html',
                            '.txt',
                            '.css',
                            '.json']):
                        enhanced_log(
                            "[SEGMENT_SKIP] Non-video segment discarded: %s" %
                            line, "WARNING", "AppCore")
                        continue

                # Determine if it is a TS, fMP4 or playlist segment
                if '.m3u8' in segment_url_lower or 'playlist' in segment_url_lower:
                    # It is a playlist, use proxy/m3u
                    if headers_query:
                        proxy_url = "http://127.0.0.1:7860/proxy/m3u?url=%s&%s" % (
                            quote(segment_url), headers_query)
                    else:
                        proxy_url = "http://127.0.0.1:7860/proxy/m3u?url=%s" % quote(
                            segment_url)
                elif '.fmp4' in segment_url_lower:
                    # OPTIMISED SOLUTION: For Freeshot, use direct fMP4 (no conversion)
                    # Modern Enigma2 handles fMP4 natively
                    encoded_url = quote(segment_url, safe='')
                    if headers_query:
                        proxy_url = "http://127.0.0.1:7860/proxy/ts?url=%s&fmp4=1&stream_id=%s&%s" % (
                            encoded_url, stream_id, headers_query)
                    else:
                        proxy_url = "http://127.0.0.1:7860/proxy/ts?url=%s&fmp4=1&stream_id=%s" % (
                            encoded_url, stream_id)
                    enhanced_log(
                        "[FMP4_DIRECT] Direct fMP4 segment: %s" % segment_url[-50:],
                        "INFO",
                        "AppCore")
                    enhanced_log(
                        "[FMP4_DIRECT] Proxy URL: %s..." % proxy_url[:100],
                        "DEBUG",
                        "AppCore")
                else:
                    # It is a TS segment (any other extension, including .html for DLHD), use proxy/ts
                    # stream_id MUST be in the query string for decryption
                    if headers_query:
                        proxy_url = "http://127.0.0.1:7860/proxy/ts?url=%s&stream_id=%s&%s" % (
                            quote(segment_url), stream_id, headers_query)
                    else:
                        proxy_url = "http://127.0.0.1:7860/proxy/ts?url=%s&stream_id=%s" % (
                            quote(segment_url), stream_id)

                    # Specific log for DLHD segments (including encoded ones)
                    if is_dlhd_domain:
                        enhanced_log("[DLHD_SEGMENT] DLHD segment processed as TS: %s" % segment_url.split(
                            '/')[-1][:30], "INFO", "AppCore")
                    if dlhd_masked:
                        proxy_url += "&dlhd_masked=1"

                enhanced_log(
                    "[SEGMENT_PROXY] Segment transformed to proxy: %s" % segment_url[-50:],
                    "DEBUG",
                    "AppCore")
                modified_m3u8.append(proxy_url)
            else:
                modified_m3u8.append(line)

        # Add AES key at the beginning for DLHD if present
        if aes_key_line:
            # Insert key after #EXT-X-VERSION
            final_lines = []
            key_inserted = False
            for line in modified_m3u8:
                final_lines.append(line)
                if line.startswith('#EXT-X-VERSION') and not key_inserted:
                    final_lines.append(aes_key_line)
                    key_inserted = True
            modified_m3u8 = final_lines

        # If M3U8 is empty, try alternative .m3u8 URL
        segment_lines = [line for line in modified_m3u8 if line and not line.startswith(
            '#') and line.strip()]
        if len(segment_lines) == 0:
            enhanced_log(
                "[M3U8_EMPTY] M3U8 empty - TRYING ALTERNATIVE .m3u8 URL",
                "WARNING",
                "AppCore")

            # Try .m3u8 URL instead of .css
            if final_url.endswith('.css'):
                alt_url = final_url.replace('.css', '.m3u8')
                enhanced_log(
                    "[M3U8_ALT] Trying alternative URL: %s" % alt_url,
                    "INFO",
                    "AppCore")

                try:
                    alt_response = make_persistent_request(
                        alt_url,
                        headers=current_headers_for_proxy,
                        timeout=get_dynamic_timeout(alt_url)
                    )

                    if alt_response.status_code == 200:
                        alt_content = alt_response.text
                        if alt_content.strip().startswith('#EXTM3U') and 'EXTINF' in alt_content:
                            # Verify it contains real video segments
                            alt_segments = [line for line in alt_content.splitlines(
                            ) if line and not line.startswith('#') and line.strip()]
                            video_segments = [
                                seg for seg in alt_segments if not any(
                                    ext in seg.lower() for ext in [
                                        '.js', '.html', '.txt', '.css', '.json'])]

                            if len(video_segments) > 0:
                                enhanced_log(
                                    "[M3U8_ALT] Alternative URL with %d video segments" %
                                    len(video_segments), "INFO", "AppCore")

                                # Replace content
                                m3u_content = alt_content
                                final_url = alt_url

                                # Reprocess fully
                                parsed_url = urlparse(final_url)
                                base_url = "%s://%s%s/" % (
                                    parsed_url.scheme,
                                    parsed_url.netloc,
                                    parsed_url.path.rsplit('/', 1)[0]
                                )
                                headers_query = "&".join(["h_%s=%s" % (quote(k), quote(
                                    v)) for k, v in current_headers_for_proxy.items()])

                                extract_key_info_from_m3u8(
                                    m3u_content.splitlines(), stream_id, base_url, current_headers_for_proxy, result)

                                # Reprocess segments
                                modified_m3u8 = []
                                for line in m3u_content.splitlines():
                                    line = line.strip()
                                    if line.startswith(
                                            "#EXT-X-KEY") and 'AES-128' in line:
                                        continue
                                    elif line and not line.startswith("#"):
                                        segment_url = urljoin(base_url, line)
                                        segment_url_lower = segment_url.lower()

                                        if is_subtitle_resource(segment_url):
                                            enhanced_log(
                                                "[SUBTITLE_SKIP] Subtitle segment discarded in alternative M3U8: %s" %
                                                line, "INFO", "AppCore")
                                            continue

                                        # Discard non-video segments
                                        if any(
                                            ext in segment_url_lower for ext in [
                                                '.js', '.html', '.txt', '.css', '.json']):
                                            continue

                                        # Process as valid TS segment
                                        if headers_query:
                                            proxy_url = "http://127.0.0.1:7860/proxy/ts?url=%s&stream_id=%s&%s" % (
                                                quote(segment_url), stream_id, headers_query)
                                        else:
                                            proxy_url = "http://127.0.0.1:7860/proxy/ts?url=%s&stream_id=%s" % (
                                                quote(segment_url), stream_id)

                                        modified_m3u8.append(proxy_url)
                                    else:
                                        modified_m3u8.append(line)

                                enhanced_log(
                                    "[M3U8_ALT] Alternative M3U8 processed successfully", "INFO", "AppCore")
                            else:
                                enhanced_log(
                                    "[M3U8_ALT] Alternative URL has no valid video segments", "WARNING", "AppCore")
                        else:
                            enhanced_log(
                                "[M3U8_ALT] Alternative URL is not a valid M3U8", "WARNING", "AppCore")
                    else:
                        enhanced_log(
                            "[M3U8_ALT] Alternative URL HTTP %s" %
                            alt_response.status_code, "WARNING", "AppCore")

                except Exception as alt_error:
                    enhanced_log(
                        "[M3U8_ALT] Alternative URL error: %s" % alt_error,
                        "ERROR",
                        "AppCore")

        # NECESSARY MODIFICATION: Completely remove #EXT-X-KEY when
        # dlhd_masked=1
        if dlhd_masked:
            m3u8_lines = [line for line in "\n".join(modified_m3u8).split('\n')
                          if not line.strip().startswith('#EXT-X-KEY')]
            final_m3u8 = '\n'.join(m3u8_lines) + "\n"
            enhanced_log(
                "[DLHD_MASKED] Removed #EXT-X-KEY line from M3U8 for dlhd_masked=1",
                "INFO",
                "AppCore")
        else:
            final_m3u8 = "\n".join(modified_m3u8) + "\n"

        enhanced_log(
            "[M3U8_FINAL] Final M3U8 (%d characters):" % len(final_m3u8),
            "DEBUG",
            "AppCore")
        enhanced_log(
            "[M3U8_FINAL] First 500 characters: %s" % final_m3u8[:500],
            "DEBUG",
            "AppCore")

        # FINAL VALIDATION: Verify M3U8 has valid segments
        segment_count = len([line for line in final_m3u8.splitlines(
        ) if line and not line.startswith('#') and line.strip()])
        if segment_count == 0:
            enhanced_log(
                "[M3U8_VALIDATION] Final M3U8 has no segments - possible issue",
                "WARNING",
                "AppCore")
        else:
            enhanced_log(
                "[M3U8_VALIDATION] Final M3U8 has %d valid segments" %
                segment_count, "INFO", "AppCore")

        final_m3u8_bytes = final_m3u8.encode()
        if is_vavoo_request:
            VAVOO_FINAL_M3U8_CACHE[stream_id] = {
                'content': final_m3u8_bytes,
                'timestamp': time.time(),
                'in_progress': False,
            }
            enhanced_log(
                "[VAVOO_M3U8_CACHE] Playlist saved for refresh (%d segments)" %
                segment_count, "DEBUG", "AppCore")

        return {
            'content': final_m3u8_bytes,
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }

    except Exception as e:
        enhanced_log("Error: %s" % str(e), "ERROR", "proxy_m3u")
        return {
            'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }


@route_registry.route('/proxy/resolve')
def proxy_resolve(request=None, **kwargs):
    """Proxy to resolve and return an M3U8 URL using DaddyLive method 2025 - Enigma2"""
    request_args = kwargs or {}
    url = request_args.get('url', '').strip()
    if not url:
        return {
            'content': "Error: Missing 'url' parameter",
            'status': 400,
            'content_type': 'text/plain'
        }

    request_headers = {
        unquote(key[2:]).replace("_", "-"): unquote(value).strip()
        for key, value in request_args.items()
        if key.lower().startswith("h_")
    }
    try:
        result = resolve_m3u8_link(url, request_headers)

        if not result["resolved_url"]:
            return {
                'content': "Error: Unable to resolve URL",
                'status': 500,
                'content_type': 'text/plain'
            }

        headers_query = "&".join(
            ["h_%s=%s" % (quote(k), quote(v)) for k, v in result["headers"].items()])
        m3u_content = ("#EXTM3U\n"
                       "#EXTINF:-1,Resolved Channel\n"
                       "/proxy/m3u?url=%s&%s" %
                       (quote(result['resolved_url']), headers_query))

        return {
            'content': m3u_content,
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }

    except Exception as e:
        enhanced_log(
            "Error during URL resolution: %s" % str(e),
            "ERROR",
            "AppCore")
        return {
            'content': "Error during URL resolution: %s" % str(e),
            'status': 500,
            'content_type': 'text/plain'
        }


# URL mapping cache
URL_MAPPING = {}
URL_COUNTER = 1


def create_short_url(long_url, headers_query, stream_id):
    """Create short URLs for TS segments"""
    global URL_COUNTER

    # Create short key
    short_key = "ts%d" % URL_COUNTER
    URL_COUNTER += 1

    # Save mapping
    URL_MAPPING[short_key] = {
        'url': long_url,
        'headers': headers_query,
        'stream_id': stream_id
    }

    return "http://127.0.0.1:7860/proxy/ts?key=%s" % short_key


@route_registry.route('/proxy/init.hls.fmp4')
def proxy_init_fmp4(request=None, **kwargs):
    """Proxy for fMP4 init segments (Freeshot) with synthetic fallback"""
    enhanced_log(
        "[INIT_FMP4] Starting init fMP4 processing",
        "INFO",
        "proxy_fmp4")

    token = kwargs.get('token', '').strip()
    if not token:
        enhanced_log("[INIT_FMP4] Missing token", "ERROR", "proxy_fmp4")
        return {'content': b'', 'status': 400, 'content_type': 'text/plain'}

    # Build init URL based on the current domain
    init_url = "https://beautifulpeople.lovecdn.ru/SkySport24IT/init.hls.fmp4?token=%s" % token

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        'Referer': 'https://beautifulpeople.lovecdn.ru/SkySport24IT/embed.html?token=%s' % token,
        'Origin': 'https://beautifulpeople.lovecdn.ru'}

    try:
        response = make_enigma2_request(init_url, headers=headers, timeout=10)
        response.raise_for_status()

        enhanced_log(
            "[INIT_FMP4] Init downloaded: %d bytes" % len(response.content),
            "INFO",
            "proxy_fmp4")

        return {
            'content': response.content,
            'status': 200,
            'content_type': 'video/mp4'
        }

    except Exception as e:
        enhanced_log(
            "[INIT_FMP4] Init server failed: %s" % e,
            "WARNING",
            "proxy_fmp4")
        enhanced_log(
            "[INIT_FMP4] Generating synthetic fMP4 init",
            "INFO",
            "proxy_fmp4")

        # SOLUTION: Minimal synthetic fMP4 init segment for Enigma2
        # Contains essential ftyp + moov boxes for fMP4 decoding
        synthetic_init = bytes.fromhex(
            '0000001c667479706d736468000000006d7364686d70343200000000'  # ftyp box
            '000000286d6f6f76000000206d766864000000000000000000000000'  # moov + mvhd
            '000003e800000000000100000100000000000000000000000000'      # mvhd data
        )

        enhanced_log(
            "[INIT_FMP4] Synthetic init generated: %d bytes" %
            len(synthetic_init), "INFO", "proxy_fmp4")

        return {
            'content': synthetic_init,
            'status': 200,
            'content_type': 'video/mp4'
        }


@route_registry.route('/proxy/ts')
def proxy_ts(request=None, **kwargs):
    """TS proxy optimised for Enigma2 with AES-128 decryption and fMP4 + DLHD .html handling"""
    enhanced_log(
        "[PROXY_TS] === START TS SEGMENT PROCESSING ===",
        "INFO",
        "proxy_ts")

    # DETAILED DEBUG LOGGING
    enhanced_log(
        "[PROXY_TS] Received kwargs: %s" % list(
            kwargs.keys()),
        "DEBUG",
        "proxy_ts")

    ts_url = kwargs.get('url', '').strip()
    ts_url = unquote(ts_url)
    stream_id = kwargs.get('stream_id', '')
    is_fmp4 = kwargs.get('fmp4', '0') == '1'
    is_dlhd_masked = kwargs.get('dlhd_masked', '0') == '1'

    enhanced_log("[PROXY_TS] Extracted URL: %s" %
                 (ts_url[-50:] if ts_url else 'EMPTY'), "INFO", "proxy_ts")
    enhanced_log("[PROXY_TS] Stream ID: %s" % stream_id, "INFO", "proxy_ts")
    enhanced_log(
        "[PROXY_TS] fMP4: %s, DLHD masked: %s" % (is_fmp4, is_dlhd_masked),
        "INFO",
        "proxy_ts")

    if not ts_url:
        enhanced_log(
            "[PROXY_TS] Missing URL - CRITICAL ERROR",
            "ERROR",
            "proxy_ts")
        return {
            'content': b'',
            'status': 400,
            'content_type': 'text/plain'
        }

    # If the URL already belongs to the external proxy, pass it through
    # directly without any local processing (decrypt/convert).
    if EXTERNAL_PROXY_AVAILABLE and is_proxy_esterno_attivo(
    ) and is_url_del_proxy_esterno(ts_url):
        enhanced_log(
            "[PROXY_TS] URL belongs to external proxy, direct passthrough",
            "INFO", "proxy_ts")
        try:
            from .external_proxy import _get_session
            resp = _get_session().get(
                ts_url,
                timeout=(5, 15),
                verify=False,
                allow_redirects=True,
                stream=False
            )
            ct = resp.headers.get('Content-Type', 'video/mp2t')
            return {
                'content': resp.content,
                'status': resp.status_code,
                'content_type': ct}
        except Exception as e:
            enhanced_log(
                "[PROXY_TS] External proxy passthrough error: %s" % e,
                "WARNING", "proxy_ts")
            return {
                'content': b'',
                'status': 502,
                'content_type': 'video/mp2t'}

    enhanced_log(
        "[PROXY_TS] Valid URL received, continuing processing",
        "INFO",
        "proxy_ts")

    # IMPROVED DLHD DETECTION: All segments from DLHD domains are potentially
    # video
    if not is_dlhd_masked:
        is_dlhd_masked = is_daddy_domain(
            ts_url) or 'playerfuncc.fun' in ts_url.lower()
        enhanced_log(
            "[PROXY_TS] DLHD auto-detected: %s" % is_dlhd_masked,
            "DEBUG",
            "proxy_ts")

    enhanced_log("[PROXY_TS] Segment request: %s" % (ts_url.split(
        '/')[-1] if '/' in ts_url else ts_url[-30:]), "INFO", "proxy_ts")
    if stream_id:
        enhanced_log(
            "[PROXY_TS] Stream ID: %s" % stream_id,
            "INFO",
            "proxy_ts")
    if is_fmp4:
        enhanced_log(
            "[PROXY_TS] fMP4 mode activated",
            "INFO",
            "proxy_ts")
    if is_dlhd_masked:
        enhanced_log(
            "[DLHD_MASKED] DLHD segment detected (masked video)",
            "INFO",
            "proxy_ts")

    # Extract custom headers
    enhanced_log(
        "[PROXY_TS] Extracting custom headers...",
        "DEBUG",
        "proxy_ts")
    headers = {
        unquote(key[2:]).replace("_", "-"): unquote(value).strip()
        for key, value in kwargs.items()
        if key.lower().startswith("h_")
    }
    enhanced_log(
        "[PROXY_TS] Extracted headers: %d elements" % len(headers),
        "DEBUG",
        "proxy_ts")

    # Reduced timeouts for segments
    if stream_id in STREAM_KEY_INFO:
        saved_headers = STREAM_KEY_INFO[stream_id].get('headers', {}) or {}
        merged_headers = saved_headers.copy()
        merged_headers.update(headers)
        headers = merged_headers

    timeout = 4 if 'lovecdn.ru' in ts_url.lower() else 8
    enhanced_log(
        "[PROXY_TS] Timeout set: %ds" % timeout,
        "DEBUG",
        "proxy_ts")

    try:
        enhanced_log(
            "[PROXY_TS] === START SEGMENT DOWNLOAD ===",
            "INFO",
            "proxy_ts")

        # Use persistent DLHD session if available
        dlhd_session = get_dlhd_session()
        if dlhd_session and any(domain in ts_url.lower()
                                for domain in ['kiko2.ru', 'giokko.ru']):
            enhanced_log(
                "[PROXY_TS] Using persistent DLHD session",
                "INFO",
                "proxy_ts")
            response = dlhd_session.get(
                ts_url, headers=headers, timeout=timeout, verify=False)
        else:
            enhanced_log(
                "[PROXY_TS] Using standard request",
                "DEBUG",
                "proxy_ts")
            response = make_persistent_request(
                ts_url, headers=headers, timeout=timeout)

        enhanced_log(
            "[PROXY_TS] HTTP response: %s" % response.status_code,
            "INFO",
            "proxy_ts")
        response.raise_for_status()
        ts_content = response.content

        enhanced_log(
            "[PROXY_TS] === SEGMENT DOWNLOADED: %d bytes ===" %
            len(ts_content), "INFO", "proxy_ts")

        # =====================================================================
        # EXTERNAL PROXY: Register CDN domain for recognition
        # =====================================================================
        if is_dlhd_masked or is_daddy_domain(ts_url):
            register_cdn_domain(ts_url)
        # =====================================================================

        # IMPROVED DLHD .html/.css HANDLING: These are masked TS segments
        non_ts_content_type = get_non_ts_content_type(ts_url, ts_content)
        if non_ts_content_type and not is_dlhd_masked:
            enhanced_log(
                "[PROXY_TS] Non-TS resource served without decryption: %s" %
                non_ts_content_type, "INFO", "proxy_ts")
            return {
                'content': ts_content,
                'status': 200,
                'content_type': non_ts_content_type
            }

        if is_direct_media_url(ts_url):
            enhanced_log(
                "[PROXY_TS] Direct media served without TS conversion: %s" % ts_url[-60:],
                "INFO",
                "proxy_ts")
            return {
                'content': ts_content,
                'status': 200,
                'content_type': 'video/mp4'
            }

        # =====================================================================
        # EXTERNAL PROXY: Fetch segment via external proxy
        # =====================================================================
        if EXTERNAL_PROXY_AVAILABLE and is_proxy_esterno_attivo() and (
                'stream.mardio.link' in ts_url.lower() or is_cdn_daddy_url(ts_url)):
            enhanced_log(
                "Delegating segment to external proxy",
                "INFO",
                "proxy_ts")
            try:
                # Build proxy URL with headers from kwargs
                proxy_segment_url = "http://127.0.0.1:7860/proxy/ts?url=%s&stream_id=%s" % (
                    quote(ts_url), stream_id)
                for key, value in kwargs.items():
                    if key.lower().startswith("h_"):
                        proxy_segment_url += "&%s=%s" % (key, value)
                # Fetch via external proxy
                response = fetch_segment_via_proxy_esterno(
                    proxy_segment_url, timeout=timeout)
                if response and response.status_code == 200:
                    enhanced_log(
                        "Segment fetched via external proxy",
                        "INFO",
                        "proxy_ts")
                    return {
                        'content': response.content,
                        'status': 200,
                        'content_type': 'video/mp2t'
                    }
            except Exception as e:
                enhanced_log(
                    "External proxy segment fetch failed: %s" %
                    e, "WARNING", "proxy_ts")
                # Fallback to normal processing
        # =====================================================================

        if is_dlhd_masked:
            enhanced_log(
                "[DLHD_MASKED] === PROCESSING MASKED SEGMENT ===",
                "INFO",
                "proxy_ts")
            # Verify it is actually a TS segment (sync byte 0x47)
            if len(ts_content) > 0:
                enhanced_log(
                    "[DLHD_MASKED] First byte: 0x%02x" % ts_content[0],
                    "DEBUG",
                    "proxy_ts")
                if not is_valid_ts_payload(ts_content):
                    enhanced_log(
                        "[DLHD_MASKED] Segment lacks TS sync byte, may be encrypted",
                        "WARNING",
                        "proxy_ts")
                    # Try decryption if available
                    if stream_id and AES_AVAILABLE:
                        enhanced_log(
                            "[DLHD_MASKED] Attempting decryption of masked segment",
                            "INFO",
                            "proxy_ts")
                        aes_key = get_aes_key_for_stream(
                            stream_id, headers, ts_url)
                        if aes_key:
                            enhanced_log(
                                "[DLHD_MASKED] AES key found, decrypting",
                                "INFO",
                                "proxy_ts")
                            decrypted = decrypt_ts_if_needed(
                                ts_content, stream_id, headers, ts_url)
                            if decrypted != ts_content and is_valid_ts_payload(
                                    decrypted):
                                ts_content = decrypted
                                enhanced_log(
                                    "[DLHD_MASKED] Masked segment decrypted successfully", "INFO", "proxy_ts")
                            else:
                                enhanced_log(
                                    "[DLHD_MASKED] Decryption failed or unnecessary", "WARNING", "proxy_ts")
                        else:
                            enhanced_log(
                                "[DLHD_MASKED] AES key not available",
                                "ERROR",
                                "proxy_ts")
                else:
                    enhanced_log(
                        "[DLHD_MASKED] Masked segment already in valid TS format",
                        "INFO",
                        "proxy_ts")
            else:
                enhanced_log(
                    "[DLHD_MASKED] Empty segment!",
                    "ERROR",
                    "proxy_ts")

        # fMP4 handling: For Freeshot and other fMP4 providers
        elif is_fmp4 or '.fmp4' in ts_url.lower():
            enhanced_log(
                "[FMP4_PROCESS] Processing fMP4 segment",
                "DEBUG",
                "proxy_ts")

            # For Enigma2, convert fMP4 to TS if necessary
            if stream_id and stream_id in STREAM_KEY_INFO:
                stream_info = STREAM_KEY_INFO[stream_id]
                if stream_info.get('is_freeshot', False):
                    # For Freeshot, keep native fMP4 (modern Enigma2 supports
                    # it)
                    enhanced_log(
                        "[FMP4_NATIVE] Freeshot: keeping native fMP4 for Enigma2",
                        "INFO",
                        "proxy_ts")
                    return {
                        'content': ts_content,
                        'status': 200,
                        'content_type': 'video/mp4'
                    }
                else:
                    # For other providers, convert to TS
                    enhanced_log(
                        "[FMP4_CONVERT] Converting fMP4 → TS for compatibility",
                        "INFO",
                        "proxy_ts")
                    ts_content = convert_fmp4_to_ts(ts_content, stream_id)
            else:
                # Fallback: always convert
                ts_content = convert_fmp4_to_ts(ts_content, stream_id)

        # Check if already decrypted (sync byte 0x47 for TS)
        enhanced_log(
            "[PROXY_TS] === VERIFYING SEGMENT FORMAT ===",
            "INFO",
            "proxy_ts")
        if len(ts_content) > 0:
            enhanced_log(
                "[PROXY_TS] Segment first byte: 0x%02x" % ts_content[0],
                "DEBUG",
                "proxy_ts")
            if is_valid_ts_payload(ts_content):
                enhanced_log(
                    "[PROXY_TS] Segment already decrypted (sync byte 0x47)",
                    "INFO",
                    "proxy_ts")
                return {
                    'content': ts_content,
                    'status': 200,
                    'content_type': 'video/mp2t'
                }
            else:
                enhanced_log(
                    "[PROXY_TS] Segment requires decryption (first byte: 0x%02x)" %
                    ts_content[0], "WARNING", "proxy_ts")
        else:
            enhanced_log("[PROXY_TS] Empty segment!", "ERROR", "proxy_ts")

        # Try AES decryption if needed
        enhanced_log(
            "[PROXY_TS] === START AES DECRYPTION ===",
            "INFO",
            "proxy_ts")
        if stream_id and AES_AVAILABLE:
            enhanced_log(
                "[PROXY_TS] Searching for AES key for stream %s" % stream_id,
                "INFO",
                "proxy_ts")

            # Always call decrypt_ts_if_needed
            decrypted = decrypt_ts_if_needed(
                ts_content, stream_id, headers, ts_url)
            if decrypted != ts_content:
                ts_content = decrypted
                enhanced_log(
                    "[PROXY_TS] DECRYPTION SUCCESSFUL: %d bytes" %
                    len(ts_content), "INFO", "proxy_ts")
                if len(ts_content) > 0:
                    enhanced_log(
                        "[PROXY_TS] Sync byte after decryption: 0x%02x" %
                        ts_content[0], "INFO", "proxy_ts")
            else:
                enhanced_log(
                    "[PROXY_TS] Decryption did not modify content",
                    "WARNING",
                    "proxy_ts")
        else:
            if not stream_id:
                enhanced_log(
                    "[PROXY_TS] Missing stream ID - decryption skipped",
                    "WARNING",
                    "proxy_ts")
            if not AES_AVAILABLE:
                enhanced_log(
                    "[PROXY_TS] AES not available - decryption skipped",
                    "WARNING",
                    "proxy_ts")

        # Determine final content-type
        enhanced_log(
            "[PROXY_TS] === PREPARING FINAL RESPONSE ===",
            "INFO",
            "proxy_ts")
        if is_fmp4 or '.fmp4' in ts_url.lower() or is_direct_media_url(ts_url):
            content_type = 'video/mp4'
            enhanced_log(
                "[PROXY_TS] Content-Type: video/mp4 (fMP4)",
                "INFO",
                "proxy_ts")
        else:
            # Both normal TS and .html DLHD use video/mp2t
            content_type = 'video/mp2t'
            enhanced_log(
                "[PROXY_TS] Content-Type: video/mp2t (TS)",
                "INFO",
                "proxy_ts")

        # Final content verification
        if len(ts_content) > 0:
            enhanced_log(
                "[PROXY_TS] === SEGMENT READY: %d bytes, sync: 0x%02x ===" %
                (len(ts_content), ts_content[0]), "INFO", "proxy_ts")
        else:
            enhanced_log(
                "[PROXY_TS] === EMPTY SEGMENT - CRITICAL ERROR ===",
                "ERROR",
                "proxy_ts")

        if is_dlhd_masked:
            enhanced_log(
                "[DLHD_MASKED] DLHD segment ready as TS: %d bytes" %
                len(ts_content), "INFO", "proxy_ts")

        return {
            'content': ts_content,
            'status': 200,
            'content_type': content_type
        }

    except Exception as e:
        enhanced_log(
            "[PROXY_TS] === CRITICAL ERROR DURING PROCESSING ===",
            "ERROR",
            "proxy_ts")
        enhanced_log(
            "[PROXY_TS] Error: %s: %s" % (
                type(e).__name__, str(e)),
            "ERROR",
            "proxy_ts")

        # Log stack trace for debugging
        import traceback
        enhanced_log(
            "[PROXY_TS] Stack trace: %s" % traceback.format_exc(),
            "ERROR",
            "proxy_ts")

        # IMPROVED FALLBACK: Empty but valid TS segment to avoid interruptions
        # For DLHD, generate a TS packet with correct PAT
        if is_dlhd_masked:
            enhanced_log(
                "[DLHD_FALLBACK] Generating DLHD TS fallback",
                "WARNING",
                "proxy_ts")
            # TS packet with PAT for DLHD
            fallback_ts = bytes([
                0x47, 0x40, 0x00, 0x10,  # TS header with sync byte
                0x00,  # Adaptation field control
                0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00,  # PAT
                0x00, 0x01, 0xF0, 0x00, 0x2A, 0xB1, 0x04, 0xB2
            ]) + b'\xFF' * (188 - 20)  # Padding
            enhanced_log(
                "[DLHD_FALLBACK] DLHD TS fallback generated: %d bytes" %
                len(fallback_ts), "WARNING", "proxy_ts")
        else:
            enhanced_log(
                "[PROXY_TS] Generating standard TS fallback",
                "WARNING",
                "proxy_ts")
            fallback_ts = b'\x47\x1F\xFF\x10' + b'\xFF' * 184
            enhanced_log(
                "[PROXY_TS] TS fallback generated: %d bytes" %
                len(fallback_ts), "WARNING", "proxy_ts")

        return {
            'content': fallback_ts,
            'status': 200,
            'content_type': 'video/mp2t'
        }


# Global cache for AES keys with metadata
AES_KEY_CACHE = {}
STREAM_KEY_INFO = {}  # Store key information per stream
STREAM_HEADER_INFO = {}  # NEW: Cache for headers associated with a stream
# Cache for unavailable segments (avoid repeated requests)
FAILED_SEGMENTS_CACHE = {}


def cleanup_expired_segments():
    """Automatically clean expired segments from cache with optimised timeouts"""
    current_time = time.time()
    expired_keys = []

    # Very short cache (3s) for more frequent retries
    for key, entry in FAILED_SEGMENTS_CACHE.items():
        if current_time - entry['timestamp'] > 3:  # Expired after 3 seconds
            expired_keys.append(key)

    for key in expired_keys:
        del FAILED_SEGMENTS_CACHE[key]

    # Clean old init segments (over 2 minutes for live streams)
    old_init_count = 0
    for stream_id in list(STREAM_KEY_INFO.keys()):
        stream_info = STREAM_KEY_INFO[stream_id]
        if 'init_segment' in stream_info and 'init_timestamp' in stream_info:
            if current_time - \
                    stream_info['init_timestamp'] > 120:  # 2 minutes for live streams
                del stream_info['init_segment']
                del stream_info['init_timestamp']
                old_init_count += 1

    if expired_keys or old_init_count > 0:
        enhanced_log(
            "[SEGMENT_CLEANUP] Removed %d expired segments (3s) and %d old init segments from cache" %
            (len(expired_keys), old_init_count), "DEBUG", "AppCore")


def clear_stream_cache():
    """Completely clear cache for channel change"""
    old_stream_count = len(STREAM_KEY_INFO)
    old_key_count = len(AES_KEY_CACHE)

    STREAM_KEY_INFO.clear()
    AES_KEY_CACHE.clear()
    STREAM_HEADER_INFO.clear()
    FAILED_SEGMENTS_CACHE.clear()
    VAVOO_FINAL_M3U8_CACHE.clear()
    URL_MAPPING.clear()
    # URL_COUNTER = 1

    enhanced_log(
        "[CACHE_CLEAR] Complete cleanup: %d streams, %d AES keys" % (
            old_stream_count, old_key_count),
        "INFO",
        "AppCore")


def is_valid_video_segment(url, strict_mode=False, is_dlhd=False):
    """Validate that the segment is a valid video file

    Args:
        url: Segment URL
        strict_mode: If False, accept URLs without extension (could be TS without ext)
                     If True, reject URLs without recognised extension
        is_dlhd: If True, allow .html/.css (DLHD uses masked video segments)
    """
    url_lower = url.lower()
    # Valid video extensions
    valid_extensions = (
        '.ts',
        '.m3u8',
        '.mp4',
        '.mkv',
        '.webm',
        '.flv',
        '.mov',
        '.avi')
    # Non-video extensions to exclude (but .html/.css is allowed for DLHD)
    invalid_extensions = (
        '.php',
        '.js',
        '.png',
        '.jpg',
        '.jpeg',
        '.gif',
        '.svg',
        '.txt',
        '.xml',
        '.json')

    # For DLHD, .html/.css/.js/.txt is considered valid (masked video segments)
    if is_dlhd and any(
        ext in url_lower for ext in [
            '.html',
            '.css',
            '.js',
            '.txt']):
        enhanced_log(
            "[DLHD_MASKED] DLHD segment accepted (masked video): %s" % url[-50:],
            "INFO",
            "AppCore")
        return True

    # Check non-video extensions - ALWAYS REJECT (except .html/.css for DLHD)
    for ext in invalid_extensions:
        if url_lower.endswith(ext):
            enhanced_log(
                "[SEGMENT_VALIDATION] Non-video segment discarded: %s" % url[-50:],
                "WARNING",
                "AppCore")
            return False

    # If not DLHD, also discard .html/.css/.js/.txt
    if not is_dlhd and any(
        ext in url_lower for ext in [
            '.html',
            '.css',
            '.js',
            '.txt']):
        enhanced_log(
            "[SEGMENT_VALIDATION] .html/.css/.js/.txt segment discarded (non-DLHD): %s" % url[-50:],
            "WARNING",
            "AppCore")
        return False

    # If it has a valid video extension, accept
    for ext in valid_extensions:
        if url_lower.endswith(ext):
            return True

    # If it has no extension but contains 'playlist' or 'm3u', accept (could
    # be M3U8 without extension)
    if 'playlist' in url_lower or 'm3u' in url_lower:
        return True

    # If no recognised extension
    if strict_mode:
        # In strict mode, reject
        enhanced_log(
            "[SEGMENT_VALIDATION] Segment without valid extension rejected: %s" % url[-50:],
            "WARNING",
            "AppCore")
        return False
    else:
        # In permissive mode, accept (could be TS without extension)
        enhanced_log(
            "[SEGMENT_VALIDATION] Segment without extension accepted (permissive mode): %s" % url[-50:],
            "INFO",
            "AppCore")
        return True


def extract_key_info_from_m3u8(
        m3u8_content,
        stream_id,
        base_url,
        stream_headers=None,
        resolved_data=None):
    """Extract key information from M3U8 with detailed FASE_2 logging"""
    is_daddy = is_daddy_domain(base_url)
    is_freeshot = 'lovecdn.ru' in base_url.lower()

    if is_daddy:
        enhanced_log(
            "[FASE_2] Analysing playlist for key, IV and segment",
            "INFO",
            "AppCore")
    elif is_freeshot:
        enhanced_log(
            "[FREESHOT_M3U8] Analysing fMP4 playlist (not encrypted)",
            "INFO",
            "AppCore")

    try:
        first_segment = None
        segment_sequence = 0
        for line in m3u8_content:
            if line.startswith('#EXT-X-MEDIA-SEQUENCE'):
                try:
                    segment_sequence = int(line.split(':')[1].strip())
                    enhanced_log(
                        "[SEQUENCE] Initial sequence: %d" % segment_sequence,
                        "DEBUG",
                        "AppCore")
                except Exception as sequence_error:
                    enhanced_log(
                        "[SEQUENCE] Invalid media sequence: %s" %
                        sequence_error, "DEBUG", "AppCore")
            if not line.startswith('#') and line.strip():
                first_segment = line.strip()
                break
        for line in m3u8_content:
            if line.startswith('#EXT-X-KEY') and 'AES-128' in line:
                uri_match = re.search(r'URI="([^"]+)"', line)
                iv_match = re.search(r'IV=([^,]+)', line)
                if not uri_match:
                    enhanced_log(
                        "[KEY_EXTRACTION] URI not found in KEY line: %s" % line[:100],
                        "WARNING",
                        "AppCore")
                    continue
                relative_key_uri = uri_match.group(1)
                key_uri = urljoin(base_url, relative_key_uri)

                # NOTE: DaddyLive uses dynamic key URLs with 'number' parameter that changes
                # The URL is saved as is - if it becomes obsolete, it will be
                # handled in get_aes_key_for_stream
                if is_daddy and 'giokko.ru' in key_uri:
                    enhanced_log(
                        "[KEY_INFO] Dynamic DaddyLive key URL: %s..." % key_uri[:80],
                        "DEBUG",
                        "AppCore")
                iv_bytes = None
                if iv_match:
                    iv_value = iv_match.group(1).strip('"\'')
                    enhanced_log(
                        "[IV] Extracted IV value: %s" % iv_value,
                        "DEBUG",
                        "AppCore")
                    if iv_value.startswith('0x'):
                        iv_value = iv_value[2:]
                    if all(c in '0123456789abcdefABCDEF' for c in iv_value):
                        try:
                            iv_bytes = bytes.fromhex(iv_value)
                            enhanced_log(
                                "[IV] Converted from hex: %s" %
                                iv_bytes.hex(), "DEBUG", "AppCore")
                        except Exception:
                            iv_bytes = iv_value.encode('latin-1')
                            enhanced_log(
                                "[IV] Hex conversion failed, using as string: %s" %
                                iv_bytes.hex(), "WARNING", "AppCore")
                    else:
                        iv_bytes = iv_value.encode('latin-1')
                        enhanced_log(
                            "[IV] Interpreted as ASCII string: %s" %
                            iv_bytes.hex(), "DEBUG", "AppCore")
                    if len(iv_bytes) != 16:
                        if len(iv_bytes) < 16:
                            iv_bytes = iv_bytes + bytes(16 - len(iv_bytes))
                            enhanced_log(
                                "[IV] IV too short, padded to: %s" %
                                iv_bytes.hex(), "WARNING", "AppCore")
                        else:
                            iv_bytes = iv_bytes[:16]
                            enhanced_log(
                                "[IV] IV too long, truncated to: %s" %
                                iv_bytes.hex(), "WARNING", "AppCore")
                if not iv_bytes:
                    iv_bytes = hashlib.md5(stream_id.encode()).digest()[:16]
                    enhanced_log(
                        "[KEY_EXTRACTION] Invalid IV, using generated IV: %s" %
                        iv_bytes.hex(), "WARNING", "AppCore")
                if not isinstance(iv_bytes, bytes):
                    iv_bytes = str(iv_bytes).encode('latin-1')
                if len(iv_bytes) < 16:
                    iv_bytes = iv_bytes + bytes(16 - len(iv_bytes))
                    enhanced_log(
                        "[KEY_EXTRACTION] IV too short, zero-padded: %s" %
                        iv_bytes.hex(), "WARNING", "AppCore")
                elif len(iv_bytes) > 16:
                    iv_bytes = iv_bytes[:16]
                    enhanced_log(
                        "[KEY_EXTRACTION] IV too long, truncated: %s" %
                        iv_bytes.hex(), "WARNING", "AppCore")
                iv_hex = iv_bytes.hex()
                # PATCH: create entry BEFORE any assignment
                # Also save headers for use in key download
                existing = STREAM_KEY_INFO.get(stream_id, {})
                STREAM_KEY_INFO[stream_id] = {
                    'key_uri': key_uri,
                    'iv': iv_bytes,
                    'iv_base': iv_bytes,
                    'sequence': segment_sequence,
                    'method': 'AES-128',
                    'is_daddy': is_daddy,
                    'is_freeshot': is_freeshot,
                    'base_url': base_url,
                    'headers': stream_headers or {},
                    'last_used': time.time(),
                    'playlist_id': existing.get('playlist_id'),
                }

                if is_daddy:
                    enhanced_log(
                        "[FASE_2] Key found: %s..." % key_uri[:80],
                        "INFO",
                        "AppCore")
                    enhanced_log(
                        "[FASE_2] Base IV found: %s" % iv_hex,
                        "INFO",
                        "AppCore")
                    enhanced_log(
                        "[FASE_2] Initial sequence: %d" % segment_sequence,
                        "INFO",
                        "AppCore")
                    if first_segment:
                        full_segment_url = urljoin(base_url, first_segment)
                        enhanced_log(
                            "[FASE_2] First segment found: %s..." % first_segment[:80],
                            "DEBUG",
                            "AppCore")
                        enhanced_log(
                            "[FASE_2] Absolute key URI: %s" % key_uri,
                            "DEBUG",
                            "AppCore")
                        enhanced_log(
                            "[FASE_2] Absolute segment URL: %s" %
                            full_segment_url, "DEBUG", "AppCore")
                else:
                    enhanced_log(
                        "Key info saved for stream %s" % stream_id,
                        "INFO",
                        "AppCore")
                    enhanced_log(
                        "[KEY_EXTRACTION] URI: %s..." % key_uri[:80],
                        "DEBUG",
                        "AppCore")
                    enhanced_log(
                        "[KEY_EXTRACTION] IV: %s" % iv_hex,
                        "DEBUG",
                        "AppCore")
                return True
        if is_freeshot:
            enhanced_log(
                "[FREESHOT_M3U8] No AES key needed for fMP4 (unencrypted stream)",
                "INFO",
                "AppCore")
        else:
            enhanced_log(
                "[KEY_EXTRACTION] No valid AES-128 key found in M3U8",
                "WARNING",
                "AppCore")
        return False
    except Exception as e:
        enhanced_log(
            "Key info extraction error: %s" % e,
            "ERROR",
            "AppCore")
        return False


def get_aes_key_for_stream(stream_id, headers, segment_url=None):
    """Get AES key with automatic key change detection and persistent DLHD session"""
    enhanced_log(
        "[AES_KEY] === START AES KEY SEARCH for stream %s ===" % stream_id,
        "INFO",
        "AppCore")

    if stream_id not in STREAM_KEY_INFO:
        enhanced_log(
            "[AES_KEY] Stream %s not found in STREAM_KEY_INFO" % stream_id,
            "ERROR",
            "AppCore")
        return None

    key_info = STREAM_KEY_INFO[stream_id]
    key_uri = key_info.get('key_uri')
    if not key_uri:
        enhanced_log(
            "[AES_KEY] key_uri missing for stream %s" % stream_id,
            "ERROR",
            "AppCore")
        return None

    enhanced_log(
        "[AES_KEY] key_uri found: %s" % key_uri[-30:],
        "DEBUG",
        "AppCore")

    cache_key = "%s_%s" % (stream_id, key_uri)
    stream_headers = key_info.get('headers', {})
    enhanced_log(
        "[AES_KEY] Stream headers: %d elements" % len(stream_headers),
        "DEBUG",
        "AppCore")

    # KEY CHANGE DETECTION: If the key URL has changed, invalidate cache
    current_key_uri = key_info.get('key_uri')
    last_key_uri = key_info.get('last_key_uri')

    if last_key_uri and current_key_uri != last_key_uri:
        enhanced_log(
            "[KEY_CHANGE] Detected key change: %s → %s" % (
                last_key_uri[-10:], current_key_uri[-10:]),
            "INFO",
            "AppCore")
        # Clear old key cache
        old_cache_key = "%s_%s" % (stream_id, last_key_uri)
        if old_cache_key in AES_KEY_CACHE:
            del AES_KEY_CACHE[old_cache_key]
        # Update reference
        key_info['last_key_uri'] = current_key_uri
        cache_key = "%s_%s" % (stream_id, current_key_uri)

    # Check if we already have the key in cache
    if cache_key in AES_KEY_CACHE:
        enhanced_log(
            "[AES_KEY] Key found in cache: %s" % cache_key,
            "INFO",
            "AppCore")
        # Heartbeat every 30 seconds only for existing keys
        last_heartbeat = key_info.get('last_heartbeat', 0)
        current_time = time.time()

        if current_time - last_heartbeat > 30:
            heartbeat_url = stream_headers.get('Heartbeat-Url')
            if heartbeat_url:
                enhanced_log("[HEARTBEAT] Sending heartbeat: %s" %
                             heartbeat_url[-30:], "DEBUG", "AppCore")
                try:
                    hb_headers = {
                        'Authorization': stream_headers.get('Authorization', ''),
                        'X-Channel-Key': stream_headers.get('X-Channel-Key', ''),
                        'X-Client-Token': stream_headers.get('X-Client-Token', ''),
                        'User-Agent': stream_headers.get('User-Agent', ''),
                        'Referer': stream_headers.get('Referer', ''),
                        'Origin': stream_headers.get('Origin', '')
                    }

                    # Use persistent DLHD session if available
                    dlhd_session = get_dlhd_session()
                    if dlhd_session:
                        enhanced_log(
                            "[HEARTBEAT] Using persistent DLHD session",
                            "DEBUG",
                            "AppCore")
                        response = dlhd_session.get(
                            heartbeat_url, headers=hb_headers, timeout=2, verify=False)
                    else:
                        response = make_persistent_request(
                            heartbeat_url, headers=hb_headers, timeout=2)

                    if response.status_code == 200:
                        key_info['last_heartbeat'] = current_time
                        enhanced_log(
                            "[HEARTBEAT] Heartbeat successful for stream %s" %
                            stream_id, "DEBUG", "AppCore")
                    else:
                        enhanced_log(
                            "[HEARTBEAT] Heartbeat failed: %s" %
                            response.status_code, "WARNING", "AppCore")
                except Exception as e:
                    enhanced_log(
                        "[HEARTBEAT] Heartbeat error: %s" % e,
                        "WARNING",
                        "AppCore")

        return AES_KEY_CACHE[cache_key]

    # Download new AES key
    enhanced_log(
        "[AES_KEY] === DOWNLOAD NEW AES KEY ===",
        "INFO",
        "AppCore")
    try:
        enhanced_log(
            "[NEW_KEY] Downloading new key: %s" % key_uri[-20:],
            "INFO",
            "AppCore")
        key_headers = {
            k: v for k,
            v in stream_headers.items() if k != 'Heartbeat-Url'}
        enhanced_log(
            "[NEW_KEY] Headers for download: %s" % list(
                key_headers.keys()),
            "DEBUG",
            "AppCore")

        # Reduced timeouts for Enigma2
        timeout = 5 if 'kiko2.ru' in key_uri else 8
        enhanced_log("[NEW_KEY] Timeout: %ds" % timeout, "DEBUG", "AppCore")

        # Use persistent DLHD session to maintain auth cookies
        dlhd_session = get_dlhd_session()
        if dlhd_session and 'kiko2.ru' in key_uri:
            enhanced_log(
                "[DLHD_KEY] Using persistent DLHD session for AES key",
                "INFO",
                "AppCore")
            response = dlhd_session.get(
                key_uri,
                headers=key_headers,
                timeout=timeout,
                verify=False)
        else:
            enhanced_log(
                "[NEW_KEY] Using standard request",
                "DEBUG",
                "AppCore")
            response = make_persistent_request(
                key_uri, headers=key_headers, timeout=timeout)

        enhanced_log(
            "[NEW_KEY] HTTP response: %s" % response.status_code,
            "INFO",
            "AppCore")

        if response.status_code != 200:
            enhanced_log(
                "[NEW_KEY] AES key failed (HTTP %s)" % response.status_code,
                "ERROR",
                "AppCore")

            # If it fails, try to invalidate DLHD cache to force refresh
            if DLHD_AVAILABLE and dlhd_extractor and response.status_code in [
                    403, 404]:
                try:
                    if hasattr(dlhd_extractor,
                               'invalidate_cache_for_url') and segment_url:
                        dlhd_extractor.invalidate_cache_for_url(segment_url)
                        enhanced_log(
                            "[DLHD_INVALIDATE] DLHD cache invalidated for key error",
                            "INFO",
                            "AppCore")
                except Exception:
                    pass

            return None

        aes_key = response.content

        enhanced_log(
            "[NEW_KEY] Key downloaded: %d bytes" % len(aes_key),
            "INFO",
            "AppCore"
        )

        if len(aes_key) == 16:
            AES_KEY_CACHE[cache_key] = aes_key
            key_info['last_heartbeat'] = time.time()
            key_info['last_key_uri'] = key_uri

            enhanced_log(
                "[NEW_KEY] === NEW AES KEY SAVED (%d bytes) ===" % len(
                    aes_key),
                "INFO",
                "AppCore"
            )

            return aes_key
        else:
            enhanced_log(
                "[NEW_KEY] Invalid AES key size: %d bytes (expected 16)" %
                len(aes_key), "ERROR", "AppCore")

        return None

    except Exception as e:
        enhanced_log(
            "[NEW_KEY] === AES KEY DOWNLOAD ERROR: %s: %s ===" % (
                type(e).__name__,
                str(e)
            ),
            "ERROR",
            "AppCore"
        )

        import traceback

        enhanced_log(
            "[NEW_KEY] Stack trace: %s" % traceback.format_exc(),
            "ERROR",
            "AppCore"
        )

        return None


def decrypt_ts_segment(ts_content, aes_key, stream_id):
    """AES-128 decryption with Enigma2 fallback support"""
    if not AES_AVAILABLE or not aes_key:
        return ts_content

    try:
        # Get IV for this stream
        iv = None
        if stream_id in STREAM_KEY_INFO and 'iv' in STREAM_KEY_INFO[stream_id]:
            iv = STREAM_KEY_INFO[stream_id]['iv']

            # If IV is a string, convert to bytes
            if isinstance(iv, str):
                try:
                    # Remove possible 0x prefix
                    iv_str = iv[2:] if iv.startswith('0x') else iv

                    # Try to convert from hex
                    if all(c in '0123456789abcdefABCDEF' for c in iv_str):
                        iv = bytes.fromhex(iv_str)
                        enhanced_log(
                            "[IV] Converted from hex: %s" % iv.hex(),
                            "DEBUG",
                            "proxy_ts"
                        )
                    else:
                        # If not valid hex, use as ASCII string
                        iv = iv_str.encode('latin-1')
                        enhanced_log(
                            "[IV] Interpreted as string: %s" % iv.hex(),
                            "DEBUG",
                            "proxy_ts")
                except Exception as e:
                    enhanced_log(
                        "[IV] IV conversion error: %s" % e,
                        "WARNING",
                        "proxy_ts"
                    )
                    iv = None

            # Ensure IV is exactly 16 bytes
            if iv is not None:
                if len(iv) < 16:
                    # If too short, pad with zeros at the end
                    iv = iv + (b'\x00' * (16 - len(iv)))
                    enhanced_log(
                        "[IV] IV too short, padded: %s" % iv.hex(),
                        "WARNING",
                        "proxy_ts"
                    )
                elif len(iv) > 16:
                    # If too long, take first 16 bytes
                    iv = iv[:16]
                    enhanced_log(
                        "[IV] IV too long, truncated: %s" % iv.hex(),
                        "WARNING",
                        "proxy_ts"
                    )

        # If we don't have a valid IV, use default
        if iv is None or len(iv) != 16:
            iv = b'\x00' * 16
            enhanced_log(
                "[IV] Using default IV",
                "WARNING",
                "proxy_ts"
            )
        # Save correct IV for future use
        if stream_id in STREAM_KEY_INFO:
            STREAM_KEY_INFO[stream_id]['iv'] = iv

        enhanced_log(
            "[IV] Final IV for decryption: %s" % iv.hex(),
            "DEBUG",
            "proxy_ts"
        )

        # Log IV and key for debug
        is_daddy = STREAM_KEY_INFO.get(stream_id, {}).get('is_daddy', False)
        if is_daddy:
            enhanced_log(
                "[DECRYPT] IV (hex): %s" % iv.hex(),
                "DEBUG",
                "AppCore"
            )

            enhanced_log(
                "[DECRYPT] Key (hex): %s" % aes_key.hex(),
                "DEBUG",
                "AppCore"
            )

        # Decryption with available library
        try:
            if AES_MODULE == "cryptography":
                try:
                    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                    from cryptography.hazmat.backends import default_backend
                except ImportError:
                    return ts_content
                cipher = Cipher(
                    algorithms.AES(aes_key),
                    modes.CBC(iv),
                    backend=default_backend())
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(ts_content) + decryptor.finalize()
            else:
                cipher = AES_MODULE.new(aes_key, AES_MODULE.MODE_CBC, iv)
                decrypted = cipher.decrypt(ts_content)

            # Try to remove PKCS7 padding
            if len(decrypted) > 0:
                padding_length = decrypted[-1]
                if 0 < padding_length <= 16:
                    if all(
                            b == padding_length for b in decrypted[-padding_length:]):
                        decrypted = decrypted[:-padding_length]

            # Verify TS sync byte (0x47) at the start of the packet
            if len(decrypted) > 0 and decrypted[0] == 0x47:
                return decrypted

            # If sync byte is incorrect, try decrypting without removing
            # padding
            if AES_MODULE == "cryptography":
                cipher = Cipher(
                    algorithms.AES(aes_key),
                    modes.CBC(iv),
                    backend=default_backend())
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(ts_content) + decryptor.finalize()
            else:
                cipher = AES_MODULE.new(aes_key, AES_MODULE.MODE_CBC, iv)
                decrypted = cipher.decrypt(ts_content)

            return decrypted

        except Exception as decrypt_error:
            enhanced_log(
                "Decryption error: %s" % decrypt_error,
                "ERROR",
                "proxy_ts"
            )
            return ts_content
    except Exception as e:
        enhanced_log("Decryption error: %s" % e, "ERROR", "proxy_ts")
        return ts_content


def create_robust_session():
    """Create an optimized session for Enigma2 with built-in retry support and cookie handling"""
    session = requests.Session()

    session.headers.update({
        'Connection': 'close'  # Important for Enigma2 receivers
    })

    original_request = session.request

    def request_with_retry(method, url, **kwargs):
        retry_codes = [429, 500, 502, 503, 504]

        for attempt in range(3):
            try:
                response = original_request(method, url, **kwargs)

                if response.status_code not in retry_codes:
                    return response

                if attempt < 2:
                    time.sleep(1 * (attempt + 1))

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError
            ):
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
                    continue

                raise

        return response

    session.request = request_with_retry

    return session


def get_persistent_session(proxy_url=None):
    """Get a persistent session from the pool or create a new one"""
    pool_key = proxy_url if proxy_url else 'default'
    current_time = time.time()

    with SESSION_LOCK:
        session = SESSION_POOL.get(pool_key)

        if session is not None:
            session_age = current_time - getattr(
                session,
                "_sp_created_at",
                current_time
            )

            requests_count = getattr(
                session,
                "_sp_requests_count",
                0
            )

            if (
                session_age > SESSION_MAX_AGE or
                requests_count >= SESSION_MAX_REQUESTS
            ):
                try:
                    session.close()

                except Exception as close_error:
                    enhanced_log(
                        "Error closing expired session %s: %s" % (
                            pool_key,
                            close_error
                        ),
                        "DEBUG",
                        "AppCore"
                    )

                del SESSION_POOL[pool_key]
                session = None

        if session is None:
            session = create_robust_session()

            if session is None:
                enhanced_log(
                    "Unable to create session for: %s" % pool_key,
                    "get_persistent_session",
                    "AppCore"
                )
                return None

            if proxy_url:
                session.proxies.update({
                    'http': proxy_url,
                    'https': proxy_url
                })

            session._sp_created_at = current_time
            session._sp_requests_count = 0

            SESSION_POOL[pool_key] = session

            enhanced_log(
                "New persistent session created for: %s" % pool_key,
                "get_persistent_session",
                "AppCore"
            )

        SESSION_POOL[pool_key]._sp_requests_count = (
            getattr(
                SESSION_POOL[pool_key],
                "_sp_requests_count",
                0
            ) + 1
        )

        return SESSION_POOL[pool_key]


def make_persistent_request(
        url,
        headers=None,
        timeout=None,
        proxy_url=None,
        **kwargs):
    """Optimized HTTP request for Enigma2 with persistent DLHD session"""
    from html import unescape as html_unescape

    url = html_unescape(url)

    enhanced_log(
        "[PERSISTENT_REQUEST] URL: %s..." % url[:100],
        "DEBUG",
        "AppCore"
    )

    # Use persistent DLHD session for kiko2.ru domains
    dlhd_session = get_dlhd_session()

    if dlhd_session and any(
            domain in url.lower()
            for domain in ['kiko2.ru', 'giokko.ru']):

        enhanced_log(
            "[DLHD_SESSION] Using persistent DLHD session",
            "DEBUG",
            "AppCore"
        )

        try:
            response = dlhd_session.get(
                url,
                headers=headers,
                timeout=timeout or REQUEST_TIMEOUT,
                verify=False,
                **kwargs
            )

            enhanced_log(
                "[DLHD_SESSION] Response: %s" % response.status_code,
                "DEBUG",
                "AppCore"
            )

            return response

        except Exception as e:
            enhanced_log(
                "[DLHD_SESSION] Error: %s" % e,
                "WARNING",
                "AppCore"
            )
            # Fallback to standard method

    # Standard method for other domains
    request_headers = headers.copy() if headers else {}

    for header_name in list(request_headers.keys()):
        if header_name.lower().startswith("x-easyproxy-"):
            request_headers.pop(header_name, None)

    final_timeout = timeout or REQUEST_TIMEOUT

    response = None

    for attempt in range(3):
        try:
            session = get_persistent_session(proxy_url)

            if session is None:
                enhanced_log(
                    "Unable to obtain persistent session",
                    "ERROR",
                    "AppCore"
                )
                raise Exception("Unable to obtain persistent session")

            enhanced_log(
                "[PERSISTENT_REQUEST] Attempt %d/3" % (attempt + 1),
                "DEBUG",
                "AppCore"
            )

            if request_headers:
                response = session.get(
                    url,
                    headers=request_headers,
                    timeout=final_timeout,
                    verify=VERIFY_SSL,
                    **kwargs
                )
            else:
                response = session.get(
                    url,
                    timeout=final_timeout,
                    verify=VERIFY_SSL,
                    **kwargs
                )

            enhanced_log(
                "[PERSISTENT_REQUEST] Response: %s" % response.status_code,
                "DEBUG",
                "AppCore"
            )

            retry_codes = [418, 429, 500, 502, 503, 504]

            if response.status_code not in retry_codes:
                return response

            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as e:

            enhanced_log(
                "[PERSISTENT_REQUEST] Connection error on attempt %d: %s"
                % (attempt + 1, e),
                "ERROR",
                "AppCore"
            )

            with SESSION_LOCK:
                pool_key = proxy_url if proxy_url else 'default'

                if pool_key in SESSION_POOL:
                    del SESSION_POOL[pool_key]

            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise

        except Exception as e:
            enhanced_log(
                "[PERSISTENT_REQUEST] Generic error: %s" % e,
                "ERROR",
                "AppCore"
            )
            raise

    return response


# KEY proxy WITHOUT CACHE
@route_registry.route('/proxy/key')
def proxy_key(request=None, **kwargs):
    """AES-128 KEY proxy for DLHD keys"""
    enhanced_log("Proxy Key", "INFO", "AppCore")

    key_url = kwargs.get('url', '').strip()

    if not key_url:
        enhanced_log(
            "[PROXY_KEY] Missing key URL",
            "ERROR",
            "AppCore"
        )

        return {
            'content': b"Error: Missing key URL",
            'status': 400,
            'content_type': 'text/plain'
        }

    # Extract custom headers
    headers = {
        unquote(key[2:]).replace("_", "-"): unquote(value).strip()
        for key, value in kwargs.items()
        if key.lower().startswith("h_")
    }

    try:
        enhanced_log(
            "[PROXY_KEY] Downloading key: %s" % key_url[-30:],
            "INFO",
            "AppCore"
        )

        # Use persistent DLHD session if available
        dlhd_session = get_dlhd_session()

        if dlhd_session and 'kiko2.ru' in key_url:
            enhanced_log(
                "[PROXY_KEY] Using persistent DLHD session",
                "DEBUG",
                "AppCore"
            )

            response = dlhd_session.get(
                key_url,
                headers=headers,
                timeout=8,
                verify=False
            )
        else:
            response = make_persistent_request(
                key_url,
                headers=headers,
                timeout=8
            )

        response.raise_for_status()
        key_content = response.content

        if len(key_content) == 16:
            enhanced_log(
                "[PROXY_KEY] AES key downloaded: %d bytes" % len(
                    key_content),
                "INFO",
                "AppCore"
            )

            return {
                'content': key_content,
                'status': 200,
                'content_type': 'application/octet-stream'
            }

        enhanced_log(
            "[PROXY_KEY] Invalid key size: %d bytes" % len(key_content),
            "ERROR",
            "AppCore"
        )

        return {
            'content': b"Error: Invalid AES key",
            'status': 500,
            'content_type': 'text/plain'
        }

    except Exception as e:
        enhanced_log(
            "[PROXY_KEY] Error: %s" % e,
            "ERROR",
            "AppCore"
        )

        return {
            'content': ("Key error: %s" % str(e)).encode(),
            'status': 500,
            'content_type': 'text/plain'
        }


@route_registry.route('/service/notify_m3u')
def notify_m3u(request=None, **kwargs):
    """Internal notification used by Pipeline when it updates the M3U file."""
    path = kwargs.get('path', '')
    enhanced_log("M3U notification received: %s" % path, "INFO", "AppCore")
    return {
        'content': b"OK",
        'status': 200,
        'content_type': 'text/plain'
    }


# Global lists for proxies, populated by load_config
PROXY_LIST = []
DADDY_PROXY_LIST = []


def get_daddy_proxy_list():
    """Return the global list of DaddyLive proxies."""
    return DADDY_PROXY_LIST


def _normalize_proxy_url(proxy):
    if not proxy:
        return proxy
    proxy = proxy.strip()
    if proxy.startswith(
        ('http://',
         'https://',
         'socks4://',
         'socks5://',
         'socks5h://')):
        return proxy
    return 'http://' + proxy


class ConfigManager:
    def __init__(self):
        """Initialize the configuration manager."""
        self.config_file = 'streamproxy_config.json'
        self.default_config = {
            'PROXY': '',
            'DADDY_PROXY': '',
            'REQUEST_TIMEOUT': 8,
            'VERIFY_SSL': False,
            'NO_PROXY_DOMAINS': 'github.com,raw.githubusercontent.com',
        }

    def load_config(self):
        """
        Load the Enigma2 configuration in an optimized way.
        Search for a JSON configuration file in predefined locations and
        populate the configuration and global proxy lists.
        """
        global PROXY_LIST, DADDY_PROXY_LIST

        config = self.default_config.copy()

        config_paths = [
            '/usr/lib/enigma2/python/Plugins/Extensions/StreamProxy/SPconfig.txt',
            '/usr/lib/enigma2/python/Plugins/Extensions/StreamProxy/streamproxy_config.json',
            'SPconfig.txt',
            self.config_file]

        loaded_path = None

        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        file_config = json.load(f)

                        for key, value in file_config.items():
                            if key not in config or config.get(
                                    key) in ('', None):
                                config[key] = value

                    loaded_path = path
                except (IOError, json.JSONDecodeError) as e:
                    enhanced_log(
                        "Error loading %s: %s" % (path, e),
                        "load_config",
                        "AppCore"
                    )

        if not loaded_path:
            enhanced_log(
                "No configuration file found. Using default values.",
                "load_config",
                "AppCore"
            )

        proxy_str = config.get('PROXY', '')

        PROXY_LIST = [
            _normalize_proxy_url(p)
            for p in proxy_str.split(',')
            if p.strip()
        ] if proxy_str else []

        if PROXY_LIST:
            enhanced_log(
                "Configured general proxies: %d" % len(PROXY_LIST),
                "load_config",
                "AppCore"
            )

        daddy_proxy_str = config.get('DADDY_PROXY', '')

        DADDY_PROXY_LIST = [
            _normalize_proxy_url(p)
            for p in daddy_proxy_str.split(',')
            if p.strip()
        ] if daddy_proxy_str else []

        if DADDY_PROXY_LIST:
            enhanced_log(
                "Configured DaddyLive proxies: %d" % len(DADDY_PROXY_LIST),
                "load_config",
                "AppCore"
            )

        return config

    def save_config(self, config):
        """Save configuration to the JSON file in the default path."""
        path_to_save = self.config_file

        try:
            with open(path_to_save, 'w', encoding='utf-8') as f:
                config_to_save = {
                    k: config.get(k)
                    for k in self.default_config.keys()
                    if k in config
                }
                json.dump(config_to_save, f, indent=4)

            enhanced_log(
                "Configuration saved to: %s" % path_to_save,
                "save_config",
                "AppCore"
            )

            return True

        except IOError as e:
            enhanced_log(
                "Error saving configuration: %s" % e,
                "save_config",
                "AppCore"
            )

            return False

    def apply_config_to_app(self, config):
        """
        Apply configuration to a Flask app instance, if available.
        In a pure Enigma2 context, this function may not be used.
        """
        try:
            from flask import current_app
            if current_app:
                for key, value in config.items():
                    current_app.config[key] = value
            return True
        except (ImportError, RuntimeError):
            return True


config_manager = ConfigManager()


class AppCoreNoCache:
    def __init__(self):
        enhanced_log(
            "AppCore NoCache initialized",
            "INFO",
            "AppCore"
        )

    def handle_request(self, route_name, *args, **kwargs):
        enhanced_log(
            "Request: %s" % route_name,
            "INFO",
            "AppCore"
        )

        enhanced_log(
            "[DEBUG] handle_request kwargs: %s" % kwargs,
            "DEBUG",
            "AppCore"
        )

        if route_name not in route_registry.routes:
            return {
                'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
                'status': 200,
                'content_type': 'application/vnd.apple.mpegurl'
            }
        return route_registry.dispatch(route_name, **kwargs)


# Callback for ServiceMonitor
def service_monitor_callback(route_name, *args, **kwargs):
    enhanced_log(
        "ServiceMonitor → AppCore: %s" % route_name,
        "INFO",
        "AppCore"
    )

    enhanced_log(
        "[DEBUG] Received arguments: args=%s, kwargs=%s" % (args, kwargs),
        "DEBUG",
        "AppCore"
    )

    try:
        app_core = AppCoreNoCache()

        enhanced_log(
            "[DEBUG] Before handle_request: kwargs=%s" % kwargs,
            "DEBUG",
            "AppCore")

        return app_core.handle_request(route_name, **kwargs)
    except Exception as e:
        enhanced_log("Callback error: %s" % str(e), "ERROR", "AppCore")
        return {
            'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }


enhanced_log(
    "AppCoreSC NoCache fully initialized",
    "INFO",
    "AppCore")
