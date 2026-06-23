"""Generic HLS extractor sincrono per StreamProxy/Enigma2."""

from urllib.parse import urlparse

try:
    from .base import BaseExtractor
except (ImportError, ValueError):
    from base import BaseExtractor


class GenericHLSExtractor(BaseExtractor):
    def __init__(self, request_headers=None, proxies=None):
        super(GenericHLSExtractor, self).__init__(request_headers, proxies, extractor_name="generic")

    def extract(self, url, **kwargs):
        parsed = urlparse(url)
        origin = "{}://{}".format(parsed.scheme, parsed.netloc)
        headers = {
            "user-agent": self.base_headers.get("User-Agent"),
        }

        has_referer = False
        has_origin = False
        for key, value in self.request_headers.items():
            lower_key = key.lower()
            if lower_key == "referer":
                has_referer = True
                headers["referer"] = value
            elif lower_key == "origin":
                has_origin = True
                headers["origin"] = value

        referer = kwargs.get("h_Referer") or kwargs.get("h_referer")
        if not referer and "cccdn.net" not in parsed.netloc:
            referer = origin + "/"

        explicit_origin = kwargs.get("h_Origin") or kwargs.get("h_origin")
        if not explicit_origin and "cccdn.net" not in parsed.netloc:
            explicit_origin = origin

        if referer and not has_referer:
            headers["referer"] = referer
        if explicit_origin and not has_origin:
            headers["origin"] = explicit_origin

        allowed_headers = set([
            "authorization", "x-api-key", "x-auth-token", "cookie", "x-channel-key",
            "accept", "accept-language", "accept-encoding", "dnt",
            "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site", "sec-fetch-user",
            "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
            "pragma", "cache-control", "priority",
        ])
        blocked_headers = set(["x-forwarded-for", "x-real-ip", "forwarded", "via", "host"])

        for key, value in self.request_headers.items():
            lower_key = key.lower()
            if lower_key == "user-agent":
                if "chrome" in value.lower() or "applewebkit" in value.lower():
                    headers["user-agent"] = value
                continue
            if lower_key in ("referer", "origin") or lower_key in blocked_headers:
                continue
            if lower_key in allowed_headers:
                headers[lower_key] = value

        if "cookie" in headers:
            headers["cookie"] = headers["cookie"].strip()
            if not headers["cookie"].endswith(";"):
                headers["cookie"] += ";"

        headers.setdefault("accept-language", "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7,it;q=0.6")
        headers.setdefault("accept-encoding", "gzip, deflate")

        return {
            "destination_url": url,
            "request_headers": headers,
            "mediaflow_endpoint": "hls_proxy",
        }
