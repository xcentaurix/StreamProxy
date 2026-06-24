# -*- coding: utf-8 -*-
# vix_extractor.py - VixCloud/VixSrc HLS extractor for Enigma2
import json
import re
import time
import html
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse

try:
    import curl_cffi.requests as requests
except ImportError:
    try:
        import requests
        from requests.adapters import HTTPAdapter
    except ImportError:
        requests = None
        HTTPAdapter = None

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
            print("[%s] [%s] %s" % (level, tag, msg))


class VixExtractorError(Exception):
    pass


class VixSrcExtractor:
    """VixCloud/VixSrc HLS extractor for Enigma2, aligned with EasyProxy source."""

    def __init__(self):
        self.base_headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"),
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.5",
            "accept-encoding": "gzip, deflate",
            "connection": "keep-alive",
        }
        self.mediaflow_endpoint = "hls_manifest_proxy"
        self.is_vixsrc = True
        self.session = None
        self.using_curl_cffi = False

        if requests:
            # Try curl_cffi first to avoid detection
            try:
                if hasattr(
                        requests,
                        'get') and 'curl_cffi' in str(
                        type(requests)):
                    self.using_curl_cffi = True
                    self.session = requests.Session(impersonate="chrome120")
                    enhanced_log(
                        "Using curl_cffi to avoid detection", "INFO", "VIX")
                else:
                    self.session = requests.Session()
                    self.session.verify = False
            except Exception:
                self.session = requests.Session()
                self.session.verify = False

            if self.session and not self.using_curl_cffi:
                self.session.headers.update(self.base_headers)
                if Retry and HTTPAdapter:
                    retry = Retry(
                        total=3,
                        backoff_factor=1,
                        status_forcelist=[429, 500, 502, 503, 504],
                        allowed_methods=["HEAD", "GET"],
                    )
                    adapter = HTTPAdapter(
                        max_retries=retry, pool_connections=4, pool_maxsize=8)
                    self.session.mount("http://", adapter)
                    self.session.mount("https://", adapter)

    def _fresh_headers(self, **extra_headers):
        headers = self.base_headers.copy()
        headers.update(extra_headers)
        return headers

    @staticmethod
    def _normalize_base_site(url):
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise VixExtractorError("Invalid VixSrc URL")
        return "%s://%s" % (parsed.scheme, parsed.netloc)

    def _request(
            self,
            url,
            headers=None,
            timeout=12,
            retries=3,
            initial_delay=1):
        if not self.session:
            raise VixExtractorError("requests not available")

        final_headers = headers or self._fresh_headers()
        last_error = None

        for attempt in range(retries):
            try:
                enhanced_log("GET %d/%d %s..." %
                             (attempt + 1, retries, url[:120]), "DEBUG", "VIX")

                if self.using_curl_cffi:
                    response = self.session.get(
                        url,
                        headers=final_headers,
                        timeout=timeout,
                        allow_redirects=True
                    )
                else:
                    response = self.session.get(
                        url,
                        headers=final_headers,
                        timeout=timeout,
                        verify=False,
                        allow_redirects=True
                    )

                if response.status_code == 200:
                    return response
                if response.status_code == 404:
                    raise VixExtractorError(
                        "VixSrc content not found (404): %s" % url)

                last_error = "HTTP %s" % response.status_code
                enhanced_log("HTTP %s on %s" %
                             (response.status_code, url[:80]), "WARNING", "VIX")

            except VixExtractorError:
                raise
            except Exception as exc:
                last_error = exc
                enhanced_log("Connection error attempt %d on %s: %s" %
                             (attempt + 1, url[:80], exc), "WARNING", "VIX")

            if attempt < retries - 1:
                time.sleep(initial_delay * (2 ** attempt))

        raise VixExtractorError(
            "Request failed for %s: %s" %
            (url, last_error))

    @staticmethod
    def _raise_if_embed_expired(url):
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
            raise VixExtractorError(
                "Expired VixSrc embed URL (expired at %d, current %d). "
                "Use original /movie/ or /tv/ URL to refresh tokens." %
                (expires_ts, now_ts))

    def _resolve_embed_url_from_api(self, url, parsed_url):
        """Resolve the current embed URL via VixSrc JSON API."""
        site_url = self._normalize_base_site(url)
        path_parts = [p for p in parsed_url.path.strip("/").split("/") if p]

        api_url = None
        if len(path_parts) >= 2 and path_parts[0] == "movie":
            api_url = "%s/api/movie/%s" % (site_url, path_parts[1])
        elif len(path_parts) >= 4 and path_parts[0] == "tv":
            api_url = "%s/api/tv/%s/%s/%s" % (site_url,
                                              path_parts[1],
                                              path_parts[2],
                                              path_parts[3])

        if not api_url:
            return None

        try:
            response = self._request(
                api_url,
                headers=self._fresh_headers(
                    accept="application/json, text/plain, */*",
                    referer=url),
                retries=2)
        except VixExtractorError as e:
            enhanced_log("API request failed: %s" % e, "WARNING", "VIX")
            return None

        try:
            enhanced_log("VixSrc API raw response (first 500): %s..." %
                         response.text[:500], "DEBUG", "VIX")
            payload = json.loads(response.text)
        except (ValueError, json.JSONDecodeError):
            # Handle HTML escaped or wrapped
            text = None
            pre_match = re.search(
                r"<pre[^>]*>(.*?)</pre>",
                response.text,
                re.DOTALL)
            if pre_match:
                text = html.unescape(pre_match.group(1))
            else:
                stripped = response.text.strip()
                if stripped.startswith("{"):
                    text = html.unescape(stripped)

            if text:
                try:
                    payload = json.loads(text)
                except (ValueError, json.JSONDecodeError) as exc2:
                    enhanced_log(
                        "Invalid API response from %s: %s" %
                        (api_url, exc2), "ERROR", "VIX")
                    return None
            else:
                enhanced_log(
                    "Invalid API response from %s: response is not JSON" %
                    api_url, "ERROR", "VIX")
                return None

        embed_path = payload.get("src")
        if not embed_path:
            enhanced_log(
                "Missing embed src in API response from %s" %
                api_url, "WARNING", "VIX")
            return None

        return urljoin(site_url, embed_path)

    def _version(self, site_url):
        """Get version for Inertia headers."""
        try:
            response = self._request(
                "%s/request-a-title" %
                site_url,
                headers=self._fresh_headers(
                    referer=site_url +
                    "/",
                    origin=site_url),
                retries=2,
                timeout=8)
            match = re.search(
                r'<div[^>]*id="app"[^>]*data-page="([^"]*)"[^>]*>',
                response.text,
                re.IGNORECASE)
            if not match:
                enhanced_log(
                    "Version not found, using fallback",
                    "WARNING",
                    "VIX")
                return "unknown"

            try:
                data = json.loads(match.group(1).replace("&quot;", '"'))
                return data.get("version", "unknown")
            except (KeyError, ValueError, AttributeError, json.JSONDecodeError):
                enhanced_log(
                    "Version parsing failed, using fallback",
                    "WARNING",
                    "VIX")
                return "unknown"

        except Exception as exc:
            enhanced_log(
                "Error retrieving version: %s, using fallback" %
                str(exc)[
                    :100], "WARNING", "VIX")
            return "unknown"

    def _extract_playlist_from_embed(self, script_content):
        """Extract playlist URL from the current embed structure, with legacy fallback."""
        master_playlist_match = re.search(
            r"window\.masterPlaylist\s*=\s*\{.*?params\s*:\s*\{(?P<params>.*?)\}\s*,\s*url\s*:\s*['\"](?P<url>[^'\"]+)['\"]",
            script_content,
            re.DOTALL,
        )
        if master_playlist_match:
            params_block = master_playlist_match.group("params")
            playlist_url = master_playlist_match.group(
                "url").replace("\\/", "/")

            token_match = re.search(
                r"['\"]token['\"]\s*:\s*['\"]([^'\"]+)['\"]",
                params_block)
            expires_match = re.search(
                r"['\"]expires['\"]\s*:\s*['\"](\d+)['\"]", params_block)
            asn_match = re.search(
                r"['\"]asn['\"]\s*:\s*['\"]([^'\"]*)['\"]",
                params_block)

            if token_match and expires_match:
                return self._append_playlist_query(
                    playlist_url,
                    token=token_match.group(1),
                    expires=expires_match.group(1),
                    can_play_fhd=(
                        "window.canPlayFHD = true" in script_content or "canPlayFHD" in script_content),
                    asn=asn_match.group(1) if asn_match and asn_match.group(1) else None,
                )

        # Legacy fallback
        token_match = re.search(
            r"['\"]token['\"]\s*:\s*['\"](\w+)['\"]",
            script_content)
        expires_match = re.search(
            r"['\"]expires['\"]\s*:\s*['\"](\d+)['\"]",
            script_content)
        server_url_match = re.search(
            r"url\s*:\s*['\"]([^'\"]+)['\"]", script_content)

        if not all([token_match, expires_match, server_url_match]):
            token_match = token_match or re.search(
                r"token['\"]\s*:\s*['\"]([^'\"]+)['\"]", script_content)
            expires_match = expires_match or re.search(
                r"expires['\"]\s*:\s*['\"](\d+)['\"]", script_content)

        if not all([token_match, expires_match, server_url_match]):
            raise VixExtractorError(
                "Missing mandatory parameters in JS script (token/expires/url)")

        asn_match = re.search(
            r"['\"]asn['\"]\s*:\s*['\"]([^'\"]*)['\"]",
            script_content)
        return self._append_playlist_query(
            server_url_match.group(1),
            token=token_match.group(1),
            expires=expires_match.group(1),
            can_play_fhd=(
                "window.canPlayFHD = true" in script_content or "canPlayFHD" in script_content),
            asn=asn_match.group(1) if asn_match and asn_match.group(1) else None,
        )

    def _append_playlist_query(
            self,
            base_url,
            token,
            expires,
            can_play_fhd=False,
            asn=None):
        base_url = (base_url or "").replace("\\/", "/")
        parsed = urlparse(base_url)
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        query_params.extend([("token", str(token)), ("expires", str(expires))])
        if can_play_fhd:
            query_params.append(("h", "1"))
        query_params.append(("lang", "it"))
        if asn:
            query_params.append(("asn", str(asn)))
        return urlunparse(parsed._replace(query=urlencode(query_params)))

    def _find_playlist_script(self, html):
        scripts = re.findall(
            r"<script\b[^>]*>(.*?)</script>",
            html,
            re.IGNORECASE | re.DOTALL)
        for script in scripts:
            if "window.masterPlaylist" in script or "'token':" in script or '"token":' in script:
                return script
        match = re.search(
            r"<body[^>]*>.*?<script[^>]*>(.*?)</script>",
            html,
            re.DOTALL | re.IGNORECASE)
        return match.group(1) if match else None

    def _extract_from_html(self, html):
        """Extract playlist URL from HTML via script content, then data-page JSON."""
        script = self._find_playlist_script(html)
        if script:
            try:
                return self._extract_playlist_from_embed(script)
            except VixExtractorError:
                # Not critical, try fallback
                pass

        # Fallback: data-page JSON
        match = re.search(
            r'<div[^>]*id="app"[^>]*data-page="([^"]*)"[^>]*>',
            html,
            re.IGNORECASE)
        if not match:
            return None

        try:
            data = json.loads(match.group(1).replace("&quot;", '"'))

            def _search_json(obj):
                results = {}
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        kl = k.lower()
                        if kl in (
                                "token",
                                "expires",
                                "url",
                                "src") and isinstance(
                                v,
                                str):
                            results[kl] = v
                        elif not (results.get("token") and results.get("expires") and results.get("url")):
                            results.update(_search_json(v))
                elif isinstance(obj, list):
                    for item in obj:
                        results.update(_search_json(item))
                        if results.get("token") and results.get(
                                "expires") and results.get("url"):
                            break
                return results

            found = _search_json(data)
            if found.get("token") and found.get(
                    "expires") and found.get("url"):
                parsed = urlparse(found["url"])
                query_params = parse_qsl(parsed.query, keep_blank_values=True)
                query_params.extend(
                    [("token", found["token"]), ("expires", found["expires"])])
                if "canPlayFHD" in html:
                    query_params.append(("h", "1"))
                query_params.append(("lang", "it"))
                return urlunparse(
                    parsed._replace(
                        query=urlencode(query_params)))
        except (json.JSONDecodeError, Exception) as exc:
            enhanced_log(
                "Fallback JSON parsing error: %s" %
                str(exc)[
                    :100], "DEBUG", "VIX")
        return None

    def extract(self, url):
        """Extract the master HLS playlist from VixSrc/VixCloud."""
        enhanced_log("START extract: %s..." % url[:80], "INFO", "VIX")
        try:
            if not url.startswith("http"):
                url = "https://" + re.sub(r"^//", "", url)

            # Rewrite calpezz8.space as in the server proxy
            url = url.replace(
                "vixsrc.to",
                "calpezz8.space").replace(
                "vixcloud.co",
                "calpezz8.space")

            parsed_url = urlparse(url)
            response = None

            # Passthrough: URL already resolved
            if "/playlist/" in parsed_url.path:
                enhanced_log(
                    "URL already resolved - direct passthrough",
                    "INFO",
                    "VIX")
                return {
                    "resolved_url": url,
                    "destination_url": url,
                    "headers": self._fresh_headers(),
                    "request_headers": self._fresh_headers(),
                    "mediaflow_endpoint": self.mediaflow_endpoint,
                }

            if "/embed/" in parsed_url.path:
                self._raise_if_embed_expired(url)
                if parsed_url.netloc.lower().endswith("vixcloud.co"):
                    vix_url = url.replace("vixcloud.co", "vixsrc.to")
                    enhanced_log(
                        "Rewrite URL to vixsrc.to: %s" %
                        vix_url, "INFO", "VIX")
                else:
                    vix_url = url
                response = self._request(
                    vix_url, headers=self._fresh_headers(
                        referer=self._normalize_base_site(vix_url) + "/"), )

            elif "iframe" in url:
                site_url = url.split("/iframe")[0]
                version = self._version(site_url)
                inertia_headers = self._fresh_headers(
                    **{"x-inertia": "true", "x-inertia-version": version})
                response = self._request(url, headers=inertia_headers)
                iframe_match = re.search(
                    r'<iframe[^>]*src="([^"]*)"[^>]*>',
                    response.text,
                    re.IGNORECASE)
                if not iframe_match:
                    raise VixExtractorError("No iframe found in response")
                iframe_url = urljoin(site_url + "/", iframe_match.group(1))
                response = self._request(iframe_url, headers=inertia_headers)

            elif "/movie/" in parsed_url.path or "/tv/" in parsed_url.path:
                # Try API first, then direct fallback
                embed_url = self._resolve_embed_url_from_api(url, parsed_url)
                if embed_url:
                    try:
                        response = self._request(
                            embed_url, headers=self._fresh_headers(
                                referer=url), retries=2)
                    except VixExtractorError:
                        enhanced_log(
                            "Embed URL failed, trying direct request", "WARNING", "VIX")
                        response = self._request(url, retries=2)
                else:
                    response = self._request(url, retries=2)

            else:
                raise VixExtractorError("Unsupported VixSrc URL type")

            if response.status_code != 200:
                raise VixExtractorError(
                    "URL component extraction failed, invalid request")

            final_url = self._extract_from_html(response.text)
            if not final_url:
                raise VixExtractorError("No playlist data found in response")

            # Rewrite vixcloud.co/vixsrc.to → calpezz8.space in the final URL
            # as in the server proxy
            final_url = final_url.replace(
                "vixcloud.co", "calpezz8.space").replace(
                "vixsrc.to", "calpezz8.space")
            stream_url = url.replace(
                "vixcloud.co",
                "calpezz8.space").replace(
                "vixsrc.to",
                "calpezz8.space")

            enhanced_log("SUCCESS: %s..." % final_url[:120], "INFO", "VIX")

            # Enigma2 optimisation: Download M3U8 with robust error handling
            m3u8_content = None
            try:
                enhanced_log(
                    "Downloading M3U8 content for AES key extraction...",
                    "INFO",
                    "VIX")
                m3u8_response = self._request(
                    final_url,
                    headers=self._fresh_headers(Referer=stream_url),
                    timeout=8,  # Reduced timeout for Enigma2
                    retries=2   # Fewer retries to avoid blocking
                )

                if m3u8_response.status_code == 200:
                    content_text = m3u8_response.text

                    # Verify it is a valid M3U8
                    if content_text.strip().startswith('#EXTM3U'):
                        m3u8_content = content_text
                        enhanced_log(
                            "M3U8 downloaded: %d characters" %
                            len(m3u8_content), "INFO", "VIX")

                        # Log for AES key debugging
                        if '#EXT-X-KEY' in m3u8_content:
                            enhanced_log(
                                "AES key found in M3U8", "INFO", "VIX")
                    else:
                        enhanced_log(
                            "Content is not a valid M3U8", "WARNING", "VIX")
                else:
                    enhanced_log(
                        "M3U8 download failed: HTTP %s" %
                        m3u8_response.status_code, "WARNING", "VIX")
            except Exception as m3u8_error:
                enhanced_log(
                    "M3U8 download error (non-critical): %s" %
                    str(m3u8_error)[
                        :100], "DEBUG", "VIX")

            result = {
                "resolved_url": final_url,
                "destination_url": final_url,
                "headers": self._fresh_headers(Referer=stream_url),
                "request_headers": self._fresh_headers(Referer=stream_url),
                "mediaflow_endpoint": self.mediaflow_endpoint,
            }

            # Add M3U8 content if available
            if m3u8_content:
                result["m3u8_content"] = m3u8_content
                enhanced_log(
                    "Returned M3U8 with AES keys for decryption",
                    "INFO",
                    "VIX")
            else:
                enhanced_log(
                    "M3U8 not downloaded - TS segments may not be decrypted",
                    "WARNING",
                    "VIX")

            return result

        except VixExtractorError as exc:
            enhanced_log("Extraction error: %s" % exc, "ERROR", "VIX")
            return None
        except Exception as exc:
            enhanced_log(
                "Unexpected error: %s" %
                str(exc)[
                    :200],
                "ERROR",
                "VIX")
            return None

    def close(self):
        """Close the session definitively."""
        if self.session:
            try:
                self.session.close()
            except Exception:
                # Do not log the error to avoid spam on Enigma2
                pass
            finally:
                self.session = None


# Alias for compatibility with existing code
VixCloudExtractor = VixSrcExtractor

# Global instance
vix_extractor = VixSrcExtractor()
