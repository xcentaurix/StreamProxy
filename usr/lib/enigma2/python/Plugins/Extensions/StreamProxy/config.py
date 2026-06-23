# config.py
from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigText, ConfigInteger

def initConfig():
    config.plugins.streamproxy = ConfigSubsection()
    config.plugins.streamproxy.enabled = ConfigYesNo(default=True)
    config.plugins.streamproxy.port = ConfigInteger(default=7860, limits=(1024, 65535))
    config.plugins.streamproxy.filter_enabled = ConfigYesNo(default=True)
    config.plugins.streamproxy.show_notifications = ConfigYesNo(default=True)
    config.plugins.streamproxy.selected_channels = ConfigText(default="")
    config.plugins.streamproxy.use_custom_useragent = ConfigYesNo(default=False)
    config.plugins.streamproxy.custom_useragent = ConfigText(default="Enigma2 StreamProxy")
    config.plugins.streamproxy.show_log = ConfigYesNo(default=True)  # Modificato a True
    config.plugins.streamproxy.log_max_lines = ConfigInteger(default=5000, limits=(100, 10000))  # Aumentato il limite
    config.plugins.streamproxy.debug_mode = ConfigYesNo(default=True)  # Aggiunto debug mode
    config.plugins.streamproxy.cache_dir = ConfigText(default="/tmp/streamproxy_cache")
    config.plugins.streamproxy.save()
