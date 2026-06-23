# -*- coding: utf-8 -*-
# freeshot_extractor.py - Freeshot (https://www.freeshot.live/live-tv)
# Extractor for Enigma2
import re
from urllib.parse import urlparse, quote

try:
    import requests
except ImportError:
    requests = None

try:
    from ..StreamProxyLog import enhanced_log
except (ImportError, ValueError):
    try:
        from StreamProxyLog import enhanced_log
    except ImportError:
        def enhanced_log(msg, level="INFO", tag="FREESHOT"):
            print("[%s] [%s] %s" % (level, tag, msg))


class ExtractorError(Exception):
    pass


class FreeshotExtractor:
    def __init__(self, request_headers=None):
        self.request_headers = request_headers or {}
        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Referer": "https://thisnot.business/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        self.channel_map = {
            "26": "SkySportUnoIT",
            "206": "Rai-2",
            "208": "Rai-4",
            "209": "Canale5",
            "321": "MediasetExtra",
            "349": "RAIItaliaSudAfrica",  # Rai Italia
            "380": "RAISportIT",  # Rai Sport HD
            "383": "SkySport24IT",  # Sky Sport 24
            "385": "Supertennis",
            "318": "SkySportTennisIT",
            "423": "",  # FmNews Italia
            "428": "",  # EuroNews
            "459": "RaiNews",  # Rai News
            "642": "LA7",
            "643": "LA7D",
            "721": "MilanTV",  # Milan TV
            "763": "euro1it",
            "764": "euro2it",
            "775": "InterTV",  # Inter TV
            "784": "bikechannel",  # Bike Channel
            "785": "italia2",  # Italia2 Tv
            "skysportunoit": "SkySportUnoIT",
            "skysportarenait": "SkySportArenaIT",
            "skysportmaxit": "SkySportMaxIT",
            "skysporttennisit": "SkySportTennisIT",
            "skysport24it": "SkySport24IT",
            "skysportf1it": "SkySportF1IT",
            "skysportmotogpit": "SkySportMotoGPIT",
            "skysportgolfit": "SkySportGolfIT",
            "skysportcalcioit": "SkySportCalcioIT",
            "dazn1": "ZonaDAZN",
            "dazn": "ZonaDAZN",
            "zonadazn": "ZonaDAZN",
            "rai1": "Rai-1",
            "rai2": "Rai-2",
            "rai3": "Rai-3",
            "canale-5": "Canale5",
            "mediaset-extra-it": "MediasetExtra",
            "rai-sport-hd": "RAISportIT",
        }
        if requests:
            self.session = requests.Session()
            self.session.headers.update(self.base_headers)
        else:
            self.session = None

    def fix_video_url(self, m3u8_url, headers=None):
        try:
            if ('lovecdn.ru' in m3u8_url and
                'index.fmp4.m3u8' in m3u8_url and
                    'tracks-v1' not in m3u8_url):
                video_url = m3u8_url.replace(
                    'index.fmp4.m3u8', 'tracks-v1/index.fmp4.m3u8')
                enhanced_log(
                    "URL fixed from index.fmp4.m3u8 to tracks-v1/index.fmp4.m3u8",
                    "INFO",
                    "FREESHOT")
                return video_url
            return m3u8_url
        except Exception as e:
            enhanced_log("Error fixing video URL: %s" % e, "DEBUG", "FREESHOT")
            return m3u8_url

    def is_freeshot_link(self, url):
        if not url:
            return False
        url_lower = url.lower()
        return ('popcdn.day' in url_lower or
                'freeshot.live' in url_lower or
                'lovecdn.ru' in url_lower or
                'planetary.lovecdn.ru' in url_lower or
                'beautifulpeople.lovecdn.ru' in url_lower)

    def extract(self, url, **kwargs):
        if not self.session:
            raise ExtractorError("Requests module not available")

        # Handle direct lovecdn.ru URL
        if 'lovecdn.ru' in url.lower() and url.startswith('http'):
            enhanced_log(
                "FreeshotExtractor: Direct lovecdn.ru URL: %s..." % url[:100],
                "INFO",
                "FREESHOT")
            url = self.fix_video_url(url, self.base_headers)
            parsed = urlparse(url)
            base_url = "%s://%s/" % (parsed.scheme, parsed.netloc)
            token_match = re.search(r'token=([^&]+)', url)
            token = token_match.group(1) if token_match else 'default'
            channel_path = parsed.path.split(
                '/')[1] if len(parsed.path.split('/')) > 1 else 'SkySport24IT'
            embed_referer = "%s%s/embed.html?token=%s" % (
                base_url, channel_path, token)

            return {
                "resolved_url": url,
                "headers": {
                    "User-Agent": self.base_headers["User-Agent"],
                    "Referer": embed_referer,
                    "Origin": base_url.rstrip('/')
                },
                "stream_type": "fmp4",
                "base_url": base_url
            }

        # Handle already resolved player URL
        if 'popcdn.day/player/' in url.lower() and url.startswith('http'):
            enhanced_log(
                "FreeshotExtractor: Already resolved player URL: %s" % url,
                "INFO",
                "FREESHOT")

            try:
                response = self.session.get(url, timeout=15)
                if response.status_code == 200:
                    body = response.text

                    # Look for M3U8 URL in the page
                    patterns = [
                        r'"([^"]*\.m3u8[^"]*)"',
                        r"'([^']*\.m3u8[^']*)'",
                        r'source\s*:\s*["\']([^"\']+)["\']',
                        r'file\s*:\s*["\']([^"\']+)["\']'
                    ]

                    m3u8_url = None
                    for pattern in patterns:
                        matches = re.findall(pattern, body, re.IGNORECASE)
                        for match in matches:
                            if '.m3u8' in match or 'index.fmp4' in match:
                                m3u8_url = match
                                break
                        if m3u8_url:
                            break

                    if m3u8_url:
                        # Clean JSON escape characters
                        m3u8_url = m3u8_url.replace('\\/', '/')

                        if not m3u8_url.startswith('http'):
                            if m3u8_url.startswith('//'):
                                m3u8_url = 'https:' + m3u8_url
                            elif m3u8_url.startswith('/'):
                                m3u8_url = 'https://popcdn.day' + m3u8_url

                        m3u8_url = self.fix_video_url(
                            m3u8_url, self.base_headers)
                        enhanced_log(
                            "FreeshotExtractor: Extracted M3U8 -> %s" %
                            m3u8_url, "INFO", "FREESHOT")

                        return {
                            "resolved_url": m3u8_url,
                            "headers": {
                                "User-Agent": self.base_headers["User-Agent"],
                                "Referer": url,
                                "Origin": "https://popcdn.day"
                            },
                            "stream_type": "fmp4",
                            "base_url": "https://popcdn.day/"
                        }
            except Exception as e:
                enhanced_log(
                    "Error extracting from player page: %s" % e,
                    "DEBUG",
                    "FREESHOT")

            # Fallback
            channel_code = url.rstrip('/').split('/')[-1]
            m3u8_url = "https://popcdn.day/stream/%s/index.fmp4.m3u8" % channel_code
            m3u8_url = self.fix_video_url(m3u8_url, self.base_headers)
            enhanced_log(
                "FreeshotExtractor: Fallback M3U8 -> %s" % m3u8_url,
                "INFO",
                "FREESHOT")

            return {
                "resolved_url": m3u8_url,
                "headers": {
                    "User-Agent": self.base_headers["User-Agent"],
                    "Referer": url,
                    "Origin": "https://popcdn.day"
                },
                "stream_type": "fmp4",
                "base_url": "https://popcdn.day/"
            }

        # Extract channel code from freeshot.live URL
        channel_code = None
        if 'freeshot.live' in url.lower():
            parts = url.rstrip('/').split('/')
            if len(parts) >= 3:
                channel_name = parts[-2]
                channel_id = parts[-1]

                channel_code = self.channel_map.get(channel_id)
                if channel_code:
                    enhanced_log(
                        "ID: %s -> Channel: %s" % (channel_id, channel_code),
                        "DEBUG",
                        "FREESHOT")
                else:
                    normalized_name = channel_name.replace('-', '').lower()
                    channel_code = self.channel_map.get(normalized_name)
                    if channel_code:
                        enhanced_log(
                            "Name: %s -> %s" % (channel_name, channel_code),
                            "DEBUG",
                            "FREESHOT")
                    else:
                        channel_code = channel_name
                        enhanced_log(
                            "Fallback: %s -> %s" %
                            (channel_name, channel_code), "DEBUG", "FREESHOT")

        if channel_code:
            target_url = "https://popcdn.day/go.php?stream=%s" % quote(
                channel_code)
        elif not url.startswith('http'):
            target_url = "https://popcdn.day/go.php?stream=%s" % quote(url)
        elif "popcdn.day" not in url and 'lovecdn.ru' not in url:
            target_url = "https://popcdn.day/go.php?stream=%s" % quote(url)
        else:
            target_url = url

        enhanced_log("FreeshotExtractor: Resolving %s (code: %s)" %
                     (target_url, channel_code), "INFO", "FREESHOT")

        try:
            response = self.session.get(target_url, timeout=15)
            if response.status_code != 200:
                raise ExtractorError(
                    "Freeshot request failed: %s" % response.status_code)

            body = response.text
            match = re.search(
                r'frameborder="0"\s+src="([^"]+)"',
                body,
                re.IGNORECASE)

            if not match:
                raise ExtractorError("Freeshot iframe not found")

            iframe_url = match.group(1)
            m3u8_url = iframe_url.replace('embed.html', 'index.fmp4.m3u8')
            m3u8_url = self.fix_video_url(m3u8_url, self.base_headers)

            enhanced_log(
                "FreeshotExtractor: Resolved -> %s" % m3u8_url,
                "INFO",
                "FREESHOT")
            enhanced_log(
                "FreeshotExtractor: Iframe URL -> %s" % iframe_url,
                "DEBUG",
                "FREESHOT")

            result = {
                "resolved_url": m3u8_url,
                "headers": {
                    "User-Agent": self.base_headers["User-Agent"],
                    "Referer": iframe_url,
                    "Origin": "https://%s" % urlparse(iframe_url).netloc
                },
                "stream_type": "fmp4",
                "base_url": "https://%s/" % urlparse(iframe_url).netloc
            }

            enhanced_log(
                "FreeshotExtractor: Stream type -> fMP4",
                "DEBUG",
                "FREESHOT")
            return result
        except Exception as e:
            enhanced_log(
                "FreeshotExtractor error: %s" %
                e, "ERROR", "FREESHOT")
            import traceback
            enhanced_log(
                "FreeshotExtractor traceback: %s" % traceback.format_exc(),
                "DEBUG",
                "FREESHOT")
            raise ExtractorError("Freeshot extraction failed: %s" % str(e))

    def close(self):
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass


def is_freeshot_link(url):
    if not url:
        return False
    url_lower = url.lower()
    return ('popcdn.day' in url_lower or
            'freeshot.live' in url_lower or
            'lovecdn.ru' in url_lower or
            'planetary.lovecdn.ru' in url_lower or
            'beautifulpeople.lovecdn.ru' in url_lower)


def resolve_freeshot_url(url, headers=None):
    extractor = FreeshotExtractor(headers)
    try:
        return extractor.extract(url)
    finally:
        extractor.close()


freeshot_extractor = FreeshotExtractor()
