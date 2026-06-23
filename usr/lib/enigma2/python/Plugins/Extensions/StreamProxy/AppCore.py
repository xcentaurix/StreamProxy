# AppCoreSC - Versione SENZA CACHE ottimizzata per Enigma2
from .StreamProxyLog import enhanced_log as _enhanced_log
from urllib.parse import urlparse, urljoin, unquote, quote
import requests
import re
import time
import hashlib
import os
import json
import random
import binascii  # Per log hex dettagliati domini daddy
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
    """Filtro leggero per evitare I/O eccessivo nei path caldi su Enigma2."""
    if not VERBOSE_LOGS:
        if level == "DEBUG":
            return
        if tag in _HOT_LOG_TAGS and level == "INFO":
            return
    return _enhanced_log(msg, level, tag)


# Import LiveTV extractor per domini powerset
try:
    from .extractor.livetv_extractor import process_powerset_url, is_powerset_domain
    LIVETV_AVAILABLE = True
    enhanced_log("✅ LiveTV extractor disponibile", "INFO", "AppCore")
except ImportError as e:
    LIVETV_AVAILABLE = False

    def process_powerset_url(*args, **kwargs):
        return None

    def is_powerset_domain(*args, **kwargs):
        return False
    enhanced_log(
        f"⚠️ LiveTV extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

# Gestione librerie crittografia per Enigma2
AES_AVAILABLE = False
AES_MODULE = None
try:
    from Crypto.Cipher import AES as CryptoAES
    AES_MODULE = CryptoAES
    AES_AVAILABLE = True
    enhanced_log("✅ Crypto.Cipher.AES disponibile", "INFO", "AppCore")
except ImportError:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        AES_MODULE = "cryptography"
        AES_AVAILABLE = True
        enhanced_log("✅ cryptography disponibile", "INFO", "AppCore")
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
            "⚠️ Nessuna libreria AES disponibile - decrittazione disabilitata",
            "WARNING",
            "AppCore")


def convert_fmp4_to_ts(fmp4_content, stream_id=None):
    """SOLUZIONE OTTIMIZZATA: Gestione intelligente fMP4 per Enigma2

    Per Freeshot, invia direttamente fMP4 senza conversione per evitare problemi A/V.
    La conversione TS è usata solo quando strettamente necessaria.
    """
    try:
        if len(fmp4_content) < 8:
            enhanced_log(
                "⚠️ [FMP4_CONVERT] Segmento troppo piccolo, uso fallback",
                "WARNING",
                "proxy_ts")
            # Fallback: segmento TS vuoto ma valido
            return b'\x47\x1F\xFF\x10' + b'\xFF' * 184

        # Verifica formato contenuto
        if len(fmp4_content) > 0 and fmp4_content[0] == 0x47:
            enhanced_log(
                "ℹ️ [FMP4_CONVERT] Contenuto già in formato TS",
                "INFO",
                "proxy_ts")
            return fmp4_content

        # Verifica header fMP4
        if len(fmp4_content) >= 8:
            header_type = fmp4_content[4:8]
            if header_type not in [b'ftyp', b'styp', b'moof', b'mdat']:
                enhanced_log(
                    f"⚠️ [FMP4_CONVERT] Header non riconosciuto: {header_type}, provo comunque",
                    "WARNING",
                    "proxy_ts")

        enhanced_log(
            f"🔄 [FMP4_CONVERT] Processamento {
                len(fmp4_content)} bytes fMP4",
            "DEBUG",
            "proxy_ts")

        # ✅ SOLUZIONE CRITICA: Per Freeshot, invia SEMPRE fMP4 diretto
        # Enigma2 moderno gestisce fMP4 nativamente meglio della conversione TS
        if stream_id and stream_id in STREAM_KEY_INFO:
            stream_info = STREAM_KEY_INFO[stream_id]
            if stream_info.get('is_freeshot', False):
                enhanced_log(
                    f"✅ [FMP4_DIRECT] Freeshot: invio diretto fMP4 (ottimale per Enigma2)",
                    "INFO",
                    "proxy_ts")
                enhanced_log(
                    f"📊 [FMP4_DIRECT] Dimensione: {
                        len(fmp4_content)} bytes",
                    "DEBUG",
                    "proxy_ts")
                return fmp4_content

        # ✅ SOLUZIONE MIGLIORATA: Init segment obbligatorio per video
        init_data = b''
        if stream_id and stream_id in STREAM_KEY_INFO:
            init_segment = STREAM_KEY_INFO[stream_id].get('init_segment')
            if init_segment:
                enhanced_log(
                    f"📦 [FMP4_CONVERT] Usando init segment: {
                        len(init_segment)} bytes", "DEBUG", "proxy_ts")
                init_data = init_segment
            else:
                enhanced_log(
                    f"⚠️ [FMP4_CONVERT] Init segment mancante per stream {stream_id}",
                    "WARNING",
                    "proxy_ts")

        ts_packets = []

        # Dimensione pacchetto TS standard
        TS_PACKET_SIZE = 188
        TS_PAYLOAD_SIZE = 184  # 188 - 4 byte header

        # ✅ CORREZIONE: PID ottimizzati per Enigma2
        PAT_PID = 0x0000
        PMT_PID = 0x1000
        VIDEO_PID = 0x0100
        AUDIO_PID = 0x0101
        PCR_PID = VIDEO_PID  # PCR sempre dal video

        continuity_counter = 0

        # ✅ SOLUZIONE MIGLIORATA: PAT ottimizzato per Enigma2
        pat_payload = bytes([
            0x00,  # table_id (PAT)
            0xB0, 0x0D,  # section_syntax_indicator + section_length
            0x00, 0x01,  # transport_stream_id
            0xC1,  # version_number + current_next_indicator
            0x00, 0x00,  # section_number + last_section_number
            0x00, 0x01,  # program_number (1)
            (PMT_PID >> 8) | 0xE0, PMT_PID & 0xFF,  # program_map_PID
            # CRC32 corretto per Enigma2
            0x2A, 0xB1, 0x04, 0xB2
        ])

        pat_padded = pat_payload + b'\xFF' * \
            (TS_PAYLOAD_SIZE - len(pat_payload))
        pat_header = bytes([0x47, 0x40, 0x00, 0x10])  # PAT con PUSI=1
        pat_packet = pat_header + pat_padded
        ts_packets.append(pat_packet)

        # ✅ SOLUZIONE MIGLIORATA: PMT con stream_type corretti per Enigma2
        pmt_payload = bytes([
            0x02,  # table_id (PMT)
            0xB0, 0x17,  # section_syntax_indicator + section_length
            0x00, 0x01,  # program_number
            0xC1,  # version_number + current_next_indicator
            0x00, 0x00,  # section_number + last_section_number
            (PCR_PID >> 8) | 0xE0, PCR_PID & 0xFF,  # PCR_PID (video)
            0xF0, 0x00,  # program_info_length (0)
            # ✅ CORREZIONE: Stream video H.264 AVC
            0x1B,  # stream_type (H.264/AVC) - Enigma2 compatibile
            (VIDEO_PID >> 8) | 0xE0, VIDEO_PID & 0xFF,  # elementary_PID
            0xF0, 0x00,  # ES_info_length (0)
            # ✅ CORREZIONE: Stream audio AAC
            0x0F,  # stream_type (AAC ADTS) - Enigma2 compatibile
            (AUDIO_PID >> 8) | 0xE0, AUDIO_PID & 0xFF,  # elementary_PID
            0xF0, 0x00,  # ES_info_length (0)
            # CRC32 corretto
            0x2F, 0x44, 0xB9, 0x9B
        ])

        pmt_padded = pmt_payload + b'\xFF' * \
            (TS_PAYLOAD_SIZE - len(pmt_payload))
        pmt_header = bytes([0x47, 0x50, 0x00, 0x10])  # PMT con PUSI=1
        pmt_packet = pmt_header + pmt_padded
        ts_packets.append(pmt_packet)

        enhanced_log(
            "📺 [FMP4_CONVERT] Aggiunto PAT/PMT ottimizzato per Enigma2",
            "DEBUG",
            "proxy_ts")

        # ✅ SOLUZIONE CRITICA: Combina init + payload per metadati video completi
        if init_data:
            # Init segment DEVE essere processato per metadati video corretti
            payload_data = init_data + fmp4_content
            enhanced_log(
                f"📦 [FMP4_CONVERT] Combinato init ({
                    len(init_data)}) + payload ({
                    len(fmp4_content)}) = {
                    len(payload_data)} bytes",
                "DEBUG",
                "proxy_ts")
        else:
            # ⚠️ Senza init segment, il video potrebbe non funzionare
            payload_data = fmp4_content
            enhanced_log(
                f"⚠️ [FMP4_CONVERT] ATTENZIONE: Nessun init segment - video potrebbe non funzionare!",
                "WARNING",
                "proxy_ts")

        # ✅ NUOVO: Timestamp base per sincronizzazione A/V
        import time
        base_timestamp = int(time.time() *
                             90000) & 0x1FFFFFFFF  # 33-bit timestamp

        # ✅ SOLUZIONE MIGLIORATA: PES header ottimizzato per video Enigma2
        video_continuity = 2  # Inizia da 2 (dopo PAT e PMT)
        audio_continuity = 0

        # ✅ NUOVO: Genera PCR iniziale per sincronizzazione
        pcr_base = base_timestamp

        # Processa i dati in chunk ottimizzati per Enigma2
        # Spazio per PES header completo nel primo pacchetto
        chunk_size = TS_PAYLOAD_SIZE - 19

        # Processa i dati in chunk
        pos = 0
        packet_num = 0

        while pos < len(payload_data):
            if packet_num == 0:
                # Primo pacchetto con PES header
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

                # Spazio disponibile per dati
                adaptation_field_length = 7
                available_space = TS_PAYLOAD_SIZE - \
                    adaptation_field_length - len(pes_header)
                chunk = payload_data[pos:pos + available_space]

                # Adaptation field con PCR
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
                    packet_payload += b'\xFF' * \
                        (TS_PAYLOAD_SIZE - adaptation_field_length - len(packet_payload))

                ts_header = bytes([
                    0x47,
                    0x40 | ((VIDEO_PID >> 8) & 0x1F),
                    VIDEO_PID & 0xFF,
                    0x30 | (video_continuity & 0x0F)
                ])

                ts_packet = ts_header + adaptation_field + packet_payload
                pos += len(chunk)
            else:
                # Pacchetti successivi
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

        # ✅ NUOVO: Aggiungi pacchetti audio AAC sintetici per compatibilità A/V
        # Enigma2 si aspetta sia video che audio per funzionare correttamente
        for audio_frame in range(3):  # 3 frame audio per segmento
            # PES header audio AAC
            # 1920 = 90000/46.875 (AAC frame duration)
            audio_pts = (base_timestamp + audio_frame * 1920) & 0x1FFFFFFFF

            audio_pts_bytes = [
                0x21 | ((audio_pts >> 29) & 0x0E),
                (audio_pts >> 22) & 0xFF,
                0x01 | ((audio_pts >> 14) & 0xFE),
                (audio_pts >> 7) & 0xFF,
                0x01 | ((audio_pts << 1) & 0xFE)
            ]

            # Frame AAC silenzioso (7 bytes ADTS header + 1 byte payload)
            aac_frame = bytes([
                0xFF, 0xF1,  # ADTS sync + profile
                0x50, 0x80,  # sampling freq + channel config
                0x23, 0xFC,  # frame length + buffer fullness
                0x00, 0x00   # payload (silenzioso)
            ])

            audio_pes_header = bytes([
                0x00, 0x00, 0x01, 0xC0,  # PES start code + stream_id (audio)
                0x00, 0x00,  # PES_packet_length (0 = unbounded)
                0x84, 0x80, 0x05  # PES flags + header length
            ] + audio_pts_bytes)

            # Combina PES header con frame AAC
            audio_payload = audio_pes_header + aac_frame

            # Padding se necessario
            if len(audio_payload) < TS_PAYLOAD_SIZE:
                audio_payload = audio_payload + b'\xFF' * \
                    (TS_PAYLOAD_SIZE - len(audio_payload))

            # Header TS per audio
            audio_ts_header = bytes([
                0x47,  # sync_byte
                0x40 | ((AUDIO_PID >> 8) & 0x1F),  # PUSI=1 + PID high
                AUDIO_PID & 0xFF,  # PID low
                0x10 | (audio_continuity & 0x0F)  # payload_only + continuity
            ])

            audio_ts_packet = audio_ts_header + audio_payload[:TS_PAYLOAD_SIZE]
            ts_packets.append(audio_ts_packet)
            audio_continuity = (audio_continuity + 1) % 16

        # Combina tutti i pacchetti TS
        ts_stream = b''.join(ts_packets)

        enhanced_log(
            f"✅ [FMP4_CONVERT] Creati {
                len(ts_packets)} pacchetti TS ({
                len(ts_stream)} bytes)",
            "INFO",
            "proxy_ts")
        enhanced_log(
            f"📊 [FMP4_CONVERT] Struttura: PAT + PMT + {
                len(ts_packets) -
                5} video + PCR",
            "DEBUG",
            "proxy_ts")

        # Verifica sync byte
        if ts_stream and ts_stream[0] == 0x47:
            enhanced_log(
                "✅ [FMP4_CONVERT] Stream TS valido (sync byte 0x47)",
                "DEBUG",
                "proxy_ts")
        else:
            enhanced_log(
                "❌ [FMP4_CONVERT] ERRORE: Stream TS non valido!",
                "ERROR",
                "proxy_ts")

        enhanced_log(
            f"✅ [FMP4_CONVERT] Conversione completata: {
                len(ts_stream)} bytes TS",
            "INFO",
            "proxy_ts")

        return ts_stream

    except Exception as e:
        enhanced_log(
            f"❌ [FMP4_CONVERT] Errore conversione: {e}",
            "ERROR",
            "proxy_ts")
        # ✅ FALLBACK MIGLIORATO: Stream TS completo e valido per Enigma2
        try:
            # PAT completo
            pat = bytes([0x47,
                         0x40,
                         0x00,
                         0x10,
                         0x00]) + bytes([0x00,
                                         0xB0,
                                         0x0D,
                                         0x00,
                                         0x01,
                                         0xC1,
                                         0x00,
                                         0x00,
                                         0x00,
                                         0x01,
                                         0xF0,
                                         0x00,
                                         0x2A,
                                         0xB1,
                                         0x04,
                                         0xB2]) + b'\xFF' * 167

            # PMT completo con video + audio
            pmt = bytes([0x47,
                         0x50,
                         0x00,
                         0x10,
                         0x02]) + bytes([0x00,
                                         0xB0,
                                         0x17,
                                         0x00,
                                         0x01,
                                         0xC1,
                                         0x00,
                                         0x00,
                                         0xE1,
                                         0x00,
                                         0xF0,
                                         0x00]) + bytes([0x1B,
                                                         0xE1,
                                                         0x00,
                                                         0xF0,
                                                         0x00,
                                                         0x0F,
                                                         0xE1,
                                                         0x01,
                                                         0xF0,
                                                         0x00,
                                                         0x2F,
                                                         0x44,
                                                         0xB9,
                                                         0x9B]) + b'\xFF' * 163

            # Pacchetto video con PES header completo e PTS
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

            # Pacchetto audio AAC sintetico
            audio_pes = bytes([0x00,
                               0x00,
                               0x01,
                               0xC0,
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
            audio_payload = audio_pes + b'\xFF' * (184 - len(audio_pes))
            audio = bytes([0x47, 0x41, 0x01, 0x10]) + audio_payload

            fallback_ts = pat + pmt + video + audio
            enhanced_log(
                f"🔧 [FMP4_CONVERT] Fallback TS completo generato: {
                    len(fallback_ts)} bytes", "INFO", "proxy_ts")
            return fallback_ts
        except Exception as fallback_error:
            # Fallback di emergenza
            emergency_ts = b'\x47\x1F\xFF\x10' + b'\xFF' * 184
            enhanced_log(
                f"[FMP4_CONVERT] Errore fallback TS completo: {fallback_error}",
                "WARNING",
                "proxy_ts")
            enhanced_log(
                f"🆘 [FMP4_CONVERT] Fallback di emergenza: {
                    len(emergency_ts)} bytes",
                "WARNING",
                "proxy_ts")
            return emergency_ts


def is_valid_ts_payload(data, packets_to_check=5):
    """Verifica leggera MPEG-TS: sync byte 0x47 su piu' pacchetti da 188 byte."""
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
    """Genera un piccolo segmento TS valido da inviare quando un segmento cifrato e' inutilizzabile."""
    pat = bytes([
        0x47, 0x40, 0x00, 0x10, 0x00,
        0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00,
        0x00, 0x01, 0xF0, 0x00, 0x2A, 0xB1, 0x04, 0xB2
    ]) + b'\xFF' * 167
    null_packet = b'\x47\x1F\xFF\x10' + b'\xFF' * 184
    return pat + (null_packet * max(0, packet_count - 1))


def get_non_ts_content_type(url, content=None):
    """Riconosce risorse HLS non-video che non devono passare dalla decrittazione TS."""
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
    """Riconosce playlist/segmenti sottotitoli che non devono essere trattati come TS."""
    url_lower = (url or "").lower().split("?", 1)[0]
    subtitle_extensions = (".vtt", ".webvtt", ".srt", ".ttml", ".dfxp")
    subtitle_markers = ("/subtitle/", "/subtitles/", "/subs/")
    return url_lower.endswith(subtitle_extensions) or any(
        marker in url_lower for marker in subtitle_markers)


def is_subtitle_media_tag(line):
    """Riconosce tag HLS EXT-X-MEDIA dedicati ai sottotitoli."""
    line_upper = (line or "").upper()
    return line_upper.startswith(
        "#EXT-X-MEDIA") and "TYPE=SUBTITLES" in line_upper


def decrypt_ts_if_needed(ts_content, stream_id, headers, segment_url=None):
    """Decrittazione AES-128 con logging dettagliato per debug DLHD"""
    enhanced_log(
        f"🔐 [DECRYPT_TS] === INIZIO DECRITTAZIONE per stream {stream_id} ===",
        "INFO",
        "AppCore")

    if not AES_AVAILABLE:
        enhanced_log(f"❌ [DECRYPT_TS] AES non disponibile", "ERROR", "AppCore")
        return ts_content

    if len(ts_content) == 0:
        enhanced_log(f"❌ [DECRYPT_TS] Contenuto vuoto", "ERROR", "AppCore")
        return ts_content

    non_ts_content_type = get_non_ts_content_type(segment_url, ts_content)
    if non_ts_content_type:
        enhanced_log(
            f"[DECRYPT_TS] Risorsa non-TS rilevata ({non_ts_content_type}), decrittazione saltata",
            "INFO",
            "AppCore")
        return ts_content

    if len(ts_content) % 16 != 0:
        enhanced_log(
            f"[DECRYPT_TS] Lunghezza {
                len(ts_content)} non multipla di 16, segmento cifrato incompleto/non allineato",
            "WARNING",
            "AppCore")
        return make_fallback_ts_segment()

    # Log primo byte per debug
    enhanced_log(
        f"🔍 [DECRYPT_TS] Primo byte contenuto: 0x{
            ts_content[0]:02x}",
        "INFO",
        "AppCore")

    # ✅ CORREZIONE: Non saltare la decrittazione anche se sync byte è 0x47
    # Alcuni segmenti DLHD potrebbero avere 0x47 ma essere comunque criptati

    try:
        # Ottieni info stream
        stream_info = STREAM_KEY_INFO.get(stream_id, {})
        if not stream_info:
            enhanced_log(
                f"❌ [DECRYPT_TS] Stream info non trovato per {stream_id}",
                "ERROR",
                "AppCore")
            return ts_content

        enhanced_log(
            f"✅ [DECRYPT_TS] Stream info trovato per {stream_id}",
            "INFO",
            "AppCore")

        # Ottieni chiave AES
        aes_key = get_aes_key_for_stream(stream_id, headers, segment_url)
        if not aes_key:
            enhanced_log(
                f"❌ [DECRYPT_TS] Chiave AES non disponibile",
                "ERROR",
                "AppCore")
            return ts_content

        enhanced_log(
            f"✅ [DECRYPT_TS] Chiave AES ottenuta: {
                len(aes_key)} bytes",
            "INFO",
            "AppCore")

        # Usa IV dal stream info
        iv = stream_info.get('iv', b'\x00' * 16)
        if isinstance(iv, str):
            try:
                iv_str = iv.replace('0x', '') if iv.startswith('0x') else iv
                iv = bytes.fromhex(iv_str)
                enhanced_log(
                    f"🔢 [DECRYPT_TS] IV convertito da hex: {
                        iv.hex()}", "DEBUG", "AppCore")
            except Exception as iv_error:
                iv = iv.encode('latin-1')
                enhanced_log(
                    f"[DECRYPT_TS] IV non esadecimale, uso bytes latin-1: {iv_error}",
                    "DEBUG",
                    "AppCore")
                enhanced_log(
                    f"🔢 [DECRYPT_TS] IV convertito da stringa: {
                        iv.hex()}", "DEBUG", "AppCore")

        # Assicura che IV sia 16 bytes
        if len(iv) != 16:
            iv = (iv + b'\x00' * 16)[:16]
            enhanced_log(
                f"⚠️ [DECRYPT_TS] IV aggiustato a 16 bytes: {
                    iv.hex()}", "WARNING", "AppCore")

        enhanced_log(
            f"🔢 [DECRYPT_TS] IV finale: {
                iv.hex()}",
            "DEBUG",
            "AppCore")
        enhanced_log(
            f"🔑 [DECRYPT_TS] Chiave: {
                aes_key.hex()}",
            "DEBUG",
            "AppCore")

        # Decrittazione
        enhanced_log(
            f"🔄 [DECRYPT_TS] Inizio decrittazione AES-128-CBC",
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
            f"✅ [DECRYPT_TS] Decrittazione completata: {
                len(decrypted)} bytes",
            "INFO",
            "AppCore")

        # Rimuovi padding PKCS7
        if len(decrypted) > 0:
            padding_length = decrypted[-1]
            enhanced_log(
                f"🔍 [DECRYPT_TS] Ultimo byte (padding): 0x{
                    padding_length:02x}", "DEBUG", "AppCore")

            if 0 < padding_length <= 16:
                if all(
                        b == padding_length for b in decrypted[-padding_length:]):
                    decrypted = decrypted[:-padding_length]
                    enhanced_log(
                        f"✅ [DECRYPT_TS] Padding PKCS7 rimosso: {padding_length} bytes",
                        "INFO",
                        "AppCore")
                else:
                    enhanced_log(
                        f"⚠️ [DECRYPT_TS] Padding non valido, mantengo contenuto originale",
                        "WARNING",
                        "AppCore")
            else:
                enhanced_log(
                    f"⚠️ [DECRYPT_TS] Padding fuori range, nessuna rimozione",
                    "WARNING",
                    "AppCore")

        # Verifica sync byte finale
        if len(decrypted) > 0:
            enhanced_log(
                f"🔍 [DECRYPT_TS] Primo byte dopo decrittazione: 0x{
                    decrypted[0]:02x}", "INFO", "AppCore")

            if is_valid_ts_payload(decrypted):
                enhanced_log(
                    f"✅ [DECRYPT_TS] === DECRITTAZIONE RIUSCITA (sync byte 0x47) ===",
                    "INFO",
                    "AppCore")
                return decrypted
            else:
                enhanced_log(
                    f"⚠️ [DECRYPT_TS] Sync byte non valido dopo decrittazione: 0x{
                        decrypted[0]:02x}", "WARNING", "AppCore")
                # Prova senza rimuovere padding
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
                        f"✅ [DECRYPT_TS] === DECRITTAZIONE RIUSCITA (senza rimozione padding) ===",
                        "INFO",
                        "AppCore")
                    return decrypted_no_padding
                else:
                    enhanced_log(
                        f"❌ [DECRYPT_TS] Decrittazione fallita, ritorno contenuto originale",
                        "ERROR",
                        "AppCore")
                    return make_fallback_ts_segment()
        else:
            enhanced_log(
                f"❌ [DECRYPT_TS] Contenuto decriptato vuoto",
                "ERROR",
                "AppCore")
            return make_fallback_ts_segment()

    except Exception as e:
        enhanced_log(
            f"❌ [DECRYPT_TS] === ERRORE DURANTE DECRITTAZIONE: {
                type(e).__name__}: {
                str(e)} ===",
            "ERROR",
            "AppCore")
        import traceback
        enhanced_log(
            f"🔍 [DECRYPT_TS] Stack trace: {
                traceback.format_exc()}",
            "ERROR",
            "AppCore")
        return make_fallback_ts_segment()


enhanced_log("🚀 AppCoreSC - Inizializzazione", "INFO", "AppCore")

# Import extractor separati
try:
    from .extractor.dlhd_extractor import DLHDExtractor
    dlhd_extractor = DLHDExtractor()
    DLHD_AVAILABLE = True
    # ✅ CRITICO: Salva riferimento alla sessione DLHD per usarla nel download chiavi AES
    DLHD_SESSION = dlhd_extractor.session if hasattr(
        dlhd_extractor, 'session') else None
    enhanced_log("✅ DLHD extractor disponibile", "INFO", "AppCore")
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
        f"⚠️ DLHD extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

try:
    from .extractor.vavoo_extractor import vavoo_extractor, is_vavoo_link
    VAVOO_AVAILABLE = True
    enhanced_log("✅ Vavoo extractor disponibile", "INFO", "AppCore")
except ImportError as e:
    VAVOO_AVAILABLE = False

    def vavoo_extractor(*args, **kwargs):
        return None

    def is_vavoo_link(*args, **kwargs):
        return False
    enhanced_log(
        f"⚠️ Vavoo extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

try:
    from .extractor.vix_extractor import vix_extractor
    VIX_AVAILABLE = True
    enhanced_log("✅ VixCloud extractor disponibile", "INFO", "AppCore")
except ImportError as e:
    VIX_AVAILABLE = False

    class vix_extractor:
        @staticmethod
        def extract(url):
            return None
    enhanced_log(
        f"⚠️ VixCloud extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

# TVTap è ora gestito tramite WMS Manager e ServiceMonitor


def get_dlhd_session():
    if DLHD_AVAILABLE and dlhd_extractor and hasattr(
            dlhd_extractor, 'session'):
        return dlhd_extractor.session
    return None


TVTAP_AVAILABLE = True
enhanced_log("✅ TVTap gestito tramite WMS Manager", "INFO", "AppCore")

# Sportsonline extractor
try:
    from .extractor.sportonline_extractor import extract_sportonline, is_sportonline_link
    SPORTONLINE_AVAILABLE = True
    enhanced_log("✅ Sportsonline extractor disponibile", "INFO", "AppCore")
except ImportError as e:
    SPORTONLINE_AVAILABLE = False

    def extract_sportonline(*args, **kwargs):
        return None

    def is_sportonline_link(*args, **kwargs):
        return False
    enhanced_log(
        f"⚠️ Sportsonline extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

# Sport99 / CDNLiveTV extractor
try:
    from .extractor.sport99_extractor import extract_sport99, is_sport99_link
    SPORT99_AVAILABLE = True
    enhanced_log("Sport99 extractor disponibile", "INFO", "AppCore")
except ImportError as e:
    SPORT99_AVAILABLE = False

    def extract_sport99(*args, **kwargs):
        return None

    def is_sport99_link(*args, **kwargs):
        return False
    enhanced_log(
        f"Sport99 extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

# Freeshot extractor
try:
    from .extractor.freeshot_extractor import freeshot_extractor, is_freeshot_link
    FREESHOT_AVAILABLE = True
    enhanced_log("✅ Freeshot extractor disponibile", "INFO", "AppCore")
except ImportError as e:
    FREESHOT_AVAILABLE = False

    def is_freeshot_link(*args, **kwargs):
        return False

    class freeshot_extractor:
        @staticmethod
        def extract(url):
            return None
    enhanced_log(
        f"⚠️ Freeshot extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

# Maxstream extractor
try:
    from .extractor.maxstream_extractor import MaxstreamExtractor, is_maxstream_link
    maxstream_extractor = MaxstreamExtractor()
    MAXSTREAM_AVAILABLE = True
    enhanced_log("✅ Maxstream extractor disponibile", "INFO", "AppCore")
except ImportError as e:
    MAXSTREAM_AVAILABLE = False

    def is_maxstream_link(*args, **kwargs):
        return False

    class MaxstreamExtractor:
        def extract(self, url, **kwargs):
            return None
    maxstream_extractor = MaxstreamExtractor()
    enhanced_log(
        f"⚠️ Maxstream extractor non disponibile: {e}",
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
    enhanced_log("✅ Mixdrop extractor disponibile", "INFO", "AppCore")
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
        f"⚠️ Mixdrop extractor non disponibile: {e}",
        "WARNING",
        "AppCore")

# Configurazione ottimizzata per Enigma2
VERIFY_SSL = False
REQUEST_TIMEOUT = 15  # Timeout aumentato per connessioni lente


# Cache vuote per compatibilità con ServiceMonitor
def is_direct_media_url(url):
    """Riconosce URL video diretti non-HLS."""
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

# --- Configurazione Generale ---
# VERIFY_SSL = os.environ.get('VERIFY_SSL', 'false').lower() not in ('false', '0', 'no')
# if not VERIFY_SSL:
#     app.logger.warning("ATTENZIONE: La verifica del certificato SSL è DISABILITATA. Questo potrebbe esporre a rischi di sicurezza.")
#     import urllib3
#     urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Timeout aumentato per gestire meglio i segmenti TS di grandi dimensioni
# Configurazione ottimizzata per Enigma2
try:
    REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', '15'))
except (ValueError, TypeError):
    REQUEST_TIMEOUT = 15

enhanced_log(
    f"Timeout per le richieste impostato a {REQUEST_TIMEOUT} secondi.",
    "INFO",
    "AppCore")

# Configurazioni semplificate per Enigma2 (Keep-Alive disabilitato)
try:
    KEEP_ALIVE_TIMEOUT = int(os.environ.get('KEEP_ALIVE_TIMEOUT', '60'))
    MAX_KEEP_ALIVE_REQUESTS = int(
        os.environ.get(
            'MAX_KEEP_ALIVE_REQUESTS',
            '100'))
    POOL_CONNECTIONS = int(os.environ.get('POOL_CONNECTIONS', '5'))
    POOL_MAXSIZE = int(os.environ.get('POOL_MAXSIZE', '10'))
    enhanced_log(
        f"Keep-Alive configurato: timeout={KEEP_ALIVE_TIMEOUT}s, max_requests={MAX_KEEP_ALIVE_REQUESTS}",
        "INFO",
        "AppCore")

except (ValueError, TypeError):
    KEEP_ALIVE_TIMEOUT = 60
    MAX_KEEP_ALIVE_REQUESTS = 100
    POOL_CONNECTIONS = 5
    POOL_MAXSIZE = 10
enhanced_log(
    f"Keep-Alive disabilitato: timeout={KEEP_ALIVE_TIMEOUT}s, max_requests={MAX_KEEP_ALIVE_REQUESTS}",
    "INFO",
    "AppCore")

# Pool globale di sessioni per connessioni persistenti
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
    """Richiesta HTTP ottimizzata per Enigma2 con retry automatico e gestione errori migliorata"""
    default_headers = {
        'Accept': '*/*',
        'Connection': 'close'
    }

    # Solo se non c'è User-Agent, usa quello di default
    if not headers or not headers.get('User-Agent'):
        default_headers['User-Agent'] = 'Enigma2-StreamProxy/1.2'

    if headers:
        default_headers.update(headers)

    timeout = timeout or REQUEST_TIMEOUT
    retry_codes = [429, 500, 502, 503, 504]

    # ✅ OTTIMIZZAZIONE: Per Freeshot, usa timeout più aggressivi
    is_freeshot_url = 'lovecdn.ru' in url.lower()
    if is_freeshot_url:
        timeout = min(timeout, 4)  # Max 4 secondi per Freeshot
        max_attempts = 2  # Solo 2 tentativi per velocità
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
                # Retry più veloce per Freeshot
                time.sleep(sleep_time * (attempt + 1))
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_attempts - 1:
                sleep_time = 0.1 if is_freeshot_url else 0.3
                # Retry molto veloce per timeout
                time.sleep(sleep_time * (attempt + 1))
                continue
            if is_freeshot_url:
                enhanced_log(
                    f"⚠️ [FREESHOT_TIMEOUT] Timeout dopo {max_attempts} tentativi: {url[-50:]}", "WARNING", "AppCore")
            else:
                enhanced_log(
                    f"❌ Errore richiesta dopo {max_attempts} tentativi: {e}",
                    "ERROR",
                    "AppCore")
            raise
        except requests.exceptions.HTTPError as e:
            # Per errori HTTP specifici, non fare retry
            enhanced_log(f"❌ Errore HTTP: {e}", "ERROR", "AppCore")
            raise
        except Exception as e:
            enhanced_log(f"❌ Errore richiesta: {e}", "ERROR", "AppCore")
            raise
    return response


def get_enigma2_timeout(url):
    """Timeout ottimizzati per Enigma2"""
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


# Compatibilità per codice esistente che usa vavoo_resolver
if VAVOO_AVAILABLE:
    # Usa il nuovo extractor come vavoo_resolver per compatibilità
    from .extractor.vavoo_extractor import vavoo_resolver
else:
    # Fallback dummy per compatibilità
    class DummyVavooResolver:
        def resolve_vavoo_link(self, link):
            return None

        def clear_vavoo_cache(self, x=None):
            pass
    vavoo_resolver = DummyVavooResolver()


def extract_custom_headers_from_url(url):
    """✅ Estrae headers custom dall'URL (formato: #Header=Value&Header2=Value2)"""
    if not url or '#' not in url:
        return url, {}

    try:
        # Separa URL e fragment
        url_parts = url.split('#', 1)
        clean_url = url_parts[0]
        fragment = url_parts[1] if len(url_parts) > 1 else ''

        if not fragment:
            return url, {}

        # Estrai headers dal fragment
        headers = {}
        for param in fragment.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                # Decodifica e normalizza
                key = unquote(key).strip()
                value = unquote(value).strip()
                headers[key] = value
                enhanced_log(
                    f"✅ [CUSTOM_HEADER] Estratto: {key} = {value[:50]}...", "DEBUG", "AppCore")

        return clean_url, headers
    except Exception as e:
        enhanced_log(
            f"❌ [CUSTOM_HEADER] Errore estrazione: {e}",
            "ERROR",
            "AppCore")
        return url, {}


def resolve_m3u8_link(url, headers=None, **kwargs):
    """
    Risolve URL DaddyLive con multi-endpoint e log dettagliati per debug
    Gestisce flusso completo: estrazione → validazione → chiave AES
    """
    enhanced_log(
        f"🚀 [RESOLVE_START] Inizio risoluzione URL: {url[:100]}...", "INFO", "AppCore")

    if not url:
        enhanced_log("❌ [RESOLVE_ERROR] URL non fornito", "ERROR", "AppCore")
        return {"resolved_url": None, "headers": {}}

    # ✅ ESTRAI HEADERS CUSTOM DALL'URL (Origin, Referer, User-Agent)
    clean_url, custom_headers = extract_custom_headers_from_url(url)
    if custom_headers:
        enhanced_log(
            f"✅ [CUSTOM_HEADERS] Estratti {
                len(custom_headers)} headers custom",
            "INFO",
            "AppCore")
        url = clean_url  # Usa URL pulito senza fragment

    current_headers = headers.copy() if headers else {}
    # Aggiungi headers custom estratti
    current_headers.update(custom_headers)
    enhanced_log(
        f"🔍 [RESOLVE_HEADERS] Headers iniziali: {
            len(current_headers)} elementi",
        "DEBUG",
        "AppCore")

    # 1. Estrazione header dall'URL
    enhanced_log(
        "📋 [RESOLVE_STEP1] Inizio estrazione header dall'URL",
        "INFO",
        "AppCore")
    clean_url = url
    extracted_headers = {}

    if '&h_' in url or '%26h_' in url:
        enhanced_log(
            "🔍 [RESOLVE_HEADERS] Rilevati parametri header nell'URL",
            "INFO",
            "AppCore")
        temp_url = url

        if 'vavoo.to' in temp_url.lower() and '%26' in temp_url:
            temp_url = temp_url.replace('%26', '&')
            enhanced_log(
                "🔄 [RESOLVE_HEADERS] Sostituito %26 con & per Vavoo",
                "DEBUG",
                "AppCore")

        if '%26h_' in temp_url:
            temp_url = unquote(unquote(temp_url))
            enhanced_log(
                "🔄 [RESOLVE_HEADERS] Doppio unquote applicato",
                "DEBUG",
                "AppCore")

        url_parts = temp_url.split('&h_', 1)
        clean_url = url_parts[0]
        header_params = '&h_' + url_parts[1]
        enhanced_log(
            f"🔍 [RESOLVE_HEADERS] URL pulito: {clean_url[:50]}...", "DEBUG", "AppCore")
        enhanced_log(
            f"🔍 [RESOLVE_HEADERS] Parametri header: {header_params[:100]}...", "DEBUG", "AppCore")

        for param in header_params.split('&'):
            if param.startswith('h_'):
                try:
                    key_value = param[2:].split('=', 1)
                    if len(key_value) == 2:
                        key = unquote(key_value[0]).replace('_', '-')
                        value = unquote(key_value[1])
                        extracted_headers[key] = value
                        enhanced_log(f"✅ [RESOLVE_HEADERS] Estratto header: {key} = {value[:20]}...", "DEBUG",
                                     "AppCore")
                except Exception as e:
                    enhanced_log(
                        f"❌ [RESOLVE_HEADERS] Errore estrazione {param}: {e}",
                        "ERROR",
                        "AppCore")

    final_headers = {**current_headers, **extracted_headers}
    enhanced_log(
        f"✅ [RESOLVE_STEP1] Headers finali: {
            len(final_headers)} elementi",
        "INFO",
        "AppCore")

    # 2. Controllo tipo URL con extractor separati
    enhanced_log("📋 [RESOLVE_STEP2] Controllo tipo URL", "INFO", "AppCore")

    # Controllo Sport99 / CDNLiveTV - dominio specifico prima dei matcher
    # generici
    if SPORT99_AVAILABLE and is_sport99_link(clean_url):
        enhanced_log(
            f"[RESOLVE_SPORT99] Rilevato link Sport99/CDNLiveTV: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            resolved_sport99 = extract_sport99(clean_url, final_headers)
            if resolved_sport99 and resolved_sport99.get("resolved_url"):
                enhanced_log(
                    "[RESOLVE_SPORT99] Sport99 risolto con successo",
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
                    "[RESOLVE_SPORT99] Sport99 resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"[RESOLVE_SPORT99] Errore Sport99 resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo PowerSet (LiveTV), dopo i domini piu specifici
    if LIVETV_AVAILABLE and is_powerset_domain(clean_url):
        enhanced_log(
            f"✅ [RESOLVE_POWERSET] Rilevato dominio powerset: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            resolved_powerset = process_powerset_url(clean_url, final_headers)
            if resolved_powerset and resolved_powerset.get("resolved_url"):
                enhanced_log(
                    "✅ [RESOLVE_POWERSET] PowerSet risolto con successo",
                    "INFO",
                    "AppCore")
                # Combina gli headers esistenti con quelli del resolver
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
                    "⚠️ [RESOLVE_POWERSET] PowerSet resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_POWERSET] Errore PowerSet resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo DaddyLive/DLHD con extractor separato
    if DLHD_AVAILABLE and dlhd_extractor.is_daddylive_link(clean_url):
        enhanced_log(
            f"✅ [RESOLVE_DLHD] Rilevato link DaddyLive/DLHD: {clean_url[:50]}...", "INFO", "AppCore")
        enhanced_log(
            "🚀 [DLHD_FLOW] === INIZIO FLUSSO ESTRAZIONE DADDYLIVE ===",
            "INFO",
            "AppCore")
        try:
            resolved_dlhd = dlhd_extractor.extract_stream(clean_url)
            if resolved_dlhd and resolved_dlhd.get("destination_url"):
                enhanced_log(
                    "✅ [DLHD_FLOW] === FLUSSO COMPLETATO CON SUCCESSO ===",
                    "INFO",
                    "AppCore")
                enhanced_log(
                    f"🎯 [DLHD_FLOW] URL finale: {
                        resolved_dlhd['destination_url']}",
                    "INFO",
                    "AppCore")

                # Combina gli headers finali con quelli del resolver
                combined_headers = {**final_headers, **
                                    resolved_dlhd.get("request_headers", {})}

                # Log headers per debug
                enhanced_log(
                    f"📤 [DLHD_FLOW] Headers combinati: {
                        list(
                            combined_headers.keys())}",
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
                    "❌ [DLHD_FLOW] === FLUSSO FALLITO - NESSUN URL ===",
                    "ERROR",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [DLHD_FLOW] === FLUSSO FALLITO - ERRORE: {e} ===",
                "ERROR",
                "AppCore")
            import traceback
            enhanced_log(
                f"🔍 [DLHD_FLOW] Traceback: {
                    traceback.format_exc()}",
                "DEBUG",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo VixCloud con extractor separato
    if VIX_AVAILABLE and any(vix_domain in clean_url.lower()
                             for vix_domain in ['vix', 'vixcloud', 'vixsrc']):
        enhanced_log(
            f"✅ [RESOLVE_VIX] Rilevato link VixCloud: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            resolved_vix = vix_extractor.extract(clean_url)
            if resolved_vix and (resolved_vix.get(
                    "resolved_url") or resolved_vix.get("m3u8_content")):
                enhanced_log(
                    "✅ [RESOLVE_VIX] VixCloud risolto con successo",
                    "INFO",
                    "AppCore")
                # CORREZIONE: Restituisce l'intero dizionario dal resolver Vix,
                # non solo una parte, per preservare 'm3u8_content'.
                resolved_vix["headers"] = {
                    **final_headers, **resolved_vix.get("headers", {})}
                return resolved_vix
            else:
                enhanced_log(
                    "⚠️ [RESOLVE_VIX] VixCloud resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_VIX] Errore VixCloud resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo Vavoo con extractor separato
    if VAVOO_AVAILABLE and is_vavoo_link(clean_url):
        enhanced_log(
            f"✅ [RESOLVE_VAVOO] Rilevato link Vavoo: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            resolved_vavoo = vavoo_extractor.extract(clean_url, final_headers)
            if resolved_vavoo and resolved_vavoo.get("resolved_url"):
                enhanced_log(
                    "✅ [RESOLVE_VAVOO] Vavoo risolto con successo",
                    "INFO",
                    "AppCore")
                return resolved_vavoo
            else:
                enhanced_log(
                    "⚠️ [RESOLVE_VAVOO] Vavoo resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_VAVOO] Errore Vavoo resolver: {e}",
                "ERROR",
                "AppCore")
            # FALLBACK: Se Vavoo fallisce, prova a restituire un M3U8 di errore
            # più user-friendly
            if "timeout" in str(e).lower() or "connection" in str(e).lower():
                enhanced_log(
                    "🔄 [RESOLVE_VAVOO] Timeout/connessione - restituisco fallback",
                    "WARNING",
                    "AppCore")
                return {
                    "resolved_url": None,
                    "headers": final_headers,
                    "m3u8_content": "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-ENDLIST\n# Vavoo server temporaneamente non disponibile\n"
                }
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo Sportsonline
    if SPORTONLINE_AVAILABLE and is_sportonline_link(clean_url):
        enhanced_log(
            f"✅ [RESOLVE_SPORTONLINE] Rilevato link Sportsonline: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            resolved_sport = extract_sportonline(clean_url)
            if resolved_sport and resolved_sport.get("resolved_url"):
                enhanced_log(
                    "✅ [RESOLVE_SPORTONLINE] Sportsonline risolto con successo",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **
                                    resolved_sport.get("headers", {})}
                return {
                    "resolved_url": resolved_sport["resolved_url"],
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "⚠️ [RESOLVE_SPORTONLINE] Sportsonline resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_SPORTONLINE] Errore Sportsonline resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo Freeshot
    if FREESHOT_AVAILABLE and is_freeshot_link(clean_url):
        enhanced_log(
            f"✅ [RESOLVE_FREESHOT] Rilevato link Freeshot: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            resolved_freeshot = freeshot_extractor.extract(clean_url)
            if resolved_freeshot and resolved_freeshot.get("resolved_url"):
                enhanced_log(
                    "✅ [RESOLVE_FREESHOT] Freeshot risolto con successo",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **
                                    resolved_freeshot.get("headers", {})}
                return {
                    "resolved_url": resolved_freeshot["resolved_url"],
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "⚠️ [RESOLVE_FREESHOT] Freeshot resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_FREESHOT] Errore Freeshot resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo Maxstream
    if MAXSTREAM_AVAILABLE and is_maxstream_link(clean_url):
        enhanced_log(
            f"✅ [RESOLVE_MAXSTREAM] Rilevato link Maxstream: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            # Estrai parametri season/episode se presenti
            season = kwargs.get('season')
            episode = kwargs.get('episode')
            resolved_maxstream = maxstream_extractor.extract(
                clean_url, season=season, episode=episode)
            if resolved_maxstream and resolved_maxstream.get("resolved_url"):
                enhanced_log(
                    "✅ [RESOLVE_MAXSTREAM] Maxstream risolto con successo",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **
                                    resolved_maxstream.get("headers", {})}
                return {
                    "resolved_url": resolved_maxstream["resolved_url"],
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "⚠️ [RESOLVE_MAXSTREAM] Maxstream resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_MAXSTREAM] Errore Maxstream resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo Mixdrop
    if MIXDROP_AVAILABLE and (is_mixdrop_link(clean_url) or any(
            domain in clean_url.lower() for domain in MIXDROP_DOMAINS)):
        enhanced_log(
            f"✅ [RESOLVE_MIXDROP] Rilevato link Mixdrop: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            resolved_mixdrop = mixdrop_extractor.extract(clean_url)
            mixdrop_url = resolved_mixdrop.get("resolved_url") or resolved_mixdrop.get(
                "destination_url") if resolved_mixdrop else None
            mixdrop_headers = resolved_mixdrop.get("headers") or resolved_mixdrop.get(
                "request_headers") if resolved_mixdrop else {}
            if resolved_mixdrop and mixdrop_url:
                enhanced_log(
                    "✅ [RESOLVE_MIXDROP] Mixdrop risolto con successo",
                    "INFO",
                    "AppCore")
                combined_headers = {**final_headers, **mixdrop_headers}
                return {
                    "resolved_url": mixdrop_url,
                    "headers": combined_headers}
            else:
                enhanced_log(
                    "⚠️ [RESOLVE_MIXDROP] Mixdrop resolver ha restituito None",
                    "WARNING",
                    "AppCore")
                return {"resolved_url": clean_url, "headers": final_headers}
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_MIXDROP] Errore Mixdrop resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # Controllo TVTap diretto
    if TVTAP_AVAILABLE and any(
        pattern in clean_url.lower() for pattern in [
            'tvtap',
            'rocktalk.net',
            'taptube.net',
            'authsign=',
            'stream.mardio.link']):
        enhanced_log(
            f"✅ [RESOLVE_TVTAP] Rilevato link TVTap: {clean_url[:50]}...", "INFO", "AppCore")
        try:
            # TVTap viene gestito direttamente, restituisci l'URL pulito
            return {
                "resolved_url": clean_url,
                "headers": final_headers,
                "tvtap_info": {"direct_stream": True}
            }
        except Exception as e:
            enhanced_log(
                f"❌ [RESOLVE_TVTAP] Errore TVTap resolver: {e}",
                "ERROR",
                "AppCore")
            return {"resolved_url": clean_url, "headers": final_headers}

    # URL generico - passthrough
    enhanced_log(
        "🔄 [RESOLVE_PASSTHROUGH] URL generico, passthrough",
        "INFO",
        "AppCore")
    return {"resolved_url": clean_url, "headers": final_headers}


def get_dynamic_timeout(url, base_timeout=REQUEST_TIMEOUT):
    """Calcola timeout dinamico ottimizzato per velocità di cambio canale."""
    url_lower = url.lower()

    # CORREZIONE: Timeout ridotti per migliorare la reattività del cambio
    # canale
    if '.ts' in url_lower:
        # Segmenti TS: timeout ridotti
        if any(d in url_lower for d in ['kiko2.ru', 'daddylive', 'daddy']):
            return 6  # DaddyLive TS: 6s (ridotto)
        elif any(d in url_lower for d in ['vavoo', 'shouurvki7jtfax', 'ngolpdkyoctjcddxshli469r']):
            return 8  # Vavoo TS: 8s (ridotto da 10s)
        else:
            return 6  # Altri TS: 6s
    elif '.m3u8' in url_lower:
        # Playlist M3U8: timeout ridotti per cambio canale veloce
        if any(d in url_lower for d in ['kiko2.ru', 'daddylive', 'daddy']):
            return 8  # DaddyLive M3U8: 8s (ridotto)
        elif any(d in url_lower for d in ['vavoo', 'shouurvki7jtfax', 'ngolpdkyoctjcddxshli469r']):
            return 10  # Vavoo M3U8: 10s (ridotto da 12s)
        else:
            return 8  # Altri M3U8: 8s
    else:
        # Richieste generiche: timeout ridotti
        if any(
            d in url_lower for d in [
                'vavoo',
                'shouurvki7jtfax',
                'ngolpdkyoctjcddxshli469r']):
            return 8  # Vavoo generico: 8s (ridotto da 10s)
        else:
            return 6  # Altri: 6s


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
                f"[VAVOO_PREFETCH] Attendo prefetch per {stream_id} fino a {wait_timeout}s",
                "INFO",
                "AppCore")
            event.wait(wait_timeout)
            entry = VAVOO_M3U8_PREFETCH_CACHE.get(stream_id)
            if not entry:
                return None

    if entry.get('in_progress'):
        enhanced_log(
            f"[VAVOO_PREFETCH] Prefetch ancora in corso per {stream_id}",
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
        f"⚡ [VAVOO_PREFETCH] M3U8 da prefetch per stream {stream_id}",
        "INFO",
        "AppCore")
    if consume:
        return VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
    return entry.copy()


def _clear_vavoo_resolved_url_cache(reason=""):
    """Pulisce solo gli URL CDN Vavoo risolti, mantenendo firma/sessione se possibile."""
    if not VAVOO_AVAILABLE:
        return
    try:
        cache = getattr(vavoo_extractor, "_url_cache", None)
        if isinstance(cache, dict):
            cache.clear()
            enhanced_log(
                f"[VAVOO] Cache URL risolti pulita{
                    ': ' + reason if reason else ''}",
                "INFO",
                "AppCore")
        elif hasattr(vavoo_extractor, "clear_cache"):
            vavoo_extractor.clear_cache()
            enhanced_log(
                f"[VAVOO] Cache extractor pulita{
                    ': ' + reason if reason else ''}",
                "INFO",
                "AppCore")
    except Exception as exc:
        enhanced_log(
            f"[VAVOO] Errore pulizia cache URL: {exc}",
            "DEBUG",
            "AppCore")


def prefetch_vavoo_m3u8(m3u_url, headers=None):
    """Avvia in background la risoluzione Vavoo prima che Enigma2 chieda l'M3U8.

    Per Vavoo il prefetch prepara solo l'URL CDN. La playlist viene scaricata
    dalla richiesta reale, evitando due download CDN paralleli al cambio canale.
    """
    if not m3u_url or 'vavoo' not in m3u_url.lower():
        return False

    stream_id = get_stream_id_from_url(m3u_url)
    existing = VAVOO_M3U8_PREFETCH_CACHE.get(stream_id)
    if existing and time.time() - existing.get('timestamp', 0) < 20:
        enhanced_log(
            f"⚡ [VAVOO_PREFETCH] Prefetch già disponibile/in corso per {stream_id}",
            "DEBUG",
            "AppCore")
        return True

    event = threading.Event()
    VAVOO_M3U8_PREFETCH_CACHE[stream_id] = {
        'in_progress': True,
        'timestamp': time.time(),
        'event': event}

    def _worker():
        try:
            enhanced_log(
                f"⚡ [VAVOO_PREFETCH] Avvio prefetch per {stream_id}",
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
                    f"✅ [VAVOO_PREFETCH] M3U8 pronto per {stream_id}: {
                        len(m3u_content)} caratteri", "INFO", "AppCore")
            else:
                VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
                enhanced_log(
                    f"⚠️ [VAVOO_PREFETCH] Contenuto non valido per {stream_id}",
                    "WARNING",
                    "AppCore")
        except Exception as exc:
            VAVOO_M3U8_PREFETCH_CACHE.pop(stream_id, None)
            _clear_vavoo_resolved_url_cache("prefetch fallito")
            enhanced_log(
                f"⚠️ [VAVOO_PREFETCH] Fallito per {stream_id}: {exc}",
                "WARNING",
                "AppCore")
        finally:
            event.set()

    threading.Thread(target=_worker, daemon=True).start()
    return True


def wait_vavoo_prefetch(m3u_url, timeout=0):
    """Ritorna il risultato del prefetch Vavoo, aspettando poco se è in corso."""
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
        "[VAVOO] Download playlist con sessione fresh",
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

    # Controlla se è un URL DaddyLive
    is_daddylive = (
        'kiko2.ru' in url.lower() or
        re.search(r'stream-\d+', url.lower()) is not None or
        'thedaddy.dad' in url.lower() or
        'daddylive' in url.lower()
    )

    # Controlla se è Mixdrop (richiede proxy per IP)
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
                "[VAVOO_PROXY] Uso proxy per CDN/resolve Vavoo",
                "INFO",
                "AppCore")
            return {'http': chosen_proxy, 'https': chosen_proxy}

    # Se è DaddyLive o Mixdrop, usa i proxy specifici
    if is_daddylive or is_mixdrop:
        daddy_proxies = get_daddy_proxy_list()
        if daddy_proxies:
            chosen_proxy = random.choice(daddy_proxies)
            return {'http': chosen_proxy, 'https': chosen_proxy}

    # Altrimenti usa i proxy generali
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
    """Estrae l'ID del canale da vari formati URL"""
    match_premium = re.search(r'/premium(\d+)/mono\.m3u8$', url)
    if match_premium:
        return match_premium.group(1)

    match_player = re.search(
        r'/(?:watch|stream|cast|player)/stream-(\d+)\.php', url)
    if match_player:
        return match_player.group(1)

    return None


def refresh_freeshot_token(channel_name, old_token):
    """Refresh automatico del token Freeshot scaduto - OTTIMIZZATO"""
    try:
        if not FREESHOT_AVAILABLE:
            return None

        enhanced_log(
            f"🔄 [FREESHOT_REFRESH] Refresh token per canale: {channel_name}",
            "INFO",
            "AppCore")

        # Mappa dei canali Freeshot più comuni
        channel_mapping = {
            'SkySport24IT': 'sky-sport-24-it',
            'SkySportUnoIT': 'sky-sport-uno-it',
            'SkySportDueIT': 'sky-sport-due-it',
            'SkySportCalcioIT': 'sky-sport-calcio-it',
            'SkySportArenaIT': 'sky-sport-arena-it',
            'SkySportMaxIT': 'sky-sport-max-it'
        }

        # Trova il nome del canale per Freeshot
        freeshot_channel = channel_mapping.get(channel_name)
        if not freeshot_channel:
            # Fallback migliorato: converti automaticamente
            freeshot_channel = channel_name.lower()
            # Aggiungi trattini prima delle parole chiave
            freeshot_channel = freeshot_channel.replace('sky', 'sky-')
            freeshot_channel = freeshot_channel.replace('sport', 'sport-')
            freeshot_channel = freeshot_channel.replace('24', '-24')
            freeshot_channel = freeshot_channel.replace('it', '-it')
            # Pulisci doppi trattini
            freeshot_channel = freeshot_channel.replace('--', '-')
            if not freeshot_channel.endswith('-it'):
                freeshot_channel += '-it'

        # Usa ID canale generico per Sky Sport 24
        channel_id = '383' if 'sport-24' in freeshot_channel else '26'

        # Estrai stream da Freeshot con nuovo token
        freeshot_url = f"https://www.freeshot.live/live-tv/{freeshot_channel}/{channel_id}"
        enhanced_log(
            f"🔄 [FREESHOT_REFRESH] Tentativo refresh: {freeshot_url}",
            "DEBUG",
            "AppCore")

        fresh_result = freeshot_extractor.extract(freeshot_url)
        if fresh_result and fresh_result.get('resolved_url'):
            fresh_url = fresh_result['resolved_url']

            # Estrai il nuovo token
            token_match = re.search(r'token=([^&]+)', fresh_url)
            if token_match:
                new_token = token_match.group(1)
                enhanced_log(
                    f"✅ [FREESHOT_REFRESH] Nuovo token ottenuto: {new_token[:20]}...", "INFO", "AppCore")
                return new_token
            else:
                enhanced_log(
                    f"⚠️ [FREESHOT_REFRESH] Token non trovato nell'URL",
                    "WARNING",
                    "AppCore")
                return None
        else:
            enhanced_log(
                f"❌ [FREESHOT_REFRESH] Extractor fallito",
                "ERROR",
                "AppCore")
            return None

    except Exception as e:
        enhanced_log(
            f"❌ [FREESHOT_REFRESH] Errore refresh token: {e}",
            "ERROR",
            "AppCore")
        return None


def get_stream_id_from_url(url):
    """
    ✅ SOLUZIONE CRITICA: Genera Stream ID deterministico per canale per evitare conflitti

    Il problema originale: ogni risoluzione genera UUID random → stream_id diversi
    per lo stesso canale → Enigma2 non trova la cache → visione interrotta

    SOLUZIONE: Usa hash del canale per Stream ID coerente per lo stesso canale
    """
    import hashlib

    # Per DaddyLive, usa l'ID del canale come base
    if 'daddyhd.com' in url or 'daddylive' in url:
        channel_match = re.search(r'[?&]id=(\d+)', url)
        if channel_match:
            channel_id = channel_match.group(1)
            # ✅ CRITICO: Usa hash SHA256 troncato per unicità stabile
            stream_id = hashlib.sha256(
                f"daddy_{channel_id}".encode()).hexdigest()[:12]
            enhanced_log(
                f"🆔 [STREAM_ID] Stream ID deterministico per canale DaddyLive {channel_id}: {stream_id}",
                "INFO",
                "AppCore")
            return stream_id

    # Per VIX, usa ID stabili invece dell'URL completo: token/rendition
    # cambiano spesso.
    if 'vixsrc.to/tv/' in url or 'vixcloud.co/tv/' in url:
        tv_match = re.search(r'/tv/(\d+)(?:/(\d+))?(?:/(\d+))?', url)
        if tv_match:
            tv_key = "_".join([part for part in tv_match.groups() if part])
            stream_id = hashlib.sha256(
                f"vix_tv_{tv_key}".encode()).hexdigest()[:12]
            enhanced_log(
                f"ðŸ†” [STREAM_ID] Stream ID deterministico per VIX tv {tv_key}: {stream_id}",
                "INFO",
                "AppCore")
            return stream_id

    # Per VIX, usa l'ID del playlist come base
    if 'vixsrc.to/playlist/' in url or 'vixcloud.co/playlist/' in url:
        playlist_match = re.search(r'/playlist/(\d+)', url)
        if playlist_match:
            playlist_id = playlist_match.group(1)
            stream_id = hashlib.sha256(
                f"vix_{playlist_id}".encode()).hexdigest()[:12]
            enhanced_log(
                f"🆔 [STREAM_ID] Stream ID deterministico per VIX playlist {playlist_id}: {stream_id}",
                "INFO",
                "AppCore")
            return stream_id

    # Per Freeshot, usa il nome del canale come base
    if 'lovecdn.ru' in url:
        channel_match = re.search(r'lovecdn\.ru/([^/]+)/', url)
        if channel_match:
            channel_name = channel_match.group(1)
            stream_id = hashlib.sha256(
                f"freeshot_{channel_name}".encode()).hexdigest()[:12]
            enhanced_log(
                f"🆔 [STREAM_ID] Stream ID deterministico per Freeshot {channel_name}: {stream_id}",
                "INFO",
                "AppCore")
            return stream_id

    # Per VAVOO, estrai l'ID del canale
    if 'vavoo' in url.lower():
        channel_match = re.search(r'[?&]id=([^&]+)', url)
        if channel_match:
            channel_id = channel_match.group(1)
            stream_id = hashlib.sha256(
                f"vavoo_{channel_id}".encode()).hexdigest()[:12]
            enhanced_log(
                f"🆔 [STREAM_ID] Stream ID deterministico per Vavoo {channel_id}: {stream_id}",
                "INFO",
                "AppCore")
            return stream_id

    # Per altri URL, usa l'URL stesso come base (meno ideale, ma comunque
    # stabile)
    stream_id = hashlib.sha256(url.encode()).hexdigest()[:12]
    enhanced_log(
        f"🆔 [STREAM_ID] Stream ID deterministico generico: {stream_id}",
        "INFO",
        "AppCore")
    return stream_id


def is_daddy_domain(url):
    """Verifica se l'URL appartiene ai domini daddy per log dettagliati"""
    if not url:
        return False
    url_lower = url.lower()
    return any(d in url_lower for d in [
        'kiko2.ru', 'giokko.ru', 'daddylive', 'daddy', 'dlhd', 'thedaddy.dad',
        'chevy.', 'tigertestxtg.sbs', 'soyspace.cyou'
    ])


def detect_m3u_type(content):
    """Rileva se è un M3U (lista IPTV) o un M3U8 (flusso HLS)"""
    if "#EXTM3U" in content and "#EXTINF" in content:
        return "m3u8"
    return "m3u"


def replace_key_uri(line, headers_query):
    """Sostituisce l'URI della chiave AES-128 con il proxy"""
    match = re.search(r'URI="([^"]+)"', line)
    if match:
        key_url = match.group(1)
        proxied_key_url = f"http://127.0.0.1:7860/proxy/key?url={
            quote(key_url)}&{headers_query}"
        return line.replace(key_url, proxied_key_url)
    return line


def get_proxy_with_fallback(url, max_retries=3):
    """Ottiene un proxy con fallback automatico in caso di errore"""
    if not PROXY_LIST:
        return None

    # Prova diversi proxy in caso di errore
    for attempt in range(max_retries):
        try:
            proxy_config = get_proxy_for_url(url)
            if proxy_config:
                return proxy_config
        except Exception:
            continue

    return None


# Route Registry SEMPLIFICATO
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
            f"🔍 [DEBUG] dispatch {name}: args={args}, kwargs={kwargs}",
            "DEBUG",
            "AppCore")

        if name in self.routes:
            # Assicurati di passare **kwargs
            return self.routes[name](**kwargs)
        raise ValueError(f"Route '{name}' non trovata")


route_registry = RouteRegistry()


# Proxy MPD per DASH
@route_registry.route('/proxy/mpd')
def proxy_mpd(request=None, **kwargs):
    """Proxy MPD - Enigma2 non supporta DASH nativamente"""
    mpd_url = kwargs.get('url', '').strip()
    enhanced_log(
        f"⚠️ [MPD] Enigma2 non supporta DASH: {mpd_url[:100]}...", "WARNING", "AppCore")

    m3u8_content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-ENDLIST\n"
        f"# Stream MPD/DASH non supportato da Enigma2\n"
    )
    return {
        'content': m3u8_content.encode(),
        'status': 200,
        'content_type': 'application/vnd.apple.mpegurl'
    }


# Proxy M3U SENZA CACHE
@route_registry.route('/proxy/m3u')
def proxy_m3u(request=None, **kwargs):
    """Proxy M3U SENZA CACHE - Risultati diretti"""
    enhanced_log("🎬 Proxy M3U", "INFO", "AppCore")

    m3u_url = kwargs.get('url', '').strip()
    enhanced_log(f"🔍 [DEBUG] URL ricevuto: {m3u_url}", "DEBUG", "AppCore")

    if not m3u_url:
        enhanced_log("❌ [DEBUG] URL vuoto!", "ERROR", "AppCore")

        return {
            'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }

    try:
        # Estrai headers custom dai parametri (h_User-Agent, h_Referer, etc.)
        custom_headers = {
            unquote(key[2:]).replace("_", "-"): unquote(value).strip()
            for key, value in kwargs.items()
            if key.lower().startswith("h_")
        }
        if custom_headers:
            enhanced_log(
                f"📤 [PROXY_M3U] Headers custom estratti: {
                    list(
                        custom_headers.keys())}",
                "DEBUG",
                "AppCore")

        # ✅ ESTRAI PARAMETRO dlhd_masked dalla richiesta (verrà aggiornato dopo resolve)
        dlhd_masked_param = kwargs.get('dlhd_masked', '0') == '1'
        enhanced_log(
            f"🎭 [DLHD_MASKED] Parametro dlhd_masked iniziale: {dlhd_masked_param}",
            "DEBUG",
            "AppCore")

        # ✅ SOLUZIONE CRITICA: Stream ID deterministico evita clearance accidentale
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
                        f"[VAVOO_M3U8_CACHE] Refresh gia' in corso, riuso ultima playlist valida ({
                            int(cached_age)}s)", "INFO", "AppCore")
                    return {
                        'content': cached_content,
                        'status': 200,
                        'content_type': 'application/vnd.apple.mpegurl'
                    }
                if cached_content and cached_age < 6:
                    enhanced_log(
                        f"[VAVOO_M3U8_CACHE] Playlist recente da cache ({
                            int(cached_age)}s)", "INFO", "AppCore")
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

        # Verifica se è un refresh automatico dello stesso canale
        # ✅ MIGLIORATO: Usa lo stream_id per identificare se è lo stesso canale
        is_same_channel = current_stream_id in STREAM_KEY_INFO

        if not is_same_channel:
            # Cambio canale, pulisci cache per evitare conflitti
            clear_stream_cache()
            enhanced_log(
                f"🧹 [CACHE_CLEAR] Cache pulite per cambio canale. Nuovo stream_id: {current_stream_id}",
                "INFO",
                "AppCore")
        else:
            # ✅ NUOVO: Se è lo stesso canale, riusa la cache ma aggiorna timestamp
            enhanced_log(
                f"♻️  [CACHE_REUSE] Stesso canale (stream_id: {current_stream_id}), cache riutilizzata",
                "INFO",
                "AppCore")
            # Controllo intelligente scadenza token JWT per DaddyLive
            if 'daddyhd.com' in m3u_url or 'daddylive' in m3u_url:
                try:
                    stream_info = STREAM_KEY_INFO[current_stream_id]
                    headers = stream_info.get('headers', {})
                    auth_header = headers.get('Authorization', '')

                    if auth_header.startswith('Bearer '):
                        token = auth_header[7:]
                        try:
                            import jwt
                            # Decodifica senza verifica per leggere exp
                            decoded = jwt.decode(
                                token, options={
                                    "verify_signature": False})
                            exp_time = decoded.get('exp', 0)
                            current_time = time.time()
                            remaining_time = exp_time - current_time

                            # Refresh solo se mancano meno di 2 minuti alla
                            # scadenza
                            if remaining_time < 120:
                                enhanced_log(
                                    f"🔄 [TOKEN_REFRESH] Token scade tra {
                                        int(remaining_time)}s, refresh necessario", "INFO", "AppCore")

                                # Invalida cache DLHD per questo canale
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
                                                    f"🗑️ [DLHD_CACHE] Cache invalidata per canale {channel_id}", "INFO", "AppCore")
                                    except Exception as cache_error:
                                        enhanced_log(
                                            f"[DLHD_CACHE] Errore invalidazione cache: {cache_error}", "DEBUG", "AppCore")

                                # Rimuovi stream per forzare nuovo download
                                del STREAM_KEY_INFO[current_stream_id]
                                keys_to_remove = [
                                    k for k in AES_KEY_CACHE.keys() if k.startswith(current_stream_id)]
                                for k in keys_to_remove:
                                    del AES_KEY_CACHE[k]
                                is_same_channel = False  # Forza nuovo download
                                enhanced_log(
                                    f"♻️  [CACHE_INVALIDATED] Cache invalidata per refresh token",
                                    "INFO",
                                    "AppCore")
                            else:
                                enhanced_log(
                                    f"✅ [TOKEN_VALID] Token valido per altri {
                                        int(remaining_time)}s", "DEBUG", "AppCore")
                        except ImportError:
                            enhanced_log(
                                "⚠️ [TOKEN_CHECK] PyJWT non disponibile, uso fallback temporale",
                                "WARNING",
                                "AppCore")
                            # Fallback: refresh ogni 4 minuti se PyJWT non
                            # disponibile
                            last_used = stream_info.get('last_used', 0)
                            if time.time() - last_used > 240:
                                enhanced_log(
                                    f"🔄 [FALLBACK_REFRESH] Refresh fallback dopo 4 minuti", "INFO", "AppCore")
                                del STREAM_KEY_INFO[current_stream_id]
                                is_same_channel = False
                        except Exception as e:
                            enhanced_log(
                                f"⚠️ [TOKEN_CHECK] Errore verifica token: {e}", "WARNING", "AppCore")
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [TOKEN_CHECK] Errore controllo token: {e}",
                        "WARNING",
                        "AppCore")

        enhanced_log(
            "🔍 [DEBUG] Chiamata resolve_m3u8_link direttamente",
            "DEBUG",
            "AppCore")
        if prefetched_result:
            enhanced_log(
                "[VAVOO_PREFETCH] Uso risultato pre-risolto",
                "INFO",
                "AppCore")
            result = prefetched_result
            if custom_headers:
                result["headers"] = {
                    **result.get("headers", {}), **custom_headers}
        else:
            result = resolve_m3u8_link(m3u_url, custom_headers)
        enhanced_log(
            f"🔍 [DEBUG] Risultato resolve: {result}",
            "DEBUG",
            "AppCore")

        if not result.get("resolved_url") and not result.get("m3u8_content"):
            return {
                'content': "Errore: Impossibile risolvere l'URL in un M3U8 valido.".encode(),
                'status': 500,
                'content_type': 'text/plain'}

        final_url = result.get("resolved_url")

        # ✅ CORREZIONE: Rileva automaticamente segmenti DLHD mascherati DOPO aver ottenuto final_url
        is_dlhd_domain = final_url and is_daddy_domain(final_url)
        dlhd_masked = kwargs.get(
            'dlhd_masked',
            '0') == '1' or is_dlhd_domain or is_daddy_domain(m3u_url)
        enhanced_log(
            f"🎭 [DLHD_MASKED] Parametro dlhd_masked: {dlhd_masked} (auto-rilevato: {is_dlhd_domain})",
            "INFO",
            "AppCore")

        # ✅ CORREZIONE CRITICA: Inizializza m3u_content prima dell'uso
        m3u_content = result.get("m3u8_content", "")
        current_headers_for_proxy = result.get("headers", {}).copy()
        # Nei passthrough VIX il resolver puo' ricreare gli header base e perdere
        # h_Referer arrivato dalla playlist master. VIX lo usa per
        # key/segmenti.
        current_headers_for_proxy.update(custom_headers or {})

        if final_url and is_direct_media_url(final_url):
            headers_query = "&".join(
                [f"h_{quote(k)}={quote(v)}" for k, v in current_headers_for_proxy.items()])
            media_stream_id = get_stream_id_from_url(m3u_url)
            encoded_media_url = quote(final_url, safe='')
            proxy_media_url = f"http://127.0.0.1:7860/proxy/ts?url={encoded_media_url}&fmp4=1&stream_id={media_stream_id}"
            if headers_query:
                proxy_media_url += f"&{headers_query}"
            enhanced_log(
                f"🎬 [DIRECT_MEDIA] URL diretto risolto, genero playlist wrapper: {final_url[:80]}...", "INFO", "AppCore")
            return {
                'content': b'',
                'status': 302,
                'content_type': 'video/mp4',
                'redirect_url': proxy_media_url
            }

        # Se il resolver (es. Vix) non ha già fornito il contenuto, scaricalo
        if not m3u_content:
            # ✅ OTTIMIZZAZIONE: Timeout ridotti per Enigma2
            timeout_to_use = 6 if 'kiko2.ru' in final_url else get_dynamic_timeout(
                final_url)
            enhanced_log(
                f"🕐 [M3U8_TIMEOUT] Timeout ottimizzato: {timeout_to_use}s",
                "DEBUG",
                "AppCore")

            # Usa proxy per Mixdrop
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
                    "[VAVOO] 403 su URL CDN risolto, pulisco cache e ritento una volta",
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
                    "[VAVOO] 403 persistente, provo varianti header CDN",
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
                            f"[VAVOO] Playlist CDN accettata con headers: {
                                list(
                                    variant_headers.keys())}",
                            "INFO",
                            "AppCore")
                        break
            if not m3u_content:
                m3u_response.raise_for_status()
                m3u_content = m3u_response.text
                final_url = m3u_response.url  # Aggiorna con l'URL finale dopo i redirect

            # ✅ VALIDAZIONE: Verifica che sia un M3U8 valido
            if not m3u_content.strip().startswith('#EXTM3U'):
                enhanced_log(
                    "❌ [M3U8_VALIDATION] Contenuto non è un M3U8 valido (probabilmente HTML)",
                    "ERROR",
                    "AppCore")
                enhanced_log(
                    f"📄 [M3U8_VALIDATION] Primi 200 caratteri: {m3u_content[:200]}", "DEBUG", "AppCore")
                return {
                    'content': "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-ENDLIST\n# Errore: URL non restituisce M3U8 valido\n".encode(),
                    'status': 200,
                    'content_type': 'application/vnd.apple.mpegurl'}
        else:
            enhanced_log(
                "ℹ️ [proxy_m3u] Utilizzo contenuto M3U8 pre-processato dal resolver.",
                "INFO",
                "AppCore")

        enhanced_log(
            f"📄 [M3U8_CONTENT] Contenuto M3U8 ricevuto ({
                len(m3u_content)} caratteri):",
            "DEBUG",
            "AppCore")
        enhanced_log(
            f"📄 [M3U8_CONTENT] Prime 500 caratteri: {m3u_content[:500]}", "DEBUG", "AppCore")

        parsed_url = urlparse(final_url)
        base_url = f"{
            parsed_url.scheme}://{
            parsed_url.netloc}{
            parsed_url.path.rsplit(
                '/', 1)[0]}/"

        # CRITICO: Crea query string con gli header dalla risoluzione
        headers_query = "&".join(
            [f"h_{quote(k)}={quote(v)}" for k, v in current_headers_for_proxy.items()])
        stream_id = get_stream_id_from_url(m3u_url)

        # CRITICO: Salva le informazioni dello stream per i segmenti TS
        extract_key_info_from_m3u8(
            m3u_content.splitlines(),
            stream_id,
            base_url,
            current_headers_for_proxy,
            result)

        # ✅ CORREZIONE: Salva sempre le informazioni base dello stream anche senza chiave AES
        if stream_id not in STREAM_KEY_INFO:
            STREAM_KEY_INFO[stream_id] = {
                'headers': current_headers_for_proxy or {},
                'base_url': base_url,
                'is_daddy': is_daddy_domain(final_url),
                'is_freeshot': 'lovecdn.ru' in final_url.lower()
            }
            enhanced_log(
                f"💾 [STREAM_INFO] Salvate info base per stream {stream_id}",
                "DEBUG",
                "AppCore")
        else:
            # ✅ AGGIORNAMENTO CRITICO: Aggiorna headers se lo stream esiste già
            # Questo è fondamentale per i segmenti TS che devono ricevere gli
            # headers corretti
            existing_headers = STREAM_KEY_INFO[stream_id].get('headers', {})
            existing_headers.update(current_headers_for_proxy or {})
            STREAM_KEY_INFO[stream_id]['headers'] = existing_headers
            enhanced_log(
                f"🔄 [STREAM_INFO] Aggiornati headers per stream esistente {stream_id}",
                "DEBUG",
                "AppCore")
            enhanced_log(
                f"📝 [STREAM_INFO] Headers salvati: {
                    list(
                        existing_headers.keys())}",
                "DEBUG",
                "AppCore")

        # Pulisci automaticamente segmenti scaduti più frequentemente
        if random.randint(
                1, 5) == 1:  # 20% di probabilità per pulizia più frequente
            cleanup_expired_segments()

        modified_m3u8 = []
        aes_key_line = None  # Salva la linea della chiave AES per DLHD

        for line in m3u_content.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-KEY") and 'AES-128' in line:
                # Per DLHD, mantieni la chiave AES nel M3U8
                if is_daddy_domain(final_url) or is_daddy_domain(m3u_url):
                    # Sostituisci l'URI della chiave con il proxy
                    uri_match = re.search(r'URI="([^"]+)"', line)
                    if uri_match:
                        key_url = urljoin(base_url, uri_match.group(1))
                        proxy_key_url = f"http://127.0.0.1:7860/proxy/key?url={
                            quote(key_url)}&{headers_query}"
                        aes_key_line = line.replace(
                            uri_match.group(1), proxy_key_url)
                        enhanced_log(
                            f"🔑 [DLHD_KEY] Chiave AES mantenuta nel M3U8: {key_url[-30:]}", "INFO", "AppCore")
                continue
            elif line.startswith("#EXT-X-MAP") and 'URI="' in line:
                # ✅ SOLUZIONE OTTIMIZZATA: Per fMP4, mantieni EXT-X-MAP per compatibilità nativa
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    init_url = urljoin(base_url, uri_match.group(1))
                    enhanced_log(
                        f"📥 [INIT_MAP] Init segment URL: {init_url}",
                        "INFO",
                        "AppCore")

                    # ✅ CORREZIONE: Assicurati che STREAM_KEY_INFO esista
                    if stream_id not in STREAM_KEY_INFO:
                        STREAM_KEY_INFO[stream_id] = {
                            'headers': current_headers_for_proxy or {},
                            'base_url': base_url,
                            'is_daddy': is_daddy_domain(final_url),
                            'is_freeshot': 'lovecdn.ru' in final_url.lower()
                        }

                    # ✅ NUOVO APPROCCIO: Per Freeshot, mantieni EXT-X-MAP nel M3U8
                    # Enigma2 moderno può gestire init segment automaticamente
                    if STREAM_KEY_INFO[stream_id].get('is_freeshot', False):
                        # Trasforma l'URI in proxy per mantenere gli headers
                        if headers_query:
                            proxy_init_url = f"http://127.0.0.1:7860/proxy/ts?url={
                                quote(init_url)}&fmp4=1&stream_id={stream_id}&{headers_query}"
                        else:
                            proxy_init_url = f"http://127.0.0.1:7860/proxy/ts?url={
                                quote(init_url)}&fmp4=1&stream_id={stream_id}"

                        # Sostituisci l'URI originale con il proxy
                        line = line.replace(uri_match.group(1), proxy_init_url)
                        enhanced_log(
                            f"✅ [INIT_MAP] EXT-X-MAP mantenuto con proxy per Freeshot",
                            "INFO",
                            "AppCore")
                        modified_m3u8.append(line)
                        continue
                    else:
                        # Per altri provider, scarica e salva init segment
                        # (comportamento originale)
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
                                    f"✅ [INIT_DOWNLOAD] Init segment salvato: {
                                        len(init_content)} bytes", "INFO", "AppCore")

                            # Rimuovi EXT-X-MAP per compatibilità
                            enhanced_log(
                                f"⚠️ [INIT_SKIP] Rimosso EXT-X-MAP per compatibilità Enigma2",
                                "INFO",
                                "AppCore")
                            continue

                        except Exception as e:
                            enhanced_log(
                                f"❌ [INIT_DOWNLOAD] Errore download init: {e}", "ERROR", "AppCore")
                            # Rimuovi EXT-X-MAP anche in caso di errore
                            continue
                else:
                    enhanced_log(
                        f"⚠️ [INIT_SKIP] EXT-X-MAP senza URI valido",
                        "WARNING",
                        "AppCore")
                    continue
            elif line.startswith("#EXT-X-MEDIA") and 'URI="' in line:
                if is_subtitle_media_tag(line):
                    enhanced_log(
                        f"[SUBTITLE_SKIP] Traccia sottotitoli rimossa dall'M3U8 per evitare richieste VTT via TS",
                        "INFO",
                        "AppCore")
                    continue

                # Trasforma URI audio/sottotitoli in URL proxy
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    media_url = uri_match.group(1)
                    media_url = urljoin(base_url, media_url)
                    if is_subtitle_resource(media_url):
                        enhanced_log(
                            f"[SUBTITLE_SKIP] Playlist sottotitoli rimossa: {media_url[-60:]}", "INFO", "AppCore")
                        continue
                    if headers_query:
                        proxy_media_url = f"http://127.0.0.1:7860/proxy/m3u?url={
                            quote(media_url)}&{headers_query}"
                    else:
                        proxy_media_url = f"http://127.0.0.1:7860/proxy/m3u?url={
                            quote(media_url)}"
                    line = line.replace(uri_match.group(1), proxy_media_url)
                modified_m3u8.append(line)
            elif line and not line.startswith("#"):
                segment_url = urljoin(base_url, line)
                segment_url_lower = segment_url.lower()

                if is_subtitle_resource(segment_url):
                    enhanced_log(
                        f"[SUBTITLE_SKIP] Segmento sottotitoli scartato: {line}",
                        "INFO",
                        "AppCore")
                    continue

                # ✅ CORREZIONE CRITICA: Validazione migliorata per segmenti DLHD
                is_dlhd_domain = is_daddy_domain(
                    segment_url_lower) or dlhd_masked

                if is_dlhd_domain:
                    # Per DLHD, mantieni TUTTI i segmenti da domini DLHD (anche quelli codificati)
                    # Scarta solo immagini, font, CSS/JS reali
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
                            f"⚠️ [SEGMENT_SKIP] Segmento non-video scartato (DLHD): {line}",
                            "WARNING",
                            "AppCore")
                        continue
                    # Accetta TUTTI gli altri segmenti da domini DLHD (inclusi
                    # quelli codificati)
                    enhanced_log(
                        f"✅ [DLHD_SEGMENT] Segmento DLHD accettato: {line[:50]}...", "DEBUG", "AppCore")
                else:
                    # Per altri provider, scarta .html/.css/.js/.txt
                    # normalmente
                    if any(
                        ext in segment_url_lower for ext in [
                            '.js',
                            '.html',
                            '.txt',
                            '.css',
                            '.json']):
                        enhanced_log(
                            f"⚠️ [SEGMENT_SKIP] Segmento non-video scartato: {line}",
                            "WARNING",
                            "AppCore")
                        continue

                # ✅ SOLUZIONE FREESHOT: Conversione automatica fMP4 → TS per Enigma2
                # Enigma2 ha problemi con fMP4, convertiamo tutto in TS

                # Determina se è un segmento TS, fMP4 o una playlist
                if '.m3u8' in segment_url_lower or 'playlist' in segment_url_lower:
                    # È una playlist, usa proxy/m3u
                    if headers_query:
                        proxy_url = f"http://127.0.0.1:7860/proxy/m3u?url={
                            quote(segment_url)}&{headers_query}"
                    else:
                        proxy_url = f"http://127.0.0.1:7860/proxy/m3u?url={
                            quote(segment_url)}"
                elif '.fmp4' in segment_url_lower:
                    # ✅ SOLUZIONE OTTIMIZZATA: Per Freeshot, usa fMP4 diretto (no conversione)
                    # Enigma2 moderno gestisce fMP4 nativamente
                    encoded_url = quote(segment_url, safe='')
                    if headers_query:
                        proxy_url = f"http://127.0.0.1:7860/proxy/ts?url={encoded_url}&fmp4=1&stream_id={stream_id}&{headers_query}"
                    else:
                        proxy_url = f"http://127.0.0.1:7860/proxy/ts?url={encoded_url}&fmp4=1&stream_id={stream_id}"
                    enhanced_log(
                        f"📦 [FMP4_DIRECT] Segmento fMP4 diretto: {segment_url[-50:]}", "INFO", "AppCore")
                    enhanced_log(
                        f"🔗 [FMP4_DIRECT] URL proxy: {proxy_url[:100]}...", "DEBUG", "AppCore")
                else:
                    # È un segmento TS (qualsiasi altra estensione, inclusi .html per DLHD), usa proxy/ts
                    # ✅ CRITICO: stream_id DEVE essere nel query string per la decrittazione
                    if headers_query:
                        proxy_url = f"http://127.0.0.1:7860/proxy/ts?url={
                            quote(segment_url)}&stream_id={stream_id}&{headers_query}"
                    else:
                        proxy_url = f"http://127.0.0.1:7860/proxy/ts?url={
                            quote(segment_url)}&stream_id={stream_id}"

                    # Log specifico per segmenti DLHD (inclusi quelli
                    # codificati)
                    if is_dlhd_domain:
                        enhanced_log(
                            f"🎭 [DLHD_SEGMENT] Segmento DLHD processato come TS: {segment_url.split('/')[-1][:30]}...", "INFO", "AppCore")
                        # Forza content-type corretto per segmenti DLHD
                    if dlhd_masked:
                        proxy_url += "&dlhd_masked=1"

                enhanced_log(
                    f"✅ [SEGMENT_PROXY] Segmento trasformato in proxy: {segment_url[-50:]}", "DEBUG", "AppCore")
                modified_m3u8.append(proxy_url)
            else:
                modified_m3u8.append(line)

        # Aggiungi la chiave AES all'inizio per DLHD se presente
        if aes_key_line:
            # Inserisci la chiave dopo #EXT-X-VERSION
            final_lines = []
            key_inserted = False
            for line in modified_m3u8:
                final_lines.append(line)
                if line.startswith('#EXT-X-VERSION') and not key_inserted:
                    final_lines.append(aes_key_line)
                    key_inserted = True
            modified_m3u8 = final_lines

        # ✅ CORREZIONE CRITICA: Se M3U8 è vuoto, prova URL alternativo .m3u8
        segment_lines = [line for line in modified_m3u8 if line and not line.startswith(
            '#') and line.strip()]
        if len(segment_lines) == 0:
            enhanced_log(
                "⚠️ [M3U8_EMPTY] M3U8 vuoto - PROVO URL .m3u8 ALTERNATIVO",
                "WARNING",
                "AppCore")

            # Prova URL .m3u8 invece di .css
            if final_url.endswith('.css'):
                alt_url = final_url.replace('.css', '.m3u8')
                enhanced_log(
                    f"🔄 [M3U8_ALT] Tentativo URL alternativo: {alt_url}",
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
                            # Verifica che contenga segmenti video reali
                            alt_segments = [line for line in alt_content.splitlines(
                            ) if line and not line.startswith('#') and line.strip()]
                            video_segments = [
                                seg for seg in alt_segments if not any(
                                    ext in seg.lower() for ext in [
                                        '.js', '.html', '.txt', '.css', '.json'])]

                            if len(video_segments) > 0:
                                enhanced_log(
                                    f"✅ [M3U8_ALT] URL alternativo con {
                                        len(video_segments)} segmenti video", "INFO", "AppCore")

                                # Sostituisci contenuto
                                m3u_content = alt_content
                                final_url = alt_url

                                # Riprocessa completamente
                                parsed_url = urlparse(final_url)
                                base_url = f"{
                                    parsed_url.scheme}://{
                                    parsed_url.netloc}{
                                    parsed_url.path.rsplit(
                                        '/', 1)[0]}/"
                                headers_query = "&".join(
                                    [f"h_{quote(k)}={quote(v)}" for k, v in current_headers_for_proxy.items()])

                                extract_key_info_from_m3u8(
                                    m3u_content.splitlines(), stream_id, base_url, current_headers_for_proxy, result)

                                # Riprocessa segmenti
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
                                                f"[SUBTITLE_SKIP] Segmento sottotitoli scartato in M3U8 alternativo: {line}",
                                                "INFO",
                                                "AppCore")
                                            continue

                                        # Scarta segmenti non-video
                                        if any(
                                            ext in segment_url_lower for ext in [
                                                '.js', '.html', '.txt', '.css', '.json']):
                                            continue

                                        # Processa come segmento TS valido
                                        if headers_query:
                                            proxy_url = f"http://127.0.0.1:7860/proxy/ts?url={
                                                quote(segment_url)}&stream_id={stream_id}&{headers_query}"
                                        else:
                                            proxy_url = f"http://127.0.0.1:7860/proxy/ts?url={
                                                quote(segment_url)}&stream_id={stream_id}"

                                        modified_m3u8.append(proxy_url)
                                    else:
                                        modified_m3u8.append(line)

                                enhanced_log(
                                    f"✅ [M3U8_ALT] M3U8 alternativo processato con successo", "INFO", "AppCore")
                            else:
                                enhanced_log(
                                    f"⚠️ [M3U8_ALT] URL alternativo senza segmenti video validi",
                                    "WARNING",
                                    "AppCore")
                        else:
                            enhanced_log(
                                f"⚠️ [M3U8_ALT] URL alternativo non è M3U8 valido",
                                "WARNING",
                                "AppCore")
                    else:
                        enhanced_log(
                            f"⚠️ [M3U8_ALT] URL alternativo HTTP {
                                alt_response.status_code}", "WARNING", "AppCore")

                except Exception as alt_error:
                    enhanced_log(
                        f"❌ [M3U8_ALT] Errore URL alternativo: {alt_error}",
                        "ERROR",
                        "AppCore")

        # ✅ MODIFICA NECESSARIA: Rimuovi completamente #EXT-X-KEY quando dlhd_masked=1
        if dlhd_masked:
            # Rimuovi tutte le righe che iniziano con #EXT-X-KEY
            m3u8_lines = [line for line in "\n".join(modified_m3u8).split('\n')
                          if not line.strip().startswith('#EXT-X-KEY')]
            final_m3u8 = '\n'.join(m3u8_lines) + "\n"
            enhanced_log(
                f"🎭 [DLHD_MASKED] Rimossa riga #EXT-X-KEY dall'M3U8 per dlhd_masked=1",
                "INFO",
                "AppCore")
        else:
            final_m3u8 = "\n".join(modified_m3u8) + "\n"

        enhanced_log(
            f"📄 [M3U8_FINAL] M3U8 finale ({
                len(final_m3u8)} caratteri):",
            "DEBUG",
            "AppCore")
        enhanced_log(
            f"📄 [M3U8_FINAL] Prime 500 caratteri: {final_m3u8[:500]}", "DEBUG", "AppCore")

        # ✅ VALIDAZIONE FINALE: Verifica che M3U8 abbia segmenti validi
        segment_count = len([line for line in final_m3u8.splitlines(
        ) if line and not line.startswith('#') and line.strip()])
        if segment_count == 0:
            enhanced_log(
                "⚠️ [M3U8_VALIDATION] M3U8 finale senza segmenti - possibile problema",
                "WARNING",
                "AppCore")
        else:
            enhanced_log(
                f"✅ [M3U8_VALIDATION] M3U8 finale con {segment_count} segmenti validi",
                "INFO",
                "AppCore")

        final_m3u8_bytes = final_m3u8.encode()
        if is_vavoo_request:
            VAVOO_FINAL_M3U8_CACHE[stream_id] = {
                'content': final_m3u8_bytes,
                'timestamp': time.time(),
                'in_progress': False,
            }
            enhanced_log(
                f"[VAVOO_M3U8_CACHE] Playlist salvata per refresh ({segment_count} segmenti)",
                "DEBUG",
                "AppCore")

        return {
            'content': final_m3u8_bytes,
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }

    except Exception as e:
        enhanced_log(f"❌ Errore: {str(e)}", "ERROR", "proxy_m3u")
        return {
            'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }


@route_registry.route('/proxy/resolve')
def proxy_resolve(request=None, **kwargs):
    """Proxy per risolvere e restituire un URL M3U8 con metodo DaddyLive 2025 - Enigma2"""
    request_args = kwargs or {}
    url = request_args.get('url', '').strip()
    if not url:
        return {
            'content': "Errore: Parametro 'url' mancante",
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
                'content': "Errore: Impossibile risolvere l'URL",
                'status': 500,
                'content_type': 'text/plain'
            }

        headers_query = "&".join(
            [f"h_{quote(k)}={quote(v)}" for k, v in result["headers"].items()])
        m3u_content = (
            f"#EXTM3U\n"
            f"#EXTINF:-1,Canale Risolto\n"
            f"/proxy/m3u?url={quote(result['resolved_url'])}&{headers_query}"
        )

        return {
            'content': m3u_content,
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }

    except Exception as e:
        enhanced_log(
            f"Errore durante la risoluzione dell'URL: {
                str(e)}", "ERROR", "AppCore")
        return {
            'content': f"Errore durante la risoluzione dell'URL: {str(e)}",
            'status': 500,
            'content_type': 'text/plain'
        }


# Cache per URL mapping
URL_MAPPING = {}
URL_COUNTER = 1


def create_short_url(long_url, headers_query, stream_id):
    """Crea URL brevi per i segmenti TS"""
    global URL_COUNTER

    # Crea chiave breve
    short_key = f"ts{URL_COUNTER}"
    URL_COUNTER += 1

    # Salva mapping
    URL_MAPPING[short_key] = {
        'url': long_url,
        'headers': headers_query,
        'stream_id': stream_id
    }

    return f"http://127.0.0.1:7860/proxy/ts?key={short_key}"

# Proxy TS
# In AppCore.py, nel metodo proxy_ts, aggiungi log dettagliati:


@route_registry.route('/proxy/init.hls.fmp4')
def proxy_init_fmp4(request=None, **kwargs):
    """Proxy per segmenti init fMP4 (Freeshot) con fallback sintetico"""
    enhanced_log(
        "🎬 [INIT_FMP4] Inizio processamento init fMP4",
        "INFO",
        "proxy_fmp4")

    token = kwargs.get('token', '').strip()
    if not token:
        enhanced_log("❌ [INIT_FMP4] Token mancante", "ERROR", "proxy_fmp4")
        return {'content': b'', 'status': 400, 'content_type': 'text/plain'}

    # Costruisci URL init basato sul dominio corrente
    init_url = f"https://beautifulpeople.lovecdn.ru/SkySport24IT/init.hls.fmp4?token={token}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        'Referer': f'https://beautifulpeople.lovecdn.ru/SkySport24IT/embed.html?token={token}',
        'Origin': 'https://beautifulpeople.lovecdn.ru'}

    try:
        response = make_enigma2_request(init_url, headers=headers, timeout=10)
        response.raise_for_status()

        enhanced_log(
            f"✅ [INIT_FMP4] Init scaricato: {len(response.content)} bytes", "INFO", "proxy_fmp4")

        return {
            'content': response.content,
            'status': 200,
            'content_type': 'video/mp4'
        }

    except Exception as e:
        enhanced_log(
            f"⚠️ [INIT_FMP4] Server init fallito: {e}",
            "WARNING",
            "proxy_fmp4")
        enhanced_log(
            "🔧 [INIT_FMP4] Genero init sintetico per fMP4",
            "INFO",
            "proxy_fmp4")

        # ✅ SOLUZIONE: Init segment fMP4 sintetico minimo per Enigma2
        # Contiene ftyp + moov box essenziali per decodifica fMP4
        synthetic_init = bytes.fromhex(
            '0000001c667479706d736468000000006d7364686d70343200000000'  # ftyp box
            '000000286d6f6f76000000206d766864000000000000000000000000'  # moov + mvhd
            '000003e800000000000100000100000000000000000000000000'      # mvhd data
        )

        enhanced_log(
            f"✅ [INIT_FMP4] Init sintetico generato: {
                len(synthetic_init)} bytes",
            "INFO",
            "proxy_fmp4")

        return {
            'content': synthetic_init,
            'status': 200,
            'content_type': 'video/mp4'
        }


@route_registry.route('/proxy/ts')
def proxy_ts(request=None, **kwargs):
    """Proxy TS ottimizzato per Enigma2 con decrittazione AES-128 e gestione fMP4 + DLHD .html"""
    enhanced_log(
        "🎬 [PROXY_TS] === INIZIO PROCESSAMENTO SEGMENTO TS ===",
        "INFO",
        "proxy_ts")

    # ✅ LOGGING DETTAGLIATO PER DEBUG
    enhanced_log(
        f"🔍 [PROXY_TS] Kwargs ricevuti: {
            list(
                kwargs.keys())}",
        "DEBUG",
        "proxy_ts")

    ts_url = kwargs.get('url', '').strip()
    stream_id = kwargs.get('stream_id', '')
    is_fmp4 = kwargs.get('fmp4', '0') == '1'
    is_dlhd_masked = kwargs.get('dlhd_masked', '0') == '1'

    enhanced_log(
        f"📋 [PROXY_TS] URL estratto: {ts_url[-50:] if ts_url else 'VUOTO'}", "INFO", "proxy_ts")
    enhanced_log(f"📋 [PROXY_TS] Stream ID: {stream_id}", "INFO", "proxy_ts")
    enhanced_log(
        f"📋 [PROXY_TS] fMP4: {is_fmp4}, DLHD masked: {is_dlhd_masked}",
        "INFO",
        "proxy_ts")

    if not ts_url:
        enhanced_log(
            "❌ [PROXY_TS] URL mancante - ERRORE CRITICO",
            "ERROR",
            "proxy_ts")
        return {
            'content': b'',
            'status': 400,
            'content_type': 'text/plain'
        }

    enhanced_log(
        f"✅ [PROXY_TS] URL valido ricevuto, continuo processamento",
        "INFO",
        "proxy_ts")

    # ✅ RILEVAMENTO DLHD MIGLIORATO: Tutti i segmenti da domini DLHD sono potenzialmente video
    if not is_dlhd_masked:
        is_dlhd_masked = is_daddy_domain(
            ts_url) or 'playerfuncc.fun' in ts_url.lower()
        enhanced_log(
            f"🔍 [PROXY_TS] DLHD rilevato automaticamente: {is_dlhd_masked}",
            "DEBUG",
            "proxy_ts")

    enhanced_log(
        f"📦 [PROXY_TS] Richiesta segmento: {ts_url.split('/')[-1] if '/' in ts_url else ts_url[-30:]}", "INFO", "proxy_ts")
    if stream_id:
        enhanced_log(
            f"🆔 [PROXY_TS] Stream ID: {stream_id}",
            "INFO",
            "proxy_ts")
    if is_fmp4:
        enhanced_log(
            f"📹 [PROXY_TS] Modalità fMP4 attivata",
            "INFO",
            "proxy_ts")
    if is_dlhd_masked:
        enhanced_log(
            f"🎭 [DLHD_MASKED] Segmento DLHD rilevato (video mascherato)",
            "INFO",
            "proxy_ts")

    # Estrai headers custom
    enhanced_log(
        f"📝 [PROXY_TS] Estrazione headers custom...",
        "DEBUG",
        "proxy_ts")
    headers = {
        unquote(key[2:]).replace("_", "-"): unquote(value).strip()
        for key, value in kwargs.items()
        if key.lower().startswith("h_")
    }
    enhanced_log(
        f"📝 [PROXY_TS] Headers estratti: {
            len(headers)} elementi",
        "DEBUG",
        "proxy_ts")

    # ✅ OTTIMIZZAZIONE: Timeout ridotti per segmenti
    if stream_id in STREAM_KEY_INFO:
        saved_headers = STREAM_KEY_INFO[stream_id].get('headers', {}) or {}
        merged_headers = saved_headers.copy()
        merged_headers.update(headers)
        headers = merged_headers

    timeout = 4 if 'lovecdn.ru' in ts_url.lower() else 8
    enhanced_log(
        f"⏰ [PROXY_TS] Timeout impostato: {timeout}s",
        "DEBUG",
        "proxy_ts")

    try:
        enhanced_log(
            f"🔄 [PROXY_TS] === INIZIO DOWNLOAD SEGMENTO ===",
            "INFO",
            "proxy_ts")

        # ✅ CORREZIONE CRITICA: Usa sessione persistente DLHD se disponibile
        dlhd_session = get_dlhd_session()
        if dlhd_session and any(domain in ts_url.lower()
                                for domain in ['kiko2.ru', 'giokko.ru']):
            enhanced_log(
                f"🍪 [PROXY_TS] Usando sessione persistente DLHD",
                "INFO",
                "proxy_ts")
            response = dlhd_session.get(
                ts_url, headers=headers, timeout=timeout, verify=False)
        else:
            enhanced_log(
                f"🌐 [PROXY_TS] Usando richiesta standard",
                "DEBUG",
                "proxy_ts")
            response = make_persistent_request(
                ts_url, headers=headers, timeout=timeout)

        enhanced_log(
            f"✅ [PROXY_TS] Risposta HTTP: {
                response.status_code}",
            "INFO",
            "proxy_ts")
        response.raise_for_status()
        ts_content = response.content

        enhanced_log(
            f"✅ [PROXY_TS] === SEGMENTO SCARICATO: {
                len(ts_content)} bytes ===",
            "INFO",
            "proxy_ts")

        # ✅ GESTIONE DLHD .html/.css MIGLIORATA: Questi sono segmenti TS mascherati
        non_ts_content_type = get_non_ts_content_type(ts_url, ts_content)
        if non_ts_content_type and not is_dlhd_masked:
            enhanced_log(
                f"[PROXY_TS] Risorsa non-TS servita senza decrittazione: {non_ts_content_type}",
                "INFO",
                "proxy_ts")
            return {
                'content': ts_content,
                'status': 200,
                'content_type': non_ts_content_type
            }

        if is_direct_media_url(ts_url):
            enhanced_log(
                f"🎬 [PROXY_TS] Media diretto servito senza conversione TS: {ts_url[-60:]}", "INFO", "proxy_ts")
            return {
                'content': ts_content,
                'status': 200,
                'content_type': 'video/mp4'
            }

        if is_dlhd_masked:
            enhanced_log(
                f"🎭 [DLHD_MASKED] === PROCESSAMENTO SEGMENTO MASCHERATO ===",
                "INFO",
                "proxy_ts")
            # Verifica che sia effettivamente un segmento TS (sync byte 0x47)
            if len(ts_content) > 0:
                enhanced_log(
                    f"🔍 [DLHD_MASKED] Primo byte: 0x{
                        ts_content[0]:02x}", "DEBUG", "proxy_ts")
                if not is_valid_ts_payload(ts_content):
                    enhanced_log(
                        f"⚠️ [DLHD_MASKED] Segmento non ha sync byte TS, potrebbe essere criptato",
                        "WARNING",
                        "proxy_ts")
                    # Prova decrittazione se disponibile
                    if stream_id and AES_AVAILABLE:
                        enhanced_log(
                            f"🔐 [DLHD_MASKED] Tentativo decrittazione segmento mascherato",
                            "INFO",
                            "proxy_ts")
                        aes_key = get_aes_key_for_stream(
                            stream_id, headers, ts_url)
                        if aes_key:
                            enhanced_log(
                                f"🔑 [DLHD_MASKED] Chiave AES trovata, decrittazione in corso",
                                "INFO",
                                "proxy_ts")
                            decrypted = decrypt_ts_if_needed(
                                ts_content, stream_id, headers, ts_url)
                            if decrypted != ts_content and is_valid_ts_payload(
                                    decrypted):
                                ts_content = decrypted
                                enhanced_log(
                                    f"✅ [DLHD_MASKED] Segmento mascherato decriptato con successo",
                                    "INFO",
                                    "proxy_ts")
                            else:
                                enhanced_log(
                                    f"⚠️ [DLHD_MASKED] Decrittazione fallita o non necessaria",
                                    "WARNING",
                                    "proxy_ts")
                        else:
                            enhanced_log(
                                f"❌ [DLHD_MASKED] Chiave AES non disponibile", "ERROR", "proxy_ts")
                else:
                    enhanced_log(
                        f"✅ [DLHD_MASKED] Segmento mascherato già in formato TS valido",
                        "INFO",
                        "proxy_ts")
            else:
                enhanced_log(
                    f"❌ [DLHD_MASKED] Segmento vuoto!",
                    "ERROR",
                    "proxy_ts")

        # ✅ GESTIONE fMP4: Per Freeshot e altri provider fMP4
        elif is_fmp4 or '.fmp4' in ts_url.lower():
            enhanced_log(
                f"📹 [FMP4_PROCESS] Processamento segmento fMP4",
                "DEBUG",
                "proxy_ts")

            # Per Enigma2, converti fMP4 in TS se necessario
            if stream_id and stream_id in STREAM_KEY_INFO:
                stream_info = STREAM_KEY_INFO[stream_id]
                if stream_info.get('is_freeshot', False):
                    # Per Freeshot, mantieni fMP4 nativo (Enigma2 moderno lo
                    # supporta)
                    enhanced_log(
                        f"✅ [FMP4_NATIVE] Freeshot: mantengo fMP4 nativo per Enigma2",
                        "INFO",
                        "proxy_ts")
                    return {
                        'content': ts_content,
                        'status': 200,
                        'content_type': 'video/mp4'
                    }
                else:
                    # Per altri provider, converti in TS
                    enhanced_log(
                        f"🔄 [FMP4_CONVERT] Conversione fMP4 → TS per compatibilità",
                        "INFO",
                        "proxy_ts")
                    ts_content = convert_fmp4_to_ts(ts_content, stream_id)
            else:
                # Fallback: converti sempre
                ts_content = convert_fmp4_to_ts(ts_content, stream_id)

        # Verifica se è già decriptato (sync byte 0x47 per TS)
        enhanced_log(
            f"🔍 [PROXY_TS] === VERIFICA FORMATO SEGMENTO ===",
            "INFO",
            "proxy_ts")
        if len(ts_content) > 0:
            enhanced_log(
                f"🔍 [PROXY_TS] Primo byte segmento: 0x{
                    ts_content[0]:02x}", "DEBUG", "proxy_ts")
            if is_valid_ts_payload(ts_content):
                enhanced_log(
                    f"✅ [PROXY_TS] Segmento già decriptato (sync byte 0x47)",
                    "INFO",
                    "proxy_ts")
                return {
                    'content': ts_content,
                    'status': 200,
                    'content_type': 'video/mp2t'
                }
            else:
                enhanced_log(
                    f"⚠️ [PROXY_TS] Segmento richiede decrittazione (primo byte: 0x{
                        ts_content[0]:02x})", "WARNING", "proxy_ts")
        else:
            enhanced_log(f"❌ [PROXY_TS] Segmento vuoto!", "ERROR", "proxy_ts")

        # Prova decrittazione AES se necessario
        enhanced_log(
            f"🔐 [PROXY_TS] === INIZIO DECRITTAZIONE AES ===",
            "INFO",
            "proxy_ts")
        if stream_id and AES_AVAILABLE:
            enhanced_log(
                f"🔑 [PROXY_TS] Ricerca chiave AES per stream {stream_id}",
                "INFO",
                "proxy_ts")

            # ✅ CORREZIONE CRITICA: Chiama sempre decrypt_ts_if_needed
            decrypted = decrypt_ts_if_needed(
                ts_content, stream_id, headers, ts_url)
            if decrypted != ts_content:
                ts_content = decrypted
                enhanced_log(
                    f"✅ [PROXY_TS] DECRITTAZIONE RIUSCITA: {
                        len(ts_content)} bytes", "INFO", "proxy_ts")
                if len(ts_content) > 0:
                    enhanced_log(
                        f"✅ [PROXY_TS] Sync byte dopo decrittazione: 0x{
                            ts_content[0]:02x}", "INFO", "proxy_ts")
            else:
                enhanced_log(
                    f"⚠️ [PROXY_TS] Decrittazione non ha modificato il contenuto",
                    "WARNING",
                    "proxy_ts")
        else:
            if not stream_id:
                enhanced_log(
                    f"⚠️ [PROXY_TS] Stream ID mancante - decrittazione saltata",
                    "WARNING",
                    "proxy_ts")
            if not AES_AVAILABLE:
                enhanced_log(
                    f"⚠️ [PROXY_TS] AES non disponibile - decrittazione saltata",
                    "WARNING",
                    "proxy_ts")

        # Determina content-type finale
        enhanced_log(
            f"📝 [PROXY_TS] === PREPARAZIONE RISPOSTA FINALE ===",
            "INFO",
            "proxy_ts")
        if is_fmp4 or '.fmp4' in ts_url.lower() or is_direct_media_url(ts_url):
            content_type = 'video/mp4'
            enhanced_log(
                f"📹 [PROXY_TS] Content-Type: video/mp4 (fMP4)",
                "INFO",
                "proxy_ts")
        else:
            # Sia per TS normali che per .html DLHD, usa video/mp2t
            content_type = 'video/mp2t'
            enhanced_log(
                f"📺 [PROXY_TS] Content-Type: video/mp2t (TS)",
                "INFO",
                "proxy_ts")

        # Verifica finale del contenuto
        if len(ts_content) > 0:
            enhanced_log(
                f"✅ [PROXY_TS] === SEGMENTO PRONTO: {
                    len(ts_content)} bytes, sync: 0x{
                    ts_content[0]:02x} ===",
                "INFO",
                "proxy_ts")
        else:
            enhanced_log(
                f"❌ [PROXY_TS] === SEGMENTO VUOTO - PROBLEMA CRITICO ===",
                "ERROR",
                "proxy_ts")

        if is_dlhd_masked:
            enhanced_log(
                f"✅ [DLHD_MASKED] Segmento DLHD pronto come TS: {
                    len(ts_content)} bytes", "INFO", "proxy_ts")

        return {
            'content': ts_content,
            'status': 200,
            'content_type': content_type
        }

    except Exception as e:
        enhanced_log(
            f"❌ [PROXY_TS] === ERRORE CRITICO DURANTE PROCESSAMENTO ===",
            "ERROR",
            "proxy_ts")
        enhanced_log(
            f"❌ [PROXY_TS] Errore: {
                type(e).__name__}: {
                str(e)}",
            "ERROR",
            "proxy_ts")

        # Log stack trace per debug
        import traceback
        enhanced_log(
            f"🔍 [PROXY_TS] Stack trace: {
                traceback.format_exc()}",
            "ERROR",
            "proxy_ts")

        # ✅ FALLBACK MIGLIORATO: Segmento TS vuoto ma valido per evitare interruzioni
        # Per DLHD, genera un pacchetto TS con PAT corretto
        if is_dlhd_masked:
            enhanced_log(
                f"🎭 [DLHD_FALLBACK] Generazione fallback TS per DLHD",
                "WARNING",
                "proxy_ts")
            # Pacchetto TS con PAT per DLHD
            fallback_ts = bytes([
                0x47, 0x40, 0x00, 0x10,  # TS header con sync byte
                0x00,  # Adaptation field control
                0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00,  # PAT
                0x00, 0x01, 0xF0, 0x00, 0x2A, 0xB1, 0x04, 0xB2
            ]) + b'\xFF' * (188 - 20)  # Padding
            enhanced_log(
                f"🎭 [DLHD_FALLBACK] Fallback TS DLHD generato: {
                    len(fallback_ts)} bytes",
                "WARNING",
                "proxy_ts")
        else:
            enhanced_log(
                f"🆘 [PROXY_TS] Generazione fallback TS standard",
                "WARNING",
                "proxy_ts")
            fallback_ts = b'\x47\x1F\xFF\x10' + b'\xFF' * 184
            enhanced_log(
                f"🆘 [PROXY_TS] Fallback TS generato: {
                    len(fallback_ts)} bytes",
                "WARNING",
                "proxy_ts")

        return {
            'content': fallback_ts,
            'status': 200,
            'content_type': 'video/mp2t'
        }


# Cache globale per le chiavi AES con metadati
AES_KEY_CACHE = {}
STREAM_KEY_INFO = {}  # Memorizza info chiavi per stream
# NUOVO: Cache per gli header associati a uno stream
STREAM_HEADER_INFO = {}
# ✅ NUOVO: Cache per segmenti non disponibili (evita richieste ripetute)
FAILED_SEGMENTS_CACHE = {}


def cleanup_expired_segments():
    """Pulisce automaticamente i segmenti scaduti dalla cache con timeout ottimizzati"""
    global FAILED_SEGMENTS_CACHE, STREAM_KEY_INFO, AES_KEY_CACHE
    current_time = time.time()
    expired_keys = []

    # ✅ OTTIMIZZAZIONE: Cache molto breve (3s) per retry più frequenti
    for key, entry in FAILED_SEGMENTS_CACHE.items():
        if current_time - entry['timestamp'] > 3:  # Scaduti dopo 3 secondi
            expired_keys.append(key)

    for key in expired_keys:
        del FAILED_SEGMENTS_CACHE[key]

    # Pulisci init segments vecchi (oltre 2 minuti per stream live)
    old_init_count = 0
    for stream_id in list(STREAM_KEY_INFO.keys()):
        stream_info = STREAM_KEY_INFO[stream_id]
        if 'init_segment' in stream_info and 'init_timestamp' in stream_info:
            if current_time - \
                    stream_info['init_timestamp'] > 120:  # 2 minuti per stream live
                del stream_info['init_segment']
                del stream_info['init_timestamp']
                old_init_count += 1

    # ✅ NUOVO: Pulisci anche chiavi AES molto vecchie (oltre 5 minuti)
    old_aes_keys = []
    for key in list(AES_KEY_CACHE.keys()):
        # Le chiavi AES non hanno timestamp, ma possiamo pulire quelle non usate di recente
        # Per ora manteniamo tutte le chiavi per evitare re-download
        pass

    if expired_keys or old_init_count > 0:
        enhanced_log(
            f"🧹 [SEGMENT_CLEANUP] Rimossi {
                len(expired_keys)} segmenti scaduti (3s) e {old_init_count} init segments vecchi dalla cache",
            "DEBUG",
            "AppCore")


def clear_stream_cache():
    """Pulisce completamente la cache per cambio canale"""
    global AES_KEY_CACHE, STREAM_KEY_INFO, STREAM_HEADER_INFO, URL_MAPPING, URL_COUNTER, FAILED_SEGMENTS_CACHE, VAVOO_FINAL_M3U8_CACHE

    # ✅ SOLUZIONE AGGRESSIVA: Pulisci TUTTO per evitare conflitti tra canali
    old_stream_count = len(STREAM_KEY_INFO)
    old_key_count = len(AES_KEY_CACHE)

    # Pulisci completamente tutte le cache
    STREAM_KEY_INFO.clear()
    AES_KEY_CACHE.clear()
    STREAM_HEADER_INFO.clear()
    FAILED_SEGMENTS_CACHE.clear()
    VAVOO_FINAL_M3U8_CACHE.clear()
    URL_MAPPING.clear()
    URL_COUNTER = 1

    enhanced_log(
        f"🧹 [CACHE_CLEAR] Pulizia completa: {old_stream_count} stream, {old_key_count} chiavi AES",
        "INFO",
        "AppCore")


def is_valid_video_segment(url, strict_mode=False, is_dlhd=False):
    """✅ CORREZIONE 1: Valida che il segmento sia un file video valido

    Args:
        url: URL del segmento
        strict_mode: Se False, accetta URL senza estensione (potrebbero essere TS senza ext)
                     Se True, scarta URL senza estensione riconosciuta
        is_dlhd: Se True, permette .html/.css (DLHD usa segmenti video mascherati)
    """
    url_lower = url.lower()
    # Estensioni video valide
    valid_extensions = (
        '.ts',
        '.m3u8',
        '.mp4',
        '.mkv',
        '.webm',
        '.flv',
        '.mov',
        '.avi')
    # Estensioni non-video da escludere (ma .html/.css è permesso per DLHD)
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

    # Per DLHD, .html/.css/.js/.txt è considerato valido (segmenti video
    # mascherati)
    if is_dlhd and any(
        ext in url_lower for ext in [
            '.html',
            '.css',
            '.js',
            '.txt']):
        enhanced_log(
            f"✅ [DLHD_MASKED] Segmento DLHD accettato (video mascherato): {url[-50:]}", "INFO", "AppCore")
        return True

    # Controlla estensioni non-video - SCARTA SEMPRE (eccetto .html/.css per
    # DLHD)
    for ext in invalid_extensions:
        if url_lower.endswith(ext):
            enhanced_log(
                f"⚠️ [SEGMENT_VALIDATION] Segmento non-video scartato: {url[-50:]}", "WARNING", "AppCore")
            return False

    # Se non è DLHD, scarta anche .html/.css/.js/.txt
    if not is_dlhd and any(
        ext in url_lower for ext in [
            '.html',
            '.css',
            '.js',
            '.txt']):
        enhanced_log(
            f"⚠️ [SEGMENT_VALIDATION] Segmento .html/.css/.js/.txt scartato (non-DLHD): {url[-50:]}", "WARNING", "AppCore")
        return False

    # Se ha un'estensione video valida, accetta
    for ext in valid_extensions:
        if url_lower.endswith(ext):
            return True

    # Se non ha estensione ma contiene 'playlist' o 'm3u', accetta (potrebbe
    # essere M3U8 senza estensione)
    if 'playlist' in url_lower or 'm3u' in url_lower:
        return True

    # Se non ha estensione riconosciuta
    if strict_mode:
        # In modalità strict, scarta
        enhanced_log(
            f"⚠️ [SEGMENT_VALIDATION] Segmento senza estensione valida scartato: {url[-50:]}", "WARNING", "AppCore")
        return False
    else:
        # In modalità permissiva, accetta (potrebbe essere TS senza estensione)
        enhanced_log(
            f"ℹ️ [SEGMENT_VALIDATION] Segmento senza estensione accettato (modalità permissiva): {url[-50:]}", "INFO", "AppCore")
        return True


def extract_key_info_from_m3u8(
        m3u8_content,
        stream_id,
        base_url,
        stream_headers=None,
        resolved_data=None):
    """Estrae informazioni chiave dal M3U8 con log dettagliati FASE_2"""
    is_daddy = is_daddy_domain(base_url)
    is_freeshot = 'lovecdn.ru' in base_url.lower()

    if is_daddy:
        enhanced_log(
            "🔍 [FASE_2] Analisi della playlist per chiave, IV e segmento",
            "INFO",
            "AppCore")
    elif is_freeshot:
        enhanced_log(
            "🔍 [FREESHOT_M3U8] Analisi playlist fMP4 (non criptata)",
            "INFO",
            "AppCore")

    # Chiave AES non più scaricata dall'extractor, sarà scaricata da AppCore
    # quando serve
    extractor_key_bytes = None

    try:
        first_segment = None
        segment_sequence = 0
        for line in m3u8_content:
            if line.startswith('#EXT-X-MEDIA-SEQUENCE'):
                try:
                    segment_sequence = int(line.split(':')[1].strip())
                    enhanced_log(
                        f"🔢 [SEQUENCE] Sequenza iniziale: {segment_sequence}",
                        "DEBUG",
                        "AppCore")
                except Exception as sequence_error:
                    enhanced_log(
                        f"[SEQUENCE] Sequenza media non valida: {sequence_error}",
                        "DEBUG",
                        "AppCore")
            if not line.startswith('#') and line.strip():
                first_segment = line.strip()
                break
        for line in m3u8_content:
            if line.startswith('#EXT-X-KEY') and 'AES-128' in line:
                uri_match = re.search(r'URI="([^"]+)"', line)
                iv_match = re.search(r'IV=([^,]+)', line)
                if not uri_match:
                    enhanced_log(
                        f"⚠️ [KEY_EXTRACTION] URI non trovato nella linea KEY: {line[:100]}", "WARNING", "AppCore")
                    continue
                relative_key_uri = uri_match.group(1)
                key_uri = urljoin(base_url, relative_key_uri)

                # ✅ NOTA: DaddyLive usa URL chiavi dinamici con parametro 'number' che cambia
                # L'URL viene salvato così com'è - se diventa obsoleto, verrà
                # gestito in get_aes_key_for_stream
                if is_daddy and 'giokko.ru' in key_uri:
                    enhanced_log(
                        f"🔑 [KEY_INFO] URL chiave DaddyLive dinamico: {key_uri[:80]}...", "DEBUG", "AppCore")
                iv_bytes = None
                if iv_match:
                    iv_value = iv_match.group(1).strip('"\'')
                    enhanced_log(
                        f"🔢 [IV] Valore IV estratto: {iv_value}",
                        "DEBUG",
                        "AppCore")
                    if iv_value.startswith('0x'):
                        iv_value = iv_value[2:]
                    if all(c in '0123456789abcdefABCDEF' for c in iv_value):
                        try:
                            iv_bytes = bytes.fromhex(iv_value)
                            enhanced_log(
                                f"🔢 [IV] Convertito da hex: {
                                    iv_bytes.hex()}", "DEBUG", "AppCore")
                        except Exception as e:
                            iv_bytes = iv_value.encode('latin-1')
                            enhanced_log(
                                f"⚠️ [IV] Fallita conversione hex, usato come stringa: {
                                    iv_bytes.hex()}", "WARNING", "AppCore")
                    else:
                        iv_bytes = iv_value.encode('latin-1')
                        enhanced_log(
                            f"🔢 [IV] Interpretato come stringa ASCII: {
                                iv_bytes.hex()}", "DEBUG", "AppCore")
                    if len(iv_bytes) != 16:
                        if len(iv_bytes) < 16:
                            iv_bytes = iv_bytes + bytes(16 - len(iv_bytes))
                            enhanced_log(
                                f"⚠️ [IV] IV troppo corto, allungato a: {
                                    iv_bytes.hex()}", "WARNING", "AppCore")
                        else:
                            iv_bytes = iv_bytes[:16]
                            enhanced_log(
                                f"⚠️ [IV] IV troppo lungo, troncato a: {
                                    iv_bytes.hex()}", "WARNING", "AppCore")
                if not iv_bytes:
                    iv_bytes = hashlib.md5(stream_id.encode()).digest()[:16]
                    enhanced_log(
                        f"⚠️ [KEY_EXTRACTION] IV non valido, usando IV generato: {
                            iv_bytes.hex()}", "WARNING", "AppCore")
                if not isinstance(iv_bytes, bytes):
                    iv_bytes = str(iv_bytes).encode('latin-1')
                if len(iv_bytes) < 16:
                    iv_bytes = iv_bytes + bytes(16 - len(iv_bytes))
                    enhanced_log(
                        f"⚠️ [KEY_EXTRACTION] IV troppo corto, allungato con zeri: {
                            iv_bytes.hex()}", "WARNING", "AppCore")
                elif len(iv_bytes) > 16:
                    iv_bytes = iv_bytes[:16]
                    enhanced_log(
                        f"⚠️ [KEY_EXTRACTION] IV troppo lungo, troncato a: {
                            iv_bytes.hex()}", "WARNING", "AppCore")
                iv_hex = iv_bytes.hex()
                # PATCH: crea la entry PRIMA di qualsiasi assegnazione
                # ✅ CRITICO: Salva anche gli headers per usarli nel download della chiave
                STREAM_KEY_INFO[stream_id] = {
                    'key_uri': key_uri,
                    'iv': iv_bytes,
                    'iv_base': iv_bytes,
                    'sequence': segment_sequence,
                    'method': 'AES-128',
                    'is_daddy': is_daddy,
                    'is_freeshot': is_freeshot,
                    'base_url': base_url,
                    'headers': stream_headers or {},  # ✅ SALVA HEADERS
                    'last_used': time.time()
                }

                if is_daddy:
                    enhanced_log(
                        f"✅ [FASE_2] Chiave trovata: {key_uri[:80]}...", "INFO", "AppCore")
                    enhanced_log(
                        f"✅ [FASE_2] IV base trovato: {iv_hex}",
                        "INFO",
                        "AppCore")
                    enhanced_log(
                        f"✅ [FASE_2] Sequenza iniziale: {segment_sequence}",
                        "INFO",
                        "AppCore")
                    if first_segment:
                        full_segment_url = urljoin(base_url, first_segment)
                        enhanced_log(
                            f"🎯 [FASE_2] Primo segmento trovato: {first_segment[:80]}...", "DEBUG", "AppCore")
                        enhanced_log(
                            f"🔗 [FASE_2] URI Chiave assoluto: {key_uri}",
                            "DEBUG",
                            "AppCore")
                        enhanced_log(
                            f"🔗 [FASE_2] URL Segmento assoluto: {full_segment_url}",
                            "DEBUG",
                            "AppCore")
                else:
                    enhanced_log(
                        f"🔑 Info chiave salvata per stream {stream_id}",
                        "INFO",
                        "AppCore")
                    enhanced_log(
                        f"🔑 [KEY_EXTRACTION] URI: {key_uri[:80]}...", "DEBUG", "AppCore")
                    enhanced_log(
                        f"🔑 [KEY_EXTRACTION] IV: {iv_hex}",
                        "DEBUG",
                        "AppCore")
                return True
        if is_freeshot:
            enhanced_log(
                f"ℹ️ [FREESHOT_M3U8] Nessuna chiave AES necessaria per fMP4 (stream non criptato)",
                "INFO",
                "AppCore")
        else:
            enhanced_log(
                f"⚠️ [KEY_EXTRACTION] Nessuna chiave AES-128 valida trovata nel M3U8",
                "WARNING",
                "AppCore")
        return False
    except Exception as e:
        enhanced_log(
            f"❌ Errore estrazione info chiave: {e}",
            "ERROR",
            "AppCore")
        return False


def get_aes_key_for_stream(stream_id, headers, segment_url=None):
    """Ottiene la chiave AES con rilevamento automatico cambio chiave e sessione persistente DLHD"""
    enhanced_log(
        f"🔑 [AES_KEY] === INIZIO RICERCA CHIAVE AES per stream {stream_id} ===",
        "INFO",
        "AppCore")

    if stream_id not in STREAM_KEY_INFO:
        enhanced_log(
            f"❌ [AES_KEY] Stream {stream_id} non trovato in STREAM_KEY_INFO",
            "ERROR",
            "AppCore")
        return None

    key_info = STREAM_KEY_INFO[stream_id]
    key_uri = key_info.get('key_uri')
    if not key_uri:
        enhanced_log(
            f"❌ [AES_KEY] key_uri mancante per stream {stream_id}",
            "ERROR",
            "AppCore")
        return None

    enhanced_log(
        f"🔍 [AES_KEY] key_uri trovato: {key_uri[-30:]}", "DEBUG", "AppCore")

    cache_key = f"{stream_id}_{key_uri}"
    stream_headers = key_info.get('headers', {})
    enhanced_log(
        f"📝 [AES_KEY] Headers stream: {
            len(stream_headers)} elementi",
        "DEBUG",
        "AppCore")

    # RILEVAMENTO CAMBIO CHIAVE: Se l'URL della chiave è cambiato, invalida
    # cache
    current_key_uri = key_info.get('key_uri')
    last_key_uri = key_info.get('last_key_uri')

    if last_key_uri and current_key_uri != last_key_uri:
        enhanced_log(
            f"🔄 [KEY_CHANGE] Rilevato cambio chiave: {last_key_uri[-10:]} → {current_key_uri[-10:]}", "INFO", "AppCore")
        # Pulisci cache vecchia chiave
        old_cache_key = f"{stream_id}_{last_key_uri}"
        if old_cache_key in AES_KEY_CACHE:
            del AES_KEY_CACHE[old_cache_key]
        # Aggiorna riferimento
        key_info['last_key_uri'] = current_key_uri
        cache_key = f"{stream_id}_{current_key_uri}"

    # Controlla se abbiamo già la chiave in cache
    if cache_key in AES_KEY_CACHE:
        enhanced_log(
            f"✅ [AES_KEY] Chiave trovata in cache: {cache_key}",
            "INFO",
            "AppCore")
        # Heartbeat ogni 30 secondi solo per chiavi esistenti
        last_heartbeat = key_info.get('last_heartbeat', 0)
        current_time = time.time()

        if current_time - last_heartbeat > 30:
            heartbeat_url = stream_headers.get('Heartbeat-Url')
            if heartbeat_url:
                enhanced_log(
                    f"💓 [HEARTBEAT] Invio heartbeat: {heartbeat_url[-30:]}", "DEBUG", "AppCore")
                try:
                    hb_headers = {
                        'Authorization': stream_headers.get('Authorization', ''),
                        'X-Channel-Key': stream_headers.get('X-Channel-Key', ''),
                        'X-Client-Token': stream_headers.get('X-Client-Token', ''),
                        'User-Agent': stream_headers.get('User-Agent', ''),
                        'Referer': stream_headers.get('Referer', ''),
                        'Origin': stream_headers.get('Origin', '')
                    }

                    # ✅ CORREZIONE CRITICA: Usa sessione persistente DLHD se disponibile
                    dlhd_session = get_dlhd_session()
                    if dlhd_session:
                        enhanced_log(
                            f"🍪 [HEARTBEAT] Usando sessione DLHD persistente",
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
                            f"💓 [HEARTBEAT] Heartbeat riuscito per stream {stream_id}",
                            "DEBUG",
                            "AppCore")
                    else:
                        enhanced_log(
                            f"⚠️ [HEARTBEAT] Heartbeat fallito: {
                                response.status_code}", "WARNING", "AppCore")
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [HEARTBEAT] Errore heartbeat: {e}",
                        "WARNING",
                        "AppCore")

        return AES_KEY_CACHE[cache_key]

    # Scarica nuova chiave AES
    enhanced_log(
        f"🔄 [AES_KEY] === DOWNLOAD NUOVA CHIAVE AES ===",
        "INFO",
        "AppCore")
    try:
        enhanced_log(
            f"🔑 [NEW_KEY] Scarico nuova chiave: {key_uri[-20:]}", "INFO", "AppCore")
        key_headers = {
            k: v for k,
            v in stream_headers.items() if k != 'Heartbeat-Url'}
        enhanced_log(
            f"📝 [NEW_KEY] Headers per download: {
                list(
                    key_headers.keys())}",
            "DEBUG",
            "AppCore")

        # ✅ OTTIMIZZAZIONE: Timeout ridotti per Enigma2
        timeout = 5 if 'kiko2.ru' in key_uri else 8
        enhanced_log(f"⏰ [NEW_KEY] Timeout: {timeout}s", "DEBUG", "AppCore")

        # ✅ CORREZIONE CRITICA: Usa sessione persistente DLHD per mantenere cookie auth
        dlhd_session = get_dlhd_session()
        if dlhd_session and 'kiko2.ru' in key_uri:
            enhanced_log(
                f"🍪 [DLHD_KEY] Usando sessione persistente DLHD per chiave AES",
                "INFO",
                "AppCore")
            response = dlhd_session.get(
                key_uri,
                headers=key_headers,
                timeout=timeout,
                verify=False)
        else:
            enhanced_log(
                f"🌐 [NEW_KEY] Usando richiesta standard",
                "DEBUG",
                "AppCore")
            response = make_persistent_request(
                key_uri, headers=key_headers, timeout=timeout)

        enhanced_log(
            f"📊 [NEW_KEY] Risposta HTTP: {
                response.status_code}",
            "INFO",
            "AppCore")

        if response.status_code != 200:
            enhanced_log(
                f"❌ [NEW_KEY] Chiave AES fallita (HTTP {
                    response.status_code})",
                "ERROR",
                "AppCore")

            # ✅ NUOVO: Se fallisce, prova a invalidare cache DLHD per forzare refresh
            if DLHD_AVAILABLE and dlhd_extractor and response.status_code in [
                    403, 404]:
                try:
                    if hasattr(dlhd_extractor,
                               'invalidate_cache_for_url') and segment_url:
                        dlhd_extractor.invalidate_cache_for_url(segment_url)
                        enhanced_log(
                            f"🗑️ [DLHD_INVALIDATE] Cache DLHD invalidata per errore chiave",
                            "INFO",
                            "AppCore")
                except Exception:
                    pass

            return None

        aes_key = response.content
        enhanced_log(
            f"🔑 [NEW_KEY] Chiave scaricata: {
                len(aes_key)} bytes",
            "INFO",
            "AppCore")

        if len(aes_key) == 16:
            AES_KEY_CACHE[cache_key] = aes_key
            key_info['last_heartbeat'] = time.time()
            key_info['last_key_uri'] = key_uri
            enhanced_log(
                f"✅ [NEW_KEY] === NUOVA CHIAVE AES SALVATA ({
                    len(aes_key)} bytes) ===", "INFO", "AppCore")
            return aes_key
        else:
            enhanced_log(
                f"❌ [NEW_KEY] Chiave AES dimensione invalida: {
                    len(aes_key)} bytes (attesi 16)",
                "ERROR",
                "AppCore")

        return None

    except Exception as e:
        enhanced_log(
            f"❌ [NEW_KEY] === ERRORE DOWNLOAD CHIAVE AES: {
                type(e).__name__}: {
                str(e)} ===",
            "ERROR",
            "AppCore")
        import traceback
        enhanced_log(
            f"🔍 [NEW_KEY] Stack trace: {
                traceback.format_exc()}",
            "ERROR",
            "AppCore")
        return None


# Sostituisci la funzione decrypt_ts_segment (riga ~1062) con questa
# versione corretta:
def decrypt_ts_segment(ts_content, aes_key, stream_id):
    """Decrittazione AES-128 con fallback per Enigma2"""
    if not AES_AVAILABLE or not aes_key:
        return ts_content

    try:
        # Ottieni IV per questo stream
        iv = None
        if stream_id in STREAM_KEY_INFO and 'iv' in STREAM_KEY_INFO[stream_id]:
            iv = STREAM_KEY_INFO[stream_id]['iv']

            # Se l'IV è una stringa, convertila in bytes
            if isinstance(iv, str):
                try:
                    # Rimuovi eventuale prefisso 0x
                    iv_str = iv[2:] if iv.startswith('0x') else iv

                    # Prova a convertire da esadecimale
                    if all(c in '0123456789abcdefABCDEF' for c in iv_str):
                        iv = bytes.fromhex(iv_str)
                        enhanced_log(
                            f"🔢 [IV] Convertito da hex: {
                                iv.hex()}", "DEBUG", "proxy_ts")
                    else:
                        # Se non è esadecimale valido, usa come stringa ASCII
                        iv = iv_str.encode('latin-1')
                        enhanced_log(
                            f"🔢 [IV] Interpretato come stringa: {
                                iv.hex()}", "DEBUG", "proxy_ts")
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [IV] Errore conversione IV: {e}",
                        "WARNING",
                        "proxy_ts")
                    iv = None

            # Assicurati che l'IV sia esattamente 16 byte
            if iv is not None:
                if len(iv) < 16:
                    # Se è troppo corto, aggiungi zeri alla fine
                    iv = iv + (b'\x00' * (16 - len(iv)))
                    enhanced_log(
                        f"⚠️ [IV] IV troppo corto, allungato: {
                            iv.hex()}", "WARNING", "proxy_ts")
                elif len(iv) > 16:
                    # Se è troppo lungo, prendi i primi 16 byte
                    iv = iv[:16]
                    enhanced_log(
                        f"⚠️ [IV] IV troppo lungo, troncato: {
                            iv.hex()}", "WARNING", "proxy_ts")

        # Se non abbiamo un IV valido, usiamo uno di default
        if iv is None or len(iv) != 16:
            iv = b'\x00' * 16
            enhanced_log("⚠️ [IV] Usando IV di default", "WARNING", "proxy_ts")

        # Salva l'IV corretto per i prossimi utilizzi
        if stream_id in STREAM_KEY_INFO:
            STREAM_KEY_INFO[stream_id]['iv'] = iv

        enhanced_log(
            f"🔢 [IV] IV finale per decifratura: {
                iv.hex()}", "DEBUG", "proxy_ts")

        # Log IV e chiave per debug
        is_daddy = STREAM_KEY_INFO.get(stream_id, {}).get('is_daddy', False)
        if is_daddy:
            enhanced_log(
                f"🔐 [DECRYPT] IV (hex): {
                    iv.hex()}",
                "DEBUG",
                "AppCore")
            enhanced_log(
                f"🔐 [DECRYPT] Chiave (hex): {
                    aes_key.hex()}",
                "DEBUG",
                "AppCore")

        # Decrittazione con libreria disponibile
        try:
            if AES_MODULE == "cryptography":
                # Import dinamico solo se serve
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

            # Prova a rimuovere il padding PKCS7
            if len(decrypted) > 0:
                padding_length = decrypted[-1]
                if 0 < padding_length <= 16:
                    if all(
                            b == padding_length for b in decrypted[-padding_length:]):
                        decrypted = decrypted[:-padding_length]

            # Verifica il sync byte TS (0x47) all'inizio del pacchetto
            if len(decrypted) > 0 and decrypted[0] == 0x47:
                return decrypted

            # Se il sync byte non è corretto, prova a decifrare senza rimuovere
            # il padding
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
                f"❌ Errore durante la decrittazione: {decrypt_error}",
                "ERROR",
                "proxy_ts")
            return ts_content
    except Exception as e:
        enhanced_log(f"❌ Errore decrittazione: {e}", "ERROR", "proxy_ts")
        return ts_content


def create_robust_session():
    """Crea sessione ottimizzata per Enigma2 con retry integrato e cookie jar"""
    session = requests.Session()
    # ✅ CRITICO: Non sovrascrivere User-Agent di default, lascia che venga impostato per richiesta
    session.headers.update({
        'Connection': 'close'  # Importante per decoder
    })
    # ✅ CRITICO: Abilita cookie jar automatico (già abilitato di default in requests.Session)
    # session.cookies è già un CookieJar, non serve fare nulla

    # Monkey patch per retry automatico
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
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
                    continue
                raise
        return response

    session.request = request_with_retry
    return session


def get_persistent_session(proxy_url=None):
    """Ottiene una sessione persistente dal pool o ne crea una nuova"""
    global SESSION_POOL, SESSION_LOCK

    # Usa proxy_url come chiave, o 'default' se non c'è proxy
    pool_key = proxy_url if proxy_url else 'default'
    current_time = time.time()

    with SESSION_LOCK:
        session = SESSION_POOL.get(pool_key)
        if session is not None:
            session_age = current_time - \
                getattr(session, "_sp_created_at", current_time)
            requests_count = getattr(session, "_sp_requests_count", 0)
            if session_age > SESSION_MAX_AGE or requests_count >= SESSION_MAX_REQUESTS:
                try:
                    session.close()
                except Exception as close_error:
                    enhanced_log(
                        f"Errore chiusura sessione scaduta {pool_key}: {close_error}",
                        "DEBUG",
                        "AppCore")
                del SESSION_POOL[pool_key]
                session = None

        if session is None:
            session = create_robust_session()

            if session is None:
                enhanced_log(
                    f"Impossibile creare sessione per: {pool_key}",
                    "get_persistent_session",
                    "AppCore")
                return None

            # Configura proxy se fornito
            if proxy_url:
                session.proxies.update({'http': proxy_url, 'https': proxy_url})

            session._sp_created_at = current_time
            session._sp_requests_count = 0
            SESSION_POOL[pool_key] = session
            enhanced_log(
                f"Nuova sessione persistente creata per: {pool_key}",
                "get_persistent_session",
                "AppCore")

        SESSION_POOL[pool_key]._sp_requests_count = getattr(
            SESSION_POOL[pool_key], "_sp_requests_count", 0) + 1
        return SESSION_POOL[pool_key]


def make_persistent_request(
        url,
        headers=None,
        timeout=None,
        proxy_url=None,
        **kwargs):
    """Richiesta HTTP ottimizzata per Enigma2 con sessione DLHD persistente"""
    from html import unescape as html_unescape
    url = html_unescape(url)
    enhanced_log(
        f"🌐 [PERSISTENT_REQUEST] URL: {url[:100]}...", "DEBUG", "AppCore")

    # ✅ CORREZIONE CRITICA: Usa sessione DLHD persistente per domini kiko2.ru
    dlhd_session = get_dlhd_session()
    if dlhd_session and any(domain in url.lower()
                            for domain in ['kiko2.ru', 'giokko.ru']):
        enhanced_log(
            f"🍪 [DLHD_SESSION] Usando sessione persistente DLHD",
            "DEBUG",
            "AppCore")
        try:
            response = dlhd_session.get(
                url,
                headers=headers,
                timeout=timeout or REQUEST_TIMEOUT,
                verify=False,
                **kwargs)
            enhanced_log(
                f"✅ [DLHD_SESSION] Risposta: {
                    response.status_code}",
                "DEBUG",
                "AppCore")
            return response
        except Exception as e:
            enhanced_log(f"❌ [DLHD_SESSION] Errore: {e}", "WARNING", "AppCore")
            # Fallback al metodo standard

    # Metodo standard per altri domini
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
                    "❌ Impossibile ottenere sessione persistente",
                    "ERROR",
                    "AppCore")
                raise Exception("Impossibile ottenere sessione persistente")

            enhanced_log(
                f"🔄 [PERSISTENT_REQUEST] Tentativo {
                    attempt + 1}/3", "DEBUG", "AppCore")

            if request_headers:
                response = session.get(
                    url,
                    headers=request_headers,
                    timeout=final_timeout,
                    verify=VERIFY_SSL,
                    **kwargs)
            else:
                response = session.get(
                    url, timeout=final_timeout, verify=VERIFY_SSL, **kwargs)

            enhanced_log(
                f"✅ [PERSISTENT_REQUEST] Risposta: {
                    response.status_code}",
                "DEBUG",
                "AppCore")

            retry_codes = [418, 429, 500, 502, 503, 504]
            if response.status_code not in retry_codes:
                return response

            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            enhanced_log(
                f"❌ [PERSISTENT_REQUEST] Errore connessione tentativo {
                    attempt + 1}: {e}", "ERROR", "AppCore")
            with SESSION_LOCK:
                pool_key = proxy_url if proxy_url else 'default'
                if pool_key in SESSION_POOL:
                    del SESSION_POOL[pool_key]
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            else:
                raise
        except Exception as e:
            enhanced_log(
                f"❌ [PERSISTENT_REQUEST] Errore generico: {e}",
                "ERROR",
                "AppCore")
            raise

    return response


# Proxy KEY SENZA CACHE
@route_registry.route('/proxy/key')
def proxy_key(request=None, **kwargs):
    """Proxy KEY per chiavi AES-128 DLHD"""
    enhanced_log("🔑 Proxy Key", "INFO", "AppCore")

    key_url = kwargs.get('url', '').strip()
    if not key_url:
        enhanced_log("❌ [PROXY_KEY] URL chiave mancante", "ERROR", "AppCore")
        return {
            'content': b"Errore: URL chiave mancante",
            'status': 400,
            'content_type': 'text/plain'
        }

    # Estrai headers custom
    headers = {
        unquote(key[2:]).replace("_", "-"): unquote(value).strip()
        for key, value in kwargs.items()
        if key.lower().startswith("h_")
    }

    try:
        enhanced_log(
            f"🔑 [PROXY_KEY] Scarico chiave: {key_url[-30:]}", "INFO", "AppCore")

        # Usa sessione DLHD persistente se disponibile
        dlhd_session = get_dlhd_session()
        if dlhd_session and 'kiko2.ru' in key_url:
            enhanced_log(
                f"🍪 [PROXY_KEY] Usando sessione persistente DLHD",
                "DEBUG",
                "AppCore")
            response = dlhd_session.get(
                key_url, headers=headers, timeout=8, verify=False)
        else:
            response = make_persistent_request(
                key_url, headers=headers, timeout=8)

        response.raise_for_status()
        key_content = response.content

        if len(key_content) == 16:
            enhanced_log(
                f"✅ [PROXY_KEY] Chiave AES scaricata: {
                    len(key_content)} bytes",
                "INFO",
                "AppCore")
            return {
                'content': key_content,
                'status': 200,
                'content_type': 'application/octet-stream'
            }
        else:
            enhanced_log(
                f"❌ [PROXY_KEY] Chiave dimensione invalida: {
                    len(key_content)} bytes", "ERROR", "AppCore")
            return {
                'content': b"Errore: Chiave AES invalida",
                'status': 500,
                'content_type': 'text/plain'
            }

    except Exception as e:
        enhanced_log(f"❌ [PROXY_KEY] Errore: {e}", "ERROR", "AppCore")
        return {
            'content': f"Errore chiave: {str(e)}".encode(),
            'status': 500,
            'content_type': 'text/plain'
        }


@route_registry.route('/service/notify_m3u')
def notify_m3u(request=None, **kwargs):
    """Notifica interna usata da Pipeline quando aggiorna il file M3U."""
    path = kwargs.get('path', '')
    enhanced_log(f"Notifica M3U ricevuta: {path}", "INFO", "AppCore")
    return {
        'content': b"OK",
        'status': 200,
        'content_type': 'text/plain'
    }


# Liste globali per i proxy, popolate da load_config
PROXY_LIST = []
DADDY_PROXY_LIST = []


def get_daddy_proxy_list():
    """Restituisce la lista globale dei proxy per DaddyLive."""
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
        """Inizializza il gestore della configurazione."""
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
        Carica la configurazione per Enigma2 in modo ottimizzato.
        Cerca un file JSON in percorsi predefiniti e popola la configurazione
        e le liste di proxy globali.
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
                    # enhanced_log(f"✅ Configurazione caricata da: {loaded_path}", "load_config", "AppCore")
                except (IOError, json.JSONDecodeError) as e:
                    enhanced_log(
                        f"⚠️ Errore nel caricamento di {path}: {e}",
                        "load_config",
                        "AppCore")

        if not loaded_path:
            enhanced_log(
                "ℹ️ Nessun file di configurazione trovato. Uso i valori di default.",
                "load_config",
                "AppCore")

        proxy_str = config.get('PROXY', '')
        PROXY_LIST = [_normalize_proxy_url(p) for p in proxy_str.split(
            ',') if p.strip()] if proxy_str else []
        if PROXY_LIST:
            enhanced_log(
                f"ℹ️ Proxy generali configurati: {
                    len(PROXY_LIST)}",
                "load_config",
                "AppCore")

        daddy_proxy_str = config.get('DADDY_PROXY', '')
        DADDY_PROXY_LIST = [_normalize_proxy_url(p) for p in daddy_proxy_str.split(
            ',') if p.strip()] if daddy_proxy_str else []
        if DADDY_PROXY_LIST:
            enhanced_log(
                f"ℹ️ Proxy DaddyLive configurati: {
                    len(DADDY_PROXY_LIST)}",
                "load_config",
                "AppCore")

        return config

    def save_config(self, config):
        """Salva la configurazione nel file JSON nel percorso di default."""
        path_to_save = self.config_file
        try:
            with open(path_to_save, 'w', encoding='utf-8') as f:
                config_to_save = {
                    k: config.get(k) for k in self.default_config.keys() if k in config}
                json.dump(config_to_save, f, indent=4)
            enhanced_log(
                f"✅ Configurazione salvata in: {path_to_save}",
                "save_config",
                "AppCore")
            return True
        except IOError as e:
            enhanced_log(
                f"❌ Errore nel salvataggio della configurazione: {e}",
                "save_config",
                "AppCore")
            return False

    def apply_config_to_app(self, config):
        """
        Applica la configurazione a un'istanza di app Flask, se disponibile.
        In un contesto Enigma2 puro, questa funzione potrebbe non essere utilizzata.
        """
        try:
            # L'import di Flask è locale per evitare un requisito hard
            from flask import current_app
            if current_app:
                for key, value in config.items():
                    current_app.config[key] = value
            return True
        except (ImportError, RuntimeError):
            # Se Flask non è disponibile o non siamo in un contesto di app,
            # ignora.
            return True


config_manager = ConfigManager()


# AppCore SEMPLIFICATO
class AppCoreNoCache:
    def __init__(self):
        enhanced_log("AppCore NoCache inizializzato", "INFO", "AppCore")

    def handle_request(self, route_name, *args, **kwargs):
        enhanced_log(f"📥 Richiesta: {route_name}", "INFO", "AppCore")
        enhanced_log(
            f"🔍 [DEBUG] handle_request kwargs: {kwargs}",
            "DEBUG",
            "AppCore")

        if route_name not in route_registry.routes:
            return {
                'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
                'status': 200,
                'content_type': 'application/vnd.apple.mpegurl'
            }

        # CORREZIONE CRITICA: Passa kwargs correttamente
        return route_registry.dispatch(route_name, **kwargs)


# Callback per ServiceMonitor
def service_monitor_callback(route_name, *args, **kwargs):
    enhanced_log(
        f"🔄 ServiceMonitor → AppCore: {route_name}",
        "INFO",
        "AppCore")
    enhanced_log(
        f"🔍 [DEBUG] Args ricevuti: args={args}, kwargs={kwargs}",
        "DEBUG",
        "AppCore")

    try:
        app_core = AppCoreNoCache()

        # CORREZIONE CRITICA: Debug e fix del passaggio parametri
        enhanced_log(
            f"🔍 [DEBUG] Prima di handle_request: kwargs={kwargs}",
            "DEBUG",
            "AppCore")

        return app_core.handle_request(route_name, **kwargs)
    except Exception as e:
        enhanced_log(f"❌ Errore callback: {str(e)}", "ERROR", "AppCore")
        return {
            'content': "#EXTM3U\n#EXT-X-VERSION:3".encode(),
            'status': 200,
            'content_type': 'application/vnd.apple.mpegurl'
        }


enhanced_log(
    "🚀 AppCoreSC NoCache completamente inizializzato",
    "INFO",
    "AppCore")
