# vix_extractor.py - VixCloud URL extractor per Enigma2
import json
import re
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter

try:
    import urllib3
    from urllib3.util.retry import Retry
    from urllib3.exceptions import InsecureRequestWarning
    urllib3.disable_warnings(InsecureRequestWarning)
except ImportError:
    Retry = None

try:
    from ..StreamProxyLog import enhanced_log
except (ImportError, ValueError):
    try:
        from StreamProxyLog import enhanced_log
    except ImportError:
        def enhanced_log(msg, level="INFO", tag="VIX"):
            print("[{}] [{}] {}".format(level, tag, msg))


class VixCloudExtractor:
    """VixCloud/VixSrc HLS extractor per Enigma2."""

    def __init__(self):
        self.base_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        self.mediaflow_endpoint = "hls_manifest_proxy"
        self.is_vixsrc = True
        self.session = requests.Session()
        self.session.headers.update(self.base_headers)
        self.session.verify = False
        if Retry:
            retry = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET"],
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def extract(self, url):
        """Estrae la master playlist HLS da window.masterPlaylist."""
        enhanced_log("[VIX] START extract kotlin-style: {}...".format(url[:80]), "INFO", "VIX")

        try:
            clean_url = self._normalise_url(url)
            parsed_url = urlparse(clean_url)

            # Compatibilita': se l'URL e' gia' una playlist diretta, non va risolto.
            if "/playlist/" in parsed_url.path:
                enhanced_log("[VIX] URL gia' risolto - passthrough diretto", "INFO", "VIX")
                return {
                    "resolved_url": clean_url,
                    "destination_url": clean_url,
                    "headers": self._fresh_headers(),
                    "request_headers": self._fresh_headers(),
                    "mediaflow_endpoint": self.mediaflow_endpoint,
                }

            response = self._resolve_to_embed_response(clean_url, parsed_url)
            if not response:
                return None

            html = response.text
            enhanced_log("[VIX] Contenuto pagina: {} caratteri".format(len(html)), "DEBUG", "VIX")

            script = self._find_playlist_script(html)
            if not script:
                enhanced_log("[VIX] Nessuno script playlist trovato", "WARNING", "VIX")
                return None

            final_url = self._extract_playlist_from_embed(script)
            if not final_url:
                enhanced_log("[VIX] Parametri playlist mancanti o incompleti", "WARNING", "VIX")
                return None

            enhanced_log("[VIX] SUCCESS kotlin exact: {}...".format(final_url[:120]), "INFO", "VIX")
            return {
                "resolved_url": final_url,
                "destination_url": final_url,
                "headers": self._fresh_headers(Referer=clean_url),
                "request_headers": self._fresh_headers(Referer=clean_url),
                "mediaflow_endpoint": self.mediaflow_endpoint,
            }

        except Exception as e:
            enhanced_log("[VIX] VixCloud extraction error: {}".format(e), "ERROR", "VIX")
            return None

    def _normalise_url(self, url):
        if url.startswith("http"):
            return url
        return "https://" + re.sub(r"^//", "", url)

    def _fresh_headers(self, **extra_headers):
        headers = self.base_headers.copy()
        headers.update(extra_headers)
        return headers

    def _normalise_base_site(self, url):
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return "{}://{}".format(parsed.scheme, parsed.netloc)

    def _request(self, url, headers=None, timeout=8, retries=3, initial_delay=2):
        final_headers = headers or self._fresh_headers()
        last_error = None

        for attempt in range(retries):
            try:
                enhanced_log(
                    "[VIX] GET tentativo {}/{} {}...".format(attempt + 1, retries, url[:120]),
                    "DEBUG",
                    "VIX",
                )
                response = self.session.get(
                    url,
                    headers=final_headers,
                    timeout=timeout,
                    verify=False,
                )
                if response.status_code == 200:
                    return response

                last_error = "HTTP {}".format(response.status_code)
                enhanced_log(
                    "[VIX] Errore HTTP {} su {}".format(response.status_code, url[:80]),
                    "WARNING",
                    "VIX",
                )
                if response.status_code == 404:
                    return None

            except Exception as e:
                last_error = e
                enhanced_log(
                    "[VIX] Errore connessione tentativo {} su {}: {}".format(attempt + 1, url[:80], e),
                    "WARNING",
                    "VIX",
                )

            if attempt < retries - 1:
                time.sleep(initial_delay * (2 ** attempt))

        enhanced_log("[VIX] Richiesta fallita: {}".format(last_error), "ERROR", "VIX")
        return None

    def _raise_if_embed_expired(self, url):
        parsed = urlparse(url)
        if "/embed/" not in parsed.path:
            return
        expires = parse_qs(parsed.query).get("expires", [None])[0]
        if not expires:
            return
        try:
            expires_ts = int(expires)
        except (TypeError, ValueError):
            return
        now_ts = int(time.time())
        if expires_ts <= now_ts:
            raise ValueError(
                "Expired VixSrc embed URL (expired at {}, current {}). "
                "Use original /movie/ or /tv/ URL to refresh tokens.".format(expires_ts, now_ts)
            )

    def _resolve_to_embed_response(self, url, parsed_url):
        if "/embed/" in parsed_url.path:
            self._raise_if_embed_expired(url)
            site_url = self._normalise_base_site(url)
            return self._request(url, headers=self._fresh_headers(Referer=(site_url or "") + "/"))

        if "iframe" in url:
            site_url = url.split("/iframe")[0]
            version = self._version(site_url)
            inertia_headers = self._fresh_headers(**{"x-inertia": "true", "x-inertia-version": version})
            response = self._request(url, headers=inertia_headers)
            if not response:
                return None
            iframe_src = self._find_iframe_src(response.text)
            if not iframe_src:
                enhanced_log("[VIX] Nessun iframe trovato nella risposta", "WARNING", "VIX")
                return None
            return self._request(urljoin(site_url + "/", iframe_src), headers=inertia_headers)

        if "/movie/" in parsed_url.path or "/tv/" in parsed_url.path:
            embed_url = self._resolve_embed_url_from_api(url, parsed_url)
            if embed_url:
                return self._request(embed_url, headers=self._fresh_headers(Referer=url))
            return self._request(url)

        return self._request(url)

    def _resolve_embed_url_from_api(self, url, parsed):
        site_url = self._normalise_base_site(url)
        if not site_url:
            return None

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        api_url = None
        if len(path_parts) >= 2 and path_parts[0] == "movie":
            api_url = "{}/api/movie/{}".format(site_url, path_parts[1])
        elif len(path_parts) >= 4 and path_parts[0] == "tv":
            api_url = "{}/api/tv/{}/{}/{}".format(site_url, path_parts[1], path_parts[2], path_parts[3])

        if not api_url:
            return None

        response = self._request(
            api_url,
            headers=self._fresh_headers(Accept="application/json, text/plain, */*", Referer=url),
        )
        if not response:
            return None

        try:
            payload = json.loads(response.text)
        except ValueError as e:
            enhanced_log("[VIX] Risposta API non JSON: {}".format(e), "WARNING", "VIX")
            return None

        embed_path = payload.get("src")
        if not embed_path:
            enhanced_log("[VIX] API senza campo src", "WARNING", "VIX")
            return None
        return urljoin(site_url, embed_path)

    def _version(self, site_url):
        response = self._request(
            "{}/request-a-title".format(site_url),
            headers=self._fresh_headers(Referer=site_url + "/", Origin=site_url),
        )
        if not response:
            raise ValueError("Obsolete URL")

        data_page = self._find_app_data_page(response.text)
        if not data_page:
            raise ValueError("Unable to find version data")

        try:
            data = json.loads(data_page.replace("&quot;", '"'))
            return data["version"]
        except (KeyError, ValueError, AttributeError) as e:
            raise ValueError("Version parsing failure: {}".format(e))

    def _find_app_data_page(self, html):
        match = re.search(r'<div[^>]*id="app"[^>]*data-page="([^"]*)"[^>]*>', html, re.IGNORECASE)
        return match.group(1) if match else None

    def _find_iframe_src(self, html):
        match = re.search(r'<iframe[^>]*src="([^"]*)"[^>]*>', html, re.IGNORECASE)
        return match.group(1) if match else None

    def _find_playlist_script(self, html):
        scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.IGNORECASE | re.DOTALL)
        for script in scripts:
            if "window.masterPlaylist" in script or "'token':" in script or '"token":' in script:
                return script
        match = re.search(r"<body[^>]*>.*?<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _extract_playlist_from_embed(self, script):
        final_url = self._build_from_master_playlist_regex(script)
        if final_url:
            return final_url

        parsed = self._rebuild_window_assignments_to_json_kotlin_style(script)
        if parsed:
            final_url = self._build_from_master_playlist_object(parsed, script)
            if final_url:
                return final_url

        enhanced_log("[VIX] Uso fallback legacy token/expires/url", "DEBUG", "VIX")
        return self._build_from_legacy_script(script)

    def _build_from_master_playlist_regex(self, script):
        """Parsing primario allineato al source EasyProxy aggiornato."""
        master_playlist_match = re.search(
            r"window\.masterPlaylist\s*=\s*\{.*?params\s*:\s*\{(?P<params>.*?)\}\s*,\s*url\s*:\s*['\"](?P<url>[^'\"]+)['\"]",
            script,
            re.DOTALL,
        )
        if not master_playlist_match:
            return None

        params_block = master_playlist_match.group("params")
        playlist_url = master_playlist_match.group("url").replace("\\/", "/")

        token_match = re.search(r"['\"]token['\"]\s*:\s*['\"]([^'\"]+)['\"]", params_block)
        expires_match = re.search(r"['\"]expires['\"]\s*:\s*['\"](\d+)['\"]", params_block)
        asn_match = re.search(r"['\"]asn['\"]\s*:\s*['\"]([^'\"]*)['\"]", params_block)

        if not token_match or not expires_match:
            return None

        final_url = self._append_playlist_query(
            playlist_url,
            token=token_match.group(1),
            expires=expires_match.group(1),
            can_play_fhd=("window.canPlayFHD = true" in script or "canPlayFHD" in script),
            asn=asn_match.group(1) if asn_match and asn_match.group(1) else None,
        )
        return final_url

    def _rebuild_window_assignments_to_json_kotlin_style(self, script):
        raw_script = script.replace("\n", "\t")
        key_regex = re.compile(r"window\.(\w+)\s*=\s*")
        keys = [match.group(1) for match in key_regex.finditer(raw_script)]
        parts = re.split(r"window\.(?:\w+)\s*=\s*", raw_script)[1:]

        if not keys or len(keys) != len(parts):
            enhanced_log(
                "[VIX] Key/parts mismatch: keys={} parts={}".format(len(keys), len(parts)),
                "WARNING",
                "VIX",
            )
            return None

        json_objects = []
        for key, part in zip(keys, parts):
            cleaned = part.strip()
            cleaned = re.sub(r";\s*$", "", cleaned)
            cleaned = cleaned.replace(";", "")
            cleaned = re.sub(r"(\{|\[|,)\s*(\w+)\s*:", r'\1 "\2":', cleaned)
            cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned).strip()
            json_objects.append('"{}": {}'.format(key, cleaned))

        aggregated = "{\n" + ",\n".join(json_objects) + "\n}"
        aggregated = aggregated.replace("'", '"').replace("\\/", "/")

        try:
            return json.loads(aggregated)
        except Exception as e:
            enhanced_log(
                "[VIX] JSON parse fail: {}; payload={}".format(e, aggregated[:160]),
                "WARNING",
                "VIX",
            )
            return None

    def _build_from_master_playlist_object(self, parsed, script=None):
        master_playlist = parsed.get("masterPlaylist") if isinstance(parsed, dict) else None
        if not isinstance(master_playlist, dict):
            return None

        base_url = master_playlist.get("url") or ""
        if not base_url:
            return None

        params = master_playlist.get("params") or {}
        token = params.get("token")
        expires = params.get("expires")
        if token is None or expires is None:
            return None

        asn = params.get("asn")
        final_url = self._append_playlist_query(
            base_url,
            token=token,
            expires=expires,
            can_play_fhd=parsed.get("canPlayFHD") is True or (script and "canPlayFHD" in script),
            asn=asn,
        )

        return final_url

    def _build_from_legacy_script(self, script):
        token_match = re.search(r"['\"]token['\"]\s*:\s*['\"]([^'\"]+)['\"]", script)
        expires_match = re.search(r"['\"]expires['\"]\s*:\s*['\"](\d+)['\"]", script)
        server_url_match = re.search(r"url\s*:\s*['\"]([^'\"]+)['\"]", script)

        if not all([token_match, expires_match, server_url_match]):
            token_match = token_match or re.search(r"token['\"]\s*:\s*['\"]([^'\"]+)['\"]", script)
            expires_match = expires_match or re.search(r"expires['\"]\s*:\s*['\"](\d+)['\"]", script)

        if not all([token_match, expires_match, server_url_match]):
            return None

        asn_match = re.search(r"['\"]asn['\"]\s*:\s*['\"]([^'\"]*)['\"]", script)
        asn = asn_match.group(1) if asn_match and asn_match.group(1) else None
        final_url = self._append_playlist_query(
            server_url_match.group(1),
            token=token_match.group(1),
            expires=expires_match.group(1),
            can_play_fhd=("window.canPlayFHD = true" in script or "canPlayFHD" in script),
            asn=asn,
        )
        return final_url

    def _append_playlist_query(self, base_url, token, expires, can_play_fhd=False, asn=None):
        base_url = (base_url or "").replace("\\/", "/").replace("?b:1", "?b=1")
        parsed_url = urlparse(base_url)
        query_params = parse_qsl(parsed_url.query, keep_blank_values=True)
        query_params.extend([
            ("token", str(token)),
            ("expires", str(expires)),
        ])

        if can_play_fhd:
            query_params.append(("h", "1"))

        query_params.append(("lang", "it"))
        if asn:
            query_params.append(("asn", str(asn)))

        return urlunparse(parsed_url._replace(query=urlencode(query_params)))

    def _ensure_m3u8_suffix(self, final_url):
        before_query = final_url.split("?", 1)[0]
        if not re.search(r"\.m3u8$", before_query, re.IGNORECASE):
            query = final_url.split("?", 1)[1] if "?" in final_url else ""
            final_url = before_query.rstrip("/") + ".m3u8"
            if query:
                final_url += "?" + query

        return final_url

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


# Istanza globale
vix_extractor = VixCloudExtractor()
