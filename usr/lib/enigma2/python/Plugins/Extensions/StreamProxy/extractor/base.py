"""Base extractor sincrono per StreamProxy/Enigma2.

Derivato dal modello EasyProxy, ma senza dipendenze async non adatte ai decoder.
"""

import importlib
import random
import time

try:
    import requests
    from requests.adapters import HTTPAdapter
    try:
        import urllib3
        from urllib3.util.retry import Retry
        from urllib3.exceptions import InsecureRequestWarning
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
        def enhanced_log(msg, level="INFO", tag="Extractor"):
            print("[{}] [{}] {}".format(level, tag, msg))


class ExtractorError(Exception):
    pass


class BaseExtractor:
    """Base comune con sessione persistente, proxy opzionale e retry leggero."""

    def __init__(
            self,
            request_headers=None,
            proxies=None,
            extractor_name="generic"):
        self.request_headers = request_headers or {}
        self.extractor_name = extractor_name
        self.proxies = proxies
        self.base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        self.session = None
        self.mediaflow_endpoint = "hls_proxy"
        if REQUESTS_AVAILABLE:
            self.session = requests.Session()
            retry_kwargs = dict(
                total=0,
                connect=0,
                read=0,
                backoff_factor=0.5,
                status_forcelist=[403, 429, 500, 502, 503, 504],
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
                pool_connections=4,
                pool_maxsize=8)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
            self.session.headers.update(self.base_headers)
            self.session.verify = False

    def _merge_headers(self, headers=None):
        merged = dict(self.base_headers)
        merged.update(self.request_headers)
        if headers:
            merged.update(headers)
        return merged

    def _make_request(
            self,
            url,
            method="GET",
            headers=None,
            retries=2,
            timeout=15,
            **kwargs):
        if not self.session:
            raise ExtractorError("Modulo requests non disponibile")

        final_headers = self._merge_headers(headers)
        kwargs.setdefault("allow_redirects", True)
        kwargs.setdefault("verify", False)
        if self.proxies and "proxies" not in kwargs:
            kwargs["proxies"] = self.proxies

        last_error = None
        for attempt in range(max(1, retries)):
            try:
                if attempt:
                    final_headers["User-Agent"] = self.base_headers["User-Agent"]
                response = self.session.request(
                    method,
                    url,
                    headers=final_headers,
                    timeout=timeout,
                    **kwargs
                )
                if response.status_code not in (
                        403, 429, 500, 502, 503, 504) or attempt == retries - 1:
                    response.raise_for_status()
                    return response
                enhanced_log(
                    "[{}] HTTP {}, retry {}".format(
                        self.extractor_name,
                        response.status_code,
                        attempt + 1),
                    "DEBUG",
                    "Extractor")
                last_error = ExtractorError(
                    "HTTP {}".format(response.status_code))
            except Exception as exc:
                last_error = exc
                enhanced_log(
                    "[{}] richiesta fallita: {}".format(
                        self.extractor_name,
                        exc),
                    "DEBUG",
                    "Extractor")
            time.sleep(0.25 + random.random() * 0.25)

        raise ExtractorError(
            "Request failed for {}: {}".format(
                url, last_error))

    def close(self):
        if self.session:
            self.session.close()
