# dlhd_extractor.py - DLHD Extractor per Enigma2 basato su EasyProxy
# Riscritto completamente seguendo il processo del sorgente originale

import re
import json
import base64
import os
import time
import random
import string
import threading
import importlib.util
from urllib.parse import urlparse, urljoin
from typing import Dict, Any, Optional, List

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

DLSTREAMS_ENTRY_ORIGIN = "https://dlhd.dad"
DLHD_EXTRACTOR_PATCH_VERSION = "2026-04-26-enigma2-dlhd-verify-payload-v10"


def _load_local_module(module_name, relative_path):
    module_path = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__))),
        relative_path)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if not spec or not spec.loader:
        raise ImportError("Impossibile caricare {}".format(relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Import utilities: caricate da file per evitare conflitto con utils.py
# nella root.
try:
    packed_module = _load_local_module(
        "streamproxy_utils_packed", os.path.join(
            "utils", "packed.py"))
    drm_module = _load_local_module(
        "streamproxy_utils_drm_handler", os.path.join(
            "utils", "drm_handler.py"))
    detect = packed_module.detect
    unpack = packed_module.unpack
    UnpackingError = packed_module.UnpackingError
    DRMHandler = drm_module.DRMHandler
except ImportError:
    # Fallback se utils non disponibili sul decoder.
    def detect(source): return False
    def unpack(source): return source

    class UnpackingError(Exception):
        pass

    class DRMHandler:
        def __init__(self): pass
        def has_crypto(self): return False

# Import enhanced_log per integrazione con StreamProxy
try:
    from ..StreamProxyLog import enhanced_log
except (ImportError, ValueError):
    try:
        from StreamProxyLog import enhanced_log
    except ImportError:
        def enhanced_log(msg, level="INFO", tag="DLHD"):
            print(f"[{level}] [{tag}] {msg}")


class DLHDExtractorError(Exception):
    """Eccezione specifica per errori DLHD"""
    pass


class DLHDExtractor:
    """
    DLHD Extractor per Enigma2 - Riscritto seguendo EasyProxy

    PROCESSO COMPLETO:
    1. Carica configurazione dinamica da worker remoto
    2. Estrae parametri auth dall'iframe
    3. Esegue POST auth con parametri estratti
    4. Effettua server lookup per ottenere server_key
    5. Invia heartbeat per stabilire sessione
    6. Costruisce URL stream finale con template dinamici
    7. Gestisce cache con validazione TTL
    """

    def __init__(self, request_headers=None):
        enhanced_log(
            f"[INIT] Inizializzazione DLHDExtractor per Enigma2 ({DLHD_EXTRACTOR_PATCH_VERSION})",
            "INFO",
            "DLHD")

        # Headers base anti-bot
        self.user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
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

        # Carica configurazione proxy
        self.proxies = self._load_proxy_config()

        # Sessione HTTP persistente
        if REQUESTS_AVAILABLE:
            self.session = requests.Session()

            # Retry strategy compatibile anche con urllib3 vecchi dei firmware
            # Enigma2.
            retry_kwargs = dict(
                total=0,
                connect=0,
                read=0,
                backoff_factor=1,
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
                pool_connections=5,
                pool_maxsize=10)
            self.session.mount('http://', adapter)
            self.session.mount('https://', adapter)
            self.session.headers.update(self.base_headers)
            self.session.verify = False

            enhanced_log("[INIT] Sessione HTTP configurata", "DEBUG", "DLHD")
        else:
            self.session = None
            enhanced_log(
                "[INIT] Modulo requests non disponibile",
                "WARNING",
                "DLHD")

        # Cache e configurazione
        self.cache_file = '/tmp/.dlhd_cache_enigma2' if os.path.exists(
            '/tmp') else '.dlhd_cache_enigma2'
        cache_data = self._load_cache()

        # Stream cache
        self._stream_cache = cache_data.get('streams', {})

        # Lista iframe hosts (caricata da cache o fallback)
        self.iframe_hosts = cache_data.get('hosts', [])

        # Configurazione server dinamica dal worker (TEMPLATE completi come
        # EasyProxy)
        self.auth_url = cache_data.get(
            'auth_url', 'https://security.kiko2.ru/auth2.php')
        self.stream_cdn_template = cache_data.get(
            'stream_cdn_template',
            'https://top1.kiko2.ru/top1/cdn/{CHANNEL}/mono.css')
        self.stream_other_template = cache_data.get(
            'stream_other_template',
            'https://{SERVER_KEY}new.kiko2.ru/{SERVER_KEY}/{CHANNEL}/mono.css')
        self.heartbeat_url = cache_data.get(
            'heartbeat_url', 'https://chevy.kiko2.ru/heartbeat')
        self.server_lookup_url = cache_data.get(
            'server_lookup_url', 'https://chevy.kiko2.ru/server_lookup')
        self.base_domain = cache_data.get('base_domain', 'kiko2.ru')

        # Nuovo processo DLStreams: entry origin stabile, stream origin scoperto runtime.
        # Su Enigma2 non usiamo Playwright/aiohttp, ma manteniamo la stessa
        # logica URL/header.
        self.entry_origin = DLSTREAMS_ENTRY_ORIGIN
        self.stream_origin = cache_data.get('stream_origin', self.entry_origin)
        self.mediaflow_endpoint = "hls_manifest_proxy"
        self._manifest_cache = {}
        self._last_working_player = cache_data.get('last_working_player', {})
        self._captured_cookies = []

        # Host fallback noti funzionanti
        self.fallback_hosts = [
            'tigertestxtg.sbs',
            'epicplayplay.cfd',
            'iframe.kiko2.ru',
            'iframe2.kiko2.ru',
            'iframe3.kiko2.ru'
        ]

        # Inizializza hosts se vuoti
        if not self.iframe_hosts:
            enhanced_log(
                "[INIT] Lista host vuota, carico fallback",
                "INFO",
                "DLHD")
            self.iframe_hosts = self.fallback_hosts.copy()
        else:
            for fallback_host in reversed(self.fallback_hosts):
                if fallback_host not in self.iframe_hosts:
                    self.iframe_hosts.insert(0, fallback_host)

        # DRM handler
        self.drm_handler = DRMHandler()

        # Lock per thread safety
        self._extraction_locks = {}
        self._config_refreshed = False

        # Statistiche
        self.stats = {
            'requests': 0,
            'cache_hits': 0,
            'auth_failures': 0,
            'successful_extractions': 0
        }

        enhanced_log(
            f"[INIT] Cache caricata: {
                len(
                    self._stream_cache)} streams, {
                len(
                    self.iframe_hosts)} hosts",
            "INFO",
            "DLHD")
        enhanced_log(f"[INIT] Auth URL: {self.auth_url}", "DEBUG", "DLHD")
        enhanced_log(
            f"[INIT] Base Domain: {
                self.base_domain}",
            "DEBUG",
            "DLHD")

    def _load_proxy_config(self):
        """Carica configurazione proxy da SPconfig.txt"""
        try:
            config_paths = [
                '/usr/lib/enigma2/python/Plugins/Extensions/StreamProxy/SPconfig.txt',
                'SPconfig.txt',
                '/tmp/SPconfig.txt']
            for path in config_paths:
                if os.path.exists(path):
                    enhanced_log(
                        f"[PROXY] File config trovato: {path}", "DEBUG", "DLHD")
                    with open(path, 'r') as f:
                        config = json.load(f)
                        daddy_proxy = config.get(
                            'DADDY_PROXY') or config.get('PROXY')
                        if daddy_proxy:
                            enhanced_log(
                                "[PROXY] Proxy configurato", "INFO", "DLHD")
                            proxy_url = f'http://{daddy_proxy}' if not daddy_proxy.startswith(
                                'http') else daddy_proxy
                            return {
                                'http': proxy_url,
                                'https': proxy_url
                            }
        except Exception as e:
            enhanced_log(f"[PROXY] Errore caricamento: {e}", "ERROR", "DLHD")
        return None

    def _http_request(self, method, url, headers=None, timeout=8, **kwargs):
        """Richiesta HTTP sincrona con retry leggero, pensata per Enigma2."""
        if not self.session:
            raise DLHDExtractorError("Sessione HTTP non disponibile")

        request_headers = dict(self.base_headers)
        if headers:
            request_headers.update(headers)

        kwargs.setdefault("allow_redirects", True)
        if self.proxies and "proxies" not in kwargs:
            kwargs["proxies"] = self.proxies
        kwargs.setdefault("verify", False)

        last_error = None
        for attempt in range(2):
            try:
                if attempt:
                    request_headers["User-Agent"] = random.choice(
                        self.user_agents)
                    request_headers["Cache-Control"] = "no-cache"
                    request_headers["Pragma"] = "no-cache"

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
                    f"[HTTP] HTTP {response.status_code}, retry: {url[:90]}", "DEBUG", "DLHD")
                last_error = DLHDExtractorError(f"HTTP {response.status_code}")
                time.sleep(0.25)
            except Exception as exc:
                last_error = exc
                enhanced_log(
                    f"[HTTP] Errore {method} {url[:90]}: {exc}", "DEBUG", "DLHD")
                if attempt:
                    break
                time.sleep(0.25)

        if last_error:
            raise last_error
        raise DLHDExtractorError("Richiesta HTTP fallita")

    def _http_get(self, url, headers=None, timeout=8, **kwargs):
        return self._http_request(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            **kwargs)

    def _http_post(self, url, headers=None, timeout=8, **kwargs):
        return self._http_request(
            "POST",
            url,
            headers=headers,
            timeout=timeout,
            **kwargs)

    def _load_cache(self):
        """Carica cache da file Base64 (come EasyProxy)"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    encoded_data = f.read()
                    if not encoded_data:
                        return {'hosts': [], 'streams': {}}

                    try:
                        decoded_data = base64.b64decode(
                            encoded_data).decode('utf-8')
                        data = json.loads(decoded_data)

                        # Pulizia cache vecchia (> 24h)
                        current_time = time.time()
                        if 'streams' in data:
                            old_keys = []
                            for k, v in data['streams'].items():
                                if isinstance(v, dict) and 'timestamp' in v:
                                    if current_time - \
                                            v['timestamp'] > 86400:  # 24h
                                        old_keys.append(k)
                            for k in old_keys:
                                del data['streams'][k]

                        return data
                    except Exception:
                        return {'hosts': [], 'streams': {}}
        except Exception as e:
            enhanced_log(f"[CACHE] Errore caricamento: {e}", "ERROR", "DLHD")
        return {'hosts': [], 'streams': {}}

    def _save_cache(self):
        """Salva cache su file Base64 (come EasyProxy)"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                cache_data = {
                    'hosts': self.iframe_hosts,
                    'streams': self._stream_cache,
                    'auth_url': self.auth_url,
                    'stream_cdn_template': self.stream_cdn_template,
                    'stream_other_template': self.stream_other_template,
                    'heartbeat_url': self.heartbeat_url,
                    'server_lookup_url': self.server_lookup_url,
                    'base_domain': self.base_domain,
                    'stream_origin': getattr(
                        self,
                        'stream_origin',
                        DLSTREAMS_ENTRY_ORIGIN),
                    'last_working_player': getattr(
                        self,
                        '_last_working_player',
                        {}),
                    'timestamp': time.time()}
                json_data = json.dumps(cache_data)
                encoded_data = base64.b64encode(
                    json_data.encode('utf-8')).decode('utf-8')
                f.write(encoded_data)
        except Exception as e:
            enhanced_log(f"[CACHE] Errore salvataggio: {e}", "ERROR", "DLHD")

    def _fetch_iframe_hosts(self):
        """Scarica lista aggiornata degli host iframe (come EasyProxy)"""
        # URL offuscato per evitare scraping statico
        encoded_url = "aHR0cHM6Ly9pZnJhbWUuZGxoZC5kcGRucy5vcmcv"
        url = base64.b64decode(encoded_url).decode('utf-8')

        enhanced_log(
            "[HOSTS] Aggiornamento lista iframe hosts",
            "INFO",
            "DLHD")

        try:
            resp = self._http_get(url, timeout=3)
            if resp.status_code == 200:
                text = resp.text

                # Validazione contenuto
                if len(text) < 50 or 'error' in text.lower():
                    enhanced_log(
                        "[HOSTS] Contenuto sospetto", "WARNING", "DLHD")
                    return False

                lines = [line.strip()
                         for line in text.splitlines() if line.strip()]
                new_hosts = []

                # Parsing con supporto per configurazione completa (come
                # EasyProxy)
                for line in lines:
                    if line.startswith('#AUTH_URL:'):
                        self.auth_url = line.replace('#AUTH_URL:', '').strip()
                        enhanced_log(
                            "[HOSTS] Auth URL aggiornato", "INFO", "DLHD")
                    elif line.startswith('#STREAM_CDN_TEMPLATE:'):
                        self.stream_cdn_template = line.replace(
                            '#STREAM_CDN_TEMPLATE:', '').strip()
                        enhanced_log(
                            "[HOSTS] Stream CDN Template aggiornato", "INFO", "DLHD")
                    elif line.startswith('#STREAM_OTHER_TEMPLATE:'):
                        self.stream_other_template = line.replace(
                            '#STREAM_OTHER_TEMPLATE:', '').strip()
                        enhanced_log(
                            "[HOSTS] Stream Other Template aggiornato", "INFO", "DLHD")
                    elif line.startswith('#HEARTBEAT_URL:'):
                        self.heartbeat_url = line.replace(
                            '#HEARTBEAT_URL:', '').strip()
                        enhanced_log(
                            "[HOSTS] Heartbeat URL aggiornato", "INFO", "DLHD")
                    elif line.startswith('#SERVER_LOOKUP_URL:'):
                        self.server_lookup_url = line.replace(
                            '#SERVER_LOOKUP_URL:', '').strip()
                        enhanced_log(
                            "[HOSTS] Server Lookup URL aggiornato", "INFO", "DLHD")
                    elif line.startswith('#BASE_DOMAIN:'):
                        self.base_domain = line.replace(
                            '#BASE_DOMAIN:', '').strip()
                        enhanced_log(
                            "[HOSTS] Base Domain aggiornato", "INFO", "DLHD")
                    elif not line.startswith('#'):
                        clean_host = line.strip()
                        if self._validate_host(clean_host):
                            new_hosts.append(clean_host)

                if new_hosts:
                    self.iframe_hosts = new_hosts
                    enhanced_log(
                        f"[HOSTS] Lista aggiornata: {len(self.iframe_hosts)} hosts", "INFO", "DLHD")
                    self._save_cache()
                    return True
                else:
                    enhanced_log(
                        "[HOSTS] Nessun host valido trovato",
                        "WARNING",
                        "DLHD")
            else:
                enhanced_log(
                    f"[HOSTS] HTTP {
                        resp.status_code}",
                    "ERROR",
                    "DLHD")

        except Exception as e:
            enhanced_log(f"[HOSTS] Errore: {e}", "ERROR", "DLHD")

        return False

    def _validate_host(self, host):
        """Valida un host iframe"""
        if not host or len(host) < 5:
            return False
        if '.' not in host:
            return False
        if any(char in host for char in [' ', '\t', '\n', '\r']):
            return False
        return True

    def _validate_cache(self, channel_id):
        """Valida cache con controllo TTL e HEAD request (come EasyProxy)"""
        if channel_id not in self._stream_cache:
            return False

        cached = self._stream_cache[channel_id]
        expires_at = cached.get("expires_at")
        if expires_at:
            try:
                if time.time() > (float(expires_at) - 30):
                    enhanced_log(
                        f"[CACHE_VALIDATE] Token in scadenza per {channel_id}",
                        "INFO",
                        "DLHD")
                    del self._stream_cache[channel_id]
                    return False
            except (TypeError, ValueError):
                pass

        # ✅ CORREZIONE: TTL ridotto a 30 minuti per evitare cache stale
        if 'timestamp' in cached:
            try:
                ts = float(cached['timestamp'])
                if time.time() - ts > 1800:  # 30 min invece di 2h
                    enhanced_log(
                        f"[CACHE_VALIDATE] Cache scaduta per {channel_id}",
                        "WARNING",
                        "DLHD")
                    del self._stream_cache[channel_id]
                    return False
            except (TypeError, ValueError):
                enhanced_log(
                    f"[CACHE_VALIDATE] Timestamp invalido per {channel_id}",
                    "WARNING",
                    "DLHD")
                del self._stream_cache[channel_id]
                return False

        # ✅ CORREZIONE: Invalida cache se contiene segmenti non-video
        stream_url = cached.get('destination_url', '')
        if 'mono.css' in stream_url:
            if cached.get('dlstreams_process') and time.time() - \
                    cached.get('timestamp', 0) <= 3:
                enhanced_log(
                    f"[CACHE_VALIDATE] Micro-cache DLStreams valida per {channel_id}",
                    "DEBUG",
                    "DLHD")
                return True
            enhanced_log(
                f"[CACHE_VALIDATE] Cache DLStreams scaduta per {channel_id}",
                "DEBUG",
                "DLHD")
            del self._stream_cache[channel_id]
            return False

        enhanced_log(
            f"[CACHE_VALIDATE] Cache valida per {channel_id}",
            "DEBUG",
            "DLHD")
        return True

    def extract_channel_id(self, url):
        """Estrae channel ID da URL (come EasyProxy)"""
        patterns = [
            r'/premium(\d+)/mono',
            r'(?:id=|premium)(\d+)',
            r'/(?:watch|stream|cast|player)/stream-(\d+)\.php',
            r'watch\.php\?id=(\d+)',
            r'(?:%2F|/)stream-(\d+)\.php',
            r'stream-(\d+)\.php',
            r'[?&]id=(\d+)',
            r'daddyhd\.php\?id=(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                channel_id = match.group(1)
                enhanced_log(
                    f"[CHANNEL_ID] Estratto: {channel_id}",
                    "DEBUG",
                    "DLHD")
                return channel_id

        enhanced_log("[CHANNEL_ID] Non trovato", "ERROR", "DLHD")
        return None

    def is_daddylive_link(self, url):
        """Verifica se è un link DaddyLive"""
        url_lower = url.lower()
        is_daddy = any(
            d in url_lower for d in [
                'daddylive',
                'dlhd',
                'daddyhd',
                'dlstreams']) or bool(
            re.search(
                r'watch\.php\?id=\d+',
                url_lower))
        if is_daddy:
            enhanced_log("[IS_DADDY] Link DaddyLive rilevato", "DEBUG", "DLHD")
        return is_daddy

    @staticmethod
    def _origin_of(url):
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _build_player_urls(self, channel_id):
        origin = self.entry_origin.rstrip("/")
        return [
            f"{origin}/stream/stream-{channel_id}.php",
            f"{origin}/cast/stream-{channel_id}.php",
            f"{origin}/watch/stream-{channel_id}.php",
            f"{origin}/plus/stream-{channel_id}.php",
            f"{origin}/casting/stream-{channel_id}.php",
            f"{origin}/player/stream-{channel_id}.php",
        ]

    def _prioritize_player_urls(self, channel_id):
        players = self._build_player_urls(channel_id)
        cached_player = self._last_working_player.get(channel_id)
        if not cached_player:
            return players
        if cached_player not in players:
            self._last_working_player.pop(channel_id, None)
            return players
        return [cached_player] + \
            [player for player in players if player != cached_player]

    def _clear_channel_cache(self, channel_id):
        self._last_working_player.pop(channel_id, None)
        self._manifest_cache.pop(f"premium{channel_id}", None)
        self._stream_cache.pop(channel_id, None)

    def _get_cookie_header_for_url(self, url):
        if not self.session:
            return None
        try:
            prepared = requests.Request("GET", url).prepare()
            cookie_header = requests.cookies.get_cookie_header(
                self.session.cookies, prepared)
            return cookie_header or None
        except Exception:
            return None

    def _prime_dlstreams_session(self, player_url, referer=None):
        warmup_headers = {
            "User-Agent": self.base_headers.get("User-Agent", random.choice(self.user_agents)),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": self.base_headers.get("Accept-Language", "en-US,en;q=0.9"),
        }
        referer = referer or self.base_headers.get("Referer")
        if referer:
            warmup_headers["Referer"] = referer

        try:
            resp = self._http_get(
                player_url, headers=warmup_headers, timeout=5)
            enhanced_log(
                f"[DLSTREAMS] Warm-up {player_url}: HTTP {resp.status_code}", "DEBUG", "DLHD")
            if resp.status_code == 200:
                return resp.text
        except Exception as exc:
            enhanced_log(
                f"[DLSTREAMS] Warm-up fallito per {player_url}: {exc}",
                "DEBUG",
                "DLHD")
        return None

    def _lookup_server_key_dlstreams(
            self,
            lookup_base,
            channel_key,
            referer_origin):
        lookup_url = f"{
            lookup_base.rstrip('/')}/server_lookup?channel_id={channel_key}"
        headers = {
            "Referer": f"{referer_origin.rstrip('/')}/",
            "User-Agent": self.base_headers.get("User-Agent", random.choice(self.user_agents)),
            "Accept": "application/json, text/plain, */*",
        }
        try:
            resp = self._http_get(lookup_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                key = data.get("server_key", "wind")
                if isinstance(key, str) and key:
                    enhanced_log(
                        f"[DLSTREAMS] server_key: {key}", "DEBUG", "DLHD")
                    return key
            enhanced_log(
                f"[DLSTREAMS] server_lookup HTTP {
                    resp.status_code}", "DEBUG", "DLHD")
        except Exception as exc:
            enhanced_log(
                f"[DLSTREAMS] server_lookup fallito: {exc}",
                "DEBUG",
                "DLHD")
        return None

    def _fetch_manifest_directly(self, url, headers):
        try:
            resp = self._http_get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                text = resp.text
                if self._is_valid_media_manifest(text, url):
                    self.stream_origin = self._origin_of(url)
                    enhanced_log(
                        f"[DLSTREAMS] Manifest diretto valido: {url}", "INFO", "DLHD")
                    return text
                if text.lstrip().startswith("#EXTM3U"):
                    enhanced_log(
                        f"[DLSTREAMS] Manifest scartato: playlist non video o asset web ({url})",
                        "WARNING",
                        "DLHD")
            enhanced_log(
                f"[DLSTREAMS] Manifest diretto non valido HTTP {
                    resp.status_code}: {url}", "DEBUG", "DLHD")
        except Exception as exc:
            enhanced_log(
                f"[DLSTREAMS] Fetch manifest diretto fallito: {exc}",
                "DEBUG",
                "DLHD")
        return None

    def _is_valid_media_manifest(self, text, manifest_url=None):
        """Accetta playlist HLS DLHD, scartando playlist-esca composte da asset web."""
        if not text:
            return False

        stripped = text.lstrip()
        if not stripped.startswith("#EXTM3U"):
            return False

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        hls_tags = (
            "#EXTINF",
            "#EXT-X-TARGETDURATION",
            "#EXT-X-STREAM-INF",
            "#EXT-X-MEDIA-SEQUENCE",
            "#EXT-X-KEY",
            "#EXT-X-MAP",
        )
        if not any(line.startswith(hls_tags) for line in lines):
            return False

        media_lines = [line for line in lines if not line.startswith("#")]
        if not media_lines:
            return any(line.startswith("#EXT-X-STREAM-INF") for line in lines)

        accepted = 0
        rejected_assets = 0
        for line in media_lines:
            if self._looks_like_dlhd_media_segment(line, manifest_url):
                accepted += 1
            else:
                rejected_assets += 1

        if accepted:
            if rejected_assets:
                enhanced_log(
                    f"[DLSTREAMS] Manifest con {accepted} segmenti validi e {rejected_assets} asset scartati",
                    "DEBUG",
                    "DLHD")
            return True
        return False

    def _looks_like_dlhd_media_segment(self, line, manifest_url=None):
        candidate = line.strip()
        if not candidate:
            return False

        absolute_url = urljoin(
            manifest_url or self.stream_origin or self.entry_origin,
            candidate)
        parsed = urlparse(absolute_url)
        path_lower = parsed.path.lower()
        url_lower = absolute_url.lower()
        manifest_host = urlparse(manifest_url or "").netloc.lower()
        same_manifest_host = bool(
            manifest_host and parsed.netloc.lower() == manifest_host)

        static_markers = (
            "/static/",
            "/assets/",
            "/asset/",
            "/dist/",
            "/public/",
            "/js/",
            "/css/",
            "/fonts/",
            "/vendor",
            "aiphototovideo",
        )
        hard_invalid_ext = (
            ".json",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".woff",
            ".woff2",
            ".ttf",
            ".ico",
            ".map")
        masked_ext = (".css", ".html", ".js", ".txt")
        video_ext = (".ts", ".m4s", ".m4v", ".mp4", ".m3u8", ".fmp4")

        if any(marker in url_lower for marker in static_markers):
            return False
        if path_lower.endswith(hard_invalid_ext):
            return False
        if path_lower.endswith(video_ext):
            return True

        if path_lower.endswith(masked_ext):
            if same_manifest_host and any(
                marker in path_lower for marker in (
                    "/proxy/",
                    "/segment/",
                    "/segments/",
                    "/live/",
                    "/hls/")):
                return True
            if same_manifest_host and re.search(
                    r"/(?:premium|stream|mono|chunk|seg)[^/]*", path_lower):
                return True
            return False

        # Segmenti senza estensione: validi solo se arrivano dallo stesso
        # gateway o da path HLS/proxy.
        if same_manifest_host:
            return True
        return any(
            marker in path_lower for marker in (
                "/proxy/",
                "/segment/",
                "/segments/",
                "/live/",
                "/hls/"))

    def _manifest_candidate_variants(self, url):
        variants = [url]
        if url.endswith("/mono.css"):
            variants.extend([
                url[:-len("/mono.css")] + "/mono.m3u8",
                url[:-len("/mono.css")] + "/index.m3u8",
                url[:-len("/mono.css")] + "/playlist.m3u8",
            ])
        elif url.endswith(".css"):
            variants.append(url[:-4] + ".m3u8")
        seen = set()
        return [
            item for item in variants if not (
                item in seen or seen.add(item))]

    def _extract_dlstreams_candidates_from_html(
            self, html, base_url, channel_key):
        """Estrae URL stream dal markup del player, equivalente leggero del capture browser."""
        if not html:
            return []

        normalized = html.replace("\\/", "/").replace("&amp;", "&")
        candidates = []

        absolute_patterns = [
            r'https?://[^"\'<>\s]+/proxy/[^"\'<>\s]+' +
            re.escape(channel_key) +
            r'[^"\'<>\s]*',
            r'https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*',
            r'https?://[^"\'<>\s]+\.mp4[^"\'<>\s]*',
        ]
        for pattern in absolute_patterns:
            candidates.extend(re.findall(pattern, normalized, re.IGNORECASE))

        relative_patterns = [
            r'["\'](/proxy/[^"\']+' + re.escape(channel_key) + r'[^"\']*)["\']',
            r'["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'["\']([^"\']+\.mp4[^"\']*)["\']',
        ]
        for pattern in relative_patterns:
            for match in re.findall(pattern, normalized, re.IGNORECASE):
                candidates.append(urljoin(base_url, match))

        cleaned = []
        seen = set()
        for candidate in candidates:
            candidate = candidate.strip().rstrip("\\")
            candidate = candidate.split("\\x")[0]
            if candidate and candidate not in seen:
                seen.add(candidate)
                cleaned.append(candidate)
        return cleaned

    def _extract_iframe_candidates_from_html(self, html, base_url, channel_id):
        if not html:
            return []

        normalized = html.replace("\\/", "/").replace("&amp;", "&")
        candidates = []
        patterns = [
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            r'(?:iframe|embed|player)[^"\']*["\'](https?://[^"\']+)["\']',
            r'["\'](https?://[^"\']+(?:premiumtv|daddyhd|stream)[^"\']*(?:id=|stream-)' +
            re.escape(
                str(channel_id)) +
            r'[^"\']*)["\']',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, normalized, re.IGNORECASE):
                candidate = urljoin(base_url, match.strip())
                if not candidate.startswith("http"):
                    continue
                if any(
                    token in candidate.lower() for token in [
                        "premiumtv",
                        "daddyhd",
                        "stream",
                        "embed",
                        "iframe"]):
                    candidates.append(candidate)

        cleaned = []
        seen = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                cleaned.append(candidate)
        if cleaned:
            enhanced_log(
                f"[DLSTREAMS] Iframe candidates trovati: {
                    len(cleaned)}", "INFO", "DLHD")
        return cleaned

    def _extract_modern_m3u8_servers(self, html):
        """Estrae i gateway M3U8 dal player moderno DLHD/chevy."""
        if not html:
            return []

        normalized = html.replace("\\/", "/").replace("&amp;", "&")
        servers = []

        block_match = re.search(
            r'M3U8_SERVERS\s*=\s*\[(.*?)\]',
            normalized,
            re.IGNORECASE | re.DOTALL)
        if block_match:
            servers.extend(
                re.findall(
                    r'["\']([^"\']+)["\']',
                    block_match.group(1)))

        single_match = re.search(
            r'M3U8_SERVER\s*=\s*["\']([^"\']+)["\']',
            normalized,
            re.IGNORECASE)
        if single_match:
            servers.append(single_match.group(1))

        cleaned = []
        seen = set()
        for server in servers:
            server = server.strip().replace(
                "https://",
                "").replace(
                "http://",
                "").strip("/")
            if not server or server in seen:
                continue
            if "." not in server:
                continue
            seen.add(server)
            cleaned.append(server)
        return cleaned

    def _candidate_lookup_bases(self, html, preferred_base, iframe_origin):
        """Ordina i possibili gateway /server_lookup e /proxy scoperti dal player."""
        bases = []

        def add_base(value):
            if not value:
                return
            value = value.strip().rstrip("/")
            if not value:
                return
            if not value.startswith("http"):
                value = "https://" + value.lstrip("/")
            if value not in bases:
                bases.append(value)

        add_base(preferred_base)
        for server in self._extract_modern_m3u8_servers(html):
            add_base(server)
        add_base(self.stream_origin)
        add_base(iframe_origin)
        add_base(self.entry_origin)
        return bases

    def _extract_stream_urls_from_data(self, data):
        urls = []

        def walk(value):
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, str):
                cleaned = value.replace("\\/", "/").replace("&amp;", "&")
                for match in re.findall(
                    r'https?://[^"\'<>\s]+(?:\.m3u8|\.css|/proxy/)[^"\'<>\s]*',
                    cleaned,
                        re.IGNORECASE):
                    if match not in urls:
                        urls.append(match)

        walk(data)
        return urls

    def _build_stream_url_candidates(
            self,
            server,
            server_key,
            channel_key,
            extra_data=None):
        """Costruisce candidati stream moderni e legacy a partire da server_key."""
        candidates = []

        def add(url):
            if url and url not in candidates:
                candidates.append(url)

        for url in self._extract_stream_urls_from_data(extra_data or {}):
            add(url)

        server = (
            server or "").replace(
            "https://",
            "").replace(
            "http://",
            "").strip("/")
        server_base = "https://{}".format(server) if server else ""
        server_root = server
        if server_root.startswith("chevy."):
            server_root = server_root[len("chevy."):]

        if server_key == "top1/cdn":
            if server_base:
                add("{}/proxy/top1/cdn/{}/mono.css".format(server_base, channel_key))
            for domain in [
                server_root,
                self.base_domain,
                "newkso.ru",
                    "kiko2.ru"]:
                if domain:
                    add("https://top1.{}/top1/cdn/{}/mono.css".format(domain, channel_key))
                    add("https://top1new.{}/top1/cdn/{}/mono.css".format(domain, channel_key))
        else:
            if server_base:
                add("{}/proxy/{}/{}/mono.css".format(server_base,
                    server_key, channel_key))
            for domain in [
                server_root,
                self.base_domain,
                "newkso.ru",
                    "kiko2.ru"]:
                if domain:
                    add("https://{}new.{}/{}/{}/mono.css".format(server_key,
                        domain, server_key, channel_key))
                    add("https://{}.{}/{}/{}/mono.css".format(server_key,
                        domain, server_key, channel_key))

        enhanced_log(
            f"[MODERN_FLOW] Stream candidati costruiti: {
                len(candidates)}", "DEBUG", "DLHD")
        return candidates

    def _extract_modern_channel_key(self, html, channel_id):
        if html:
            match = re.search(
                r'CHANNEL_KEY\s*=\s*["\']([^"\']+)["\']',
                html,
                re.IGNORECASE)
            if match and match.group(1):
                return match.group(1).strip()
        return f"premium{channel_id}"

    def _build_dlhd_client_token(
            self,
            channel_key,
            auth_country,
            auth_ts,
            user_agent):
        screen_res = "1920x1080"
        timezone = "Europe/Rome"
        lang = "it-IT"
        fingerprint = f"{user_agent}|{screen_res}|{timezone}|{lang}"
        sign_data = f"{channel_key}|{auth_country}|{auth_ts}|{user_agent}|{fingerprint}"
        return base64.b64encode(sign_data.encode('utf-8')).decode('utf-8')

    def _extract_recaptcha_site_key(self, html):
        if not html:
            return None
        patterns = [
            r'RECAPTCHA_SITE_KEY\s*=\s*["\']([^"\']+)["\']',
            r'grecaptcha\.execute\(\s*["\']([^"\']+)["\']',
            r'render=([0-9A-Za-z_-]{20,})',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _build_recaptcha_v3_token(
            self,
            site_key,
            iframe_origin,
            channel_key,
            user_agent):
        """Ottiene un token reCAPTCHA v3 headless usando la stessa action del player."""
        action = f"verify_{channel_key}"
        google_headers = {
            'User-Agent': user_agent,
            'Accept-Language': 'en-US,en;q=0.9',
        }

        api_url = f"https://www.google.com/recaptcha/api.js?render={site_key}"
        api_resp = self._http_get(api_url, headers=google_headers, timeout=10)
        version_match = re.search(r'/releases/([^/]+)/', api_resp.text or '')
        if not version_match:
            raise DLHDExtractorError("Versione reCAPTCHA non trovata")
        recaptcha_version = version_match.group(1)

        encoded_origin = base64.b64encode(
            iframe_origin.encode('utf-8')).decode('utf-8').rstrip('=') + "."
        callback_id = "x" + \
            "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(12))
        anchor_params = {
            'ar': '1',
            'k': site_key,
            'co': encoded_origin,
            'hl': 'en',
            'v': recaptcha_version,
            'size': 'invisible',
            'cb': callback_id,
        }
        anchor_resp = self._http_get(
            "https://www.google.com/recaptcha/api2/anchor",
            params=anchor_params,
            headers=dict(google_headers, Referer=f"{iframe_origin}/"),
            timeout=10
        )
        anchor_match = re.search(
            r'id=["\']recaptcha-token["\'][^>]*value=["\']([^"\']+)["\']',
            anchor_resp.text or '')
        if not anchor_match:
            raise DLHDExtractorError("Anchor token reCAPTCHA non trovato")

        reload_data = {
            'v': recaptcha_version,
            'reason': 'q',
            'c': anchor_match.group(1),
            'k': site_key,
            'co': encoded_origin,
            'hl': 'en',
            'size': 'invisible',
            'sa': action,
        }
        reload_resp = self._http_post(
            f"https://www.google.com/recaptcha/api2/reload?k={site_key}",
            data=reload_data,
            headers=dict(
                google_headers,
                Referer=anchor_resp.url,
                **{'Content-Type': 'application/x-www-form-urlencoded'}
            ),
            timeout=10
        )
        token_match = re.search(
            r'["\']rresp["\']\s*,\s*["\']([^"\']+)["\']',
            reload_resp.text or '')
        if not token_match:
            raise DLHDExtractorError("Token rresp reCAPTCHA non trovato")
        return token_match.group(1)

    def _verify_modern_gateway(
            self,
            server,
            iframe_url,
            iframe_content,
            channel_key,
            user_agent):
        site_key = self._extract_recaptcha_site_key(iframe_content)
        if not site_key:
            enhanced_log(
                "[MODERN_VERIFY] Site key reCAPTCHA non trovata",
                "DEBUG",
                "DLHD")
            return False

        iframe_origin = f"https://{urlparse(iframe_url).netloc}"
        try:
            recaptcha_token = self._build_recaptcha_v3_token(
                site_key, iframe_origin, channel_key, user_agent)
            verify_headers = {
                'User-Agent': user_agent,
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'Origin': iframe_origin,
                'Referer': iframe_url,
            }
            verify_payload = {
                'recaptcha-token': recaptcha_token,
                'channel_id': channel_key,
            }
            verify_url = f"https://{server}/verify"
            verify_resp = self._http_post(
                verify_url,
                json=verify_payload,
                headers=verify_headers,
                timeout=10)
            try:
                verify_data = verify_resp.json()
            except Exception:
                verify_data = {}

            if verify_resp.status_code == 200 and verify_data.get('success'):
                enhanced_log(
                    f"[MODERN_VERIFY] Verifica reCAPTCHA riuscita su {server}",
                    "INFO",
                    "DLHD")
                data_keys = list(
                    verify_data.keys())[
                    :8] if isinstance(
                    verify_data,
                    dict) else []
                enhanced_log(
                    f"[MODERN_VERIFY] Payload keys: {data_keys}",
                    "DEBUG",
                    "DLHD")
                return verify_data

            enhanced_log(
                f"[MODERN_VERIFY] Verifica fallita su {server}: HTTP {
                    verify_resp.status_code} {
                    str(verify_data)[
                        :160]}", "WARNING", "DLHD")
        except Exception as exc:
            enhanced_log(
                f"[MODERN_VERIFY] Errore verifica su {server}: {exc}",
                "WARNING",
                "DLHD")
        return {}

    def _extract_modern_dlhd_stream(
            self,
            iframe_url,
            iframe_content,
            channel_id,
            headers):
        """Risoluzione diretta del player moderno: server_lookup + /proxy/.../mono.css."""
        channel_key = self._extract_modern_channel_key(
            iframe_content, channel_id)
        servers = self._extract_modern_m3u8_servers(iframe_content)
        if not servers:
            raise DLHDExtractorError("Gateway M3U8 moderni non trovati")

        iframe_origin = f"https://{urlparse(iframe_url).netloc}"
        user_agent = headers.get('User-Agent', random.choice(self.user_agents))
        auth_params = self._extract_auth_params(iframe_content)
        auth_token = auth_params.get('auth_token')
        auth_country = auth_params.get('auth_country') or 'IT'
        auth_ts = auth_params.get('auth_ts') or str(int(time.time()))
        client_token = None
        if auth_token:
            client_token = self._build_dlhd_client_token(
                channel_key, auth_country, auth_ts, user_agent)

        for server in servers:
            verify_data = {}
            if not auth_token:
                verify_data = self._verify_modern_gateway(
                    server, iframe_url, iframe_content, channel_key, user_agent)
                verified_gateway = bool(verify_data)
            else:
                verified_gateway = True

            lookup_url = f"https://{server}/server_lookup?channel_id={channel_key}"
            lookup_headers = {
                'User-Agent': user_agent,
                'Accept': 'application/json, text/plain, */*',
                'Referer': iframe_url,
                'Origin': iframe_origin,
            }
            if verified_gateway:
                lookup_headers['X-Recaptcha-Verified'] = '1'
            try:
                enhanced_log(
                    f"[MODERN_FLOW] Server lookup: {lookup_url}",
                    "DEBUG",
                    "DLHD")
                lookup_resp = self._http_get(
                    lookup_url, headers=lookup_headers, timeout=5)
                if lookup_resp.status_code != 200:
                    enhanced_log(
                        f"[MODERN_FLOW] Lookup HTTP {
                            lookup_resp.status_code} su {server}",
                        "DEBUG",
                        "DLHD")
                    continue

                server_data = lookup_resp.json()
                enhanced_log(
                    f"[MODERN_FLOW] Lookup data keys: {
                        list(
                            server_data.keys())[
                            :8]}",
                    "DEBUG",
                    "DLHD")
                server_key = server_data.get('server_key') or 'wind'

                stream_headers = {
                    'User-Agent': user_agent,
                    'Accept': '*/*',
                    'Referer': iframe_url,
                    'Origin': iframe_origin,
                    'X-Direct-Connection': '1',
                    'Sec-Fetch-Dest': 'empty',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'cross-site',
                }
                if verified_gateway:
                    stream_headers['X-Recaptcha-Verified'] = '1'
                if auth_token:
                    stream_headers['Authorization'] = f'Bearer {auth_token}'
                    stream_headers['X-Channel-Key'] = channel_key
                    stream_headers['Heartbeat-Url'] = self.heartbeat_url
                if client_token:
                    stream_headers['X-Client-Token'] = client_token

                extra_data = {"verify": verify_data, "lookup": server_data}
                stream_urls = self._build_stream_url_candidates(
                    server, server_key, channel_key, extra_data=extra_data)
                for stream_url in stream_urls:
                    for manifest_candidate in self._manifest_candidate_variants(
                            stream_url):
                        manifest_text = self._fetch_manifest_directly(
                            manifest_candidate, stream_headers)
                        if manifest_text:
                            enhanced_log(
                                f"[MODERN_FLOW] Manifest risolto via {manifest_candidate}", "INFO", "DLHD")
                            return {
                                "destination_url": manifest_candidate,
                                "request_headers": stream_headers,
                                "mediaflow_endpoint": "hls_manifest_proxy",
                                "captured_manifest": manifest_text,
                                "dlstreams_process": True,
                                "timestamp": time.time()
                            }
            except Exception as exc:
                enhanced_log(
                    f"[MODERN_FLOW] Errore su {server}: {exc}",
                    "DEBUG",
                    "DLHD")

        raise DLHDExtractorError(
            "Manifest moderno non recuperabile dai gateway M3U8")

    def _extract_dlstreams_process(self, url, channel_id):
        """Nuovo processo DLStreams allineato al source async, senza Playwright su Enigma2."""
        channel_key = f"premium{channel_id}"
        iframe_origin = self.entry_origin.rstrip("/")
        lookup_base = (self.stream_origin or self.entry_origin).rstrip("/")

        cached_item = self._manifest_cache.get(channel_key)
        if cached_item and time.time() - cached_item[1] < 3:
            m3u8_url, manifest_text = cached_item[0], cached_item[2]
            enhanced_log(
                f"[DLSTREAMS] Manifest da micro-cache per {channel_key}",
                "DEBUG",
                "DLHD")
            return self._build_dlstreams_result(
                m3u8_url, iframe_origin, manifest_text)

        for player_url in self._prioritize_player_urls(channel_id)[:2]:
            player_html = self._prime_dlstreams_session(
                player_url, referer=url)
            html_candidates = self._extract_dlstreams_candidates_from_html(
                player_html, player_url, channel_key)
            for candidate in html_candidates:
                playback_headers = self._build_dlstreams_headers(
                    candidate, iframe_origin)
                if ".mp4" in candidate.lower():
                    self.stream_origin = self._origin_of(candidate)
                    self._last_working_player[channel_id] = player_url
                    return self._build_dlstreams_result(
                        candidate, iframe_origin, None, playback_headers)

                manifest_text = self._fetch_manifest_directly(
                    candidate, playback_headers)
                if manifest_text:
                    self.stream_origin = self._origin_of(candidate)
                    self._manifest_cache[channel_key] = (
                        candidate, time.time(), manifest_text)
                    self._last_working_player[channel_id] = player_url
                    return self._build_dlstreams_result(
                        candidate, iframe_origin, manifest_text, playback_headers)

            iframe_candidates = self._extract_iframe_candidates_from_html(
                player_html, player_url, channel_id)
            if iframe_candidates:
                try:
                    result = self._get_stream_data_direct(
                        channel_id, iframe_candidates[:3])
                    if result:
                        self._last_working_player[channel_id] = player_url
                        return result
                except Exception as iframe_error:
                    enhanced_log(
                        f"[DLSTREAMS] Iframe estratti non risolti: {iframe_error}",
                        "DEBUG",
                        "DLHD")

            lookup_bases = self._candidate_lookup_bases(
                player_html, lookup_base, iframe_origin)
            enhanced_log(
                f"[DLSTREAMS] Gateway candidati: {
                    len(lookup_bases)}", "DEBUG", "DLHD")
            for lookup_base in lookup_bases:
                server_key = self._lookup_server_key_dlstreams(
                    lookup_base, channel_key, iframe_origin)
                server_keys = []
                for item in [server_key, "wind", "top1/cdn"]:
                    if item and item not in server_keys:
                        server_keys.append(item)

                candidate_urls = []
                for candidate_key in server_keys:
                    candidate_urls.append(
                        f"{lookup_base}/proxy/{candidate_key}/{channel_key}/mono.css")
                    lookup_host = urlparse(lookup_base).netloc
                    candidate_urls.extend(
                        self._build_stream_url_candidates(
                            lookup_host, candidate_key, channel_key))

                seen = set()
                candidate_urls = [
                    candidate for candidate in candidate_urls if not (
                        candidate in seen or seen.add(candidate))]
                for candidate in candidate_urls:
                    for manifest_candidate in self._manifest_candidate_variants(
                            candidate):
                        playback_headers = self._build_dlstreams_headers(
                            manifest_candidate, iframe_origin)
                        manifest_text = self._fetch_manifest_directly(
                            manifest_candidate, playback_headers)
                        if manifest_text:
                            self.stream_origin = self._origin_of(
                                manifest_candidate)
                            self._manifest_cache[channel_key] = (
                                manifest_candidate, time.time(), manifest_text)
                            self._last_working_player[channel_id] = player_url
                            return self._build_dlstreams_result(
                                manifest_candidate, iframe_origin, manifest_text, playback_headers)

        self._clear_channel_cache(channel_id)
        raise DLHDExtractorError(
            "DLStreams manifest diretto non recuperabile senza browser")

    def _build_dlstreams_headers(self, m3u8_url, iframe_origin):
        headers = {
            "Referer": f"{iframe_origin}/",
            "Origin": iframe_origin,
            "User-Agent": self.base_headers.get("User-Agent", random.choice(self.user_agents)),
            "Accept": "*/*",
            "X-Direct-Connection": "1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
        cookie_header = self._get_cookie_header_for_url(m3u8_url)
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    def _build_dlstreams_result(
            self,
            m3u8_url,
            iframe_origin,
            manifest_text,
            playback_headers=None):
        result = {
            "destination_url": m3u8_url,
            "request_headers": playback_headers or self._build_dlstreams_headers(
                m3u8_url,
                iframe_origin),
            "mediaflow_endpoint": "proxy_stream_endpoint" if ".mp4" in m3u8_url.lower() else self.mediaflow_endpoint,
            "dlstreams_process": True,
            "timestamp": time.time(),
        }
        if manifest_text:
            result["captured_manifest"] = manifest_text
        return result

    def _prepare_iframe_sources(self, iframe_content):
        """Prepara contenuti normalizzati/unpacked per il parsing del player offuscato."""
        raw_content = iframe_content or ""
        normalized = self._normalize_js_source(raw_content)

        sources = [raw_content, normalized]
        inline_scripts = []
        for script_body in re.findall(
            r'<script\b[^>]*>(.*?)</script>',
            raw_content,
                re.IGNORECASE | re.DOTALL):
            script_body = script_body.strip()
            if script_body:
                inline_scripts.append(script_body)
                normalized_script = self._normalize_js_source(script_body)
                sources.extend([script_body, normalized_script])

        if inline_scripts:
            enhanced_log(
                f"[AUTH_PARSE] Script inline trovati: {
                    len(inline_scripts)}", "DEBUG", "DLHD")

        for source in list(sources):
            try:
                if detect(source):
                    unpacked = unpack(source)
                    if unpacked and unpacked not in sources:
                        sources.append(unpacked)
                        enhanced_log(
                            "[AUTH_PARSE] JS inline/player unpacked con successo", "INFO", "DLHD")
            except UnpackingError as exc:
                enhanced_log(
                    f"[AUTH_PARSE] Unpack non riuscito: {exc}",
                    "DEBUG",
                    "DLHD")
            except Exception as exc:
                enhanced_log(
                    f"[AUTH_PARSE] Errore unpack: {exc}",
                    "DEBUG",
                    "DLHD")

        deduped = []
        seen = set()
        for source in sources:
            if source and source not in seen:
                seen.add(source)
                deduped.append(source)
        return deduped

    def _normalize_js_source(self, source):
        source = source or ""
        normalized = source.replace("\\/", "/").replace("&amp;", "&")
        normalized = normalized.replace("\\x3d", "=").replace(
            "\\x2f", "/").replace("\\x2b", "+")
        normalized = normalized.replace("\\u003d", "=").replace(
            "\\u002f", "/").replace("\\u002b", "+")
        normalized = normalized.replace("\\u003a", ":").replace("\\u0026", "&")
        return normalized

    def _derive_channel_key_from_url(self, iframe_url):
        match_id = re.search(r'id=([0-9]+)', iframe_url)
        if match_id:
            return f"premium{match_id.group(1)}"
        return None

    def _looks_like_channel_key(self, value):
        if not value:
            return False
        value = value.strip()
        if re.match(r'^premium[0-9]{2,6}$', value, re.IGNORECASE):
            return True
        if re.match(
            r'^(dad|sport|live|channel)[0-9]{2,6}$',
            value,
                re.IGNORECASE):
            return True
        return False

    def _extract_jwt_token(self, sources):
        jwt_patterns = [
            r'["\'](eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+)["\']',
            r'Bearer\s+(eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+)',
            r'(?:AUTH_TOKEN|authToken|token)\s*["\':=,\s]+\s*["\']?(eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+)',
        ]
        for source in sources:
            for pattern in jwt_patterns:
                match = re.search(pattern, source, re.IGNORECASE)
                if match:
                    return match.group(1)
        return None

    def _extract_numeric_timestamps(self, sources):
        ts_patterns = [
            r'["\']([0-9]{10})["\']',
            r'(?:timestamp|AUTH_TS|iat)\s*["\':=,\s]+\s*["\']?([0-9]{10})',
            r'(?:expiry|AUTH_EXPIRY|exp)\s*["\':=,\s]+\s*["\']?([0-9]{10})',
        ]
        timestamps = []
        for source in sources:
            for pattern in ts_patterns:
                for value in re.findall(pattern, source, re.IGNORECASE):
                    try:
                        timestamps.append(int(value))
                    except Exception:
                        pass
        return sorted(set(timestamps))

    def _append_linked_scripts(self, iframe_url, iframe_content, headers):
        """Scarica script collegati al player iframe: spesso l'auth non e' inline."""
        if not iframe_content:
            return iframe_content

        iframe_host = urlparse(iframe_url).netloc
        script_urls = []
        discovered_urls = []
        for match in re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            iframe_content,
                re.IGNORECASE):
            script_url = urljoin(iframe_url, match.strip())
            parsed = urlparse(script_url)
            lower_url = script_url.lower()
            discovered_urls.append(script_url)
            if not parsed.scheme.startswith("http"):
                continue
            if any(
                token in lower_url for token in [
                    "google",
                    "gstatic",
                    "histats",
                    "amung",
                    "analytics",
                    "googletag",
                    "waust",
                    "whos.amung"]):
                continue
            if script_url not in script_urls:
                script_urls.append(script_url)

        if not script_urls:
            if discovered_urls:
                sample = ", ".join(discovered_urls[:5])
                enhanced_log(
                    f"[AUTH_PARSE] Script src trovati ma filtrati: {
                        len(discovered_urls)} ({sample})", "DEBUG", "DLHD")
            else:
                enhanced_log(
                    "[AUTH_PARSE] Nessuno script player collegato da scaricare",
                    "DEBUG",
                    "DLHD")
            return iframe_content

        sample = ", ".join(script_urls[:5])
        enhanced_log(
            f"[AUTH_PARSE] Script collegati candidati: {
                len(script_urls)} ({sample})",
            "DEBUG",
            "DLHD")

        script_headers = dict(headers or {})
        script_headers.update({
            'Accept': '*/*',
            'Referer': iframe_url,
            'Origin': f"https://{iframe_host}",
        })

        appended_sources = []
        for script_url in script_urls[:12]:
            try:
                resp = self._http_get(
                    script_url, headers=script_headers, timeout=4)
                if resp.status_code == 200 and resp.text:
                    appended_sources.append(
                        "\n/* linked script: {} */\n{}".format(script_url, resp.text))
                    enhanced_log(
                        f"[AUTH_PARSE] Script collegato caricato: {script_url}",
                        "DEBUG",
                        "DLHD")
                else:
                    enhanced_log(
                        f"[AUTH_PARSE] Script collegato HTTP {
                            resp.status_code}: {script_url}", "DEBUG", "DLHD")
            except Exception as exc:
                enhanced_log(
                    f"[AUTH_PARSE] Script collegato fallito {script_url}: {exc}",
                    "DEBUG",
                    "DLHD")

        if appended_sources:
            enhanced_log(
                f"[AUTH_PARSE] Aggiunti {
                    len(appended_sources)} script collegati al parsing auth",
                "INFO",
                "DLHD")
            return iframe_content + "\n" + "\n".join(appended_sources)
        return iframe_content

    def _extract_auth_params(self, js_content):
        """Estrae parametri di autenticazione (come EasyProxy)"""
        sources = self._prepare_iframe_sources(js_content)
        params = {}
        patterns = {
            'channel_key': [
                r'(?:const|var|let)\s+(?:CHANNEL_KEY|channelKey)\s*=\s*["\']([^"\';\s]+)["\']',
                r'channelKey\s*[=:]\s*["\']([^"\';\s]+)["\']',
                r'CHANNEL_KEY\s*[=:]\s*["\']([^"\';\s]+)["\']'],
            'auth_token': [
                r'(?:const|var|let)\s+AUTH_TOKEN\s*=\s*["\']([^"\';\s]+)["\']',
                r'authToken\s*[=:]\s*["\']([^"\';\s]+)["\']'],
            'auth_country': [
                r'(?:const|var|let)\s+AUTH_COUNTRY\s*=\s*["\']([^"\';\s]+)["\']',
                r'country\s*[=:]\s*["\']([^"\';\s]+)["\']'],
            'auth_ts': [
                r'(?:const|var|let)\s+AUTH_TS\s*=\s*["\']([^"\';\s]+)["\']',
                r'timestamp\s*[=:]\s*["\']([^"\';\s]+)["\']'],
            'auth_expiry': [
                r'(?:const|var|let)\s+AUTH_EXPIRY\s*=\s*["\']([^"\';\s]+)["\']',
                r'expiry\s*[=:]\s*["\']([^"\';\s]+)["\']']}

        for key, pattern_list in patterns.items():
            params[key] = None
            for source in sources:
                for pattern in pattern_list:
                    match = re.search(
                        pattern, source, re.MULTILINE | re.IGNORECASE)
                    if match:
                        value = match.group(1).strip()
                        if not value:
                            continue
                        if key == 'channel_key' and not self._looks_like_channel_key(
                                value):
                            continue
                        if key == 'auth_token' and not value.startswith('eyJ'):
                            continue
                        if key in (
                                'auth_ts',
                                'auth_expiry') and not re.match(
                                r'^[0-9]{10}$',
                                value):
                            continue
                        params[key] = value
                        break
                if params[key]:
                    break

        if not params.get('auth_token'):
            params['auth_token'] = self._extract_jwt_token(sources)

        # Fallback per parametri mancanti
        if not params['auth_country']:
            params['auth_country'] = 'IT'  # Default country

        if not params.get('auth_ts') or not params.get('auth_expiry'):
            timestamps = self._extract_numeric_timestamps(sources)
            if timestamps:
                current_time = int(time.time())
                if not params.get('auth_ts'):
                    iat_candidates = [
                        ts for ts in timestamps if abs(
                            ts - current_time) < 7200]
                    params['auth_ts'] = str(
                        min(iat_candidates)) if iat_candidates else str(
                        timestamps[0])
                if not params.get('auth_expiry'):
                    exp_candidates = [
                        ts for ts in timestamps if ts > int(
                            params['auth_ts'])]
                    params['auth_expiry'] = str(min(exp_candidates)) if exp_candidates else str(
                        int(params['auth_ts']) + 3600)

        return params

    def _extract_lovecdn_stream(self, iframe_url, iframe_content, headers):
        """Estrattore alternativo per iframe lovecdn.ru (come EasyProxy)"""
        enhanced_log("[LOVECDN] Estrazione alternativa", "INFO", "DLHD")
        try:
            # Pattern per URL stream
            m3u8_patterns = [
                r'["\']([^"\']*.m3u8[^"\']*)["\']',
                r'source[:\s]+["\']([^"\'\']+)["\']',
                r'file[:\s]+["\']([^"\'\']+.m3u8[^"\']*)["\']',
                r'hlsManifestUrl[:\s]*["\']([^"\'\']+)["\']',
            ]

            stream_url = None
            for pattern in m3u8_patterns:
                matches = re.findall(pattern, iframe_content)
                for match in matches:
                    if '.m3u8' in match and match.startswith('http'):
                        stream_url = match
                        break
                if stream_url:
                    break

            if not stream_url:
                # Costruzione dinamica
                channel_match = re.search(
                    r'(?:stream|channel)["\s:=]+["\']([^"\']+ )["\']', iframe_content)
                server_match = re.search(
                    r'(?:server|domain|host)["\s:=]+["\']([^"\']+ )["\']',
                    iframe_content)

                if channel_match:
                    channel_name = channel_match.group(1)
                    # Usa base_domain dinamico
                    server = server_match.group(
                        1) if server_match else self.base_domain
                    stream_url = f"https://{server}/{channel_name}/mono.m3u8"

            if not stream_url:
                raise DLHDExtractorError("Stream URL non trovato in lovecdn")

            iframe_origin = f"https://{urlparse(iframe_url).netloc}"
            stream_headers = {
                'User-Agent': headers['User-Agent'],
                'Referer': iframe_url,
                'Origin': iframe_origin
            }

            enhanced_log("[LOVECDN] Estrazione completata", "INFO", "DLHD")
            return {
                "destination_url": stream_url,
                "request_headers": stream_headers,
                "mediaflow_endpoint": "hls_manifest_proxy",
                "timestamp": time.time()
            }

        except Exception as e:
            enhanced_log(f"[LOVECDN] Errore: {e}", "ERROR", "DLHD")
            raise DLHDExtractorError(f"Lovecdn extraction failed: {e}")

    def _extract_new_auth_flow(self, iframe_url, iframe_content, headers):
        """Gestisce il nuovo flusso di autenticazione con estrazione euristica migliorata."""

        enhanced_log(
            "[NEW_AUTH_FLOW] Tentativo rilevamento nuovo flusso auth obfuscated",
            "INFO",
            "DLHD")
        sources = self._prepare_iframe_sources(iframe_content)

        # 1. Estrazione euristica delle variabili migliorata
        params = {}

        # Cerca il JWT (inizia con eyJ...)
        jwt_patterns = [
            r'["\']([eyJ][a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+)["\']',
            r'token["\s:=]+["\']([eyJ][a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+)["\']',
            r'AUTH_TOKEN["\s:=]+["\']([eyJ][a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+)["\']']

        for source in sources:
            for pattern in jwt_patterns:
                jwt_match = re.search(pattern, source, re.IGNORECASE)
                if jwt_match:
                    params['auth_token'] = jwt_match.group(1)
                    enhanced_log(
                        "[NEW_AUTH_FLOW] Trovato JWT Token", "INFO", "DLHD")
                    break
            if params.get('auth_token'):
                break

        # Cerca Channel Key con pattern migliorati
        channel_patterns = [
            r'["\']([a-z]+[0-9]+)["\']',
            r'channelKey["\s:=]+["\']([^"\';\s]+)["\']',
            r'CHANNEL_KEY["\s:=]+["\']([^"\';\s]+)["\']',
            r'channel["\s:=]+["\']([^"\';\s]+)["\']'
        ]

        for pattern in channel_patterns:
            for source in sources:
                key_matches = re.finditer(pattern, source, re.IGNORECASE)
                for m in key_matches:
                    val = m.group(1)
                    # Filtro piu rigoroso per channel key
                    if (
                        re.match(
                            r'^(premium|dad|sport|live|channel)[0-9]+$',
                            val,
                            re.IGNORECASE) or (
                            len(val) < 20 and any(
                                char.isdigit() for char in val) and not len(val) > 15)):
                        params['channel_key'] = val
                        enhanced_log(
                            f"[NEW_AUTH_FLOW] Trovata Channel Key: {val}", "INFO", "DLHD")
                        break
                if params.get('channel_key'):
                    break
            if params.get('channel_key'):
                break

        params['auth_token'] = params.get(
            'auth_token') or self._extract_jwt_token(sources)
        derived_channel_key = self._derive_channel_key_from_url(iframe_url)
        if derived_channel_key:
            params['channel_key'] = derived_channel_key
            enhanced_log(
                f"[NEW_AUTH_FLOW] Channel Key derivata dall'URL: {
                    params['channel_key']}", "INFO", "DLHD")
        elif params.get('channel_key') and not self._looks_like_channel_key(params['channel_key']):
            params['channel_key'] = None

        # Cerca Country con pattern migliorati
        country_patterns = [
            r'["\']([A-Z]{2})["\']',
            r'country["\s:=]+["\']([A-Z]{2})["\']',
            r'AUTH_COUNTRY["\s:=]+["\']([A-Z]{2})["\']'
        ]

        for pattern in country_patterns:
            for source in sources:
                country_match = re.search(pattern, source, re.IGNORECASE)
                if country_match:
                    params['auth_country'] = country_match.group(1)
                    break
            if params.get('auth_country'):
                break

        if not params.get('auth_country'):
            params['auth_country'] = 'IT'  # Fallback per Italia

        # Cerca Timestamp con pattern migliorati
        ts_patterns = [
            r'["\']([0-9]{10})["\']',
            r'timestamp["\s:=]+["\']([0-9]{10})["\']',
            r'AUTH_TS["\s:=]+["\']([0-9]{10})["\']',
            r'iat["\s:=]+([0-9]{10})',
            r'exp["\s:=]+([0-9]{10})'
        ]

        timestamps = []
        for pattern in ts_patterns:
            for source in sources:
                matches = re.findall(pattern, source, re.IGNORECASE)
                timestamps.extend([int(x) for x in matches])

        if timestamps:
            # Ordina i timestamp e usa il più piccolo come iat, il più grande
            # come exp
            timestamps = sorted(set(timestamps))
            current_time = int(time.time())

            # Trova il timestamp più vicino al tempo corrente per iat
            iat_candidates = [
                ts for ts in timestamps if abs(
                    ts - current_time) < 3600]  # Entro 1 ora
            if iat_candidates:
                params['auth_ts'] = str(min(iat_candidates))
            else:
                params['auth_ts'] = str(timestamps[0])

            # Trova exp (dovrebbe essere maggiore di iat)
            exp_candidates = [
                ts for ts in timestamps if ts > int(
                    params['auth_ts'])]
            if exp_candidates:
                params['auth_expiry'] = str(min(exp_candidates))
            else:
                params['auth_expiry'] = str(int(params['auth_ts']) + 3600)
        else:
            # Fallback con timestamp corrente
            current_time = int(time.time())
            params['auth_ts'] = str(current_time)
            params['auth_expiry'] = str(current_time + 3600)

        # Validazione parametri
        if not params.get('auth_token'):
            sample = sources[-1][:250].replace('\n', ' ') if sources else ''
            enhanced_log(
                f"[NEW_AUTH_FLOW] JWT non trovato. Sample sorgente: {sample}",
                "WARNING",
                "DLHD")
            raise DLHDExtractorError(
                "Impossibile estrarre JWT dal nuovo flusso")

        # ✅ CORREZIONE CRITICA: Usa sempre channel key derivata dall'URL per sicurezza
        m_url = re.search(r'id=([0-9]+)', iframe_url)
        if m_url:
            channel_id = m_url.group(1)
            params['channel_key'] = f"premium{channel_id}"
            enhanced_log(
                f"[NEW_AUTH_FLOW] ✅ Channel Key forzata dall'URL: {
                    params['channel_key']}", "INFO", "DLHD")
        elif not params.get('channel_key'):
            raise DLHDExtractorError("Channel Key mancante e non derivabile")

        enhanced_log(
            f"[NEW_AUTH_FLOW] ✅ Parametri estratti: {
                list(
                    params.keys())}",
            "INFO",
            "DLHD")

        # 2. Server Lookup (salta auth2.php)
        enhanced_log(
            "[NEW_AUTH_FLOW] 🚀 Skipping auth2.php, procedo diretto al server lookup",
            "INFO",
            "DLHD")

        user_agent = headers.get('User-Agent', random.choice(self.user_agents))
        iframe_origin = f"https://{urlparse(iframe_url).netloc}"

        channel_key = params['channel_key']
        auth_token = params['auth_token']

        # Server Lookup
        server_lookup_url = f"{
            self.server_lookup_url}?channel_id={channel_key}"
        lookup_headers = {
            'User-Agent': user_agent,
            'Accept': '*/*',
            'Referer': iframe_url,
            'Origin': iframe_origin,
        }

        enhanced_log(
            f"[NEW_AUTH_FLOW] 🔍 Server Lookup: {server_lookup_url}",
            "DEBUG",
            "DLHD")

        try:
            lookup_resp = self._http_get(
                server_lookup_url, headers=lookup_headers, timeout=5)
            lookup_resp.raise_for_status()
            server_data = lookup_resp.json()
            server_key = server_data.get('server_key')

            if not server_key:
                raise DLHDExtractorError(
                    f"No server_key in response: {server_data}")

            enhanced_log(
                f"[NEW_AUTH_FLOW] ✅ Server key: {server_key}",
                "INFO",
                "DLHD")
        except Exception as e:
            enhanced_log(
                f"[NEW_AUTH_FLOW] ❌ Server lookup fallito: {e}",
                "ERROR",
                "DLHD")
            raise DLHDExtractorError(f"Server lookup failed: {e}")

        # 3. Heartbeat per stabilire sessione
        auth_country = params.get('auth_country', 'IT')
        auth_ts = params.get('auth_ts', str(int(time.time())))
        screen_res = "1920x1080"
        timezone = "Europe/Rome"
        lang = "it-IT"
        fingerprint = f"{user_agent}|{screen_res}|{timezone}|{lang}"
        sign_data = f"{channel_key}|{auth_country}|{auth_ts}|{user_agent}|{fingerprint}"
        client_token = base64.b64encode(
            sign_data.encode('utf-8')).decode('utf-8')

        heartbeat_headers = {
            'User-Agent': user_agent,
            'Authorization': f'Bearer {auth_token}',
            'X-Channel-Key': channel_key,
            'X-Client-Token': client_token,
            'Referer': iframe_url,
            'Origin': iframe_origin,
        }

        try:
            enhanced_log(
                f"[NEW_AUTH_FLOW] 💓 Invio heartbeat: {
                    self.heartbeat_url}", "DEBUG", "DLHD")
            hb_resp = self._http_get(
                self.heartbeat_url,
                headers=heartbeat_headers,
                timeout=5)
            enhanced_log(
                f"[NEW_AUTH_FLOW] 💓 Heartbeat response: {
                    hb_resp.status_code}", "DEBUG", "DLHD")
        except Exception as hb_e:
            enhanced_log(
                f"[NEW_AUTH_FLOW] ⚠️ Heartbeat fallito: {hb_e}",
                "WARNING",
                "DLHD")

        # 4. Build Stream URL
        if server_key == 'top1/cdn':
            stream_url = self.stream_cdn_template.replace(
                '{CHANNEL}', channel_key)
            # ✅ CORREZIONE CRITICA: Forza sempre .m3u8 per evitare segmenti .html/.css
        else:
            stream_url = self.stream_other_template.replace(
                '{SERVER_KEY}', server_key).replace(
                '{CHANNEL}', channel_key)
            # ✅ CORREZIONE CRITICA: Forza sempre .m3u8 per evitare segmenti .html/.css

        enhanced_log(
            f"[NEW_AUTH_FLOW] ✅ Stream URL costruito: {stream_url}",
            "INFO",
            "DLHD")

        stream_headers = {
            'User-Agent': user_agent,
            'Referer': iframe_url,
            'Origin': iframe_origin,
            'Authorization': f'Bearer {auth_token}',
            'X-Channel-Key': channel_key,
            'Heartbeat-Url': self.heartbeat_url,
            'X-Client-Token': client_token,
        }

        return {
            "destination_url": stream_url,
            "request_headers": stream_headers,
            "mediaflow_endpoint": "hls_manifest_proxy",
            "expires_at": float(params.get('auth_expiry', 0)),
            "timestamp": time.time()
        }

    def _get_stream_data_direct(self, channel_id, hosts_to_try):
        """Estrazione diretta dall'iframe (PROCESSO PRINCIPALE come EasyProxy)"""

        user_agent = random.choice(self.user_agents)
        last_error = None

        for iframe_host in hosts_to_try:
            try:
                if str(iframe_host).startswith("http"):
                    iframe_url = str(iframe_host)
                    iframe_host = urlparse(iframe_url).netloc
                else:
                    iframe_url = f'https://{iframe_host}/premiumtv/daddyhd.php?id={channel_id}'
                enhanced_log(
                    f"[DIRECT_IFRAME] Tentativo estrazione da: {iframe_url}",
                    "INFO",
                    "DLHD")

                embed_headers = {
                    'User-Agent': user_agent,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://dlhd.dad/',
                    'Cache-Control': 'no-cache'}

                # Step 1: Fetch iframe page
                enhanced_log(
                    "[DIRECT_IFRAME] Download iframe",
                    "DEBUG",
                    "DLHD")
                resp = self._http_get(
                    iframe_url, headers=embed_headers, timeout=4)

                if resp.status_code != 200:
                    enhanced_log(
                        f"[DIRECT_IFRAME] HTTP {
                            resp.status_code}",
                        "WARNING",
                        "DLHD")
                    last_error = DLHDExtractorError(f"HTTP {resp.status_code}")
                    continue

                js_content = resp.text
                enhanced_log(
                    f"[DIRECT_IFRAME] Iframe caricato: {
                        len(js_content)} bytes", "DEBUG", "DLHD")
                js_content = self._append_linked_scripts(
                    iframe_url, js_content, embed_headers)

                try:
                    result = self._extract_modern_dlhd_stream(
                        iframe_url, js_content, channel_id, embed_headers)
                    if result:
                        enhanced_log(
                            "[DIRECT_IFRAME] Modern flow DLHD riuscito", "INFO", "DLHD")
                        return result
                except Exception as modern_error:
                    enhanced_log(
                        f"[DIRECT_IFRAME] Modern flow non disponibile: {modern_error}",
                        "DEBUG",
                        "DLHD")

                # Check lovecdn alternativo PRIMA di altri controlli
                if 'lovecdn.ru' in js_content:
                    enhanced_log(
                        "[DIRECT_IFRAME] Rilevato lovecdn.ru", "INFO", "DLHD")
                    result = self._extract_lovecdn_stream(
                        iframe_url, js_content, embed_headers)
                    if result:
                        return result

                # Check per contenuto valido
                if len(js_content) < 1000:
                    enhanced_log(
                        "[DIRECT_IFRAME] Contenuto troppo piccolo",
                        "WARNING",
                        "DLHD")
                    last_error = DLHDExtractorError(
                        "Contenuto iframe troppo piccolo")
                    continue

                # Step 2: Extract auth params (COME EASYPROXY)
                enhanced_log(
                    "[DIRECT_IFRAME] Estrazione parametri auth",
                    "DEBUG",
                    "DLHD")
                params = self._extract_auth_params(js_content)

                if not all(params.values()):
                    missing = [k for k, v in params.items() if not v]
                    enhanced_log(
                        f"[DIRECT_IFRAME] Parametri mancanti: {missing}",
                        "WARNING",
                        "DLHD")

                    # ✅ NUOVO: Prova IMMEDIATAMENTE il nuovo flusso di autenticazione se mancano parametri
                    enhanced_log(
                        "[DIRECT_IFRAME] Parametri mancanti, attivo nuovo flusso auth",
                        "INFO",
                        "DLHD")
                    try:
                        result = self._extract_new_auth_flow(
                            iframe_url, js_content, embed_headers)
                        if result:
                            enhanced_log(
                                "[DIRECT_IFRAME] ✅ Nuovo flusso riuscito per parametri mancanti",
                                "INFO",
                                "DLHD")
                            return result
                    except Exception as e:
                        enhanced_log(
                            f"[DIRECT_IFRAME] Nuovo flusso fallito: {e}", "WARNING", "DLHD")

                    last_error = DLHDExtractorError(
                        f"Missing params: {missing} and New Flow failed")
                    continue

                # Step 3: Auth POST (COME EASYPROXY)
                enhanced_log("[AUTH] POST autenticazione", "DEBUG", "DLHD")

                # ✅ PRIORITÀ MASSIMA: Attiva IMMEDIATAMENTE nuovo flusso se parametri standard mancanti
                if not all(params.values()):
                    missing = [k for k, v in params.items() if not v]
                    enhanced_log(
                        f"[AUTH] ⚡ Parametri mancanti {missing} - ATTIVO NUOVO FLUSSO IMMEDIATO",
                        "WARNING",
                        "DLHD")
                    try:
                        result = self._extract_new_auth_flow(
                            iframe_url, js_content, embed_headers)
                        if result:
                            enhanced_log(
                                "[AUTH] ✅ NUOVO FLUSSO RIUSCITO per parametri mancanti", "INFO", "DLHD")
                            return result
                    except Exception as e:
                        enhanced_log(
                            f"[AUTH] ❌ Nuovo flusso fallito: {e}", "WARNING", "DLHD")

                    last_error = DLHDExtractorError(
                        f"Missing params: {missing} and New Flow failed")
                    continue

                iframe_origin = f"https://{iframe_host}"
                form_data = {
                    'channelKey': params['channel_key'],
                    'country': params['auth_country'],
                    'timestamp': params['auth_ts'],
                    'expiry': params['auth_expiry'],
                    'token': params['auth_token']
                }

                auth_headers = {
                    'User-Agent': user_agent,
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': iframe_origin,
                    'Referer': iframe_url,
                    'Cache-Control': 'no-cache'
                }

                try:
                    auth_resp = self._http_post(
                        self.auth_url,
                        data=form_data,
                        headers=auth_headers,
                        timeout=5
                    )

                    if auth_resp.status_code != 200:
                        enhanced_log(
                            f"[AUTH] HTTP {
                                auth_resp.status_code}",
                            "WARNING",
                            "DLHD")
                        last_error = DLHDExtractorError(
                            f"Auth HTTP {auth_resp.status_code}")
                        continue

                    auth_text = auth_resp.text
                    enhanced_log(
                        f"[AUTH] Risposta: {auth_text[:100]}", "DEBUG", "DLHD")

                except Exception as auth_error:
                    enhanced_log(
                        f"[AUTH] Errore connessione auth2.php: {auth_error}",
                        "WARNING",
                        "DLHD")

                    # ✅ PRIORITÀ MASSIMA: Attiva IMMEDIATAMENTE il nuovo flusso auth se auth2.php fallisce
                    enhanced_log(
                        "[AUTH] ⚡ Auth2.php fallito - ATTIVO NUOVO FLUSSO IMMEDIATO",
                        "INFO",
                        "DLHD")
                    try:
                        result = self._extract_new_auth_flow(
                            iframe_url, js_content, embed_headers)
                        if result:
                            enhanced_log(
                                "[AUTH] ✅ NUOVO FLUSSO RIUSCITO - auth2.php bypassato", "INFO", "DLHD")
                            return result
                    except Exception as new_flow_error:
                        enhanced_log(
                            f"[AUTH] ❌ Nuovo flusso fallito: {new_flow_error}",
                            "WARNING",
                            "DLHD")

                    # Fallback: aggiorna config solo se necessario
                    if iframe_host == hosts_to_try[0] and not self._config_refreshed and '403' in str(
                            auth_error):
                        enhanced_log(
                            "[AUTH] Errore 403, aggiorno configurazione come fallback", "INFO", "DLHD")
                        self._config_refreshed = True
                        if self._fetch_iframe_hosts():
                            enhanced_log(
                                f"[AUTH] Config aggiornata, nuovo auth_url: {
                                    self.auth_url}", "INFO", "DLHD")

                    last_error = DLHDExtractorError(
                        f"Auth failed and New Flow failed: {auth_error}")
                    continue

                # Validazione risposta auth
                if 'Blocked' in auth_text or 'bad params' in auth_text.lower():
                    enhanced_log(
                        f"[AUTH] Risposta auth invalida: {auth_text[:50]}", "WARNING", "DLHD")

                    # Se è il primo host e auth fallisce, prova a refreshare
                    # config
                    if iframe_host == hosts_to_try[0] and not self._config_refreshed:
                        enhanced_log(
                            "[AUTH] Auth fallito, provo ad aggiornare config", "INFO", "DLHD")
                        self._config_refreshed = True
                        if self._fetch_iframe_hosts():
                            enhanced_log(
                                f"[AUTH] Config aggiornata, nuovo auth_url: {
                                    self.auth_url}", "INFO", "DLHD")
                            # Riprova auth con nuovo URL
                            try:
                                auth_resp = self._http_post(
                                    self.auth_url,
                                    data=form_data,
                                    headers=auth_headers,
                                    timeout=5
                                )
                                auth_text = auth_resp.text
                                enhanced_log(
                                    f"[AUTH] Nuova risposta: {auth_text[:100]}", "DEBUG", "DLHD")
                            except Exception as retry_e:
                                enhanced_log(
                                    f"[AUTH] Retry fallito: {retry_e}", "WARNING", "DLHD")

                    # ✅ PRIORITÀ MASSIMA: Se auth è bloccato, attiva IMMEDIATAMENTE nuovo flusso
                    if 'Blocked' in auth_text or 'bad params' in auth_text.lower():
                        enhanced_log(
                            "[AUTH] ⚡ Auth bloccato - ATTIVO NUOVO FLUSSO IMMEDIATO",
                            "WARNING",
                            "DLHD")
                        try:
                            result = self._extract_new_auth_flow(
                                iframe_url, js_content, embed_headers)
                            if result:
                                enhanced_log(
                                    "[AUTH] ✅ NUOVO FLUSSO RIUSCITO - auth bloccato bypassato", "INFO", "DLHD")
                                return result
                        except Exception as e:
                            enhanced_log(
                                f"[AUTH] ❌ Nuovo flusso (fallback) fallito: {e}", "WARNING", "DLHD")

                        last_error = DLHDExtractorError(
                            f"Auth blocked: {auth_text} AND New Flow failed")
                        continue

                # Prova parsing JSON
                try:
                    auth_data = json.loads(auth_text)
                    if not (auth_data.get('success')
                            or auth_data.get('valid')):
                        enhanced_log(
                            f"[AUTH] Auth fallito: {auth_data}", "WARNING", "DLHD")
                        last_error = DLHDExtractorError(
                            f"Auth failed: {auth_data}")
                        continue
                except json.JSONDecodeError:
                    # Se non è JSON, considera valido se non contiene errori
                    pass

                enhanced_log("[AUTH] Autenticazione riuscita", "INFO", "DLHD")

                # Step 4: Server Lookup (COME EASYPROXY)
                enhanced_log("[LOOKUP] Server lookup", "DEBUG", "DLHD")
                server_lookup_url = f"{
                    self.server_lookup_url}?channel_id={
                    params['channel_key']}"
                lookup_headers = {
                    'User-Agent': user_agent,
                    'Accept': '*/*',
                    'Referer': iframe_url,
                    'Origin': iframe_origin,
                }

                lookup_resp = self._http_get(
                    server_lookup_url, headers=lookup_headers, timeout=5)
                if lookup_resp.status_code != 200:
                    last_error = DLHDExtractorError(
                        f"Server lookup failed: {
                            lookup_resp.status_code}")
                    continue

                server_data = lookup_resp.json()
                server_key = server_data.get('server_key')

                if not server_key:
                    last_error = DLHDExtractorError(
                        f"No server_key: {server_data}")
                    continue

                enhanced_log(
                    f"[LOOKUP] Server key: {server_key}",
                    "INFO",
                    "DLHD")

                # Step 5: Heartbeat (NECESSARIO come EasyProxy)
                channel_key = params['channel_key']
                auth_token = params['auth_token']

                heartbeat_headers = {
                    'User-Agent': user_agent,
                    'Authorization': f'Bearer {auth_token}',
                    'X-Channel-Key': channel_key,
                    'Referer': iframe_url,
                    'Origin': iframe_origin,
                }

                try:
                    enhanced_log(
                        "[HEARTBEAT] Invio heartbeat", "DEBUG", "DLHD")
                    hb_resp = self._http_get(
                        self.heartbeat_url, headers=heartbeat_headers, timeout=5)
                    enhanced_log(
                        f"[HEARTBEAT] Risposta: {
                            hb_resp.status_code}", "DEBUG", "DLHD")
                except Exception as hb_e:
                    enhanced_log(
                        f"[HEARTBEAT] Fallito: {hb_e}", "WARNING", "DLHD")
                    # Non blocchiamo l'estrazione se il heartbeat fallisce

                # Step 6: Build final URL (COME EASYPROXY con template
                # dinamici)
                if server_key == 'top1/cdn':
                    # Usa stream_cdn_template ma forza .m3u8
                    stream_url = self.stream_cdn_template.replace(
                        '{CHANNEL}', channel_key)
                    # ✅ CORREZIONE CRITICA: Forza sempre .m3u8 per evitare segmenti .html/.css
                else:
                    # Usa stream_other_template ma forza .m3u8
                    stream_url = self.stream_other_template.replace(
                        '{SERVER_KEY}', server_key).replace(
                        '{CHANNEL}', channel_key)
                    # ✅ CORREZIONE CRITICA: Forza sempre .m3u8 per evitare segmenti .html/.css

                enhanced_log("[BUILD] Stream URL costruito", "INFO", "DLHD")

                # Genera X-Client-Token (come EasyProxy)
                auth_ts = params.get('auth_ts', '')
                auth_country = params.get('auth_country', 'IT')
                screen_res = "1920x1080"
                timezone = "Europe/Rome"
                lang = "it-IT"
                fingerprint = f"{user_agent}|{screen_res}|{timezone}|{lang}"
                sign_data = f"{channel_key}|{auth_country}|{auth_ts}|{user_agent}|{fingerprint}"
                client_token = base64.b64encode(
                    sign_data.encode('utf-8')).decode('utf-8')

                stream_headers = {
                    'User-Agent': user_agent,
                    'Referer': iframe_url,
                    'Origin': iframe_origin,
                    'Authorization': f'Bearer {auth_token}',
                    'X-Channel-Key': channel_key,
                    'Heartbeat-Url': self.heartbeat_url,
                    'X-Client-Token': client_token,
                }

                # Calcola expires_at
                expires_at = None
                try:
                    if params.get('auth_expiry'):
                        expires_at = float(params['auth_expiry'])
                except (ValueError, TypeError):
                    pass

                # Reset flag per permettere futuri refresh
                self._config_refreshed = False

                enhanced_log(
                    "[EXTRACT] Estrazione completata con successo",
                    "INFO",
                    "DLHD")
                return {
                    "destination_url": stream_url,
                    "request_headers": stream_headers,
                    "mediaflow_endpoint": "hls_manifest_proxy",
                    "expires_at": expires_at,
                    "timestamp": time.time()
                }

            except Exception as e:
                enhanced_log(
                    f"[DIRECT_IFRAME] Errore con {iframe_host}: {e}",
                    "WARNING",
                    "DLHD")
                last_error = e
                continue

        raise DLHDExtractorError(
            f"Tutti gli host iframe hanno fallito. Ultimo errore: {last_error}")

    def extract_stream(self, url, force_refresh=False):
        """Metodo principale di estrazione - Compatibile con AppCore"""
        enhanced_log(
            "[EXTRACT] === INIZIO ESTRAZIONE DLHD OTTIMIZZATA ===",
            "INFO",
            "DLHD")
        enhanced_log(f"[EXTRACT] URL: {url[:80]}...", "INFO", "DLHD")

        self.stats['requests'] += 1

        if not self.is_daddylive_link(url):
            enhanced_log("[EXTRACT] Non è un link DaddyLive", "ERROR", "DLHD")
            raise DLHDExtractorError("Non è un link DaddyLive")

        channel_id = self.extract_channel_id(url)
        if not channel_id:
            enhanced_log("[EXTRACT] Channel ID non trovato", "ERROR", "DLHD")
            raise DLHDExtractorError("Channel ID non trovato")

        enhanced_log(f"[EXTRACT] Channel ID: {channel_id}", "INFO", "DLHD")

        # Controlla cache se non force_refresh
        if not force_refresh:
            # ✅ CORREZIONE: Forza sempre nuovo download se cache contiene .css
            if not force_refresh and self._validate_cache(channel_id):
                enhanced_log(
                    f"[EXTRACT] Cache hit per canale {channel_id}",
                    "INFO",
                    "DLHD")
                self.stats['cache_hits'] += 1
                return self._stream_cache[channel_id]

        enhanced_log(
            f"[EXTRACT] Avvio estrazione per {channel_id}",
            "INFO",
            "DLHD")

        # Usa un lock per prevenire estrazioni simultanee per lo stesso canale
        # (come EasyProxy)
        if channel_id not in self._extraction_locks:
            self._extraction_locks[channel_id] = threading.Lock()

        lock = self._extraction_locks[channel_id]
        with lock:
            # Ricontrolla la cache dopo aver acquisito il lock
            if not force_refresh and channel_id in self._stream_cache:
                if self._validate_cache(channel_id):
                    enhanced_log(
                        f"[EXTRACT] Dati per il canale {channel_id} trovati in cache dopo lock",
                        "INFO",
                        "DLHD")
                    self.stats['cache_hits'] += 1
                    return self._stream_cache[channel_id]

            try:
                enhanced_log(
                    "[EXTRACT] Provo nuovo processo DLStreams diretto",
                    "INFO",
                    "DLHD")
                result = self._extract_dlstreams_process(url, channel_id)
            except Exception as dlstreams_error:
                enhanced_log(
                    f"[EXTRACT] Processo DLStreams diretto fallito: {dlstreams_error}",
                    "WARNING",
                    "DLHD")
                try:
                    result = self._get_stream_data_direct(
                        channel_id, self.iframe_hosts)
                except DLHDExtractorError:
                    # Se fallisce con gli host correnti, prova ad aggiornarli
                    enhanced_log(
                        "[EXTRACT] Tutti gli host correnti hanno fallito. Tento aggiornamento lista host",
                        "WARNING",
                        "DLHD")
                    if self._fetch_iframe_hosts():
                        enhanced_log(
                            f"[EXTRACT] Riprovo con nuovi host: {
                                self.iframe_hosts}", "INFO", "DLHD")
                        result = self._get_stream_data_direct(
                            channel_id, self.iframe_hosts)
                    else:
                        raise

            if result:
                # Salva in cache
                self._stream_cache[channel_id] = result
                self._save_cache()
                enhanced_log(
                    "[EXTRACT] Risultato salvato in cache",
                    "INFO",
                    "DLHD")

                # Log statistiche
                self.stats['successful_extractions'] += 1
                enhanced_log(
                    f"[STATS] Requests: {
                        self.stats['requests']}, Cache hits: {
                        self.stats['cache_hits']}, Success: {
                        self.stats['successful_extractions']}",
                    "DEBUG",
                    "DLHD")

                enhanced_log(
                    "[EXTRACT] === ESTRAZIONE COMPLETATA CON SUCCESSO ===",
                    "INFO",
                    "DLHD")
                return result
            else:
                raise DLHDExtractorError(
                    "Estrazione fallita dopo tutti i tentativi")

    def invalidate_cache_for_url(self, url):
        """Invalida cache per URL specifico"""
        channel_id = self.extract_channel_id(url)
        if channel_id and channel_id in self._stream_cache:
            del self._stream_cache[channel_id]
            self._save_cache()
            enhanced_log(
                f"[CACHE] Invalidata per canale {channel_id}",
                "INFO",
                "DLHD")

    def get_stats(self):
        """Restituisce statistiche di utilizzo"""
        return self.stats.copy()

    def close(self):
        """Chiude sessione e salva statistiche"""
        if self.session:
            try:
                self.session.close()
                enhanced_log("[CLOSE] Sessione chiusa", "DEBUG", "DLHD")
            except BaseException:
                pass

        # Salva statistiche finali
        enhanced_log(f"[FINAL_STATS] {self.stats}", "INFO", "DLHD")

# Funzione di compatibilità per AppCore


def create_dlhd_extractor():
    """Factory function per creare l'extractor ottimizzato"""
    return DLHDExtractor()

# Test function per debug


def test_extraction(url):
    """Funzione di test per debug"""
    extractor = DLHDExtractor()
    try:
        result = extractor.extract_stream(url)
        print(f"Estrazione riuscita: {result}")
        return result
    except Exception as e:
        print(f"Estrazione fallita: {e}")
        return None
    finally:
        extractor.close()


if __name__ == "__main__":
    # Test con URL di esempio
    test_url = "https://daddyhd.com/watch.php?id=850"
    test_extraction(test_url)
