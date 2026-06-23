# http_response.py - helper piccoli per normalizzare le risposte AppCore


def normalize_appcore_result(
        result,
        default_content_type="application/vnd.apple.mpegurl"):
    """Converte il risultato AppCore in content/status/content-type coerenti."""
    status = 200
    content_type = default_content_type

    if isinstance(result, dict):
        content = result.get("content", b"")
        status = int(result.get("status", 200) or 200)
        content_type = result.get("content_type",
                                  default_content_type) or default_content_type
    elif isinstance(result, tuple):
        raw = result[0] if result else b""
        if isinstance(raw, list):
            content = "\n".join(raw)
        else:
            content = raw
    else:
        content = result

    if content is None:
        content = b""
    elif isinstance(content, bytes):
        pass
    elif isinstance(content, bytearray):
        content = bytes(content)
    else:
        content = str(content).encode("utf-8")

    return content, status, content_type


def apply_range(content, range_header):
    """Applica un Range HTTP semplice e restituisce content/status/content-range."""
    if not range_header or not range_header.startswith("bytes="):
        return content, None, None

    total_length = len(content)
    range_spec = range_header[6:].strip()

    if "-" not in range_spec:
        return content, None, None

    start_text, end_text = range_spec.split("-", 1)
    if not start_text:
        return content, None, None

    start = int(start_text)
    end = total_length - 1 if not end_text else int(end_text)
    end = min(end, total_length - 1)

    if start < 0 or start >= total_length or end < start:
        return content, 416, "bytes */%d" % total_length

    ranged = content[start:end + 1]
    return ranged, 206, "bytes %d-%d/%d" % (start, end, total_length)
