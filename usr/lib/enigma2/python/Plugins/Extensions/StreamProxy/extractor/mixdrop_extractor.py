# mixdrop_extractor.py - Mixdrop Extractor per Enigma2
# Compatibile con Python 3 e decoder Enigma2

import re
import time
import random
import os
from urllib.parse import urlparse, urljoin

try:
    import requests
    from requests.adapters import HTTPAdapter
    try:
        import urllib3
        from urllib3.util.retry import Retry
        from urllib3.exceptions import InsecureRequestWarning
        urllib3.disable_warnings(InsecureRequestWarning)
    except ImportError:
        urllib3 = __import__("requests.packages.urllib3")
        Retry = __import__("requests.packages.urllib3.util.retry").Retry
        InsecureRequestWarning = __import__(
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
        def enhanced_log(msg, level="INFO", tag="Mixdrop"):
            print(f"[{level}] [{tag}] {msg}")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    enhanced_log(
        "BeautifulSoup non disponibile, parsing HTML limitato",
        "WARNING",
        "Mixdrop")


class MixdropExtractorError(Exception):
    """Eccezione specifica per errori Mixdrop"""
    pass


class MixdropExtractor:
    """
    Mixdrop Extractor per Enigma2
    Estrae URL video da mixdrop.co e mirror
    """

    _result_cache = {}  # Cache risultati per 10 minuti

    def __init__(self, request_headers=None):
        enhanced_log(
            "Inizializzazione MixdropExtractor per Enigma2",
            "INFO",
            "Mixdrop")

        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36']

        self.base_headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }

        if request_headers:
            self.base_headers.update(request_headers)
        self.flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "").strip()
        try:
            self.flaresolverr_timeout = int(
                os.environ.get("FLARESOLVERR_TIMEOUT", "75"))
        except ValueError:
            self.flaresolverr_timeout = 75

        # Sessione HTTP persistente
        if REQUESTS_AVAILABLE:
            self.session = requests.Session()
            retry_kwargs = dict(
                total=2,
                connect=1,
                read=1,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504],
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
            self.session.mount('http://', adapter)
            self.session.mount('https://', adapter)
            self.session.headers.update(self.base_headers)
            self.session.verify = False
            enhanced_log("Sessione HTTP configurata", "DEBUG", "Mixdrop")
        else:
            self.session = None
            enhanced_log(
                "Modulo requests non disponibile",
                "WARNING",
                "Mixdrop")

        self.mediaflow_endpoint = "proxy_stream_endpoint"

    def _http_request(self, method, url, headers=None, timeout=10, **kwargs):
        """Richiesta HTTP sincrona con retry leggero"""
        if not self.session:
            raise MixdropExtractorError("Sessione HTTP non disponibile")

        request_headers = dict(self.base_headers)
        if headers:
            request_headers.update(headers)

        kwargs.setdefault("allow_redirects", True)
        kwargs.setdefault("verify", False)

        last_error = None
        for attempt in range(2):
            try:
                if attempt:
                    request_headers["User-Agent"] = random.choice(
                        self.user_agents)

                response = self.session.request(
                    method,
                    url,
                    headers=request_headers,
                    timeout=timeout,
                    **kwargs
                )

                if response.status_code in (401, 403, 404):
                    return response
                if response.status_code not in (
                        429, 500, 502, 503, 504) or attempt:
                    return response

                enhanced_log(
                    f"HTTP {response.status_code}, retry: {url[:90]}", "DEBUG", "Mixdrop")
                last_error = MixdropExtractorError(
                    f"HTTP {response.status_code}")
                time.sleep(0.5)
            except Exception as exc:
                last_error = exc
                enhanced_log(
                    f"Errore {method} {url[:90]}: {exc}", "DEBUG", "Mixdrop")
                if attempt:
                    break
                time.sleep(0.5)

        if last_error:
            raise last_error
        raise MixdropExtractorError("Richiesta HTTP fallita")

    def _http_get(self, url, headers=None, timeout=10, **kwargs):
        return self._http_request(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            **kwargs)

    def _request_flaresolverr(self, url, session_id=None):
        """Fallback anti-bot compatibile con EasyProxy, se FLARESOLVERR_URL e' configurato."""
        if not self.flaresolverr_url:
            return None

        endpoint = self.flaresolverr_url.rstrip("/") + "/v1"
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": (self.flaresolverr_timeout + 60) * 1000,
        }
        if session_id:
            payload["session"] = session_id

        try:
            enhanced_log(
                f"Fallback FlareSolverr per: {url[:80]}...", "INFO", "Mixdrop")
            response = self.session.post(
                endpoint, json=payload, timeout=self.flaresolverr_timeout + 95)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "ok":
                enhanced_log(
                    f"FlareSolverr non ok: {
                        data.get('message')}",
                    "WARNING",
                    "Mixdrop")
                return None

            solution = data.get("solution", {})
            cookies = {
                cookie.get("name"): cookie.get("value")
                for cookie in solution.get("cookies", [])
                if cookie.get("name") and cookie.get("value") is not None
            }
            return {
                "html": solution.get(
                    "response",
                    ""),
                "url": solution.get("url") or url,
                "user_agent": solution.get("userAgent") or self.base_headers.get("User-Agent"),
                "cookies": cookies,
            }
        except Exception as e:
            enhanced_log(f"FlareSolverr fallito: {e}", "WARNING", "Mixdrop")
            return None

    def _unpack(self, packed_js):
        """Unpacker per JavaScript packed"""
        try:
            match = re.search(
                r"}\('(.*)',(\d+),(\d+),'(.*)'\.split\('\|'\)", packed_js)
            if not match:
                match = re.search(
                    r"\}\('([\s\S]*?)',\s*(\d+),\s*(\d+),\s*'([\s\S]*?)'\.split\('\|'\)", packed_js)
            if not match:
                match = re.search(
                    r"\}\(([\s\S]*?),\s*(\d+),\s*(\d+),\s*'([\s\S]*?)'\.split\('\|'\)", packed_js)
            if not match:
                return packed_js

            p, a, c, k = match.groups()
            p = p.strip("'\"")
            a, c, k = int(a), int(c), k.split('|')

            def e(c):
                res = ""
                if c >= a:
                    res = e(c // a)
                return res + \
                    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"[c % a]

            d = {e(i): (k[i] if k[i] else e(i)) for i in range(c)}
            for i in range(c):
                if str(i) not in d:
                    d[str(i)] = k[i] if k[i] else str(i)

            return re.sub(
                r'\b(\w+)\b',
                lambda m: d.get(
                    m.group(1),
                    m.group(1)),
                p)
        except Exception as e:
            enhanced_log(f"Unpack fallito: {e}", "DEBUG", "Mixdrop")
            return packed_js

    def _extract_video_url(self, html, current_url):
        """Estrae URL video dall'HTML"""
        # Unpack JavaScript se presente
        if "eval(function(p,a,c,k,e,d)" in html:
            for block in re.findall(
                r'eval\(function\(p,a,c,k,e,d\).*?\}\(.*\)\)',
                html,
                    re.S):
                unpacked = self._unpack(block)
                html += "\n" + unpacked

        # Pattern per trovare URL video
        patterns = [
            r'(?:MDCore|vsConfig)\.wurl\s*=\s*["\']([^"\']+)["\']',
            r'source\s*src\s*=\s*["\']([^"\']+)["\']',
            r'file:\s*["\']([^"\']+)["\']',
            r'["\'](https?://[^\s"\']+\.(?:mp4|m3u8)[^\s"\']*)["\']',
            r'wurl\s*:\s*["\']([^"\']+)["\']'
        ]

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                video_url = match.group(1)
                if video_url.startswith("//"):
                    video_url = "https:" + video_url
                return video_url

        # Cerca iframe embed
        if BS4_AVAILABLE:
            soup = BeautifulSoup(html, "html.parser")
            iframe = soup.find("iframe", src=re.compile(r'/e/|/emb', re.I))
            if iframe:
                iframe_url = urljoin(current_url, iframe["src"])
                return iframe_url

        return None

    def extract(self, url, **kwargs):
        """Estrae URL video da Mixdrop"""
        normalized_url = url.strip().replace(" ", "%20")

        # Check cache
        cache_key = normalized_url
        if cache_key in MixdropExtractor._result_cache:
            result, timestamp = MixdropExtractor._result_cache[cache_key]
            if time.time() - timestamp < 600:  # 10 minuti
                enhanced_log(
                    f"Cache hit per: {normalized_url[:50]}...", "INFO", "Mixdrop")
                return result

        enhanced_log(
            f"Estrazione per: {normalized_url[:50]}...", "INFO", "Mixdrop")

        # Converti /f/ in /e/ (embed)
        if "/f/" in normalized_url:
            normalized_url = normalized_url.replace("/f/", "/e/")
        if "/mix/" in normalized_url:
            normalized_url = normalized_url.replace("/mix/", "/e/")

        # Mirror domains. Normalizza anche mirror gia' in input, ad esempio
        # m1xdrop.net.
        mirror_domains = [
            "mixdrop.co",
            "mixdrop.vip",
            "m1xdrop.net",
            "m1xdrop.bz",
            "mixdrop.ch",
            "mixdrop.ps",
            "mixdrop.ag",
        ]
        parsed_url = urlparse(normalized_url)
        path_and_query = parsed_url.path
        if parsed_url.query:
            path_and_query += "?" + parsed_url.query
        mirrors = []
        if parsed_url.scheme and parsed_url.netloc:
            for domain in mirror_domains:
                mirrors.append(
                    f"{parsed_url.scheme}://{domain}{path_and_query}")
        else:
            mirrors.append(normalized_url)
        if normalized_url not in mirrors:
            mirrors.insert(0, normalized_url)

        last_error = None
        for mirror_url in mirrors:
            try:
                enhanced_log(
                    f"Tentativo mirror: {mirror_url[:50]}...", "DEBUG", "Mixdrop")

                headers = {
                    "User-Agent": self.base_headers["User-Agent"],
                    "Referer": mirror_url
                }

                cookies = {}
                final_page_url = mirror_url
                ua = headers["User-Agent"]
                response = self._http_get(
                    mirror_url, headers=headers, timeout=10)

                if response.status_code != 200:
                    enhanced_log(
                        f"HTTP {response.status_code} per {mirror_url[:50]}", "DEBUG", "Mixdrop")
                    solver_result = self._request_flaresolverr(mirror_url)
                    if not solver_result:
                        continue
                    html = solver_result["html"]
                    final_page_url = solver_result["url"]
                    ua = solver_result["user_agent"]
                    cookies = solver_result["cookies"]
                else:
                    html = response.text
                    final_page_url = response.url
                    cookies.update(response.cookies.get_dict())

                # Check Cloudflare
                if any(
                    marker in html.lower() for marker in [
                        "cf-challenge",
                        "robot",
                        "checking your browser"]):
                    enhanced_log(
                        f"Cloudflare rilevato su {mirror_url[:50]}", "WARNING", "Mixdrop")
                    solver_result = self._request_flaresolverr(mirror_url)
                    if not solver_result:
                        continue
                    html = solver_result["html"]
                    final_page_url = solver_result["url"]
                    ua = solver_result["user_agent"]
                    cookies = solver_result["cookies"]

                # Estrai URL video
                video_url = self._extract_video_url(html, final_page_url)

                if video_url:
                    # Se è un iframe, segui il redirect
                    if "/e/" in video_url or "/emb" in video_url:
                        enhanced_log(
                            f"Iframe trovato, seguo redirect: {video_url[:50]}", "DEBUG", "Mixdrop")
                        try:
                            iframe_headers = {
                                "User-Agent": ua, "Referer": final_page_url}
                            iframe_response = self._http_get(
                                video_url, headers=iframe_headers, timeout=10)
                            if iframe_response.status_code == 200:
                                iframe_html = iframe_response.text
                                video_url = self._extract_video_url(
                                    iframe_html, video_url)
                                cookies.update(
                                    iframe_response.cookies.get_dict())
                            else:
                                solver_result = self._request_flaresolverr(
                                    video_url)
                                if solver_result:
                                    video_url = self._extract_video_url(
                                        solver_result["html"], solver_result["url"])
                                    final_page_url = solver_result["url"]
                                    ua = solver_result["user_agent"]
                                    cookies.update(solver_result["cookies"])
                        except Exception as e:
                            enhanced_log(
                                f"Errore seguendo iframe: {e}", "WARNING", "Mixdrop")

                    if video_url and not video_url.startswith("http"):
                        video_url = urljoin(final_page_url, video_url)

                    if video_url:
                        result = self._build_result(
                            video_url, final_page_url, ua, cookies=cookies)

                        # Salva in cache
                        MixdropExtractor._result_cache[cache_key] = (
                            result, time.time())

                        enhanced_log(
                            f"Video estratto con successo: {video_url[:50]}...", "INFO", "Mixdrop")
                        return result

            except Exception as e:
                last_error = e
                enhanced_log(
                    f"Errore con mirror {mirror_url[:50]}: {e}", "DEBUG", "Mixdrop")
                continue

        if last_error:
            raise MixdropExtractorError(f"Estrazione fallita: {last_error}")
        raise MixdropExtractorError(
            "Video source non trovato in nessun mirror")

    def _build_result(self, video_url, referer, ua, cookies=None):
        """Costruisce risultato con headers"""
        headers = {
            "Referer": referer,
            "User-Agent": ua,
            "Origin": f"https://{urlparse(referer).netloc}"
        }
        if cookies:
            headers["Cookie"] = "; ".join(
                [f"{k}={v}" for k, v in cookies.items()])

        return {
            "resolved_url": video_url,
            "destination_url": video_url,
            "headers": headers,
            "request_headers": headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    def close(self):
        if self.session and not self.session.closed:
            self.session.close()


def is_mixdrop_link(url):
    """Verifica se è un link Mixdrop"""
    if not url:
        return False
    url_lower = url.lower()
    return any(
        domain in url_lower for domain in [
            'mixdrop.co',
            'mixdrop.vip',
            'm1xdrop.net',
            'm1xdrop.bz',
            'mixdrop.ch',
            'mixdrop.ps',
            'mixdrop.ag',
            'mxcontent.net'])


# Factory function per compatibilità
def create_mixdrop_extractor():
    return MixdropExtractor()
