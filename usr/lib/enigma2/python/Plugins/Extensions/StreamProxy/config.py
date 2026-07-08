# config.py
import os
import json
from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigText, ConfigInteger

_PROXY_CONFIG_PATH = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)),
    'configProxy.txt')


def _load_proxy_file():
    """Read configProxy.txt and return its dict, or {} on any error."""
    try:
        if os.path.exists(_PROXY_CONFIG_PATH):
            with open(_PROXY_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def initConfig():
    p = _load_proxy_file()

    config.plugins.streamproxy = ConfigSubsection()
    config.plugins.streamproxy.enabled = ConfigYesNo(default=True)
    config.plugins.streamproxy.port = ConfigInteger(
        default=7860, limits=(1024, 65535))
    config.plugins.streamproxy.filter_enabled = ConfigYesNo(default=True)
    config.plugins.streamproxy.show_notifications = ConfigYesNo(default=True)
    config.plugins.streamproxy.selected_channels = ConfigText(default="")
    config.plugins.streamproxy.use_custom_useragent = ConfigYesNo(
        default=False)
    config.plugins.streamproxy.custom_useragent = ConfigText(
        default="Enigma2 StreamProxy")
    config.plugins.streamproxy.show_log = ConfigYesNo(
        default=True)
    config.plugins.streamproxy.log_max_lines = ConfigInteger(
        default=5000, limits=(100, 10000))
    config.plugins.streamproxy.debug_mode = ConfigYesNo(
        default=True)
    config.plugins.streamproxy.cache_dir = ConfigText(
        default="/tmp/streamproxy_cache")
    _ext_active = str(
        p.get(
            'attivaProxyEsterno',
            'NO')).strip().upper() == 'YES'
    config.plugins.streamproxy.attivaProxyEsterno = ConfigYesNo(
        default=_ext_active)
    config.plugins.streamproxy.proxyUrl = ConfigText(
        default=p.get('proxyUrl', 'https://proxy.example.com'))
    config.plugins.streamproxy.apiPassword = ConfigText(
        default=p.get('apiPassword', ''))
    config.plugins.streamproxy.timeoutProxy = ConfigInteger(
        default=int(p.get('timeoutProxy', 15)), limits=(5, 120))
    _usa_ext = str(p.get('usaExtractor', 'YES')).strip().upper() == 'YES'
    config.plugins.streamproxy.usaExtractor = ConfigYesNo(default=_usa_ext)
    _usa_hls = str(p.get('usaHlsProxy', 'YES')).strip().upper() == 'YES'
    config.plugins.streamproxy.usaHlsProxy = ConfigYesNo(default=_usa_hls)
    config.plugins.streamproxy.save()
