# StreamProxySetup.py
from Screens.Screen import Screen
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.Button import Button
from Components.ActionMap import ActionMap
from Components.config import config, getConfigListEntry
from enigma import ePoint
from .locale import Locale
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
        self.changed = False  # Flag per tracciare le modifiche

        # Configura i pulsanti
        self["key_red"] = Button(Locale._("Annulla"))
        self["key_green"] = Button(Locale._("Salva"))

        # Configura la lista delle opzioni
        ConfigListScreen.__init__(self, [
            getConfigListEntry(Locale._("Abilita Stream Proxy"), config.plugins.streamproxy.enabled),
            getConfigListEntry(Locale._("Porta proxy"), config.plugins.streamproxy.port),
            getConfigListEntry(Locale._("Abilita filtro canali"), config.plugins.streamproxy.filter_enabled),
            getConfigListEntry(Locale._("Mostra notifiche"), config.plugins.streamproxy.show_notifications),
            getConfigListEntry(Locale._("Visualizza log"), config.plugins.streamproxy.show_log),
            getConfigListEntry(Locale._("Numero massimo righe log"), config.plugins.streamproxy.log_max_lines),
            getConfigListEntry(Locale._("User-Agent personalizzato"), config.plugins.streamproxy.use_custom_useragent),
        ])

        # Aggiungi il campo custom_useragent solo se use_custom_useragent è abilitato
        if config.plugins.streamproxy.use_custom_useragent.value:
            self["config"].list.append(
                getConfigListEntry(Locale._("User-Agent"), config.plugins.streamproxy.custom_useragent)
            )

        # Configura le azioni dei pulsanti
        self["actions"] = ActionMap(["SetupActions", "ColorActions"],
        {
            "green": self.save,
            "red": self.cancel,
            "save": self.save,
            "cancel": self.cancel,
            "ok": self.save,
        }, -2)

        self.onLayoutFinish.append(self.layoutFinished)
        config.plugins.streamproxy.use_custom_useragent.addNotifier(self.useragentChanged)

    def layoutFinished(self):
        self.setTitle(Locale._("StreamProxy Setup"))

    def useragentChanged(self, configElement):
        # Aggiorna la lista quando cambia use_custom_useragent
        self["config"].list = [
            getConfigListEntry(Locale._("Abilita Stream Proxy"), config.plugins.streamproxy.enabled),
            getConfigListEntry(Locale._("Porta proxy"), config.plugins.streamproxy.port),
            getConfigListEntry(Locale._("Abilita filtro canali"), config.plugins.streamproxy.filter_enabled),
            getConfigListEntry(Locale._("Mostra notifiche"), config.plugins.streamproxy.show_notifications),
            getConfigListEntry(Locale._("Visualizza log"), config.plugins.streamproxy.show_log),
            getConfigListEntry(Locale._("Numero massimo righe log"), config.plugins.streamproxy.log_max_lines),
            getConfigListEntry(Locale._("User-Agent personalizzato"), config.plugins.streamproxy.use_custom_useragent),
        ]
        if configElement.value:
            self["config"].list.append(
                getConfigListEntry(Locale._("User-Agent"), config.plugins.streamproxy.custom_useragent)
            )
        self["config"].l.setList(self["config"].list)

    def save(self):
        self.saveAll()
        self.changed = True  # Imposta il flag delle modifiche

        if config.plugins.streamproxy.enabled.value:
            proxy_manager.start_proxy()
        else:
            proxy_manager.stop_proxy()

        config.plugins.streamproxy.save()
        self.close(self.changed)  # Passa il flag delle modifiche alla callback

    def cancel(self):
        for x in self["config"].list:
            x[1].cancel()
        self.close(self.changed)  # Passa il flag delle modifiche anche in caso di annullamento

    def keySave(self):
        self.save()

    def keyCancel(self):
        self.cancel()

