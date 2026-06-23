# maxstream_extractor.py - Maxstream Extractor per Enigma2
# Compatibile con Python 3 e decoder Enigma2

import re
import time
import random
import base64
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
        def enhanced_log(msg, level="INFO", tag="Maxstream"):
            print(f"[{level}] [{tag}] {msg}")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    enhanced_log(
        "BeautifulSoup non disponibile, parsing HTML limitato",
        "WARNING",
        "Maxstream")


class MaxstreamExtractorError(Exception):
    """Eccezione specifica per errori Maxstream"""
    pass


class MaxstreamExtractor:
    """
    Maxstream Extractor per Enigma2
    Estrae URL stream da uprot.net e maxstream.video
    """

    def __init__(self, request_headers=None):
        enhanced_log(
            "Inizializzazione MaxstreamExtractor per Enigma2",
            "INFO",
            "Maxstream")

        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36']

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
            enhanced_log("Sessione HTTP configurata", "DEBUG", "Maxstream")
        else:
            self.session = None
            enhanced_log(
                "Modulo requests non disponibile",
                "WARNING",
                "Maxstream")

        self.mediaflow_endpoint = "hls_proxy"

    def _http_request(self, method, url, headers=None, timeout=8, **kwargs):
        """Richiesta HTTP sincrona con retry leggero"""
        if not self.session:
            raise MaxstreamExtractorError("Sessione HTTP non disponibile")

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
                    f"HTTP {response.status_code}, retry: {url[:90]}", "DEBUG", "Maxstream")
                last_error = MaxstreamExtractorError(
                    f"HTTP {response.status_code}")
                time.sleep(0.3)
            except Exception as exc:
                last_error = exc
                enhanced_log(
                    f"Errore {method} {url[:90]}: {exc}", "DEBUG", "Maxstream")
                if attempt:
                    break
                time.sleep(0.3)

        if last_error:
            raise last_error
        raise MaxstreamExtractorError("Richiesta HTTP fallita")

    def _http_get(self, url, headers=None, timeout=8, **kwargs):
        return self._http_request(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            **kwargs)

    def _parse_uprot_html(self, text):
        """Parse uprot HTML per estrarre link redirect"""
        # 1. Link diretti
        match = re.search(
            r'https?://(?:www\.)?(?:stayonline\.pro|maxstream\.video)[^"\'\s<>\\ ]+',
            text.replace(
                "\\/",
                "/"))
        if match:
            return match.group(0)

        # 2. JavaScript redirects
        js_match = re.search(
            r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', text)
        if js_match:
            return js_match.group(1)

        # 3. Meta refresh
        meta_match = re.search(
            r'content=["\']0;\s*url=([^"\']+)["\']', text, re.I)
        if meta_match:
            return meta_match.group(1)

        # 4. BeautifulSoup parsing
        if BS4_AVAILABLE:
            soup = BeautifulSoup(text, "html.parser")

            # Cerca bottoni/link con testo "Continue"
            for btn in soup.find_all(["a", "button"]):
                text_content = btn.get_text().strip().lower()
                if any(
                    word in text_content for word in [
                        "continue",
                        "continua",
                        "vai al"]):
                    href = btn.get("href")
                    if not href and btn.parent.name == "a":
                        href = btn.parent.get("href")

                    if href and "uprot" not in href:
                        return href

            # Selettori specifici Bulma
            for selector in [
                'a[href*="maxstream"]',
                'a[href*="stayonline"]',
                '.button.is-info',
                '.button.is-success',
                    'a.button']:
                tag = soup.select_one(selector)
                if tag and tag.get("href") and "uprot" not in tag["href"]:
                    return tag["href"]

            # Form action
            form = soup.find("form")
            if form and form.get("action") and "uprot" not in form["action"]:
                return form["action"]

        return None

    def _parse_uprot_folder(self, text, season, episode):
        """Parse folder HTML per trovare episodio specifico"""
        try:
            s_int = int(season)
            e_int = int(episode)
        except (TypeError, ValueError):
            return None

        s_pad = f"{s_int:02d}"
        e_pad = f"{e_int:02d}"

        patterns = [
            rf"S{s_pad}E{e_pad}",
            rf"\b0*{s_int}x0*{e_int}\b",
            rf"\b0*{s_int}&#215;0*{e_int}\b",
            rf"\b0*{s_int}×0*{e_int}\b",
        ]

        for pat in patterns:
            m = re.search(
                rf"{pat}[\s\S]{{0,500}}?href=['\"]([^'\"]+/msfi/[^'\"]+)['\"]",
                text,
                re.I,
            )
            if m:
                return m.group(1)
        return None

    def get_uprot(self, link, season=None, episode=None):
        """Estrae URL Maxstream da uprot redirect"""
        # Converti /msf/ in /mse/ (legacy alias)
        link = re.sub(r"/msf/", "/mse/", link)

        enhanced_log(f"Richiesta uprot: {link[:80]}...", "INFO", "Maxstream")
        text = self._http_get(link).text

        # Se è folder, risolvi episodio
        if "/msfld/" in link:
            if season is None or episode is None:
                raise MaxstreamExtractorError(
                    "msfld richiede parametri season e episode")

            episode_link = self._parse_uprot_folder(text, season, episode)
            if not episode_link:
                raise MaxstreamExtractorError(
                    f"Episodio S{season}E{episode} non trovato")

            link = episode_link
            text = self._http_get(link).text

        # Parse HTML
        res = self._parse_uprot_html(text)
        if res:
            return res

        # Check Cloudflare
        if any(
            marker in text.lower() for marker in [
                "cf-challenge",
                "ray id",
                "checking your browser"]):
            raise MaxstreamExtractorError("Cloudflare block rilevato")

        enhanced_log(
            f"Parse fallito. Content: {text[:500]}...", "ERROR", "Maxstream")
        raise MaxstreamExtractorError("Link redirect non trovato")

    def extract(self, url, **kwargs):
        """Estrae URL Maxstream"""
        season = kwargs.get("season")
        episode = kwargs.get("episode")

        maxstream_url = self.get_uprot(url, season=season, episode=episode)
        enhanced_log(f"Target URL: {maxstream_url}", "DEBUG", "Maxstream")

        headers = {
            **self.base_headers,
            "referer": "https://uprot.net/",
            "accept-language": "en-US,en;q=0.5"
        }

        text = self._http_get(maxstream_url, headers=headers).text

        # Check direct sources
        direct_match = re.search(r'sources:\s*\[\{src:\s*"([^"]+)"', text)
        if direct_match:
            return {
                "resolved_url": direct_match.group(1),
                "headers": {**self.base_headers, "referer": maxstream_url},
                "mediaflow_endpoint": self.mediaflow_endpoint,
            }

        # Packer logic
        match = re.search(r"\}\'(.+)',.+,'(.+)'\.split", text)
        if not match:
            match = re.search(
                r"eval\(function\(p,a,c,k,e,d\).+?\}\('(.+?)',.+?,'(.+?)'\.split", text, re.S)

        if not match:
            enhanced_log(
                f"Packer non trovato in: {text[:500]}...", "ERROR", "Maxstream")
            raise MaxstreamExtractorError(
                "Impossibile estrarre componenti URL")

        s1 = match.group(2)
        terms = s1.split("|")

        try:
            urlset_index = terms.index("urlset")
            hls_index = terms.index("hls")
            sources_index = terms.index("sources")
        except ValueError as e:
            enhanced_log(
                f"Termini mancanti nel packer: {e}",
                "ERROR",
                "Maxstream")
            raise MaxstreamExtractorError(f"Componenti mancanti: {e}")

        result = terms[urlset_index + 1: hls_index]
        reversed_elements = result[::-1]
        first_part_terms = terms[hls_index + 1: sources_index]
        reversed_first_part = first_part_terms[::-1]

        first_url_part = ""
        for fp in reversed_first_part:
            if "0" in fp:
                first_url_part += fp
            else:
                first_url_part += fp + "-"

        base_url = f"https://{first_url_part.rstrip('-')}.host-cdn.net/hls/"

        if len(reversed_elements) == 1:
            final_url = base_url + "," + \
                reversed_elements[0] + ".urlset/master.m3u8"
        else:
            final_url = base_url
            for element in reversed_elements:
                final_url += element + ","
            final_url = final_url.rstrip(",") + ".urlset/master.m3u8"

        self.base_headers["referer"] = url
        return {
            "resolved_url": final_url,
            "headers": self.base_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    def close(self):
        if self.session and not self.session.closed:
            self.session.close()


def is_maxstream_link(url):
    """Verifica se è un link Maxstream/Uprot"""
    if not url:
        return False
    url_lower = url.lower()
    return any(
        domain in url_lower for domain in [
            'uprot.net',
            'maxstream.video',
            'stayonline.pro'])


# Factory function per compatibilità
def create_maxstream_extractor():
    return MaxstreamExtractor()
