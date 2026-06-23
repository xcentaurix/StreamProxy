# sport99_extractor.py - Sports99/CDNLiveTV extractor per Enigma2 Python 3
import base64
import importlib
import re
import time
import urllib.parse
from urllib.parse import urljoin, urlparse

try:
    import requests
    from requests.adapters import HTTPAdapter
    try:
        import urllib3
        from urllib3.util.retry import Retry
        from urllib3.exceptions import InsecureRequestWarning
        urllib3.disable_warnings(InsecureRequestWarning)
    except ImportError:
        urllib3 = importlib.import_module("requests.packages.urllib3")
        Retry = importlib.import_module(
            "requests.packages.urllib3.util.retry").Retry
        InsecureRequestWarning = importlib.import_module(
            "requests.packages.urllib3.exceptions").InsecureRequestWarning
        urllib3.disable_warnings(InsecureRequestWarning)
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from ..StreamProxyLog import enhanced_log
except (ImportError, ValueError):
    try:
        from StreamProxyLog import enhanced_log
    except ImportError:
        def enhanced_log(msg, level="INFO", tag="SPORT99"):
            print("[%s] [%s] %s" % (level, tag, msg))


SPORT99_ENTRY_ORIGIN = "https://streamsports99.su"
CDNLIVETV_ORIGIN = "https://cdnlivetv.tv"


class Sport99ExtractorError(Exception):
    pass


class Sport99Extractor:
    """Extractor sincrono per player Sports99 che risolve stream CDNLiveTV."""

    def __init__(self, request_headers=None, proxies=None):
        self.request_headers = request_headers or {}
        self.proxies = proxies
        self.mediaflow_endpoint = "hls_manifest_proxy"
        self.base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        self.session = None
        if REQUESTS_AVAILABLE:
            self.session = requests.Session()
            retry_kwargs = dict(
                total=1,
                connect=1,
                read=1,
                backoff_factor=0.35,
                status_forcelist=[429, 500, 502, 503, 504],
                raise_on_status=False,
            )
            try:
                retry = Retry(
                    allowed_methods=[
                        "HEAD",
                        "GET",
                        "POST"],
                    **retry_kwargs)
            except TypeError:
                retry = Retry(
                    method_whitelist=[
                        "HEAD",
                        "GET",
                        "POST"],
                    **retry_kwargs)
            adapter = HTTPAdapter(
                max_retries=retry,
                pool_connections=3,
                pool_maxsize=5)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
            self.session.headers.update(self.base_headers)
            self.session.verify = False

    def update_request_headers(self, request_headers=None):
        self.request_headers = request_headers or {}

    def _get_request_header(self, name, default=None):
        for header_name, header_value in self.request_headers.items():
            if header_name.lower() == name.lower():
                return header_value
        return default

    def _merge_headers(self, headers=None):
        merged = dict(self.base_headers)
        merged.update(self.request_headers)
        if headers:
            merged.update(headers)
        return merged

    def _make_request(self, url, headers=None, timeout=15, retries=2):
        if not self.session:
            raise Sport99ExtractorError("Modulo requests non disponibile")

        final_headers = self._merge_headers(headers)
        last_error = None
        for attempt in range(max(1, retries)):
            try:
                enhanced_log("GET %s/%s %s" %
                             (attempt + 1, retries, url[:120]), "DEBUG", "SPORT99")
                response = self.session.get(
                    url,
                    headers=final_headers,
                    timeout=timeout,
                    allow_redirects=True,
                    verify=False,
                    proxies=self.proxies,
                )
                if response.status_code in (200, 401, 403, 404):
                    response.raise_for_status()
                    return response
                last_error = "HTTP %s" % response.status_code
            except Exception as exc:
                last_error = exc
                enhanced_log(
                    "Richiesta fallita: %s" %
                    exc, "WARNING", "SPORT99")
            if attempt < retries - 1:
                time.sleep(0.35)
        raise Sport99ExtractorError(
            "Richiesta fallita per %s: %s" %
            (url, last_error))

    def _build_player_headers(self, url):
        parsed = urlparse(url)
        origin = "%s://%s" % (parsed.scheme or "https",
                              parsed.netloc) if parsed.netloc else SPORT99_ENTRY_ORIGIN
        return {
            "User-Agent": self._get_request_header("User-Agent", self.base_headers["User-Agent"]),
            "Referer": self._get_request_header("Referer", origin + "/"),
            "Origin": origin,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": self._get_request_header("Accept-Language", "en-US,en;q=0.9,it;q=0.8"),
            "Upgrade-Insecure-Requests": "1",
        }

    def _build_stream_headers(self):
        return {
            "User-Agent": self._get_request_header("User-Agent", self.base_headers["User-Agent"]),
            "Referer": CDNLIVETV_ORIGIN + "/",
            "Origin": CDNLIVETV_ORIGIN,
            "Accept": "*/*",
            "Accept-Language": self._get_request_header("Accept-Language", "en-US,en;q=0.9,it;q=0.8"),
        }

    def _session_cookie_header(self):
        if not self.session:
            return None
        try:
            cookie_header = "; ".join(
                "%s=%s" % (cookie.name, cookie.value)
                for cookie in self.session.cookies
            )
            return cookie_header or None
        except Exception:
            return None

    def _unpack(self, h_value, u_value, n_value, t_value, e_value):
        try:
            separator = n_value[e_value]
            replacements = {
                n_value[index]: str(index) for index in range(
                    len(n_value))}
            result = ""

            for item in h_value.split(separator):
                if not item:
                    continue
                converted = item
                for marker, value in replacements.items():
                    converted = converted.replace(marker, value)
                try:
                    result += chr(int(converted, e_value) - t_value)
                except (ValueError, TypeError):
                    continue

            try:
                return urllib.parse.unquote(result.encode(
                    "latin-1").decode("utf-8", errors="ignore"))
            except Exception:
                return result
        except Exception as exc:
            enhanced_log("Unpack fallito: %s" % exc, "ERROR", "SPORT99")
            return ""

    @staticmethod
    def _decode_base64(value):
        value = (value or "").replace("-", "+").replace("_", "/")
        while len(value) % 4:
            value += "="
        try:
            decoded = base64.b64decode(value)
            try:
                return decoded.decode("utf-8")
            except Exception:
                return decoded.decode("latin-1")
        except Exception:
            return value

    @staticmethod
    def _extract_direct_m3u8(text):
        clean_text = (text or "").replace("\\/", "/")
        patterns = [
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)",
            r"(//[^\s\"'<>]+\.m3u8[^\s\"'<>]*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, clean_text)
            if match:
                url = match.group(1)
                if url.startswith("//"):
                    return "https:" + url
                return url
        return None

    def _extract_url_from_js(self, js_code):
        direct_url = self._extract_direct_m3u8(js_code)
        if direct_url:
            return direct_url

        consts = dict(
            re.findall(
                r"const\s+([a-zA-Z0-9_]+)\s*=\s*'([^']*)';",
                js_code or ""))
        construction_lines = re.findall(
            r"const\s+([a-zA-Z0-9_]+)\s*=\s*"
            r"([a-zA-Z0-9_]+\([a-zA-Z0-9_]+\)(?:\s*\+\s*[a-zA-Z0-9_]+\([a-zA-Z0-9_]+\))*);",
            js_code or "",
        )

        for _var_name, expression in construction_lines:
            parts = re.findall(r"\(([a-zA-Z0-9_]+)\)", expression)
            full_url = "".join([self._decode_base64(
                consts.get(part, "")) for part in parts])
            if ".m3u8" in full_url and "token=" in full_url:
                return full_url.replace("\\/", "/")

        for _var_name, expression in construction_lines:
            parts = re.findall(r"\(([a-zA-Z0-9_]+)\)", expression)
            full_url = "".join([self._decode_base64(
                consts.get(part, "")) for part in parts])
            if ".m3u8" in full_url:
                return full_url.replace("\\/", "/")
        return None

    def extract(self, url, request_headers=None, **kwargs):
        self.update_request_headers(request_headers)
        enhanced_log("Inizio estrazione: %s" % url[:120], "INFO", "SPORT99")

        response = self._make_request(
            url, headers=self._build_player_headers(url))
        html = response.text

        direct_url = self._extract_direct_m3u8(html)
        stream_url = direct_url

        if not stream_url:
            packed_match = re.search(
                r'\("([^"]+)"\s*,\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)',
                html or "",
            )
            if not packed_match:
                raise Sport99ExtractorError("Packed script non trovato")

            h_value, u_value, n_value, t_value, e_value, _unused = packed_match.groups()
            unpacked_js = self._unpack(
                h_value,
                int(u_value),
                n_value,
                int(t_value),
                int(e_value))
            stream_url = self._extract_url_from_js(unpacked_js)

        if not stream_url:
            raise Sport99ExtractorError("Nessun URL m3u8 trovato")

        stream_url = urljoin(response.url, stream_url.replace("\\/", "/"))
        stream_headers = self._build_stream_headers()
        cookie_header = self._session_cookie_header()
        if cookie_header:
            stream_headers["Cookie"] = cookie_header

        enhanced_log("M3U8 estratto: %s" % stream_url, "INFO", "SPORT99")

        result = {
            "resolved_url": stream_url,
            "destination_url": stream_url,
            "headers": stream_headers,
            "request_headers": stream_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

        try:
            manifest_response = self._make_request(
                stream_url, headers=stream_headers, timeout=10, retries=1)
            manifest_text = manifest_response.text
            if manifest_text and manifest_text.lstrip().startswith("#EXTM3U"):
                enhanced_log(
                    "Manifest M3U8 scaricato con sessione Sport99",
                    "INFO",
                    "SPORT99")
                result["resolved_url"] = manifest_response.url
                result["destination_url"] = manifest_response.url
                result["m3u8_content"] = manifest_text
            else:
                enhanced_log(
                    "Manifest Sport99 non valido, lascio fetch ad AppCore",
                    "WARNING",
                    "SPORT99")
        except Exception as exc:
            enhanced_log(
                "Prefetch manifest Sport99 fallito: %s" %
                exc, "WARNING", "SPORT99")

        return result

    def close(self):
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            self.session = None


sport99_extractor = Sport99Extractor()


def extract_sport99(url, request_headers=None):
    try:
        return sport99_extractor.extract(url, request_headers=request_headers)
    except Exception as exc:
        enhanced_log("Errore estrazione Sport99: %s" % exc, "ERROR", "SPORT99")
        return None


def is_sport99_link(url):
    if not url:
        return False
    lowered = url.lower()
    return any(domain in lowered for domain in (
        "cdnlivetv.tv",
        "streamsports99.su",
        "sports99",
        "sport99",
    ))


if __name__ == "__main__":
    print("Sport99 extractor pronto")
