# -*- coding: utf-8 -*-
# StreamProxySetup.py - Setup screen for StreamProxy

import os
import json
from Screens.Screen import Screen
from Components.ConfigList import ConfigListScreen
from Components.Button import Button
from Components.ActionMap import ActionMap
from Components.config import config, getConfigListEntry, ConfigNothing

from . import proxy_manager


class StreamProxySetup(Screen, ConfigListScreen):
    skin = """
    <screen position="center,center" size="600,440" backgroundColor="#CC1a2a4a">
        <widget name="config" position="5,5" size="590,390" scrollbarMode="showOnDemand" backgroundColor="#CC1a2a4a" />
        <ePixmap pixmap="skin_default/buttons/red.png" position="0,400" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/green.png" position="140,400" size="140,40" alphatest="on" />
        <widget name="key_red" position="0,400" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" />
        <widget name="key_green" position="140,400" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.changed = False

        self["key_red"] = Button("Cancel")
        self["key_green"] = Button("Save")

        ConfigListScreen.__init__(self, [])
        self._buildList()

        self["actions"] = ActionMap(
            ["SetupActions", "ColorActions"],
            {
                "green": self.save,
                "red": self.cancel,
                "save": self.save,
                "cancel": self.cancel,
                "ok": self.keyOK,
            }, -2)

        self.onLayoutFinish.append(self.layoutFinished)
        self.onLayoutFinish.append(self._registerNotifiers)

    def layoutFinished(self):
        self.setTitle("StreamProxy Setup")

    def _registerNotifiers(self):
        config.plugins.streamproxy.use_custom_useragent.addNotifier(
            self.useragentChanged, initial_call=False)
        config.plugins.streamproxy.attivaProxyEsterno.addNotifier(
            self.proxyEsternoChanged, initial_call=False)

    def _buildList(self):
        if "config" not in self:
            return
        cfg = config.plugins.streamproxy
        lst = [
            getConfigListEntry("*** SPconfig.txt ***", ConfigNothing()),
            getConfigListEntry("Enable Stream Proxy", cfg.enabled),
            getConfigListEntry("Proxy port", cfg.port),
            getConfigListEntry("Enable channel filter", cfg.filter_enabled),
            getConfigListEntry("Show notifications", cfg.show_notifications),
            getConfigListEntry("Show log", cfg.show_log),
            getConfigListEntry("Maximum log lines", cfg.log_max_lines),
            getConfigListEntry("Custom User-Agent", cfg.use_custom_useragent),
        ]
        if cfg.use_custom_useragent.value:
            lst.append(getConfigListEntry("User-Agent string", cfg.custom_useragent))
        lst.append(getConfigListEntry("", ConfigNothing()))
        lst.append(getConfigListEntry("*** configProxy.txt ***", ConfigNothing()))
        lst.append(getConfigListEntry("Enable external proxy", cfg.attivaProxyEsterno))
        if cfg.attivaProxyEsterno.value:
            lst += [
                getConfigListEntry("Proxy URL", cfg.proxyUrl),
                getConfigListEntry("API Password", cfg.apiPassword),
                getConfigListEntry("Timeout (sec)", cfg.timeoutProxy),
                getConfigListEntry("Use extractor", cfg.usaExtractor),
                getConfigListEntry("Use HLS proxy", cfg.usaHlsProxy),
            ]
        self["config"].list = lst
        self["config"].l.setList(lst)

    def keyOK(self):
        """Delegate OK to ConfigListScreen so text entries open the virtual keyboard."""
        ConfigListScreen.keyOK(self)

    def useragentChanged(self, _):
        self._buildList()

    def proxyEsternoChanged(self, _):
        self._buildList()

    def save(self):
        self.saveAll()
        self.changed = True
        if config.plugins.streamproxy.enabled.value:
            proxy_manager.start_proxy()
        else:
            proxy_manager.stop_proxy()
        config.plugins.streamproxy.save()
        self._saveProxyConfig()
        self.close(self.changed)

    def _saveProxyConfig(self):
        cfg = config.plugins.streamproxy
        data = {
            "attivaProxyEsterno": "SI" if cfg.attivaProxyEsterno.value else "NO",
            "proxyUrl": cfg.proxyUrl.value,
            "apiPassword": cfg.apiPassword.value,
            "timeoutProxy": cfg.timeoutProxy.value,
            "usaExtractor": "SI" if cfg.usaExtractor.value else "NO",
            "usaHlsProxy": "SI" if cfg.usaHlsProxy.value else "NO",
        }
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'configProxy.txt')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            # Invalidate external_proxy cache so new values are picked up immediately
            try:
                from . import external_proxy
                external_proxy._cfg_cache_ts = 0.0
            except Exception:
                pass
        except Exception as e:
            print("[StreamProxy] Error saving configProxy.txt: %s" % e)

    def cancel(self):
        for x in self["config"].list:
            x[1].cancel()
        self.close(self.changed)

    def keySave(self):
        self.save()

    def keyCancel(self):
        self.cancel()
