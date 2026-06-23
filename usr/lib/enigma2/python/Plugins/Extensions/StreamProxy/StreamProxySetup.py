# -*- coding: utf-8 -*-
# StreamProxySetup.py - Setup screen for StreamProxy

from Screens.Screen import Screen
from Components.ConfigList import ConfigListScreen
from Components.Button import Button
from Components.ActionMap import ActionMap
from Components.config import config, getConfigListEntry

from . import proxy_manager


class StreamProxySetup(Screen, ConfigListScreen):
    skin = """
    <screen position="center,center" size="560,400">
        <widget name="config" position="5,5" size="550,350" scrollbarMode="showOnDemand" />
        <ePixmap pixmap="skin_default/buttons/red.png" position="0,360" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/green.png" position="140,360" size="140,40" alphatest="on" />
        <widget name="key_red" position="0,360" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" />
        <widget name="key_green" position="140,360" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.changed = False  # Flag to track changes

        # Configure buttons
        self["key_red"] = Button("Cancel")
        self["key_green"] = Button("Save")

        # Configure the list of options
        ConfigListScreen.__init__(self, [
            getConfigListEntry("Enable Stream Proxy", config.plugins.streamproxy.enabled),
            getConfigListEntry("Proxy port", config.plugins.streamproxy.port),
            getConfigListEntry("Enable channel filter", config.plugins.streamproxy.filter_enabled),
            getConfigListEntry("Show notifications", config.plugins.streamproxy.show_notifications),
            getConfigListEntry("Show log", config.plugins.streamproxy.show_log),
            getConfigListEntry("Maximum log lines", config.plugins.streamproxy.log_max_lines),
            getConfigListEntry("Custom User-Agent", config.plugins.streamproxy.use_custom_useragent),
        ])

        # Add custom_useragent field only if use_custom_useragent is enabled
        if config.plugins.streamproxy.use_custom_useragent.value:
            self["config"].list.append(
                getConfigListEntry(
                    "User-Agent",
                    config.plugins.streamproxy.custom_useragent))

        # Configure button actions
        self["actions"] = ActionMap(["SetupActions", "ColorActions"],
                                    {
            "green": self.save,
            "red": self.cancel,
            "save": self.save,
            "cancel": self.cancel,
            "ok": self.save,
        }, -2)

        self.onLayoutFinish.append(self.layoutFinished)
        config.plugins.streamproxy.use_custom_useragent.addNotifier(
            self.useragentChanged)

    def layoutFinished(self):
        self.setTitle("StreamProxy Setup")

    def useragentChanged(self, configElement):
        # Update the list when use_custom_useragent changes
        self["config"].list = [
            getConfigListEntry("Enable Stream Proxy", config.plugins.streamproxy.enabled),
            getConfigListEntry("Proxy port", config.plugins.streamproxy.port),
            getConfigListEntry("Enable channel filter", config.plugins.streamproxy.filter_enabled),
            getConfigListEntry("Show notifications", config.plugins.streamproxy.show_notifications),
            getConfigListEntry("Show log", config.plugins.streamproxy.show_log),
            getConfigListEntry("Maximum log lines", config.plugins.streamproxy.log_max_lines),
            getConfigListEntry("Custom User-Agent", config.plugins.streamproxy.use_custom_useragent),
        ]
        if configElement.value:
            self["config"].list.append(
                getConfigListEntry(
                    "User-Agent",
                    config.plugins.streamproxy.custom_useragent))
        self["config"].l.setList(self["config"].list)

    def save(self):
        self.saveAll()
        self.changed = True

        if config.plugins.streamproxy.enabled.value:
            proxy_manager.start_proxy()
        else:
            proxy_manager.stop_proxy()

        config.plugins.streamproxy.save()
        self.close(self.changed)  # Pass the changed flag to the callback

    def cancel(self):
        for x in self["config"].list:
            x[1].cancel()
        # Pass the changed flag even on cancel
        self.close(self.changed)

    def keySave(self):
        self.save()

    def keyCancel(self):
        self.cancel()