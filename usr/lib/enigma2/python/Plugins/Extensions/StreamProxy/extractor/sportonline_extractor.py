# sportonline_extractor.py - Sportsonline/Sportzonline extractor per Enigma2 Python 3
import re
import time
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    requests = None

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
        def enhanced_log(msg, level="INFO", tag="SPORTONLINE"):
            print("[%s][%s] %s" % (tag, level, msg))


class SportOnlineExtractorError(Exception):
    pass


def _int2base(x, base):
    if x < 0:
        sign = -1
    elif x == 0:
        return "0"
    else:
        sign = 1

    x *= sign
    digits = []
    while x:
        digits.append("0123456789abcdefghijklmnopqrstuvwxyz"[x % base])
        x = int(x / base)
    if sign < 0:
        digits.append("-")
    digits.reverse()
    return "".join(digits)


def unpack(p, a, c, k, e=None, d=None):
    while c > 0:
        c -= 1
        if k[c]:
            p = re.sub(r"\b" + _int2base(c, a) + r"\b", k[c], p)
    return p


def extract_unpack(packed_js):
    try:
        match = re.search(r"}\((.*)\)\)", packed_js)
        if not match:
            raise ValueError("Cannot find packed data")
        p, a, c, k, e, d = eval("(%s)" % match.group(1), {"__builtins__": {}}, {})
        return unpack(p, a, c, k, e, d)
    except Exception as exc:
        raise SportOnlineExtractorError("Failed to unpack JS: %s" % exc)


class SportsonlineExtractor:
    """Versione sincrona Enigma2 allineata al source EasyProxy."""

    def __init__(self, request_headers=None):
        self.request_headers = request_headers or {}
        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        }
        self.mediaflow_endpoint = "hls_manifest_proxy"
        self.session = requests.Session() if requests else None
        if self.session:
            self.session.headers.update(self.base_headers)
            self.session.verify = False

    def update_request_headers(self, request_headers=None):
        self.request_headers = request_headers or {}

    def _get_request_header(self, name, default=None):
        for header_name, header_value in self.request_headers.items():
            if header_name.lower() == name.lower():
                return header_value
        return default

    @staticmethod
    def _get_origin(url):
        parsed = urlparse(url)
        return "%s://%s" % (parsed.scheme, parsed.netloc)

    def _copy_request_headers(self, header_map):
        copied = {}
        for request_name, output_name in header_map.items():
            value = self._get_request_header(request_name)
            if value:
                copied[output_name] = value
        return copied

    def _build_page_headers(self):
        headers = {
            "User-Agent": self._get_request_header("User-Agent", self.base_headers["User-Agent"]),
            "Accept": self._get_request_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
            "Accept-Language": self._get_request_header("Accept-Language", "en-US,en;q=0.9,it;q=0.8"),
            "Cache-Control": self._get_request_header("Cache-Control", "max-age=0"),
            "Upgrade-Insecure-Requests": self._get_request_header("Upgrade-Insecure-Requests", "1"),
            "Sec-Fetch-Site": self._get_request_header("Sec-Fetch-Site", "none"),
            "Sec-Fetch-Mode": self._get_request_header("Sec-Fetch-Mode", "navigate"),
            "Sec-Fetch-User": self._get_request_header("Sec-Fetch-User", "?1"),
            "Sec-Fetch-Dest": self._get_request_header("Sec-Fetch-Dest", "document"),
        }
        headers.update(self._copy_request_headers({
            "sec-ch-ua": "Sec-CH-UA",
            "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
            "sec-ch-ua-platform": "Sec-CH-UA-Platform",
            "Cookie": "Cookie",
            "Pragma": "Pragma",
        }))
        return headers

    def _build_iframe_headers(self, page_url, iframe_url):
        headers = self._build_page_headers()
        headers["Referer"] = page_url
        headers["Origin"] = self._get_origin(page_url)
        headers["Sec-Fetch-Site"] = "same-origin" if urlparse(page_url).netloc == urlparse(iframe_url).netloc else "cross-site"
        headers["Sec-Fetch-Dest"] = "iframe"
        headers.pop("Sec-Fetch-User", None)
        return headers

    @staticmethod
    def _looks_like_block_page(html):
        lowered = (html or "").lower()
        return any(marker in lowered for marker in (
            "sorry, you have been blocked",
            "attention required!",
            "cloudflare",
            "access denied",
        ))

    def _make_request(self, url, headers=None, retries=2, initial_delay=1, timeout=15):
        if not self.session:
            raise SportOnlineExtractorError("requests non disponibile")
        final_headers = headers or self.base_headers
        last_error = None
        for attempt in range(retries):
            try:
                enhanced_log("GET %s/%s %s" % (attempt + 1, retries, url[:120]), "DEBUG", "SPORTONLINE")
                response = self.session.get(url, headers=final_headers, timeout=timeout, verify=False)
                if response.status_code == 200:
                    html = response.text
                    if self._looks_like_block_page(html):
                        raise SportOnlineExtractorError("block page rilevata")
                    return html, response.url
                last_error = "HTTP %s" % response.status_code
            except Exception as exc:
                last_error = exc
                enhanced_log("Richiesta fallita: %s" % exc, "WARNING", "SPORTONLINE")
            if attempt < retries - 1:
                time.sleep(initial_delay)
        raise SportOnlineExtractorError("Richiesta fallita per %s: %s" % (url, last_error))

    @staticmethod
    def _detect_packed_blocks(html):
        raw_matches = []
        strict_eval_pattern = re.compile(r"eval\(function\(p,a,c,k,e,.*?\}\(.*?\)\)", re.DOTALL)
        relaxed_eval_pattern = re.compile(r"eval\(function\(p,a,c,k,e,[dr]\).*?\}\(.*?\)\)", re.DOTALL)
        script_pattern = re.compile(r"<script[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)

        for script_body in script_pattern.findall(html or ""):
            if "eval(function(p,a,c,k,e" in script_body:
                strict_matches = strict_eval_pattern.findall(script_body)
                if strict_matches:
                    raw_matches.extend(strict_matches)
                    continue
                raw_matches.extend(relaxed_eval_pattern.findall(script_body))

        if raw_matches:
            return raw_matches
        raw_matches = strict_eval_pattern.findall(html or "")
        if not raw_matches:
            raw_matches = relaxed_eval_pattern.findall(html or "")
        return raw_matches

    @staticmethod
    def _extract_m3u8_candidate(text):
        patterns = [
            r"var\s+src\s*=\s*[\"']([^\"']+\.m3u8[^\"']*)[\"']",
            r"src\s*=\s*[\"']([^\"']+\.m3u8[^\"']*)[\"']",
            r"file\s*:\s*[\"']([^\"']+\.m3u8[^\"']*)[\"']",
            r"[\"']([^\"']*https?://[^\"']+\.m3u8[^\"']*)[\"']",
            r"(https?://[^\s\"'>]+\.m3u8[^\s\"'>]*)",
            r"(//[^\s\"'>]+\.m3u8[^\s\"'>]*)",
            r"(/[^\s\"'>]+\.m3u8[^\s\"'>]*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text or "")
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _normalize_stream_url(stream_url, base_url):
        cleaned = stream_url.strip().strip("\"'").replace("\\/", "/")
        if cleaned.startswith("//"):
            parsed_base = urlparse(base_url)
            return "%s:%s" % (parsed_base.scheme or "https", cleaned)
        if not urlparse(cleaned).scheme:
            return urljoin(base_url, cleaned)
        return cleaned

    def extract(self, url, request_headers=None):
        self.update_request_headers(request_headers)
        parsed_source = urlparse(url)
        source_origin = "%s://%s" % (parsed_source.scheme, parsed_source.netloc)
        source_referer = self._get_request_header("Referer") or source_origin + "/"
        user_agent = self._get_request_header("User-Agent", self.base_headers["User-Agent"])

        main_headers = self._build_page_headers()
        main_headers["Referer"] = source_referer
        main_headers["Origin"] = source_origin
        main_html, main_url = self._make_request(url, headers=main_headers, timeout=15)

        iframe_match = re.search(r'<iframe[^>]+(?<!data-)src=["\']([^"\']+)["\']', main_html, re.IGNORECASE)
        iframe_url = main_url
        iframe_html = main_html

        if iframe_match:
            iframe_url = self._normalize_stream_url(iframe_match.group(1), main_url)
            candidates = [iframe_url]
            parsed_iframe = urlparse(iframe_url)
            if parsed_iframe.netloc.lower() == "gotdynamic.net":
                candidates.extend([
                    parsed_iframe._replace(netloc="wgstream.sx").geturl(),
                    parsed_iframe._replace(netloc="www.wgstream.sx").geturl(),
                ])

            iframe_html = None
            for candidate_url in candidates:
                try:
                    iframe_headers = self._build_iframe_headers(main_url, candidate_url)
                    iframe_html, iframe_url = self._make_request(candidate_url, headers=iframe_headers, timeout=15, retries=1)
                    break
                except Exception as exc:
                    enhanced_log("Iframe candidate fallito %s: %s" % (candidate_url, exc), "WARNING", "SPORTONLINE")
            if not iframe_html:
                raise SportOnlineExtractorError("Tutti gli iframe candidate sono falliti")
        else:
            enhanced_log("Nessun iframe, provo HTML principale", "WARNING", "SPORTONLINE")

        parsed_iframe = urlparse(iframe_url)
        playback_headers = {
            "Referer": iframe_url,
            "Origin": "%s://%s" % (parsed_iframe.scheme, parsed_iframe.netloc),
            "User-Agent": user_agent,
        }

        direct_match = self._extract_m3u8_candidate(iframe_html)
        packed_blocks = self._detect_packed_blocks(iframe_html)
        enhanced_log("Blocchi packed trovati: %s" % len(packed_blocks), "DEBUG", "SPORTONLINE")

        m3u8_url = None
        if direct_match:
            m3u8_url = direct_match
        elif packed_blocks:
            chosen_idx = 1 if len(packed_blocks) > 1 else 0
            ordered_blocks = [packed_blocks[chosen_idx]] + [
                block for index, block in enumerate(packed_blocks) if index != chosen_idx
            ]
            for block in ordered_blocks:
                try:
                    unpacked_code = extract_unpack(block)
                    m3u8_url = self._extract_m3u8_candidate(unpacked_code)
                    if m3u8_url:
                        break
                except Exception as exc:
                    enhanced_log("Unpack fallito: %s" % exc, "DEBUG", "SPORTONLINE")

        if not m3u8_url:
            raise SportOnlineExtractorError("Nessun URL m3u8 trovato")

        m3u8_url = self._normalize_stream_url(m3u8_url, iframe_url)
        enhanced_log("M3U8 estratto: %s" % m3u8_url, "INFO", "SPORTONLINE")
        return {
            "resolved_url": m3u8_url,
            "destination_url": m3u8_url,
            "headers": playback_headers,
            "request_headers": playback_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    def close(self):
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            self.session = None


_sportsonline_extractor = SportsonlineExtractor()


def extract_sportonline(url, request_headers=None):
    try:
        return _sportsonline_extractor.extract(url, request_headers=request_headers)
    except Exception as exc:
        enhanced_log("Errore estrazione Sportsonline: %s" % exc, "ERROR", "SPORTONLINE")
        return None


def is_sportonline_link(url):
    if not url:
        return False
    lowered = url.lower()
    return any(domain in lowered for domain in ("sportsonline", "sportzonline", "sportssonline"))


if __name__ == "__main__":
    test_url = "https://sportzonline.st/example"
    print(extract_sportonline(test_url))
