# livetv_extractor.py - LiveTV URL extractor per domini powerset
import re
import json
import requests
import time
from urllib.parse import urlparse, urljoin, unquote, quote
try:
    from ..StreamProxyLog import enhanced_log
except ImportError:
    try:
        from StreamProxyLog import enhanced_log
    except ImportError:
        def enhanced_log(message, level="INFO", component="LIVETV"):
            print("[%s] [%s] %s" % (level, component, message))


class LiveTVExtractorError(Exception):
    """Eccezione personalizzata per errori dell'extractor LiveTV"""
    pass


class LiveTVExtractor:
    """LiveTV URL extractor per domini powerset"""

    def __init__(self, request_headers: dict = None):
        self.base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'}
        if request_headers:
            self.base_headers.update(request_headers)

        self.session = None
        enhanced_log(
            "🚀 [LIVETV] LiveTVExtractor inizializzato",
            "INFO",
            "LIVETV")

        # Pattern per l'estrazione degli stream
        self.fallback_pattern = re.compile(
            r"source: ['\"]([^'\"]+)['\"].*?mimeType: ['\"]([^'\"]+)['\"]",
            re.IGNORECASE | re.DOTALL
        )

        self.any_m3u8_pattern = re.compile(
            r'["\']?(https?://[^"\']+\.m3u8(?:\?[^"\']*)?)["\']?',
            re.IGNORECASE
        )

        enhanced_log(
            "🔍 [LIVETV] Pattern di ricerca configurati",
            "DEBUG",
            "LIVETV")

    def _create_session(self):
        """Crea una nuova sessione HTTP"""
        if self.session:
            try:
                self.session.close()
            except Exception as e:
                enhanced_log(
                    f"Errore chiusura sessione precedente: {e}",
                    "DEBUG",
                    "LIVETV")

        self.session = requests.Session()
        self.session.headers.update(self.base_headers)
        enhanced_log("🔧 [LIVETV] Nuova sessione creata", "DEBUG", "LIVETV")
        return True

    def _make_request(self, url, method="GET", **kwargs):
        """Wrapper per requests ottimizzato per Enigma2"""
        enhanced_log(
            f"🌐 [LIVETV] Richiesta {method}: {url[:100]}...", "INFO", "LIVETV")

        if not self.session and not self._create_session():
            enhanced_log(
                "❌ [LIVETV] Impossibile creare sessione",
                "ERROR",
                "LIVETV")
            raise LiveTVExtractorError("Cannot create session")

        try:
            if method.upper() == "POST":
                response = self.session.post(
                    url,
                    timeout=15,
                    verify=False,
                    **kwargs
                )
            else:
                response = self.session.get(
                    url,
                    timeout=15,
                    verify=False,
                    **kwargs
                )

            enhanced_log(
                f"✅ [LIVETV] Risposta {
                    response.status_code}: {
                    len(
                        response.text) if hasattr(
                        response,
                        'text') else len(
                        response.content)} bytes",
                "INFO",
                "LIVETV")
            return response

        except Exception as e:
            enhanced_log(
                f"❌ [LIVETV] Errore richiesta: {e}",
                "ERROR",
                "LIVETV")
            raise

    async def extract(self, url: str, stream_title: str = None, **kwargs):
        """Extract LiveTV URL and required headers.

        Args:
            url: The channel page URL
            stream_title: Optional stream title to filter specific stream

        Returns:
            Dict[str, str]: Stream URL and required headers
        """
        try:
            enhanced_log(
                f"🚀 [LIVETV] Inizio estrazione: {url[:100]}...", "INFO", "LIVETV")

            # Get the channel page
            response = self._make_request(url)
            self.base_headers["referer"] = urljoin(url, "/")

            # Extract player API details
            player_api_base, method = await self._extract_player_api_base(response.text)
            if not player_api_base:
                raise LiveTVExtractorError("Failed to extract player API URL")

            # Get player options
            options_data = await self._get_player_options(response.text)
            if not options_data:
                raise LiveTVExtractorError("No player options found")

            # Process player options to find matching stream
            for option in options_data:
                current_title = option.get("title")
                if stream_title and current_title != stream_title:
                    continue

                # Get stream URL based on player option
                stream_data = await self._process_player_option(
                    player_api_base, method, option.get("post"), option.get("nume"), option.get("type")
                )

                if stream_data:
                    stream_url = stream_data.get("url")
                    if not stream_url:
                        continue

                    response = {
                        "resolved_url": stream_url,
                        "headers": self.base_headers,
                        "mediaflow_endpoint": "hls_manifest_proxy",
                    }

                    # Set endpoint based on stream type
                    if stream_data.get("type") == "mpd":
                        if stream_data.get(
                                "drm_key_id") and stream_data.get("drm_key"):
                            response.update(
                                {
                                    "query_params": {
                                        "key_id": stream_data["drm_key_id"],
                                        "key": stream_data["drm_key"],
                                    },
                                    "mediaflow_endpoint": "mpd_manifest_proxy",
                                }
                            )

                    enhanced_log(
                        "✅ [LIVETV] Estrazione completata con successo",
                        "INFO",
                        "LIVETV")
                    return response

            raise LiveTVExtractorError("No valid stream found")

        except Exception as e:
            enhanced_log(
                f"❌ [LIVETV] Errore estrazione: {e}",
                "ERROR",
                "LIVETV")
            raise LiveTVExtractorError(f"Extraction failed: {str(e)}")

    async def _extract_player_api_base(self, html_content: str):
        """Extract player API base URL and method."""
        admin_ajax_pattern = r'"player_api"\s*:\s*"([^"]+)".*?"play_method"\s*:\s*"([^"]+)"'
        match = re.search(admin_ajax_pattern, html_content)

        if not match:
            return None, None

        url = match.group(1).replace("\\/", "/")
        method = match.group(2)

        if method == "wp_json":
            return url, method

        url = urljoin(url, "/wp-admin/admin-ajax.php")
        return url, method

    async def _get_player_options(self, html_content: str):
        """Extract player options from HTML content."""
        pattern = r'<li[^>]*class=["\']dooplay_player_option["\'][^>]*data-type=["\']([^"\']*)["\'][^>]*data-post=["\']([^"\']*)["\'][^>]*data-nume=["\']([^"\']*)["\'][^>]*>.*?<span class=["\']title["\']>([^<]*)</span>'
        matches = re.finditer(pattern, html_content, re.DOTALL)

        return [{"type": match.group(1), "post": match.group(2), "nume": match.group(
            3), "title": match.group(4).strip()} for match in matches]

    async def _process_player_option(
            self,
            api_base: str,
            method: str,
            post: str,
            nume: str,
            type_: str):
        """Process player option to get stream URL."""
        if method == "wp_json":
            api_url = f"{api_base}{post}/{type_}/{nume}"
            response = self._make_request(api_url)
        else:
            form_data = {
                "action": "doo_player_ajax",
                "post": post,
                "nume": nume,
                "type": type_}
            response = self._make_request(
                api_base, method="POST", data=form_data)

        # Get iframe URL from API response
        try:
            data = response.json()
            iframe_url = urljoin(
                api_base,
                data.get(
                    "embed_url",
                    "").replace(
                    "\\/",
                    "/"))

            # Get stream URL from iframe
            iframe_response = self._make_request(iframe_url)
            stream_data = await self._extract_stream_url(iframe_response, iframe_url)

            return stream_data

        except Exception as e:
            enhanced_log(
                f"❌ [LIVETV] Errore processamento opzione player: {e}",
                "ERROR",
                "LIVETV")
            raise LiveTVExtractorError(
                f"Failed to process player option: {str(e)}")

    async def _extract_stream_url(self, iframe_response, iframe_url: str):
        """Extract final stream URL from iframe content."""
        try:
            # Parse URL components
            parsed_url = urlparse(iframe_url)
            query_params = dict(
                param.split("=") for param in parsed_url.query.split("&") if "=" in param)

            # Check if content is already a direct M3U8 stream
            content_types = [
                "application/x-mpegurl",
                "application/vnd.apple.mpegurl"]
            if any(ext in iframe_response.headers.get("content-type", "")
                   for ext in content_types):
                return {"url": iframe_url, "type": "m3u8"}

            stream_data = {}

            # Check for source parameter in URL
            if "source" in query_params:
                stream_data = {
                    "url": urljoin(
                        iframe_url,
                        unquote(
                            query_params["source"])),
                    "type": "m3u8",
                }

            # Check for MPD stream with DRM
            elif "zy" in query_params and ".mpd" in query_params["zy"]:
                data = query_params["zy"].split("``")
                url = data[0]
                key_id, key = data[1].split(":")
                stream_data = {
                    "url": url,
                    "type": "mpd",
                    "drm_key_id": key_id,
                    "drm_key": key}

            # Check for tamilultra specific format
            elif "tamilultra" in iframe_url:
                stream_data = {
                    "url": urljoin(
                        iframe_url,
                        parsed_url.query),
                    "type": "m3u8"}

            # Try pattern matching for stream URLs
            else:
                channel_id = query_params.get("id", "")
                stream_url = None
                html_content = iframe_response.text

                if channel_id:
                    # Try channel ID specific pattern
                    pattern = rf'{
                        re.escape(channel_id)}["\']:\s*{{\s*["\']?url["\']?\s*:\s*["\']([^"\']+)["\']'
                    match = re.search(pattern, html_content)
                    if match:
                        stream_url = match.group(1)

                # Try fallback patterns if channel ID pattern fails
                if not stream_url:
                    for pattern in [
                            self.fallback_pattern,
                            self.any_m3u8_pattern]:
                        match = pattern.search(html_content)
                        if match:
                            stream_url = match.group(1)
                            break

                if stream_url:
                    stream_data = {
                        "url": stream_url,
                        "type": "m3u8"}  # Default to m3u8

                    # Check for MPD stream and extract DRM keys
                    if stream_url.endswith(".mpd"):
                        stream_data["type"] = "mpd"
                        drm_data = await self._extract_drm_keys(html_content, channel_id)
                        if drm_data:
                            stream_data.update(drm_data)

            # If no stream data found, raise error
            if not stream_data:
                raise LiveTVExtractorError("No valid stream URL found")

            # Update stream type based on URL if not already set
            if stream_data.get("type") == "m3u8":
                if stream_data["url"].endswith(".mpd"):
                    stream_data["type"] = "mpd"
                elif not any(ext in stream_data["url"] for ext in [".m3u8", ".m3u"]):
                    # Default to m3u8 if no extension found
                    stream_data["type"] = "m3u8"

            return stream_data

        except Exception as e:
            enhanced_log(
                f"❌ [LIVETV] Errore estrazione stream URL: {e}",
                "ERROR",
                "LIVETV")
            raise LiveTVExtractorError(
                f"Failed to extract stream URL: {str(e)}")

    async def _extract_drm_keys(self, html_content: str, channel_id: str):
        """Extract DRM keys for MPD streams."""
        try:
            # Pattern for channel entry
            channel_pattern = rf'"{re.escape(channel_id)}":\s*{{[^}}]+}}'
            channel_match = re.search(channel_pattern, html_content)

            if channel_match:
                channel_data = channel_match.group(0)

                # Try clearkeys pattern first
                clearkey_pattern = r'["\']?clearkeys["\']?\s*:\s*{\s*["\'](.+?)["\']:\s*["\'](.+?)["\']'
                clearkey_match = re.search(clearkey_pattern, channel_data)

                # Try k1/k2 pattern if clearkeys not found
                if not clearkey_match:
                    k1k2_pattern = r'["\']?k1["\']?\s*:\s*["\'](.+?)["\'],\s*["\']?k2["\']?\s*:\s*["\'](.+?)["\']'
                    k1k2_match = re.search(k1k2_pattern, channel_data)
                    if k1k2_match:
                        return {
                            "drm_key_id": k1k2_match.group(1),
                            "drm_key": k1k2_match.group(2)}
                else:
                    return {
                        "drm_key_id": clearkey_match.group(1),
                        "drm_key": clearkey_match.group(2)}

            return {}

        except Exception:
            return {}

    def clear_cache(self, channel_id=None):
        """Metodo per compatibilità - pulisce la sessione"""
        enhanced_log("🧹 [LIVETV] Pulizia cache/sessione", "INFO", "LIVETV")
        if self.session:
            try:
                self.session.close()
            except Exception as e:
                enhanced_log(
                    f"Errore chiusura sessione in clear_cache: {e}",
                    "DEBUG",
                    "LIVETV")
            self.session = None

    def __del__(self):
        """Cleanup automatico"""
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass

# Funzioni di utilità per compatibilità


def is_powerset_domain(url):
    """Rileva se l'URL è un dominio powerset"""
    if not url:
        return False

    try:
        from urllib.parse import urlparse
    except ImportError:
        from urlparse import urlparse

    parsed = urlparse(url)
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0].lstrip("www.")

    powerset_domains = (
        "powerset",
        "powersetlive",
        "powersetstream",
        "livetv",
        "livetvstream",
        "streamlive",
    )

    return any(
        host == domain or host.startswith(
            domain +
            ".") or (
            "." +
            domain +
            ".") in host for domain in powerset_domains)


def process_powerset_url(url, headers=None):
    """Processa URL powerset"""
    enhanced_log(
        f"🎯 [LIVETV] Processamento URL powerset: {url[:50]}...", "INFO", "LIVETV")

    try:
        extractor = LiveTVExtractor(headers)

        # Per ora restituiamo un risultato semplice
        # In futuro qui andrà la logica specifica per powerset
        return {
            "resolved_url": url,  # Passthrough per ora
            "headers": headers or {},
            "mediaflow_endpoint": "hls_manifest_proxy"
        }

    except Exception as e:
        enhanced_log(
            f"❌ [LIVETV] Errore processamento powerset: {e}",
            "ERROR",
            "LIVETV")
        return None


# Istanza globale per compatibilità
livetv_extractor = LiveTVExtractor()

enhanced_log("✅ [LIVETV] LiveTV Extractor caricato e pronto", "INFO", "LIVETV")
