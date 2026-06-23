# http_response.py - small helpers to normalise AppCore responses


def normalize_appcore_result(
        result,
        default_content_type="application/vnd.apple.mpegurl"):
    """
    Convert AppCore result into consistent content/status/content-type.

    Args:
        result: The AppCore result (dict, tuple, or other)
        default_content_type: Fallback content type

    Returns:
        tuple: (content, status, content_type)
    """
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

    # Normalise content to bytes
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
    """
    Apply a simple HTTP Range header and return content/status/content-range.

    Args:
        content: The full content as bytes
        range_header: The Range header value (e.g., "bytes=0-100")

    Returns:
        tuple: (ranged_content, status, content_range)
               status is None if Range is not applicable or invalid.
    """
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
