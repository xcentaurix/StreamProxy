# -*- coding: utf-8 -*-
"""
external_proxy.py — Integration with external EasyProxy proxy
Reads configProxy.txt and delegates stream resolution to the external API.
"""
import os
import json
import time
import threading
import requests
from urllib.parse import unquote, urlparse, quote, urlencode

try:
    from .StreamProxyLog import enhanced_log
except ImportError:
    def enhanced_log(msg, level="INFO", tag="ExtProxy"):
        print("[%s][%s] %s" % (level, tag, msg))

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATHS = [
    os.path.join(_BASE_DIR, 'configProxy.txt'),
    'configProxy.txt',
]

_EXTRACTOR_HOSTS = {
    'vixsrc': 'vixsrc',
    'vixcloud': 'vixsrc',
    'mixdrop': 'mixdrop',
    'sport99': 'sports99',
    'cdnlivetv': 'sports99',
    'vavoo': 'vavoo',
    'freeshot': 'freeshot',
    'maxstream': 'maxstream',
    'sportonline': 'sportonline',
    'daddylive': 'dlstreams',
    'daddyhd': 'dlstreams',
    'dlhd.dad': 'dlstreams',
    'dlstreams': 'dlstreams',
    'watch.php': 'dlstreams',
}

# ── Config cache ────────────────────────────────────────────────────────
_cfg_cache = {}
_cfg_cache_ts = 0.0
_cfg_cache_ttl = 30.0
_cfg_lock = threading.Lock()

# ── Manifest cache for daddy streams ────────────────────────────────────
_manifest_cache = {}
_manifest_lock = threading.Lock()
_DADDY_MANIFEST_TTL = 8.0
_DADDY_KEYWORDS = (
    'daddylive',
    'daddyhd',
    'dlhd.dad',
    'dlstreams',
    'watch.php')
_MAX_MANIFEST_CACHE = 20  # Cache limit to avoid memory leaks

# ── Persistent HTTP session ─────────────────────────────────────────────
_session = {'instance': None}
_session_lock = threading.Lock()
_session_timeout = 15  # Default request timeout


def _get_session():
    with _session_lock:
        session = _session['instance']
        if session is None:
            session = requests.Session()
            session.verify = False
            session.headers.update(
                {'Connection': 'keep-alive', 'Accept': '*/*'})
            session._created_at = time.time()
            _session['instance'] = session
        return session


def _close_session():
    """Close and reset the HTTP session to avoid memory leaks."""
    with _session_lock:
        session = _session['instance']
        if session is not None:
            try:
                session.close()
            except Exception as e:
                enhanced_log(
                    "Error closing HTTP session: %s" %
                    e, "WARNING", "ExtProxy")
            _session['instance'] = None


def load_proxy_config():
    global _cfg_cache, _cfg_cache_ts
    now = time.time()
    with _cfg_lock:
        if now - _cfg_cache_ts < _cfg_cache_ttl and _cfg_cache:
            return _cfg_cache
        for path in _CONFIG_PATHS:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    _cfg_cache = data
                    _cfg_cache_ts = now
                    return _cfg_cache
                except Exception as e:
                    enhanced_log(
                        "Error reading configProxy.txt: %s" %
                        e, "WARNING", "ExtProxy")
        # Fallback: read from Enigma2 config if available
        try:
            from Components.config import config as e2cfg
            sp = e2cfg.plugins.streamproxy
            data = {
                "attivaProxyEsterno": "SI" if sp.attivaProxyEsterno.value else "NO",
                "proxyUrl": sp.proxyUrl.value,
                "apiPassword": sp.apiPassword.value,
                "timeoutProxy": sp.timeoutProxy.value,
                "usaExtractor": "SI" if sp.usaExtractor.value else "NO",
                "usaHlsProxy": "SI" if sp.usaHlsProxy.value else "NO",
            }
            _cfg_cache = data
            _cfg_cache_ts = now
            return _cfg_cache
        except Exception:
            pass
        return _cfg_cache or {}


def is_proxy_esterno_attivo():
    cfg = load_proxy_config()
    return str(cfg.get('attivaProxyEsterno', 'NO')).strip().upper() == 'YES'


def get_proxy_base_url():
    cfg = load_proxy_config()
    return cfg.get('proxyUrl', '').rstrip('/')


def is_url_del_proxy_esterno(url):
    proxy_url = get_proxy_base_url()
    if not proxy_url or not url:
        return False
    proxy_host = urlparse(proxy_url).netloc.lower()
    url_host = urlparse(url).netloc.lower()
    return bool(proxy_host and proxy_host == url_host)


def _detect_host(url):
    url_lower = (url or '').lower()
    for keyword, host in _EXTRACTOR_HOSTS.items():
        if keyword in url_lower:
            return host
    return None


def _is_daddy_url(url):
    url_lower = (url or '').lower()
    return any(k in url_lower for k in _DADDY_KEYWORDS)


def _url_hash(url):
    try:
        p = urlparse(url)
        return "%s%s" % (p.netloc, p.path)
    except Exception:
        return url[:120]


def _build_headers(api_password):
    h = {'Accept': '*/*'}
    if api_password:
        h['x-api-password'] = api_password
    return h


def _clean_url(url):
    # Decode only once to avoid double decoding
    clean = unquote(url)
    # Remove any residual &amp; (incorrect HTML encoding)
    while '&amp;' in clean:
        clean = clean.replace('&amp;', '&')
    return clean


def _build_proxy_url(endpoint, clean_src_url, api_password):
    encoded_url = quote(clean_src_url, safe='')
    qs = "url=%s" % encoded_url
    if api_password:
        qs += "&api_password=%s" % api_password
    return "%s?%s" % (endpoint, qs)


def build_external_segment_url(segment_url, api_password=None):
    """Build the URL to fetch a TS segment via the external proxy."""
    cfg = load_proxy_config()
    proxy_url = cfg.get('proxyUrl', '').rstrip('/')
    if not proxy_url:
        return None
    pw = api_password or cfg.get('apiPassword', '')
    endpoint = "%s/proxy/ts" % proxy_url
    return _build_proxy_url(endpoint, _clean_url(segment_url), pw)


def build_external_key_url(key_url, api_password=None):
    """Build the URL to fetch an AES key via the external proxy."""
    cfg = load_proxy_config()
    proxy_url = cfg.get('proxyUrl', '').rstrip('/')
    if not proxy_url:
        return None
    pw = api_password or cfg.get('apiPassword', '')
    endpoint = "%s/proxy/key" % proxy_url
    return _build_proxy_url(endpoint, _clean_url(key_url), pw)


def _fetch_via_session(url, req_headers, timeout, retry=1):
    session = _get_session()
    connect_timeout = min(5, timeout)
    last_exc = None
    for attempt in range(retry + 1):
        try:
            resp = session.get(url, headers=req_headers,
                               timeout=(connect_timeout, timeout),
                               allow_redirects=True)
            return resp
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            # Force session reset
            with _session_lock:
                _session['instance'] = None
            session = _get_session()
            enhanced_log(
                "[MANIFEST] Reconnection (attempt %d): %s" %
                (attempt + 1, e), "WARNING", "ExtProxy")
        except requests.exceptions.Timeout as e:
            last_exc = e
            enhanced_log(
                "[MANIFEST] Timeout (attempt %d)" %
                (attempt + 1), "WARNING", "ExtProxy")
            break
        except requests.exceptions.RequestException as e:
            last_exc = e
            enhanced_log(
                "[MANIFEST] Request error (attempt %d): %s" %
                (attempt + 1, e), "WARNING", "ExtProxy")
            break
        except Exception as e:
            last_exc = e
            enhanced_log(
                "[MANIFEST] Unexpected error (attempt %d): %s: %s" %
                (attempt + 1, type(e).__name__, e), "WARNING", "ExtProxy")
            break
    if last_exc:
        raise RuntimeError("Fetch failed") from last_exc
    raise RuntimeError("Fetch failed")


def fetch_cdn_via_easyproxy_session(cdn_url, req_headers=None, timeout=15):
    """
    Download a daddy CDN manifest/segment using the persistent EasyProxy session.
    The CDN (e.g. zalis.phantemlis.top) is only accessible through the SOCKS5 proxy
    configured in EasyProxy, so we must use its session.
    """
    session = _get_session()
    try:
        resp = session.get(
            cdn_url,
            headers=req_headers or {},
            timeout=(min(5, timeout), timeout),
            verify=False,
            allow_redirects=True
        )
        return resp
    except requests.exceptions.Timeout as e:
        enhanced_log(
            "[ExtProxy] CDN fetch timeout: %s" %
            e, "WARNING", "ExtProxy")
        raise
    except requests.exceptions.RequestException as e:
        enhanced_log(
            "[ExtProxy] CDN fetch error: %s" %
            e, "WARNING", "ExtProxy")
        raise
    except Exception as e:
        enhanced_log(
            "[ExtProxy] Unexpected CDN fetch error: %s: %s" %
            (type(e).__name__, e), "WARNING", "ExtProxy")
        raise


# Cache of active daddy CDN domains (populated during resolution)
_active_cdn_domains = set()
_cdn_lock = threading.Lock()
_MAX_CDN_DOMAINS = 100  # Cache limit to avoid memory leaks


def register_cdn_domain(url):
    """Register the CDN domain of the current session for later recognition."""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc:
            with _cdn_lock:
                if len(_active_cdn_domains) >= _MAX_CDN_DOMAINS:
                    # Remove the oldest
                    oldest = next(iter(_active_cdn_domains))
                    _active_cdn_domains.discard(oldest)
                _active_cdn_domains.add(netloc)
    except Exception as e:
        enhanced_log(
            "[ExtProxy] Error registering CDN domain: %s" %
            e, "WARNING", "ExtProxy")


def is_cdn_daddy_url(url):
    """Return True if the URL belongs to a daddy CDN domain already resolved via EasyProxy."""
    try:
        netloc = urlparse(url).netloc.lower()
        with _cdn_lock:
            return netloc in _active_cdn_domains
    except Exception as e:
        enhanced_log(
            "[ExtProxy] Error checking CDN domain: %s" %
            e, "WARNING", "ExtProxy")
        return False


def fetch_segment_via_proxy_esterno(segment_url, req_headers=None, timeout=15):
    """Download TS segment from EasyProxy (headers already in the URL as parameters)."""
    session = _get_session()

    enhanced_log(
        "[SEGMENT_FETCH] Request to EasyProxy (headers in URL)",
        "INFO",
        "ExtProxy")

    try:
        # Do NOT add headers because they are already in the URL as h_* and
        # api_password
        resp = session.get(
            segment_url,
            timeout=(min(5, timeout), timeout),
            verify=False,
            allow_redirects=True,
            stream=True
        )

        enhanced_log(
            "[SEGMENT_FETCH] HTTP %s" %
            resp.status_code,
            "INFO",
            "ExtProxy")
        return resp
    except requests.exceptions.Timeout as e:
        enhanced_log(
            "[ExtProxy] Segment fetch timeout: %s" %
            e, "WARNING", "ExtProxy")
        raise
    except requests.exceptions.RequestException as e:
        enhanced_log(
            "[ExtProxy] Segment fetch error: %s" %
            e, "WARNING", "ExtProxy")
        raise
    except Exception as e:
        enhanced_log(
            "[ExtProxy] Unexpected segment fetch error: %s: %s" %
            (type(e).__name__, e), "WARNING", "ExtProxy")
        raise


def resolve_via_proxy_esterno(url, request_headers=None):
    """
    Resolve a stream URL via the external EasyProxy proxy.

    CORRECT LOGIC:
    1. Delegate ALL stream handling to the external proxy via /proxy/manifest.m3u8
    2. Only if it fails AND it's not daddy → fallback to local
    3. For daddy: if /proxy/manifest.m3u8 fails → use /extractor/video for CDN stream URL,
       then handle the flow internally
    """
    cfg = load_proxy_config()
    proxy_url = cfg.get('proxyUrl', '').rstrip('/')
    api_password = cfg.get('apiPassword', '')
    timeout = int(cfg.get('timeoutProxy', 15))

    if not proxy_url:
        enhanced_log(
            "proxyUrl not configured in configProxy.txt",
            "ERROR",
            "ExtProxy")
        return None

    clean_src = _clean_url(url)
    enhanced_log("[ExtProxy] proxyUrl=%s timeout=%ds url=%s" %
                 (proxy_url, timeout, clean_src[:80]), "INFO", "ExtProxy")

    is_daddy = _is_daddy_url(clean_src)
    cache_key = _url_hash(clean_src) if is_daddy else None

    # ── Daddy manifest cache ────────────────────────────────────────────────
    if cache_key:
        with _manifest_lock:
            entry = _manifest_cache.get(cache_key)
        if entry and (time.time() - entry['ts']) < _DADDY_MANIFEST_TTL:
            enhanced_log(
                "[ExtProxy] Daddy manifest from cache (%.1fs)" %
                (time.time() - entry['ts']), "INFO", "ExtProxy")
            return {
                'resolved_url': entry['resolved_url'],
                'm3u8_content': entry['content'],
                'headers': entry.get('headers', {}),
            }

    api_headers = _build_headers(api_password)

    # ── STEP 1: FULL DELEGATION TO EXTERNAL PROXY via /proxy/manifest.m3u8 ──
    manifest_url = "%s/proxy/manifest.m3u8" % proxy_url
    final_url = _build_proxy_url(manifest_url, clean_src, api_password)
    enhanced_log("[ExtProxy] → FULL DELEGATION %s" %
                 final_url[:120], "INFO", "ExtProxy")

    try:
        resp = _fetch_via_session(final_url, api_headers, timeout, retry=1)
        enhanced_log(
            "[ExtProxy] ← HTTP %s" %
            resp.status_code,
            "INFO",
            "ExtProxy")

        if resp.status_code != 200:
            enhanced_log(
                "[ExtProxy] /proxy/manifest.m3u8 body=%s" % resp.text[:300],
                "WARNING", "ExtProxy")

        if resp.status_code == 200 and resp.text.strip().startswith('#EXTM3U'):
            enhanced_log(
                "[ExtProxy] Stream fully handled by external proxy",
                "INFO",
                "ExtProxy")

            # Register CDN domains for daddy
            if is_daddy:
                for line in resp.text.splitlines():
                    line = line.strip()
                    if line.startswith('http'):
                        register_cdn_domain(line)
                    elif line and not line.startswith('#'):
                        from urllib.parse import urljoin as _urljoin
                        abs_url = _urljoin(str(resp.url), line)
                        register_cdn_domain(abs_url)

            result = {
                'resolved_url': str(resp.url),
                'm3u8_content': resp.text,
                'headers': request_headers or {},
            }

            if cache_key:
                with _manifest_lock:
                    if len(_manifest_cache) > _MAX_MANIFEST_CACHE:
                        oldest = min(
                            _manifest_cache.keys(),
                            key=lambda k: _manifest_cache[k]['ts'])
                        del _manifest_cache[oldest]
                        enhanced_log(
                            "[ExtProxy] Manifest cache cleaned (removed %d entries)" %
                            len(_manifest_cache), "DEBUG", "ExtProxy")
                    _manifest_cache[cache_key] = {
                        'content': resp.text,
                        'resolved_url': str(resp.url),
                        'headers': request_headers or {},
                        'ts': time.time(),
                    }
            return result
    except requests.exceptions.Timeout as e:
        enhanced_log(
            "[ExtProxy] Timeout /proxy/manifest.m3u8: %s" %
            e, "WARNING", "ExtProxy")
    except requests.exceptions.RequestException as e:
        enhanced_log(
            "[ExtProxy] Error /proxy/manifest.m3u8: %s" %
            e, "WARNING", "ExtProxy")
    except Exception as e:
        enhanced_log(
            "[ExtProxy] Unexpected /proxy/manifest.m3u8 error: %s: %s" %
            (type(e).__name__, e), "WARNING", "ExtProxy")

    # ── STEP 2: NON-DADDY FALLBACK → /proxy/stream ──────────────────────────
    if not is_daddy:
        stream_url = "%s/proxy/stream" % proxy_url
        final_url = _build_proxy_url(stream_url, clean_src, api_password)
        enhanced_log("[ExtProxy] → GET %s" %
                     final_url[:120], "INFO", "ExtProxy")

        try:
            resp = _fetch_via_session(final_url, api_headers, timeout, retry=1)
            enhanced_log(
                "[ExtProxy] ← HTTP %s" %
                resp.status_code, "INFO", "ExtProxy")

            if resp.status_code == 200 and resp.text.strip().startswith('#EXTM3U'):
                enhanced_log(
                    "[ExtProxy] Valid M3U8 from /proxy/stream",
                    "INFO",
                    "ExtProxy")
                return {
                    'resolved_url': str(resp.url),
                    'm3u8_content': resp.text,
                    'headers': request_headers or {},
                }
        except requests.exceptions.Timeout as e:
            enhanced_log(
                "[ExtProxy] Timeout /proxy/stream: %s" %
                e, "WARNING", "ExtProxy")
        except requests.exceptions.RequestException as e:
            enhanced_log(
                "[ExtProxy] Error /proxy/stream: %s" %
                e, "WARNING", "ExtProxy")
        except Exception as e:
            enhanced_log(
                "[ExtProxy] Unexpected /proxy/stream error: %s: %s" %
                (type(e).__name__, e), "WARNING", "ExtProxy")

    # ── STEP 3: DADDY FALLBACK → /extractor/video for CDN URL and internal handling ──
    if is_daddy:
        host = _detect_host(clean_src) or 'dlstreams'
        extractor_url = "%s/extractor/video?host=%s&d=%s&api_password=%s&_t=%d" % (
            proxy_url, host, quote(clean_src), api_password, int(time.time()))
        enhanced_log("[ExtProxy] Daddy fallback → extractor for CDN URL: %s" %
                     extractor_url[:120], "INFO", "ExtProxy")
        try:
            resp = _fetch_via_session(
                extractor_url, api_headers, timeout, retry=1)
            enhanced_log(
                "[ExtProxy] extractor ← HTTP %s" %
                resp.status_code, "INFO", "ExtProxy")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = {}

                stream_url = (data.get('destination_url') or data.get(
                    'url') or data.get('stream_url') or data.get('manifest_url') or '')
                req_hdrs = data.get(
                    'request_headers') or data.get('headers') or {}

                enhanced_log(
                    "[ExtProxy] extractor data keys: %s" %
                    list(data.keys())[:10],
                    "INFO", "ExtProxy")
                enhanced_log(
                    "[ExtProxy] mediaflow_endpoint=%s mediaflow_proxy_url=%s" % (
                        str(data.get('mediaflow_endpoint', ''))[:100],
                        str(data.get('mediaflow_proxy_url', ''))[:100]),
                    "INFO", "ExtProxy")
                enhanced_log(
                    "[ExtProxy] query_params=%s" % str(data.get('query_params', {}))[:200],
                    "INFO", "ExtProxy")
                enhanced_log(
                    "[ExtProxy] destination_url=%s" % str(data.get('destination_url', ''))[:200],
                    "INFO", "ExtProxy")
                enhanced_log(
                    "[ExtProxy] request_headers=%s" % str(data.get('request_headers', {}))[:200],
                    "INFO", "ExtProxy")

                # EasyProxy MediaFlow endpoints crash (500) for Daddy.
                # Return destination_url directly — AppCore will fetch it
                # via the normal HLS pipeline with the provided headers.
                if stream_url and stream_url.startswith('http'):
                    register_cdn_domain(stream_url)
                    enhanced_log("[ExtProxy] Returning CDN URL for local HLS fetch: %s" %
                                 stream_url[:80], "INFO", "ExtProxy")
                    result = {
                        'resolved_url': stream_url,
                        'm3u8_content': None,
                        'headers': req_hdrs,
                    }
                    if cache_key:
                        with _manifest_lock:
                            if len(_manifest_cache) > _MAX_MANIFEST_CACHE:
                                oldest = min(_manifest_cache.keys(),
                                             key=lambda k: _manifest_cache[k]['ts'])
                                del _manifest_cache[oldest]
                            _manifest_cache[cache_key] = {
                                'content': None,
                                'resolved_url': stream_url,
                                'headers': req_hdrs,
                                'ts': time.time(),
                            }
                    return result
                enhanced_log(
                    "[ExtProxy] extractor without URL: %s" % str(data)[:120],
                    "WARNING", "ExtProxy")
            else:
                enhanced_log("[ExtProxy] extractor HTTP %s: %s" % (
                    resp.status_code, resp.text[:80]), "WARNING", "ExtProxy")
        except requests.exceptions.Timeout as e:
            enhanced_log(
                "[ExtProxy] Timeout extractor: %s" %
                e, "WARNING", "ExtProxy")
        except requests.exceptions.RequestException as e:
            enhanced_log(
                "[ExtProxy] Error extractor: %s" %
                e, "WARNING", "ExtProxy")
        except Exception as e:
            enhanced_log(
                "[ExtProxy] Unexpected extractor error: %s: %s" %
                (type(e).__name__, e), "WARNING", "ExtProxy")

    # ── Final fallback: retry standard endpoint ONLY if NOT daddy ──
    if not is_daddy:
        for endpoint in [
            "%s/proxy/manifest.m3u8" %
            proxy_url,
            "%s/proxy/stream" %
                proxy_url]:
            final_url = _build_proxy_url(endpoint, clean_src, api_password)
            enhanced_log("[ExtProxy] → GET %s" %
                         final_url[:120], "INFO", "ExtProxy")
            try:
                resp = _fetch_via_session(
                    final_url, api_headers, timeout, retry=1)
                enhanced_log("[ExtProxy] ← HTTP %s url=%s" %
                             (resp.status_code, resp.url[:80]), "INFO", "ExtProxy")

                if resp.status_code == 200 and resp.text.strip().startswith('#EXTM3U'):
                    enhanced_log("[ExtProxy] Valid M3U8", "INFO", "ExtProxy")
                    parsed = urlparse(clean_src)
                    origin = "%s://%s" % (parsed.scheme, parsed.netloc)
                    proxy_headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                        'Accept': '*/*',
                        'Origin': origin,
                        'Referer': origin + '/',
                    }
                    result = {
                        'resolved_url': str(resp.url),
                        'm3u8_content': resp.text,
                        'headers': proxy_headers,
                    }
                    if cache_key:
                        with _manifest_lock:
                            if len(_manifest_cache) > _MAX_MANIFEST_CACHE:
                                oldest = min(
                                    _manifest_cache.keys(),
                                    key=lambda k: _manifest_cache[k]['ts'])
                                del _manifest_cache[oldest]
                            _manifest_cache[cache_key] = {
                                'content': resp.text,
                                'resolved_url': str(resp.url),
                                'headers': proxy_headers,
                                'ts': time.time(),
                            }
                    return result

                body_preview = resp.text[:200] if resp.text else ''
                enhanced_log("[ExtProxy] %s: HTTP %s body=%s" % (endpoint.split(
                    '/')[-1], resp.status_code, body_preview[:80]), "ERROR", "ExtProxy")
                if resp.status_code == 500 and 'browser' in body_preview.lower():
                    continue

            except requests.exceptions.Timeout as e:
                enhanced_log(
                    "[ExtProxy] Timeout %s: %s" %
                    (endpoint, e), "WARNING", "ExtProxy")
            except requests.exceptions.RequestException as e:
                enhanced_log(
                    "[ExtProxy] Error %s: %s" %
                    (endpoint, e), "WARNING", "ExtProxy")
            except Exception as e:
                enhanced_log(
                    "[ExtProxy] Unexpected %s error: %s: %s" %
                    (endpoint, type(e).__name__, e), "WARNING", "ExtProxy")
    else:
        enhanced_log(
            "[ExtProxy] Daddy: NO LOCAL FALLBACK available",
            "ERROR",
            "ExtProxy")

    # ── Daddy cache fallback ────────────────────────────────────────────────
    if cache_key:
        with _manifest_lock:
            entry = _manifest_cache.get(cache_key)
        if entry:
            enhanced_log(
                "[ExtProxy] Daddy cache fallback (age %.0fs)" %
                (time.time() - entry['ts']), "WARNING", "ExtProxy")
            return {
                'resolved_url': entry['resolved_url'],
                'm3u8_content': entry['content'],
                'headers': entry.get('headers', {}),
            }

    enhanced_log("[ExtProxy] Resolution failed for: %s" %
                 url[:80], "ERROR", "ExtProxy")
    return None
