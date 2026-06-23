# -*- coding: utf-8 -*-
# plugin.py - StreamProxy main plugin module

from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.Label import Label
import os
import json

# Global variables
service_monitor = None
DEBUG_ENABLED = True
PLUGIN_ENABLED = True


def load_config():
    """Load configuration from SPconfig.txt file"""
    global DEBUG_ENABLED, PLUGIN_ENABLED

    # Configuration file path
    plugin_dir = os.path.dirname(__file__)
    config_file = os.path.join(plugin_dir, "SPconfig.txt")

    # Default configuration
    default_config = {
        "plugin_attivo": "ON",
        "log_abilitato": "ON",
        "num_lastchan": "",
        "param_lastchan": ""
    }

    try:
        if os.path.exists(config_file):
            # Read existing file
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            print("[StreamProxy] Configuration loaded from SPconfig.txt")
        else:
            # Create file with default values
            config = default_config
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            print("[StreamProxy] Created SPconfig.txt with default values")

        # Set global variables
        PLUGIN_ENABLED = (config.get("plugin_attivo", "ON") == "ON")
        DEBUG_ENABLED = (config.get("log_abilitato", "ON") == "ON")

        print("[StreamProxy] Plugin active: %s" % PLUGIN_ENABLED)
        print("[StreamProxy] Log enabled: %s" % DEBUG_ENABLED)

        return config

    except Exception as e:
        print("[StreamProxy] Config loading error: %s" % e)
        # In case of error, use default values
        PLUGIN_ENABLED = True
        DEBUG_ENABLED = True
        return default_config


def save_config(config):
    """Save configuration to SPconfig.txt file"""
    try:
        plugin_dir = os.path.dirname(__file__)
        config_file = os.path.join(plugin_dir, "SPconfig.txt")

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        print("[StreamProxy] Configuration saved to SPconfig.txt")
        return True

    except Exception as e:
        print("[StreamProxy] Config saving error: %s" % e)
        return False


def autostart(reason, **kwargs):
    """Main entry point for the plugin"""
    if reason == 0:  # Startup
        load_config()
        print("[StreamProxy] Plugin started")
    elif reason == 1:  # Shutdown
        print("[StreamProxy] Plugin stopped")


def sessionstart(reason, **kwargs):
    """Session start callback"""
    global service_monitor

    if reason == 0:
        if not PLUGIN_ENABLED:
            print("[StreamProxy] Plugin disabled - skipping initialization")
            return
        session = kwargs.get("session", None)
        if session:
            from .StreamProxyLog import enhanced_log
            enhanced_log("=== STARTING INITIALIZATION ===", "INFO", "PLUGIN")

            try:
                enhanced_log("1. Importing server...", "DEBUG", "PLUGIN")
                from . import server
                enhanced_log("2. Server imported OK", "DEBUG", "PLUGIN")

                enhanced_log("3. Starting HTTP server...", "INFO", "PLUGIN")
                result = server.start_simple_server()
                enhanced_log(
                    "4. Server result: %s" %
                    result, "DEBUG", "PLUGIN")

                enhanced_log(
                    "5. Importing ServiceMonitor...",
                    "DEBUG",
                    "PLUGIN")
                from .ServiceMonitor import StreamProxyServiceMonitor
                enhanced_log(
                    "6. ServiceMonitor imported OK",
                    "DEBUG",
                    "PLUGIN")

                service_monitor = StreamProxyServiceMonitor(session)
                enhanced_log(
                    "7. [OK] ServiceMonitor instantiated",
                    "INFO",
                    "PLUGIN")
                enhanced_log(
                    "8. [OK] INITIALIZATION COMPLETE",
                    "INFO",
                    "PLUGIN")

            except ImportError as e:
                enhanced_log("[ERROR] IMPORT ERROR: %s" % e, "ERROR", "PLUGIN")
            except Exception as e:
                enhanced_log(
                    "[ERROR] GENERIC ERROR: %s" %
                    e, "ERROR", "PLUGIN")


class StreamProxyMain(Screen):
    skin = """
        <screen position="center,center" size="560,300" title="Stream Proxy">
            <widget name="status" position="10,10" size="540,200" font="Regular;22" halign="center" valign="center"/>
            <ePixmap pixmap="skin_default/buttons/red.png" position="10,260" size="140,40" alphatest="on" />
            <ePixmap pixmap="skin_default/buttons/green.png" position="150,260" size="140,40" alphatest="on" />
            <widget name="key_red" position="10,260" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" />
            <widget name="key_green" position="150,260" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" />
        </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session

        self["status"] = Label(
            "StreamProxy - Plugin active\n\nPress GREEN for Setup\nPress RED to close")
        self["key_red"] = Label("Close")
        self["key_green"] = Label("Setup")

        self["actions"] = ActionMap(["SetupActions", "OkCancelActions", "ColorActions"],
                                    {
                                        "cancel": self.close,
                                        "ok": self.openSetup,
                                        "red": self.close,
                                        "green": self.openSetup
        }, -2)

    def openSetup(self):
        print("[StreamProxy] Opening setup...")
        self.session.open(StreamProxySetup)


class StreamProxySetup(Screen):
    skin = """
        <screen position="center,center" size="500,400" title="StreamProxy Setup">
            <widget name="menu" position="10,10" size="480,320" font="Regular;22" />
            <ePixmap pixmap="skin_default/buttons/red.png" position="10,350" size="140,40" alphatest="on" />
            <ePixmap pixmap="skin_default/buttons/green.png" position="150,350" size="140,40" alphatest="on" />
            <widget name="key_red" position="10,350" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" />
            <widget name="key_green" position="150,350" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" />
        </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session

        # Load current configuration
        self.config = load_config()
        self.proxy_enabled = (self.config.get("plugin_attivo", "ON") == "ON")
        self.debug_mode = (self.config.get("log_abilitato", "ON") == "ON")

        self["menu"] = Label()
        self.updateMenu()

        self["key_red"] = Label("Close")
        self["key_green"] = Label("Save")

        self["actions"] = ActionMap(["SetupActions", "ColorActions"],
                                    {
                                        "cancel": self.close,
                                        "red": self.close,
                                        "green": self.saveAndClose,
                                        "ok": self.toggleSetting
        }, -2)

    def saveAndClose(self):
        """Save changes and close"""
        global DEBUG_ENABLED, PLUGIN_ENABLED

        # Update configuration
        self.config["plugin_attivo"] = "ON" if self.proxy_enabled else "OFF"
        self.config["log_abilitato"] = "ON" if self.debug_mode else "OFF"

        # Save to file
        if save_config(self.config):
            # Update global variables
            PLUGIN_ENABLED = self.proxy_enabled
            DEBUG_ENABLED = self.debug_mode

            from Screens.MessageBox import MessageBox
            self.session.open(
                MessageBox,
                "Configuration saved!",
                MessageBox.TYPE_INFO,
                timeout=2)

        self.close()

    def updateMenu(self):
        menu_text = "STREAMPROXY CONFIGURATION\n\n"
        menu_text += "1. Proxy enabled: %s\n" % (
            'ON' if self.proxy_enabled else 'OFF')
        menu_text += "2. Debug mode: %s\n\n" % (
            'ON' if self.debug_mode else 'OFF')
        menu_text += "Press OK to modify\nPress GREEN to save"

        self["menu"].setText(menu_text)

    def toggleSetting(self):
        from Screens.ChoiceBox import ChoiceBox
        choices = [
            ("Proxy enabled: %s" %
             ('ON' if self.proxy_enabled else 'OFF'), "proxy"), ("Debug mode: %s" %
                                                                 ('ON' if self.debug_mode else 'OFF'), "debug")]
        self.session.openWithCallback(
            self.choiceCallback,
            ChoiceBox,
            title="Select setting to modify:",
            list=choices)

    def choiceCallback(self, choice):
        if choice:
            if choice[1] == "proxy":
                self.proxy_enabled = not self.proxy_enabled
            elif choice[1] == "debug":
                self.debug_mode = not self.debug_mode

            # Update menu immediately
            self.updateMenu()


def main(session, **kwargs):
    session.open(StreamProxyMain)


def Plugins(**kwargs):
    return [
        PluginDescriptor(
            where=PluginDescriptor.WHERE_AUTOSTART,
            fnc=autostart
        ),
        PluginDescriptor(
            where=PluginDescriptor.WHERE_SESSIONSTART,
            fnc=sessionstart
        ),
        PluginDescriptor(
            name="StreamProxy",
            description="StreamProxy plugin for Enigma2",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon="stream_proxy.png",
            fnc=main
        ),
        PluginDescriptor(
            name="StreamProxy",
            where=PluginDescriptor.WHERE_EXTENSIONSMENU,
            icon="stream_proxy.png",
            fnc=main
        )
    ]
