# vavoo_extractor.py - Vavoo URL extractor per Enigma2 Python 3
import hashlib
import re
import time
from urllib.parse import quote_plus

import requests

try:
    import urllib3
    from urllib3.exceptions import InsecureRequestWarning
    urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

try:
    from ..StreamProxyLog import enhanced_log
except ImportError:
    try:
        from StreamProxyLog import enhanced_log
    except ImportError:
        def enhanced_log(message, level="INFO", component="VAVOO"):
            print("[%s] [%s] %s" % (level, component, message))


_LOKKE_PING_URL = "https://www.lokke.app/api/app/ping"
_LOKKE_TOKEN = "ldCvE092e7gER0rVIajfsXIvRhwlrAzP6_1oEJ4q6HH89QHt24v6NNL_jQJO219hiLOXF2hqEfsUuEWitEIGN4EaHHEHb7Cd7gojc5SQYRFzU3XWo_kMeryAUbcwWnQrnf0-"
_RESOLVE_URL = "https://vavoo.to/mediahubmx-resolve.json"
_TS_PING2_URL = "https://www.vavoo.tv/api/box/ping2"
_TS_VEC = "9frjpxPjxSNilxJPCJ0XGYs6scej3dW/h/VWlnKUiLSG8IP7mfyDU7NirOlld+VtCKGj03XjetfliDMhIev7wcARo+YTU8KPFuVQP9E2DVXzY2BFo1NhE6qEmPfNDnm74eyl/7iFJ0EETm6XbYyz8IKBkAqPN/Spp3PZ2ulKg3QBSDxcVN4R5zRn7OsgLJ2CNTuWkd/h451lDCp+TtTuvnAEhcQckdsydFhTZCK5IiWrrTIC/d4qDXEd+GtOP4hPdoIuCaNzYfX3lLCwFENC6RZoTBYLrcKVVgbqyQZ7DnLqfLqvf3z0FVUWx9H21liGFpByzdnoxyFkue3NzrFtkRL37xkx9ITucepSYKzUVEfyBh+/3mtzKY26VIRkJFkpf8KVcCRNrTRQn47Wuq4gC7sSwT7eHCAydKSACcUMMdpPSvbvfOmIqeBNA83osX8FPFYUMZsjvYNEE3arbFiGsQlggBKgg1V3oN+5ni3Vjc5InHg/xv476LHDFnNdAJx448ph3DoAiJjr2g4ZTNynfSxdzA68qSuJY8UjyzgDjG0RIMv2h7DlQNjkAXv4k1BrPpfOiOqH67yIarNmkPIwrIV+W9TTV/yRyE1LEgOr4DK8uW2AUtHOPA2gn6P5sgFyi68w55MZBPepddfYTQ+E1N6R/hWnMYPt/i0xSUeMPekX47iucfpFBEv9Uh9zdGiEB+0P3LVMP+q+pbBU4o1NkKyY1V8wH1Wilr0a+q87kEnQ1LWYMMBhaP9yFseGSbYwdeLsX9uR1uPaN+u4woO2g8sw9Y5ze5XMgOVpFCZaut02I5k0U4WPyN5adQjG8sAzxsI3KsV04DEVymj224iqg2Lzz53Xz9yEy+7/85ILQpJ6llCyqpHLFyHq/kJxYPhDUF755WaHJEaFRPxUqbparNX+mCE9Xzy7Q/KTgAPiRS41FHXXv+7XSPp4cy9jli0BVnYf13Xsp28OGs/D8Nl3NgEn3/eUcMN80JRdsOrV62fnBVMBNf36+LbISdvsFAFr0xyuPGmlIETcFyxJkrGZnhHAxwzsvZ+Uwf8lffBfZFPRrNv+tgeeLpatVcHLHZGeTgWWml6tIHwWUqv2TVJeMkAEL5PPS4Gtbscau5HM+FEjtGS+KClfX1CNKvgYJl7mLDEf5ZYQv5kHaoQ6RcPaR6vUNn02zpq5/X3EPIgUKF0r/0ctmoT84B2J1BKfCbctdFY9br7JSJ6DvUxyde68jB+Il6qNcQwTFj4cNErk4x719Y42NoAnnQYC2/qfL/gAhJl8TKMvBt3Bno+va8ve8E0z8yEuMLUqe8OXLce6nCa+L5LYK1aBdb60BYbMeWk1qmG6Nk9OnYLhzDyrd9iHDd7X95OM6X5wiMVZRn5ebw4askTTc50xmrg4eic2U1w1JpSEjdH/u/hXrWKSMWAxaj34uQnMuWxPZEXoVxzGyuUbroXRfkhzpqmqqqOcypjsWPdq5BOUGL/Riwjm6yMI0x9kbO8+VoQ6RYfjAbxNriZ1cQ+AW1fqEgnRWXmjt4Z1M0ygUBi8w71bDML1YG6UHeC2cJ2CCCxSrfycKQhpSdI1QIuwd2eyIpd4LgwrMiY3xNWreAF+qobNxvE7ypKTISNrz0iYIhU0aKNlcGwYd0FXIRfKVBzSBe4MRK2pGLDNO6ytoHxvJweZ8h1XG8RWc4aB5gTnB7Tjiqym4b64lRdj1DPHJnzD4aqRixpXhzYzWVDN2kONCR5i2quYbnVFN4sSfLiKeOwKX4JdmzpYixNZXjLkG14seS6KR0Wl8Itp5IMIWFpnNokjRH76RYRZAcx0jP0V5/GfNNTi5QsEU98en0SiXHQGXnROiHpRUDXTl8FmJORjwXc0AjrEMuQ2FDJDmAIlKUSLhjbIiKw3iaqp5TVyXuz0ZMYBhnqhcwqULqtFSuIKpaW8FgF8QJfP2frADf4kKZG1bQ99MrRrb2A="


class VavooExtractorError(Exception):
    pass


class VavooExtractor:
    """Vavoo resolver sincrono per Enigma2, allineato al source EasyProxy."""

    def __init__(self, request_headers=None):
        self.base_headers = {"User-Agent": "okhttp/4.11.0"}
        if request_headers:
            self.base_headers.update(request_headers)
        self.session = None
        self.mediaflow_endpoint = "proxy_stream_endpoint"
        self._signature_cache = None
        self._signature_time = 0
        self._url_cache = {}
        enhanced_log("[VAVOO] VavooExtractor inizializzato", "INFO", "VAVOO")

    def _create_session(self):
        if self.session:
            return True
        self.session = requests.Session()
        self.session.headers.update(self.base_headers)
        self.session.verify = False
        return True

    def _post_json(self, url, payload, headers, timeout=12):
        if not self.session and not self._create_session():
            return None
        return self.session.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
            verify=False)

    def get_cached_signature(self):
        if self._signature_cache and (
                time.time() - self._signature_time) < 300:
            enhanced_log("[VAVOO] Signature da cache", "DEBUG", "VAVOO")
            return self._signature_cache

        signature = self.get_auth_signature()
        if signature:
            self._signature_cache = signature
            self._signature_time = time.time()
        return signature

    def get_auth_signature(self):
        if not self.session and not self._create_session():
            return None

        unique_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
        now_ms = int(time.time() * 1000)
        payload = {
            "token": _LOKKE_TOKEN,
            "reason": "app-blur",
            "locale": "de",
            "theme": "dark",
            "metadata": {
                "device": {
                    "type": "Handset",
                    "brand": "google",
                    "model": "Nexus",
                    "name": "21081111RG",
                    "uniqueId": unique_id},
                "os": {
                    "name": "android",
                    "version": "7.1.2",
                    "abis": ["arm64-v8a"],
                    "host": "android"},
                "app": {
                    "platform": "android",
                    "version": "1.1.0",
                    "buildId": "97215000",
                    "engine": "hbc85",
                    "signatures": ["6e8a975e3cbf07d5de823a760d4c2547f86c1403105020adee5de67ac510999e"],
                    "installer": "com.android.vending",
                },
                "version": {
                    "package": "app.lokke.main",
                    "binary": "1.1.0",
                    "js": "1.1.0"},
                "platform": {
                    "isAndroid": True,
                    "isIOS": False,
                    "isTV": False,
                    "isWeb": False,
                    "isMobile": True,
                    "isWebTV": False,
                    "isElectron": False},
            },
            "appFocusTime": 0,
            "playerActive": False,
            "playDuration": 0,
            "devMode": True,
            "hasAddon": True,
            "castConnected": False,
            "package": "app.lokke.main",
            "version": "1.1.0",
            "process": "app",
            "firstAppStart": now_ms - 86400000,
            "lastAppStart": now_ms,
            "ipLocation": None,
            "adblockEnabled": False,
            "proxy": {
                "supported": [
                    "ss",
                    "openvpn"],
                "engine": "openvpn",
                "ssVersion": 1,
                "enabled": False,
                "autoServer": True,
                "id": "fi-hel"},
            "iap": {
                "supported": True},
        }
        headers = {
            "user-agent": "okhttp/4.11.0",
            "accept": "application/json",
            "content-type": "application/json; charset=utf-8",
            "accept-encoding": "gzip",
        }

        # EasyProxy/plugin.video.vavooto usano Lokke come auth primaria.
        # La signature legacy Vavoo puo' risolvere a un flusso promozionale
        # "scarica lokke.app", quindi va usata solo se Lokke non risponde.
        for attempt in range(3):
            try:
                resp = self.session.post(
                    _LOKKE_PING_URL,
                    json=payload,
                    headers=headers,
                    timeout=10,
                    verify=False)
                if resp.status_code == 200:
                    signature = resp.json().get("addonSig")
                    if signature:
                        enhanced_log(
                            "[VAVOO] Signature lokke ottenuta", "INFO", "VAVOO")
                        return signature
                enhanced_log(
                    "[VAVOO] Lokke HTTP %s" %
                    resp.status_code, "WARNING", "VAVOO")
            except Exception as exc:
                enhanced_log(
                    "[VAVOO] Errore lokke tentativo %s: %s" %
                    (attempt + 1, exc), "WARNING", "VAVOO")

        legacy_payload = {
            "token": "tosFwQCJMS8qrW_AjLoHPQ41646J5dRNha6ZWHnijoYQQQoADQoXYSo7ki7O5-CsgN4CH0uRk6EEoJ0728ar9scCRQW3ZkbfrPfeCXW2VgopSW2FWDqPOoVYIuVPAOnXCZ5g",
            "reason": "app-blur",
            "locale": "de",
            "theme": "dark",
            "metadata": {
                "device": {"type": "Handset", "brand": "google", "model": "Nexus", "name": "21081111RG", "uniqueId": hashlib.md5(str(time.time()).encode()).hexdigest()[:16]},
                "os": {"name": "android", "version": "7.1.2", "abis": ["arm64-v8a", "armeabi-v7a", "armeabi"], "host": "android"},
                "app": {
                    "platform": "android",
                    "version": "3.1.20",
                    "buildId": "289515000",
                    "engine": "hbc85",
                    "signatures": ["6e8a975e3cbf07d5de823a760d4c2547f86c1403105020adee5de67ac510999e"],
                    "installer": "app.revanced.manager.flutter",
                },
                "version": {"package": "tv.vavoo.app", "binary": "3.1.20", "js": "3.1.20"},
            },
            "appFocusTime": 0,
            "playerActive": False,
            "playDuration": 0,
            "devMode": False,
            "hasAddon": True,
            "castConnected": False,
            "package": "tv.vavoo.app",
            "version": "3.1.20",
            "process": "app",
            "firstAppStart": int(time.time() * 1000) - 86400000,
            "lastAppStart": int(time.time() * 1000),
            "ipLocation": "",
            "adblockEnabled": True,
            "proxy": {"supported": ["ss", "openvpn"], "engine": "ss", "ssVersion": 1, "enabled": True, "autoServer": True, "id": "pl-waw"},
            "iap": {"supported": False},
        }
        legacy_headers = {
            "user-agent": "okhttp/4.11.0",
            "accept": "application/json",
            "content-type": "application/json; charset=utf-8",
            "accept-encoding": "gzip",
        }
        for ping_url in (
            "https://www.vavoo.tv/api/app/ping",
            "https://vavoo.tv/api/app/ping",
            "https://api.vavoo.tv/app/ping",
        ):
            try:
                resp = self.session.post(
                    ping_url,
                    json=legacy_payload,
                    headers=legacy_headers,
                    timeout=8,
                    verify=False)
                if resp.status_code == 200:
                    signature = resp.json().get("addonSig")
                    if signature:
                        enhanced_log(
                            "[VAVOO] Signature vavoo ottenuta", "INFO", "VAVOO")
                        return signature
                enhanced_log(
                    "[VAVOO] Vavoo ping HTTP %s" %
                    resp.status_code, "WARNING", "VAVOO")
            except Exception as exc:
                enhanced_log(
                    "[VAVOO] Errore vavoo ping %s: %s" %
                    (ping_url, exc), "WARNING", "VAVOO")
        return None

    def resolve_vavoo_link_cached(self, url):
        cached = self._url_cache.get(url)
        if cached and (time.time() - cached["time"]) < 180:
            enhanced_log("[VAVOO] URL da cache", "DEBUG", "VAVOO")
            return cached["url"]

        signature = self.get_cached_signature()
        if not signature:
            return None

        headers = {
            "user-agent": "MediaHubMX/2",
            "accept": "application/json",
            "content-type": "application/json; charset=utf-8",
            "accept-encoding": "gzip",
            "mediahubmx-signature": signature,
        }
        payload = {
            "language": "de",
            "region": "AT",
            "url": url,
            "clientVersion": "3.0.2",
        }

        try:
            resp = self._post_json(_RESOLVE_URL, payload, headers, timeout=18)
            if not resp or resp.status_code != 200:
                enhanced_log(
                    "[VAVOO] Resolve HTTP %s" %
                    (resp.status_code if resp else "none"),
                    "WARNING",
                    "VAVOO")
                return None
            data = resp.json()
            resolved_url = None
            if isinstance(data, list) and data:
                resolved_url = data[0].get("url")
            elif isinstance(data, dict):
                resolved_url = data.get("url")
                if not resolved_url and isinstance(data.get("data"), dict):
                    resolved_url = data["data"].get("url")

            if resolved_url:
                self._url_cache[url] = {
                    "url": str(resolved_url), "time": time.time()}
                enhanced_log(
                    "[VAVOO] URL risolto via mediahubmx",
                    "INFO",
                    "VAVOO")
                return str(resolved_url)
        except Exception as exc:
            enhanced_log(
                "[VAVOO] Errore resolve: %s" %
                exc, "WARNING", "VAVOO")
        return None

    def get_ts_signature(self):
        if not self.session and not self._create_session():
            return None
        for attempt in range(3):
            try:
                resp = self.session.post(
                    _TS_PING2_URL,
                    data={
                        "vec": _TS_VEC},
                    headers={
                        "content-type": "application/x-www-form-urlencoded"},
                    timeout=10,
                    verify=False,
                )
                if resp.status_code == 200:
                    signed = resp.json().get("response", {}).get("signed")
                    if signed:
                        enhanced_log(
                            "[VAVOO] TS signature ottenuta", "INFO", "VAVOO")
                        return signed
                enhanced_log(
                    "[VAVOO] ping2 HTTP %s" %
                    resp.status_code, "WARNING", "VAVOO")
            except Exception as exc:
                enhanced_log(
                    "[VAVOO] Errore ping2 tentativo %s: %s" %
                    (attempt + 1, exc), "WARNING", "VAVOO")
        return None

    def build_ts_fallback_url(self, play_url, ts_sig):
        match = re.search(r"/play/([^/?#]+)", play_url)
        if not match:
            return None
        channel_id = match.group(1)
        if not channel_id.isdigit():
            enhanced_log(
                "[VAVOO] TS fallback ignorato per ID non numerico",
                "WARNING",
                "VAVOO")
            return None
        return "https://www2.vavoo.to/live2/%s.ts?n=1&b=5&vavoo_auth=%s" % (
            channel_id,
            quote_plus(ts_sig),
        )

    def is_vavoo_link(self, url):
        if not url:
            return False
        return "vavoo.to" in url.lower() and (
            "/play/" in url.lower() or "/vavoo-iptv/play/" in url.lower())

    def resolve_vavoo_link(self, url):
        if not self.is_vavoo_link(url):
            return None
        return self.resolve_vavoo_link_cached(url)

    def extract(self, url, headers=None):
        enhanced_log("[VAVOO] Estrazione: %s..." % url[:100], "INFO", "VAVOO")
        if "vavoo.to" not in (url or "").lower():
            return {
                "resolved_url": url,
                "destination_url": url,
                "headers": headers or {},
                "request_headers": headers or {}}

        resolved_url = self.resolve_vavoo_link_cached(url)
        stream_headers = self.get_stream_headers()

        if not resolved_url:
            ts_sig = self.get_ts_signature()
            if ts_sig:
                resolved_url = self.build_ts_fallback_url(url, ts_sig)
                stream_headers = {"user-agent": "VAVOO/2.6"}

        if not resolved_url:
            enhanced_log(
                "[VAVOO] Risoluzione fallita, nessun URL riproducibile",
                "WARNING",
                "VAVOO")
            return {
                "resolved_url": None,
                "destination_url": None,
                "headers": headers or {},
                "request_headers": headers or {},
                "m3u8_content": "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-ENDLIST\n# Vavoo resolver non disponibile\n",
            }

        stream_headers["X-EasyProxy-Disable-SSL"] = "1"
        return {
            "resolved_url": resolved_url,
            "destination_url": resolved_url,
            "headers": stream_headers,
            "request_headers": stream_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
            "disable_ssl": True,
        }

    def get_stream_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://vavoo.to",
            "Origin": "https://vavoo.to",
        }

    def cleanup_cache(self):
        now = time.time()
        if now - self._signature_time > 300:
            self._signature_cache = None
            self._signature_time = 0
        for url, data in list(self._url_cache.items()):
            if now - data["time"] > 300:
                self._url_cache.pop(url, None)

    def clear_cache(self, channel_id=None):
        self._signature_cache = None
        self._signature_time = 0
        self._url_cache.clear()
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            self.session = None

    def close(self):
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            self.session = None

    def __del__(self):
        self.close()


def is_vavoo_link(url):
    return vavoo_extractor.is_vavoo_link(url)


def resolve_vavoo_url(url, headers=None):
    return vavoo_extractor.extract(url, headers)


class VavooResolverNoCache(VavooExtractor):
    def getAuthSignature(self):
        return self.get_cached_signature()

    def resolve_vavoo_link(self, link):
        return self.resolve_vavoo_link_cached(link)

    def clear_vavoo_cache(self, channel_id=None):
        return self.clear_cache(channel_id)


vavoo_extractor = VavooExtractor()
vavoo_resolver = VavooResolverNoCache()
vavoo_resolver.clear_vavoo_cache = lambda x=None: vavoo_resolver.clear_cache(x)

enhanced_log("[VAVOO] Vavoo Extractor caricato", "INFO", "VAVOO")
