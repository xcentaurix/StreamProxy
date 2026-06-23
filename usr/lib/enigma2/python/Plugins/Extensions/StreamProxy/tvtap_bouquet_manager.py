# -*- coding: utf-8 -*-
"""
TVTap Bouquet Manager - Gestione dinamica canali TVTap basata su bouquet
Rileva automaticamente i canali TVTap dal bouquet e gestisce authSign dinamici
"""

import re
import time
import threading
import hashlib
from urllib.parse import urlparse, parse_qs, unquote, quote
from datetime import datetime, timedelta

try:
    from .StreamProxyLog import enhanced_log
    from .extractor.tvtap_extractor import get_tvtap_stream, get_tvtap_channels, find_channel_by_name
except ImportError:
    def enhanced_log(message, level="INFO", component="TVTAP_BOUQUET"):
        print(f"[{level}] [{component}] {message}")

    # Fallback imports se eseguito standalone
    try:
        from extractor.tvtap_extractor import get_tvtap_stream, get_tvtap_channels, find_channel_by_name
    except ImportError:
        enhanced_log("Impossibile importare tvtap_extractor", "ERROR")


class TVTapBouquetManager:
    """
    Gestore intelligente per canali TVTap basato su analisi bouquet.

    Caratteristiche:
    - Scansione automatica bouquet per rilevare canali TVTap
    - Gestione dinamica authSign con refresh automatico
    - Cache intelligente per URL con scadenza
    - Rilevamento domini dinamici
    - Fallback automatici su errori
    """

    def __init__(self):
        self.bouquet_paths = [
            '/etc/enigma2/userbouquet.*.tv',
            '/etc/enigma2/bouquets.tv',
            '/etc/enigma2/*.tv'
        ]

        # Cache canali TVTap rilevati dai bouquet
        self.tvtap_channels = {}  # {service_ref: channel_info}
        self.url_cache = {}       # {original_url: cached_data}
        self.domain_cache = {}    # {domain: last_seen}

        # Lock per thread safety
        self.lock = threading.RLock()

        # Configurazione timing
        self.authsign_validity = 300  # 5 minuti validità authSign
        self.refresh_before_expiry = 60  # Refresh 1 minuto prima scadenza
        self.bouquet_scan_interval = 600  # Scansiona bouquet ogni 10 minuti

        # Pattern per rilevare canali TVTap
        self.tvtap_patterns = [
            r'tvtap://',
            r'tvtap_id:',
            r'rocktalk\.net',
            r'taptube\.net',
            r'authSign=',
            r'wmsAuthSign=',
            r'stream\.mardio\.link',
            r'TVTap',
            r'TVTAP'
        ]

        # Pattern per estrarre authSign
        self.authsign_patterns = [
            r'authSign=([^&]+)',
            r'wmsAuthSign=([^&]+)',
            r'auth=([^&]+)',
            r'token=([^&]+)',
            r'sig=([^&]+)'
        ]

        # Avvia scansione iniziale
        self._scan_bouquets()
        self._start_background_scanner()

        enhanced_log("TVTap Bouquet Manager inizializzato", "INFO")

    def _scan_bouquets(self):
        """Scansiona i bouquet per trovare canali TVTap."""
        enhanced_log("Inizio scansione bouquet per canali TVTap", "INFO")

        found_channels = {}

        try:
            import glob

            for pattern in self.bouquet_paths:
                for bouquet_file in glob.glob(pattern):
                    try:
                        channels = self._parse_bouquet_file(bouquet_file)
                        found_channels.update(channels)
                        enhanced_log(
                            f"Scansionato bouquet: {bouquet_file} - {len(channels)} canali TVTap", "DEBUG")
                    except Exception as e:
                        enhanced_log(
                            f"Errore scansione {bouquet_file}: {e}", "WARNING")

            with self.lock:
                self.tvtap_channels = found_channels

            enhanced_log(
                f"Scansione completata: {
                    len(found_channels)} canali TVTap trovati",
                "INFO")

        except Exception as e:
            enhanced_log(f"Errore scansione bouquet: {e}", "ERROR")

    def _parse_bouquet_file(self, bouquet_file):
        """Analizza un file bouquet per trovare canali TVTap."""
        channels = {}

        try:
            with open(bouquet_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Cerca linee SERVICE
            service_lines = re.findall(
                r'#SERVICE[^\n]*', content, re.IGNORECASE)

            for line in service_lines:
                try:
                    channel_info = self._parse_service_line(line)
                    if channel_info and self._is_tvtap_channel(channel_info):
                        service_ref = channel_info['service_ref']
                        channels[service_ref] = channel_info
                        enhanced_log(
                            f"Canale TVTap trovato: {
                                channel_info.get(
                                    'name', 'Unknown')}", "DEBUG")
                except Exception as e:
                    enhanced_log(f"Errore parsing linea service: {e}", "DEBUG")

        except Exception as e:
            enhanced_log(
                f"Errore lettura bouquet {bouquet_file}: {e}",
                "WARNING")

        return channels

    def _parse_service_line(self, line):
        """Analizza una linea SERVICE del bouquet."""
        # Formato: #SERVICE 4097:0:1:0:0:0:0:0:0:0:URL:NOME
        parts = line.split(':', 10)

        if len(parts) < 11:
            return None

        try:
            service_type = parts[0].replace('#SERVICE ', '').strip()
            url_part = parts[10] if len(parts) > 10 else ""
            name_part = parts[11] if len(parts) > 11 else ""

            # Decodifica URL
            if url_part:
                url_part = unquote(url_part)

            service_ref = ':'.join(parts[:10])

            return {
                'service_ref': service_ref,
                'service_type': service_type,
                'url': url_part,
                'name': name_part,
                'original_line': line
            }

        except Exception as e:
            enhanced_log(f"Errore parsing service line: {e}", "DEBUG")
            return None

    def _is_tvtap_channel(self, channel_info):
        """Verifica se un canale è di tipo TVTap."""
        if not channel_info:
            return False

        # Controlla URL
        url = channel_info.get('url', '').lower()
        name = channel_info.get('name', '').lower()

        # Verifica pattern TVTap
        for pattern in self.tvtap_patterns:
            if re.search(
                    pattern,
                    url,
                    re.IGNORECASE) or re.search(
                    pattern,
                    name,
                    re.IGNORECASE):
                return True

        return False

    def is_tvtap_service_ref(self, service_ref):
        """Check whether a service reference is a TVTap channel."""
        with self.lock:
            return service_ref in self.tvtap_channels

    def get_tvtap_channel_info(self, service_ref):
        """Get TVTap channel information from the service reference."""
        with self.lock:
            return self.tvtap_channels.get(service_ref)

    def resolve_tvtap_url(self, original_url, channel_name=None):
        """
        Resolve a TVTap URL handling dynamic authSign.

        Args:
            original_url (str): Original channel URL
            channel_name (str, optional): Channel name

        Returns:
            dict: {
                'resolved_url': str,
                'expires_at': datetime,
                'domain': str,
                'authsign': str
            }
        """
        enhanced_log(f"Resolving TVTap URL: {original_url[:100]}...", "INFO")

        with self.lock:
            # Check existing cache
            cache_key = self._get_cache_key(original_url)

            if cache_key in self.url_cache:
                cached_data = self.url_cache[cache_key]

                if self._is_cache_valid(cached_data):
                    enhanced_log("TVTap URL found in valid cache", "DEBUG")

                    # Start proactive refresh if needed
                    if self._needs_proactive_refresh(cached_data):
                        self._start_background_refresh(original_url, cache_key)

                    return cached_data
                else:
                    enhanced_log(
                        "TVTap cache expired, removing entry", "DEBUG")
                    del self.url_cache[cache_key]

            # Resolve new URL
            return self._resolve_fresh_url(
                original_url, channel_name, cache_key
            )

    def _resolve_fresh_url(self, original_url, channel_name, cache_key):
        """Resolve a fresh TVTap URL."""
        enhanced_log(f"Resolving fresh TVTap URL: {original_url}", "INFO")

        try:
            # Extract information from original URL
            # parsed_url = urlparse(original_url)
            # query_params = parse_qs(parsed_url.query)

            # Look for existing authSign
            current_authsign = None
            for pattern in self.authsign_patterns:
                match = re.search(pattern, original_url)
                if match:
                    current_authsign = match.group(1)
                    print(str(current_authsign))
                    break

            # Determine TVTap channel ID
            channel_id = self._extract_tvtap_id(original_url, channel_name)

            if not channel_id:
                enhanced_log(
                    "Unable to determine TVTap channel ID", "ERROR"
                )
                return None

            # Get new stream from TVTap
            new_stream_url = get_tvtap_stream(channel_id)

            if not new_stream_url:
                enhanced_log(
                    f"Unable to fetch stream for TVTap channel {channel_id}",
                    "ERROR"
                )
                return None

            # Parse new URL
            new_parsed = urlparse(new_stream_url)
            new_domain = new_parsed.netloc

            # Extract new authSign
            new_authsign = None
            for pattern in self.authsign_patterns:
                match = re.search(pattern, new_stream_url)
                if match:
                    new_authsign = match.group(1)
                    break

            # Calculate expiration
            expires_at = self._calculate_expiry(new_stream_url)

            # Create cache entry
            cache_data = {
                'resolved_url': new_stream_url,
                'original_url': original_url,
                'expires_at': expires_at,
                'domain': new_domain,
                'authsign': new_authsign,
                'channel_id': channel_id,
                'created_at': datetime.now(),
                'access_count': 0
            }

            # Save to cache
            self.url_cache[cache_key] = cache_data

            # Update domain cache
            self.domain_cache[new_domain] = datetime.now()

            enhanced_log(
                f"TVTap URL resolved: {new_domain} - authSign: {new_authsign[:10] if new_authsign else 'None'}...",
                "INFO"
            )
            enhanced_log(f"Expiration: {expires_at}", "DEBUG")

            return cache_data

        except Exception as e:
            enhanced_log(f"Error resolving TVTap URL: {e}", "ERROR")
            return None

    def _extract_tvtap_id(self, url, channel_name):
        """Extract the TVTap ID from URL or channel name."""

        # Pattern tvtap://ID
        match = re.search(r'tvtap://(\d+)', url)
        if match:
            return match.group(1)

        # Pattern tvtap_id:ID
        match = re.search(r'tvtap_id:(\d+)', url)
        if match:
            return match.group(1)

        # Check URL query parameters
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        for key in ['id', 'channel_id', 'ch_id']:
            if key in query_params:
                return query_params[key][0]

        # Try resolving by channel name
        if channel_name:
            try:
                channels = get_tvtap_channels()
                found_channel = find_channel_by_name(channel_name, channels)
                if found_channel:
                    return found_channel.get('id')
            except Exception as e:
                enhanced_log(
                    f"Error while searching channel by name: {e}",
                    "DEBUG"
                )

        return None

    def _calculate_expiry(self, url):
        """Calculate when the authSign expires."""
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)

            # Common timestamp keys
            timestamp_keys = ['ts', 'timestamp', 'time', 't', 'expires']

            for key in timestamp_keys:
                if key in query_params:
                    try:
                        ts_value = int(query_params[key][0])

                        # Looks like Unix timestamp
                        if ts_value > 1000000000:  # after year 2001
                            return datetime.fromtimestamp(ts_value)

                    except (ValueError, IndexError):
                        continue

            # Fallback default validity
            return datetime.now() + timedelta(seconds=self.authsign_validity)

        except Exception:
            return datetime.now() + timedelta(seconds=self.authsign_validity)

    def _is_cache_valid(self, cache_data):
        """Check whether cached data is still valid."""
        if not cache_data or 'expires_at' not in cache_data:
            return False

        return datetime.now() < cache_data['expires_at']

    def _needs_proactive_refresh(self, cache_data):
        """Check whether a proactive refresh is needed."""
        if not cache_data or 'expires_at' not in cache_data:
            return True

        time_to_expiry = (
            cache_data['expires_at'] - datetime.now()
        ).total_seconds()

        return time_to_expiry <= self.refresh_before_expiry

    def _start_background_refresh(self, original_url, cache_key):
        """Start background refresh thread."""
        def refresh_worker():
            try:
                enhanced_log(
                    f"Background TVTap refresh: {original_url[:50]}...",
                    "DEBUG"
                )

                time.sleep(5)  # small delay

                channel_name = None

                # Retrieve channel info from cache
                with self.lock:
                    if cache_key in self.url_cache:
                        # cache_data = self.url_cache[cache_key]

                        for service_ref, channel_info in self.tvtap_channels.items():
                            if channel_info.get('url') == original_url:
                                channel_name = channel_info.get('name')
                                break

                self._resolve_fresh_url(original_url, channel_name, cache_key)

            except Exception as e:
                enhanced_log(f"Background refresh error: {e}", "ERROR")

        thread = threading.Thread(target=refresh_worker, daemon=True)
        thread.start()

    def _get_cache_key(self, url):
        """Generate cache key for URL."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return hashlib.md5(base_url.encode()).hexdigest()

    def _start_background_scanner(self):
        """Start bouquet scanner in background."""
        def scanner_worker():
            while True:
                try:
                    time.sleep(self.bouquet_scan_interval)
                    self._scan_bouquets()
                except Exception as e:
                    enhanced_log(f"Error in bouquet scanner: {e}", "ERROR")

        scanner_thread = threading.Thread(target=scanner_worker, daemon=True)
        scanner_thread.start()
        enhanced_log("Bouquet scanner started in background", "INFO")

    def get_proxy_url_for_service(
            self,
            service_ref,
            base_proxy_url="http://127.0.0.1:7860"):
        """
        Generate proxy URL for a TVTap service reference.

        Args:
            service_ref (str): Enigma2 service reference
            base_proxy_url (str): Base proxy URL

        Returns:
            str: Proxy URL or None if error
        """
        channel_info = self.get_tvtap_channel_info(service_ref)
        if not channel_info:
            return None

        original_url = channel_info.get('url')
        if not original_url:
            return None

        # Resolve URL with updated authSign
        resolved_data = self.resolve_tvtap_url(
            original_url,
            channel_info.get('name')
        )

        if not resolved_data:
            return None

        resolved_url = resolved_data.get('resolved_url')
        if not resolved_url:
            return None

        # Build proxy URL
        proxy_url = f"{base_proxy_url}/proxy/m3u?url={quote(resolved_url)}"

        enhanced_log(
            f"TVTap proxy URL generated for: {
                channel_info.get(
                    'name',
                    'Unknown')}",
            "DEBUG")

        return proxy_url

    def cleanup_expired_cache(self):
        """Remove expired cache entries."""
        with self.lock:
            expired_keys = []

            for key, data in self.url_cache.items():
                if not self._is_cache_valid(data):
                    expired_keys.append(key)

            for key in expired_keys:
                del self.url_cache[key]

            if expired_keys:
                enhanced_log(
                    f"Removed {len(expired_keys)} expired TVTap cache entries",
                    "INFO"
                )

    def get_stats(self):
        """Return manager statistics."""
        with self.lock:
            total_cached = len(self.url_cache)
            valid_cached = sum(
                1 for data in self.url_cache.values()
                if self._is_cache_valid(data)
            )

            return {
                'tvtap_channels_found': len(self.tvtap_channels),
                'total_cached_urls': total_cached,
                'valid_cached_urls': valid_cached,
                'expired_cached_urls': total_cached - valid_cached,
                'known_domains': len(self.domain_cache)
            }

    def force_refresh_all(self):
        """Force refresh of all cached URLs."""
        with self.lock:
            urls_to_refresh = []

            for key, data in self.url_cache.items():
                original_url = data.get('original_url')
                if original_url:
                    urls_to_refresh.append((original_url, key))

            enhanced_log(
                f"Forcing refresh for {len(urls_to_refresh)} TVTap URLs",
                "INFO"
            )

            for original_url, cache_key in urls_to_refresh:
                try:
                    self._resolve_fresh_url(original_url, None, cache_key)
                except Exception as e:
                    enhanced_log(
                        f"Error refreshing {original_url}: {e}",
                        "ERROR"
                    )


tvtap_bouquet_manager = TVTapBouquetManager()


def is_tvtap_service_reference(service_ref):
    """
    Verifica se un service reference è un canale TVTap.
    """
    return tvtap_bouquet_manager.is_tvtap_service_ref(service_ref)


def get_tvtap_proxy_url_for_service(
        service_ref,
        base_proxy_url="http://127.0.0.1:7860"):
    """
    Get proxy URL for a TVTap service reference.
    """
    return tvtap_bouquet_manager.get_proxy_url_for_service(
        service_ref,
        base_proxy_url
    )


def resolve_tvtap_url_with_authsign(original_url, channel_name=None):
    """
    Resolve TVTap URL with dynamic authSign handling.
    """
    return tvtap_bouquet_manager.resolve_tvtap_url(
        original_url,
        channel_name
    )


def cleanup_tvtap_cache():
    """Clean expired TVTap cache entries."""
    tvtap_bouquet_manager.cleanup_expired_cache()


def get_tvtap_bouquet_stats():
    """Return TVTap bouquet manager statistics."""
    return tvtap_bouquet_manager.get_stats()


if __name__ == "__main__":
    # Test TVTap Bouquet Manager
    print("=== TVTap Bouquet Manager Test ===")

    # Initial stats
    stats = get_tvtap_bouquet_stats()
    print(f"Statistics: {stats}")

    # Test URL resolution
    test_url = "tvtap://850"
    print(f"\nTesting resolution: {test_url}")

    resolved = resolve_tvtap_url_with_authsign(test_url, "Rai 1")

    if resolved:
        print(f"Resolved URL: {resolved['resolved_url']}")
        print(f"Domain: {resolved['domain']}")
        print(f"AuthSign: {resolved.get('authsign', 'N/A')}")
        print(f"Expires at: {resolved['expires_at']}")
    else:
        print("Resolution failed")

    print("\n=== Test completed ===")
