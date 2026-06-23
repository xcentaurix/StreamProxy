# plugin.py
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.Label import Label
from enigma import eTimer
import os
import json

# Variabili globali
service_monitor = None
DEBUG_ENABLED = True
PLUGIN_ENABLED = True


def load_config():
    """Carica la configurazione dal file SPconfig.txt"""
    global DEBUG_ENABLED, PLUGIN_ENABLED

    # Percorso del file di configurazione
    plugin_dir = os.path.dirname(__file__)
    config_file = os.path.join(plugin_dir, "SPconfig.txt")

    # Configurazione di default
    default_config = {
        "plugin_attivo": "ON",
        "log_abilitato": "ON",
        "num_lastchan": "",
        "param_lastchan": ""
    }

    try:
        if os.path.exists(config_file):
            # Leggi il file esistente
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            print("[StreamProxy] Configurazione caricata da SPconfig.txt")
        else:
            # Crea il file con valori di default
            config = default_config
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            print("[StreamProxy] Creato SPconfig.txt con valori di default")

        # Imposta le variabili globali
        PLUGIN_ENABLED = (config.get("plugin_attivo", "ON") == "ON")
        DEBUG_ENABLED = (config.get("log_abilitato", "ON") == "ON")

        print(f"[StreamProxy] Plugin attivo: {PLUGIN_ENABLED}")
        print(f"[StreamProxy] Log abilitato: {DEBUG_ENABLED}")

        return config

    except Exception as e:
        print(f"[StreamProxy] Errore caricamento config: {e}")
        # In caso di errore, usa i valori di default
        PLUGIN_ENABLED = True
        DEBUG_ENABLED = True
        return default_config


def save_config(config):
    """Salva la configurazione nel file SPconfig.txt"""
    try:
        plugin_dir = os.path.dirname(__file__)
        config_file = os.path.join(plugin_dir, "SPconfig.txt")

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        print("[StreamProxy] Configurazione salvata in SPconfig.txt")
        return True

    except Exception as e:
        print(f"[StreamProxy] Errore salvataggio config: {e}")
        return False
def autostart(reason, **kwargs):
    """Main entry point del plugin"""
    if reason == 0:  # Avvio
        load_config()
        print("[StreamProxy] Plugin avviato")
    elif reason == 1:  # Spegnimento
        print("[StreamProxy] Plugin arrestato")


# plugin.py - VERSIONE CON ENHANCED_LOG
def sessionstart(reason, **kwargs):
    """Callback per l'avvio della sessione"""
    global service_monitor

    if reason == 0:
        if not PLUGIN_ENABLED:
            print("[StreamProxy] Plugin disabilitato - skip inizializzazione")
            return
        session = kwargs.get("session", None)
        if session:
            from .StreamProxyLog import enhanced_log
            enhanced_log("=== INIZIO INIZIALIZZAZIONE ===", "INFO", "PLUGIN")

            try:
                enhanced_log("1. Importo server...", "DEBUG", "PLUGIN")
                from . import server
                enhanced_log("2. Server importato OK", "DEBUG", "PLUGIN")

                enhanced_log("3. Avvio server HTTP...", "INFO", "PLUGIN")
                result = server.start_simple_server()
                enhanced_log(f"4. Server result: {result}", "DEBUG", "PLUGIN")

                enhanced_log("5. Importo ServiceMonitor...", "DEBUG", "PLUGIN")
                from .ServiceMonitor import StreamProxyServiceMonitor
                enhanced_log("6. ServiceMonitor importato OK", "DEBUG", "PLUGIN")

                service_monitor = StreamProxyServiceMonitor(session)
                enhanced_log("7. ✅ ServiceMonitor istanziato", "INFO", "PLUGIN")
                enhanced_log("8. ✅ TUTTO INIZIALIZZATO", "INFO", "PLUGIN")

            except ImportError as e:
                enhanced_log(f"❌ ERRORE IMPORT: {e}", "ERROR", "PLUGIN")
            except Exception as e:
                enhanced_log(f"❌ ERRORE GENERICO: {e}", "ERROR", "PLUGIN")


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

        self["status"] = Label("StreamProxy - Plugin attivo\n\nPremi VERDE per Setup\nPremi ROSSO per chiudere")
        self["key_red"] = Label("Chiudi")
        self["key_green"] = Label("Setup")

        self["actions"] = ActionMap(["SetupActions", "OkCancelActions", "ColorActions"],
                                    {
                                        "cancel": self.close,
                                        "ok": self.openSetup,
                                        "red": self.close,
                                        "green": self.openSetup
                                    }, -2)

    def openSetup(self):
        print("[StreamProxy] Apertura setup...")
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

        # Carica configurazione attuale
        self.config = load_config()
        self.proxy_enabled = (self.config.get("plugin_attivo", "ON") == "ON")
        self.debug_mode = (self.config.get("log_abilitato", "ON") == "ON")

        self["menu"] = Label()
        self.updateMenu()

        self["key_red"] = Label("Chiudi")
        self["key_green"] = Label("Salva")

        self["actions"] = ActionMap(["SetupActions", "ColorActions"],
                                    {
                                        "cancel": self.close,
                                        "red": self.close,
                                        "green": self.saveAndClose,
                                        "ok": self.toggleSetting
                                    }, -2)

    def saveAndClose(self):
        """Salva le modifiche e chiude"""
        global DEBUG_ENABLED, PLUGIN_ENABLED

        # Aggiorna la configurazione
        self.config["plugin_attivo"] = "ON" if self.proxy_enabled else "OFF"
        self.config["log_abilitato"] = "ON" if self.debug_mode else "OFF"

        # Salva nel file
        if save_config(self.config):
            # Aggiorna le variabili globali
            PLUGIN_ENABLED = self.proxy_enabled
            DEBUG_ENABLED = self.debug_mode

            from Screens.MessageBox import MessageBox
            self.session.open(MessageBox, "Configurazione salvata!", MessageBox.TYPE_INFO, timeout=2)

        self.close()

    def updateMenu(self):
        menu_text = "CONFIGURAZIONE STREAMPROXY\n\n"
        menu_text += f"1. Proxy abilitato: {'ON' if self.proxy_enabled else 'OFF'}\n"
        menu_text += f"2. Debug mode: {'ON' if self.debug_mode else 'OFF'}\n\n"
        menu_text += "Premi OK per modificare\nPremi VERDE per salvare"

        self["menu"].setText(menu_text)

    def toggleSetting(self):
        from Screens.ChoiceBox import ChoiceBox
        choices = [
            (f"Proxy abilitato: {'ON' if self.proxy_enabled else 'OFF'}", "proxy"),
            (f"Debug mode: {'ON' if self.debug_mode else 'OFF'}", "debug")
        ]
        self.session.openWithCallback(self.choiceCallback, ChoiceBox,
                                      title="Seleziona impostazione da modificare:",
                                      list=choices)

    def choiceCallback(self, choice):
        if choice:
            if choice[1] == "proxy":
                self.proxy_enabled = not self.proxy_enabled
            elif choice[1] == "debug":
                self.debug_mode = not self.debug_mode

            # Aggiorna immediatamente il menu
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
            description="Plugin StreamProxy per Enigma2",
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