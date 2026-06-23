# -*- coding: utf-8 -*-
# proxy_utils.py - Utility functions for proxy management

import os
import random
import time
import requests
import threading
from urllib.parse import urlparse
from .StreamProxyLog import enhanced_log

# Initial configuration
VERIFY_SSL = os.environ.get(
    'VERIFY_SSL',
    'false').lower() not in (
        'false',
        '0',
    'no')
if not VERIFY_SSL:
    enhanced_log("WARNING: SSL verification disabled", "WARNING", "PROXY")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# HTTP request timeout in seconds
REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', 15))

# List of available proxies
PROXY_LIST = []


def setup_proxies():
    """Load the SOCKS5 proxy list from the environment variable."""
    global PROXY_LIST
    proxy_list_str = os.environ.get('SOCKS5_PROXY')
    if proxy_list_str:
        raw_proxy_list = [p.strip()
                          for p in proxy_list_str.split(',') if p.strip()]

        if not raw_proxy_list:
            enhanced_log(
                "No valid SOCKS5 proxies found in environment variable.",
                "WARNING",
                "PROXY")
            PROXY_LIST = []
            return

        enhanced_log(
            "Found %d SOCKS5 proxies." % len(raw_proxy_list),
            "INFO",
            "PROXY")
        for proxy in raw_proxy_list:
            # Recognise and automatically convert to socks5h for remote DNS
            # resolution
            final_proxy_url = proxy
            if proxy.startswith('socks5://'):
                final_proxy_url = 'socks5h' + proxy[len('socks5'):]
                enhanced_log(
                    "Proxy converted to ensure remote DNS resolution.",
                    "INFO",
                    "PROXY")
            elif not proxy.startswith('socks5h://'):
                enhanced_log(
                    "WARNING: The proxy URL is not a valid SOCKS5 format.",
                    "WARNING",
                    "PROXY")
            PROXY_LIST.append(final_proxy_url)

        enhanced_log(
            "Make sure you have installed the required dependency: 'pip install PySocks'",
            "INFO",
            "PROXY")
    else:
        PROXY_LIST = []
        enhanced_log("No SOCKS5 proxies configured.", "INFO", "PROXY")


def get_proxy_for_url(url):
    """Select specific proxies for DaddyLive or general proxies for other domains."""
    no_proxy_domains = ['github.com']  # Domains that do not use proxy

    # Check if it is a DaddyLive URL
    is_daddylive = (
        'newkso.ru' in url.lower() or
        '/stream-' in url.lower() or
        'daddylive' in url.lower() or
        'daddy' in url.lower()
    )

    # If DaddyLive, use specific proxies
    if is_daddylive:
        enhanced_log("DaddyLive URL detected: %s" % url, "DEBUG", "PROXY")
        return get_daddy_proxy_list()

    # Otherwise use general proxies
    if not PROXY_LIST:
        return None

    try:
        parsed_url = urlparse(url)
        if any(domain in parsed_url.netloc for domain in no_proxy_domains):
            return None
    except Exception:
        pass

    chosen_proxy = random.choice(PROXY_LIST)
    return {'http': chosen_proxy, 'https': chosen_proxy}


def get_daddy_proxy_list():
    """Load the list of proxies specific to DaddyLive."""
    daddy_proxy_value = os.environ.get('DADDY_PROXY', '')
    daddy_proxies = []

    if daddy_proxy_value and daddy_proxy_value.strip():
        proxy_list = [p.strip()
                      for p in daddy_proxy_value.split(',') if p.strip()]

        for proxy in proxy_list:
            if proxy.startswith('socks5://'):
                final_proxy_url = 'socks5h' + proxy[len('socks5'):]
                enhanced_log(
                    "DaddyLive SOCKS5 proxy converted",
                    "INFO",
                    "PROXY")
            elif proxy.startswith('socks5h://'):
                final_proxy_url = proxy
                enhanced_log(
                    "DaddyLive SOCKS5H proxy configured",
                    "INFO",
                    "PROXY")
            elif proxy.startswith('http://') or proxy.startswith('https://'):
                final_proxy_url = proxy
                enhanced_log(
                    "DaddyLive HTTP/HTTPS proxy configured",
                    "INFO",
                    "PROXY")
            else:
                final_proxy_url = "http://%s" % proxy
                enhanced_log(
                    "DaddyLive proxy converted to HTTP",
                    "INFO",
                    "PROXY")

            daddy_proxies.append(final_proxy_url)

        enhanced_log(
            "Found %d DaddyLive proxies" % len(daddy_proxies),
            "INFO",
            "PROXY")

    if daddy_proxies:
        chosen_proxy = random.choice(daddy_proxies)
        return {'http': chosen_proxy, 'https': chosen_proxy}
    return get_random_proxy()


def get_random_proxy():
    """Select a random proxy from the list and format it for the requests library."""
    if not PROXY_LIST:
        return None
    chosen_proxy = random.choice(PROXY_LIST)
    return {'http': chosen_proxy, 'https': chosen_proxy}


def create_robust_session():
    """Create a robust requests session compatible with Enigma2."""
    session = requests.Session()

    # Keep-alive parameters (values compatible with embedded systems)
    KEEP_ALIVE_TIMEOUT = 10  # seconds
    MAX_KEEP_ALIVE_REQUESTS = 10
    session.headers.update({
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=%d, max=%d' % (KEEP_ALIVE_TIMEOUT, MAX_KEEP_ALIVE_REQUESTS)
    })

    # Simple retry configuration
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry_strategy = Retry(
            total=2,
            read=1,
            connect=1,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=5,
            pool_maxsize=10,
            pool_block=False
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    except Exception:
        # On Enigma2, urllib3.util.retry may be missing: fallback without
        # advanced retry
        pass

    return session


# Pool of persistent sessions
SESSION_POOL = {}
SESSION_LOCK = threading.Lock()


def get_persistent_session(proxy_url=None, max_age=300):
    """Get a persistent session from the pool or create a new one with age control."""
    pool_key = proxy_url if proxy_url else 'default'
    current_time = time.time()

    with SESSION_LOCK:
        # Check if the session exists and is not too old
        if pool_key in SESSION_POOL:
            session_data = SESSION_POOL[pool_key]
            session_age = current_time - session_data.get('created_at', 0)

            # If the session is too old, create a new one
            if session_age > max_age:
                enhanced_log(
                    "Session too old (%ds), creating new one" % session_age,
                    "INFO",
                    "PROXY")
                session = create_robust_session()
                if proxy_url:
                    session.proxies.update(
                        {'http': proxy_url, 'https': proxy_url})
                SESSION_POOL[pool_key] = {
                    'session': session,
                    'created_at': current_time,
                    'requests_count': 0
                }
            else:
                # Increment the request counter
                session_data['requests_count'] += 1
                return session_data['session']
        else:
            # Create a new session
            session = create_robust_session()
            if proxy_url:
                session.proxies.update({'http': proxy_url, 'https': proxy_url})
            SESSION_POOL[pool_key] = {
                'session': session,
                'created_at': current_time,
                'requests_count': 0
            }

        # Limit the number of sessions in the pool
        if len(SESSION_POOL) > 20:  # Maximum number of sessions
            # Remove the oldest session
            oldest_key = min(SESSION_POOL.keys(),
                             key=lambda k: SESSION_POOL[k]['created_at'])
            del SESSION_POOL[oldest_key]

        return SESSION_POOL[pool_key]['session']


def make_persistent_request(
        url,
        headers=None,
        timeout=None,
        proxy_url=None,
        **kwargs):
    """Make a request using persistent connections (compatible with Enigma2)."""
    session = get_persistent_session(proxy_url)
    # Keep-alive parameters
    KEEP_ALIVE_TIMEOUT = 10  # seconds
    MAX_KEEP_ALIVE_REQUESTS = 10
    request_headers = {
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=%d, max=%d' % (KEEP_ALIVE_TIMEOUT,
                                              MAX_KEEP_ALIVE_REQUESTS)}
    if headers:
        request_headers.update(headers)
    try:
        response = session.get(
            url,
            headers=request_headers,
            timeout=timeout or REQUEST_TIMEOUT,
            verify=VERIFY_SSL,
            **kwargs
        )
        return response
    except Exception as e:
        enhanced_log(
            "Error in persistent request: %s" % e,
            "ERROR",
            "PROXY")
        # On error, remove the session from the pool
        with SESSION_LOCK:
            pool_key = proxy_url if proxy_url else 'default'
            if pool_key in SESSION_POOL:
                del SESSION_POOL[pool_key]
        raise


def get_dynamic_timeout(url, base_timeout=None):
    """Calculate dynamic timeout based on resource type."""
    if base_timeout is None:
        base_timeout = 8  # Reduced base timeout
    url_l = url.lower() if isinstance(url, str) else ""
    if ".ts" in url_l:
        return 5  # Short fixed timeout for TS
    elif ".m3u8" in url_l:
        return 8
    else:
        return base_timeout


# Initialise proxies on module import
setup_proxies()
