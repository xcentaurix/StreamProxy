# -*- coding: utf-8 -*-
"""
TVTap WMS Manager - Specialized handling for TVTap channels using wmsAuthSign
Manages TVTap streams using stream.mardio.link with wmsAuthSign tokens
"""

import re
import time
import base64
import json
import threading
import hashlib
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote, quote
from datetime import datetime, timedelta

try:
    from .StreamProxyLog import enhanced_log
    import requests
except ImportError:
    def enhanced_log(message, level="INFO", component="TVTAP_WMS"):
        print(f"[{level}] [{component}] {message}")
    import requests


class TVTapWMSManager:
    """
    Specialized manager for TVTap channels using wmsAuthSign.
    """

    def __init__(self):
        self.url_cache = {}       # {original_url: cached_data}
        self.domain_cache = {}    # {domain: last_seen}

        # Thread safety lock
        self.lock = threading.RLock()

        # Timing configuration
        self.default_validity = 1200  # 20 minutes default validity
        self.refresh_before_expiry = 120  # Refresh 2 minutes before expiry

        # Patterns for WMS TVTap detection
        self.wms_patterns = [
            r'stream\.mardio\.link',
            r'wmsAuthSign=',
            r'wmsauthsign='
        ]

        enhanced_log("TVTap WMS Manager initialized", "INFO")

    def is_wms_tvtap_url(self, url):
        """Check whether a URL is a WMS TVTap stream."""
        if not url:
            return False

        url_lower = url.lower()
        return any(re.search(pattern, url_lower)
                   for pattern in self.wms_patterns)

    def decode_wms_authsign(self, authsign):
        """
        Decode wmsAuthSign and extract embedded information.
        """
        try:
            decoded_bytes = base64.b64decode(authsign)
            decoded_str = decoded_bytes.decode('utf-8', errors='ignore')

            enhanced_log(
                f"Decoded wmsAuthSign: {decoded_str}",
                "DEBUG"
            )

            info = {}

            # Extract server time
            server_time_match = re.search(r'server_time=([^&]+)', decoded_str)
            if server_time_match:
                info['server_time'] = server_time_match.group(1)

            # Extract validity duration
            valid_minutes_match = re.search(r'validminutes=(\d+)', decoded_str)
            if valid_minutes_match:
                info['valid_minutes'] = int(valid_minutes_match.group(1))

            # Extract hash value
            hash_match = re.search(r'hash_value=([^&]+)', decoded_str)
            if hash_match:
                info['hash_value'] = hash_match.group(1)

            # Extract id
            id_match = re.search(r'id=(\d+)', decoded_str)
            if id_match:
                info['id'] = id_match.group(1)

            return info

        except Exception as e:
            enhanced_log(f"Error decoding wmsAuthSign: {e}", "ERROR")
            return None

    def calculate_expiry_from_authsign(self, authsign):
        """Calculate expiration time from decoded authSign."""
        try:
            decoded_info = self.decode_wms_authsign(authsign)

            if not decoded_info:
                return datetime.now() + timedelta(seconds=self.default_validity)

            if 'server_time' in decoded_info and 'valid_minutes' in decoded_info:
                server_time_str = decoded_info['server_time'].strip()
                valid_minutes = decoded_info['valid_minutes']

                server_time = None

                try:
                    server_time_str = ' '.join(server_time_str.split())

                    # Manual parsing: "11/2/2025 5:15:28 PM"
                    import re
                    match = re.match(
                        r'(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+)\s+(AM|PM)',
                        server_time_str
                    )

                    if match:
                        month, day, year, hour, minute, second, ampm = match.groups()

                        hour = int(hour)

                        if ampm == 'PM' and hour != 12:
                            hour += 12
                        elif ampm == 'AM' and hour == 12:
                            hour = 0

                        server_time = datetime(
                            int(year),
                            int(month),
                            int(day),
                            hour,
                            int(minute),
                            int(second)
                        )

                        enhanced_log(
                            f"Server time parsed: {server_time}",
                            "DEBUG"
                        )
                    else:
                        raise ValueError("Invalid date format")

                except (ValueError, AttributeError) as e:
                    # Parsing failed - token likely invalid
                    enhanced_log(
                        f"Server time parsing failed: {e}, forcing refresh",
                        "ERROR"
                    )
                    return datetime.now()  # force immediate refresh

                # Calculate expiration - server uses UTC, system uses local
                # time
                now = datetime.now()

                real_expires_at = server_time + \
                    timedelta(minutes=valid_minutes)

                # Adjust for UTC+1 (Italy)
                real_expires_at = real_expires_at + timedelta(hours=1)

                enhanced_log(
                    f"Server time: {server_time} UTC, Now: {now}, Expires: {real_expires_at}",
                    "DEBUG")

                # Check if authSign is too old (>24h)
                age_hours = (now - server_time).total_seconds() / 3600

                if age_hours > 24:
                    enhanced_log(
                        f"wmsAuthSign too old! Age: {
                            age_hours:.1f}h, forcing refresh",
                        "WARNING")
                    return now

                # Check if already expired
                if real_expires_at <= now:
                    enhanced_log(
                        f"wmsAuthSign expired! Expiry: {real_expires_at}, Now: {now}",
                        "WARNING")
                    return now

                enhanced_log(
                    f"wmsAuthSign valid until: {real_expires_at}",
                    "DEBUG"
                )
                return real_expires_at

            # Fallback: only valid_minutes
            if 'valid_minutes' in decoded_info:
                valid_minutes = decoded_info['valid_minutes']

                expires_at = datetime.now() + timedelta(minutes=valid_minutes)

                enhanced_log(
                    f"Fallback expiry from validminutes: {expires_at} ({valid_minutes} min)",
                    "DEBUG")

                return expires_at

            # Default fallback
            return datetime.now() + timedelta(seconds=self.default_validity)

        except Exception as e:
            enhanced_log(f"Error calculating expiry: {e}", "ERROR")
            return datetime.now() + timedelta(seconds=self.default_validity)

    def resolve_wms_tvtap_url(self, original_url, channel_name=None):
        """
        Resolve TVTap WMS URL ALWAYS regenerating (NO CACHE).
        """
        enhanced_log(
            f"Resolving TVTap WMS URL: {original_url[:100]}...",
            "INFO"
        )

        with self.lock:
            # NO CACHE - ALWAYS FRESH
            cache_key = self._get_cache_key(original_url)

            return self._resolve_fresh_wms_url(
                original_url,
                channel_name,
                cache_key
            )

    def _resolve_fresh_wms_url(self, original_url, channel_name, cache_key):
        """Resolves a new TVTap WMS URL, first checking if wmsAuthSign is still valid."""
        enhanced_log(
            f"Resolving fresh TVTap WMS URL: {original_url}",
            "INFO"
        )

        try:
            # FIRST CHECK IF EXISTING wmsAuthSign IS STILL VALID
            parsed_url = urlparse(original_url)
            query_params = parse_qs(parsed_url.query)

            existing_authsign = None
            if 'wmsAuthSign' in query_params:
                existing_authsign = query_params['wmsAuthSign'][0]

            # If wmsAuthSign exists, validate it first
            if existing_authsign:
                decoded_info = self.decode_wms_authsign(existing_authsign)
                expires_at = self.calculate_expiry_from_authsign(
                    existing_authsign)

                now = datetime.now()
                time_to_expiry = (expires_at - now).total_seconds()

                # If valid for more than 2 minutes, reuse it
                if time_to_expiry > 120:
                    enhanced_log(
                        f"✅ Existing wmsAuthSign valid for {
                            time_to_expiry /
                            60:.1f} min, reusing it",
                        "INFO")

                    cache_data = {
                        'resolved_url': original_url,
                        'original_url': original_url,
                        'expires_at': expires_at,
                        'domain': parsed_url.netloc,
                        'authsign': existing_authsign,
                        'decoded_info': decoded_info,
                        'channel_name': channel_name,
                        'created_at': datetime.now(),
                        'access_count': 0,
                        'was_refreshed': False
                    }

                    self.url_cache[cache_key] = cache_data
                    self.domain_cache[parsed_url.netloc] = datetime.now()

                    return cache_data

                else:
                    enhanced_log(
                        f"⚠️ wmsAuthSign expires in {
                            time_to_expiry /
                            60:.1f} min, regenerating",
                        "WARNING")

            # FORCE REGENERATION OF wmsAuthSign VIA TVTap API
            enhanced_log(
                "🔄 Forcing wmsAuthSign regeneration via TVTap API",
                "INFO"
            )

            # Extract channel name
            channel_to_search = self._extract_channel_name_from_url(
                original_url, channel_name
            )

            if not channel_to_search:
                enhanced_log("❌ Unable to determine channel name", "ERROR")
                return None

            # USE TVTap API TO GET FRESH STREAM
            fresh_stream_url = self._get_fresh_tvtap_stream(channel_to_search)

            if not fresh_stream_url or not self.is_wms_tvtap_url(
                    fresh_stream_url):
                enhanced_log("❌ Unable to get stream from TVTap API", "ERROR")
                return None

            enhanced_log("✅ Fresh stream obtained from TVTap API", "INFO")

            # Parse new URL
            parsed_url = urlparse(fresh_stream_url)
            query_params = parse_qs(parsed_url.query)

            # Extract fresh wmsAuthSign
            wms_authsign = None
            if 'wmsAuthSign' in query_params:
                wms_authsign = query_params['wmsAuthSign'][0]

            if not wms_authsign:
                enhanced_log("❌ New URL does not contain wmsAuthSign", "ERROR")
                return None

            # Decode and calculate expiry
            decoded_info = self.decode_wms_authsign(wms_authsign)
            expires_at = self.calculate_expiry_from_authsign(wms_authsign)

            # ALWAYS USE FRESH URL
            resolved_url = fresh_stream_url
            domain = parsed_url.netloc

            enhanced_log(
                f"🔑 Fresh wmsAuthSign: {wms_authsign[:20]}..., expires: {expires_at}",
                "INFO"
            )

            # Create cache data
            cache_data = {
                'resolved_url': resolved_url,
                'original_url': original_url,
                'expires_at': expires_at,
                'domain': domain,
                'authsign': wms_authsign,
                'decoded_info': decoded_info,
                'channel_name': channel_name,
                'created_at': datetime.now(),
                'access_count': 0,
                'was_refreshed': True
            }

            # Save cache
            self.url_cache[cache_key] = cache_data

            # Update domain cache
            self.domain_cache[domain] = datetime.now()

            enhanced_log(f"TVTap WMS URL resolved: {domain}", "INFO")
            enhanced_log(f"Expiry: {expires_at}", "DEBUG")

            if decoded_info:
                enhanced_log(f"Decoded info: {decoded_info}", "DEBUG")

            return cache_data

        except Exception as e:
            enhanced_log(f"Error resolving TVTap WMS URL: {e}", "ERROR")
            return None

    def _is_cache_valid(self, cache_data):
        """Checks whether cached data is still valid."""
        if not cache_data or 'expires_at' not in cache_data:
            return False

        return datetime.now() < cache_data['expires_at']

    def _needs_proactive_refresh(self, cache_data):
        """Checks whether a proactive refresh is needed."""
        if not cache_data or 'expires_at' not in cache_data:
            return True

        time_to_expiry = (
            cache_data['expires_at'] -
            datetime.now()).total_seconds()
        return time_to_expiry <= self.refresh_before_expiry

    def _start_background_refresh(self, original_url, channel_name, cache_key):
        """Starts background refresh with wmsAuthSign regeneration."""
        def refresh_worker():
            try:
                enhanced_log(
                    f"Background refresh TVTap WMS URL: {original_url[:50]}...", "DEBUG")
                time.sleep(5)  # Small delay

                # Remove from cache to force regeneration
                with self.lock:
                    if cache_key in self.url_cache:
                        del self.url_cache[cache_key]
                        enhanced_log(
                            "TVTap WMS cache removed for proactive refresh", "DEBUG")

                # Force regeneration by calling resolve_wms_tvtap_url
                # This will trigger validation and wmsAuthSign regeneration
                refreshed_data = self.resolve_wms_tvtap_url(
                    original_url, channel_name)

                if refreshed_data and refreshed_data.get('was_refreshed'):
                    enhanced_log(
                        "✅ Background refresh completed successfully", "INFO")
                else:
                    enhanced_log(
                        "⚠️ Background refresh did not regenerate wmsAuthSign",
                        "WARNING")

            except Exception as e:
                enhanced_log(f"Error in WMS background refresh: {e}", "ERROR")

        thread = threading.Thread(target=refresh_worker, daemon=True)
        thread.start()

    def _extract_channel_name_from_url(self, url, provided_name=None):
        """Extracts channel name from URL with multiple fallback strategies."""
        if provided_name:
            return provided_name.strip()

        try:
            parsed = urlparse(url)
            path_parts = parsed.path.split('/')

            # Attempt 1: it-*.stream pattern
            for part in path_parts:
                if part.startswith('it-') and '.stream' in part:
                    channel_name = part.replace(
                        'it-', '').replace('.stream', '')
                    channel_name = channel_name.replace('-', ' ').title()
                    enhanced_log(
                        f"Channel name extracted (it- pattern): {channel_name}", "DEBUG")
                    return channel_name

            # Attempt 2: filename without extension
            if path_parts:
                filename = path_parts[-1].replace('.m3u8',
                                                  '').replace('playlist',
                                                              '').replace('.stream',
                                                                          '')
                filename = filename.strip('-').strip('_').strip()
                if filename and len(filename) > 2:
                    channel_name = filename.replace(
                        '-', ' ').replace('_', ' ').title()
                    enhanced_log(
                        f"Channel name extracted (filename): {channel_name}", "DEBUG")
                    return channel_name

            # Attempt 3: match against static list
            try:
                from .extractor.tvtap_extractor import get_static_italian_channels
                channels = get_static_italian_channels()
                url_lower = url.lower()

                for ch in channels:
                    ch_name_lower = ch['name'].lower().replace(' ', '')
                    if ch_name_lower in url_lower:
                        enhanced_log(
                            f"Channel name found (static match): {
                                ch['name']}", "DEBUG")
                        return ch['name']
            except Exception as e:
                enhanced_log(f"Static list fallback failed: {e}", "DEBUG")

            enhanced_log(
                "Unable to extract channel name from URL",
                "WARNING")
            return None

        except Exception as e:
            enhanced_log(f"Error extracting channel name: {e}", "ERROR")
            return None

    def _get_fresh_tvtap_stream(self, channel_name):
        """Gets a new stream URL from tvtap_extractor with detailed logging."""
        try:
            from .extractor.tvtap_extractor import get_tvtap_channels, find_channel_by_name, get_tvtap_stream

            enhanced_log(
                f"🔄 Searching new stream for channel: {channel_name}",
                "INFO"
            )

            enhanced_log("📡 Requesting TVTap API channel list...", "DEBUG")
            channels = get_tvtap_channels()
            if not channels:
                enhanced_log(
                    "❌ No channels available from TVTap API", "ERROR"
                )
                return None

            enhanced_log(
                f"✅ Received {len(channels)} channels from TVTap API",
                "DEBUG"
            )

            # Find channel by name
            enhanced_log(
                f"🔍 Searching channel '{channel_name}' in list...",
                "DEBUG"
            )
            found_channel = find_channel_by_name(channel_name, channels)
            if not found_channel:
                enhanced_log(
                    f"❌ Channel '{channel_name}' not found in TVTap list",
                    "WARNING"
                )

                # Log first 5 channels for debugging
                sample = [ch.get('name', 'N/A') for ch in channels[:5]]
                enhanced_log(
                    f"📋 Available channels (sample): {sample}",
                    "DEBUG"
                )
                return None

            channel_id = found_channel.get('id')
            if not channel_id:
                enhanced_log(
                    f"❌ Missing ID for channel '{channel_name}'",
                    "ERROR"
                )
                return None

            enhanced_log(
                f"✅ Channel found: {
                    found_channel.get('name')} (ID: {channel_id})",
                "INFO")

            # Get stream URL
            enhanced_log(
                f"📡 Requesting stream URL for ID {channel_id}...",
                "DEBUG"
            )
            stream_url = get_tvtap_stream(channel_id)

            if stream_url:
                enhanced_log(
                    f"✅ New stream URL obtained: {stream_url[:80]}...",
                    "INFO"
                )
                return stream_url
            else:
                enhanced_log(
                    f"❌ Unable to get stream URL for {channel_name}",
                    "ERROR"
                )
                return None

        except ImportError as e:
            enhanced_log(f"❌ tvtap_extractor not available: {e}", "ERROR")
            return None

        except Exception as e:
            enhanced_log(f"❌ Error getting TVTap stream: {e}", "ERROR")
            import traceback
            enhanced_log(f"Stack trace: {traceback.format_exc()}", "DEBUG")
            return None

    def _get_cache_key(self, url):
        """Generates cache key for URL."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return hashlib.md5(base_url.encode()).hexdigest()

    def get_proxy_url_for_wms_url(
            self,
            original_url,
            channel_name=None,
            base_proxy_url="http://127.0.0.1:7860"):
        """
        Generates proxy URL for a TVTap WMS URL.
        """
        if not self.is_wms_tvtap_url(original_url):
            return None

        # Resolve URL with updated authSign
        resolved_data = self.resolve_wms_tvtap_url(original_url, channel_name)
        if not resolved_data:
            return None

        resolved_url = resolved_data.get('resolved_url')
        if not resolved_url:
            return None

        # Build proxy URL
        proxy_url = f"{base_proxy_url}/proxy/m3u?url={quote(resolved_url)}"

        enhanced_log(
            f"TVTap WMS proxy URL generated for: {channel_name or 'Unknown'}",
            "DEBUG"
        )
        return proxy_url

    def cleanup_expired_cache(self):
        """Cleans expired cache entries."""
        with self.lock:
            expired_keys = []

            for key, data in self.url_cache.items():
                if not self._is_cache_valid(data):
                    expired_keys.append(key)

            for key in expired_keys:
                del self.url_cache[key]

            if expired_keys:
                enhanced_log(
                    f"Cleaned {
                        len(expired_keys)} expired TVTap WMS cache entries",
                    "INFO")

    def get_stats(self):
        """Returns manager statistics."""
        with self.lock:
            total_cached = len(self.url_cache)
            valid_cached = sum(
                1 for data in self.url_cache.values()
                if self._is_cache_valid(data)
            )

            return {
                'total_cached_urls': total_cached,
                'valid_cached_urls': valid_cached,
                'expired_cached_urls': total_cached - valid_cached,
                'known_domains': len(self.domain_cache)
            }

    def force_refresh_all(self):
        """Forces refresh of all cached URLs."""
        with self.lock:
            # For now, simply clears entire cache
            old_count = len(self.url_cache)
            self.url_cache.clear()

            enhanced_log(
                f"TVTap WMS cache cleared: {old_count} URLs removed",
                "INFO"
            )


# Global manager instance
tvtap_wms_manager = TVTapWMSManager()


def is_wms_tvtap_url(url):
    """Checks if URL is a TVTap WMS stream."""
    return tvtap_wms_manager.is_wms_tvtap_url(url)


def resolve_wms_tvtap_url(original_url, channel_name=None):
    """Resolves TVTap WMS URL with dynamic wmsAuthSign handling."""
    return tvtap_wms_manager.resolve_wms_tvtap_url(original_url, channel_name)


def get_wms_proxy_url(
        original_url,
        channel_name=None,
        base_proxy_url="http://127.0.0.1:7860"):
    """Returns proxy URL for a TVTap WMS stream."""
    return tvtap_wms_manager.get_proxy_url_for_wms_url(
        original_url, channel_name, base_proxy_url
    )


def cleanup_wms_cache():
    """Cleans expired TVTap WMS cache."""
    tvtap_wms_manager.cleanup_expired_cache()


def get_wms_stats():
    """Returns TVTap WMS statistics."""
    return tvtap_wms_manager.get_stats()


if __name__ == "__main__":
    # WMS manager test
    print("=== TVTap WMS Manager Test ===")

    test_url = (
        "http://stream.mardio.link:8081/live/it-babytv.stream/"
        "playlist.m3u8?wmsAuthSign="
        "c2VydmVyX3RpbWU9OS82LzIwMjUgNToyNjozMyBBTSZoYXNoX3ZhbHVl="
    )

    print(f"Test URL: {test_url}")
    print(f"Is WMS TVTap: {is_wms_tvtap_url(test_url)}")

    if is_wms_tvtap_url(test_url):
        resolved = resolve_wms_tvtap_url(test_url, "Baby TV")

        if resolved:
            print(f"Resolved: {resolved['resolved_url']}")
            print(f"Domain: {resolved['domain']}")
            print(f"AuthSign: {resolved.get('authsign', 'N/A')[:20]}...")
            print(f"Expires: {resolved['expires_at']}")
            print(f"Decoded info: {resolved.get('decoded_info', {})}")
        else:
            print("Resolution failed")

    stats = get_wms_stats()
    print(f"Statistics: {stats}")

    print("\n=== Test completed ===")
