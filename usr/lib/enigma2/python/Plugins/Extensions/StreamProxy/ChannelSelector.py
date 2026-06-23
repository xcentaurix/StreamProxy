from Screens.ChannelSelection import ChannelSelection
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Button import Button
from Components.Input import Input
from enigma import eServiceReference, eTimer
from .StreamProxyLog import enhanced_log
from urllib.parse import unquote, urlparse, parse_qs


class ChannelSelector(ChannelSelection):
    skin = """
        <screen name="ChannelSelector" position="center,center" size="1200,900" title="Seleziona canali">
            <eLabel text="Seleziona i canali da usare per Stream Proxy" position="20,10" size="1160,40" font="Regular;24" halign="center" />
            <widget name="list" position="20,60" size="1160,700" scrollbarMode="showOnDemand" />
            <eLabel text="Cerca:" position="20,770" size="60,40" font="Regular;22" />
            <widget name="search_input" position="90,770" size="500,40" font="Regular;22" />
            <widget name="status" position="20,820" size="1160,40" font="Regular;22" halign="center" />
            <widget name="selectAllButton" position="600,770" size="200,40" font="Regular;22" />
            <eLabel text="OK = Seleziona/Deseleziona, VERDE = Salva, GIALLO = Seleziona Tutto" position="20,870" size="1160,30" font="Regular;20" halign="center" />
        </screen>
    """

    def __init__(self, session, selected=None):
        enhanced_log("__init__ chiamato", "DEBUG", "ChannelSelector")

        # Salva il reference PRIMA di tutto
        self.target_service_ref = session.nav.getCurrentlyPlayingServiceReference()
        if self.target_service_ref:
            enhanced_log(
                f"Service ref salvato: {
                    self.target_service_ref.toString()[
                        :100]}...",
                "DEBUG",
                "ChannelSelector")
        # Inizializza la classe padre
        ChannelSelection.__init__(self, session)

        self.setTitle("Seleziona canali per Stream Proxy")
        self.selected = selected or []
        self.setSelectionMode(ChannelSelection.SelectionModeMultiple)

        # Contatore tentativi
        self.selection_attempts = 0
        self.max_attempts = 10

        # Widgets
        self["status"] = Label(
            "OK: Seleziona/Deseleziona, Verde: Salva, Giallo: Tutto")
        self["search_input"] = Input(text="", maxSize=False, type=Input.TEXT)
        self["selectAllButton"] = Button("Seleziona Tutto")

        # Timer per la ricerca
        self.search_timer = eTimer()
        self.search_timer.callback.append(self.searchChannels)
        self.last_search = ""

        # Timer per selezione ritardata
        self.position_timer = eTimer()
        self.position_timer.callback.append(self.tryPositionChannel)

        # Imposta i servizi selezionati
        if selected:
            self.setSelectedServices(selected)

        # Actions
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "ChannelSelectBaseActions",
                                     "DirectionActions", "KeyboardInputActions"], {
            "ok": self.toggleSelection,
            "cancel": self.exit,
            "green": self.saveSelection,
            "yellow": self.selectAll,
            "red": self.debugInfo,  # Aggiungi debug con tasto rosso
            "left": self.moveLeft,
            "right": self.moveRight,
            "up": self.moveUp,
            "down": self.moveDown,
            "1": self.number1,
            "2": self.number2,
            "3": self.number3,
            "4": self.number4,
            "5": self.number5,
            "6": self.number6,
            "7": self.number7,
            "8": self.number8,
            "9": self.number9,
            "0": self.number0,
            "back": self.keyBack,
            "delete": self.keyDelete,
        }, -1)

        # Avvia il posizionamento dopo un breve delay
        self.onFirstExecBegin.append(self.startPositioning)

    def startPositioning(self):
        """Avvia il processo di posizionamento"""
        enhanced_log("startPositioning chiamato", "DEBUG", "ChannelSelector")
        # Aspetta 500ms prima del primo tentativo
        self.position_timer.start(500, True)

    def tryPositionChannel(self):
        """Tenta di posizionare sul canale corrente"""
        self.selection_attempts += 1
        enhanced_log(
            f"Tentativo {
                self.selection_attempts}/{
                self.max_attempts}",
            "DEBUG",
            "ChannelSelector")

        if self.selection_attempts > self.max_attempts:
            enhanced_log(
                "Raggiunto limite tentativi",
                "DEBUG",
                "ChannelSelector")
            return

        if not self.target_service_ref or not self.target_service_ref.valid():
            enhanced_log(
                "Nessun service ref valido",
                "DEBUG",
                "ChannelSelector")
            return

        try:
            # Metodo 1: Prova zap2Service (il più diretto)
            if hasattr(self, 'zap2Service'):
                enhanced_log(
                    "Provo con zap2Service",
                    "DEBUG",
                    "ChannelSelector")
                self.zap2Service(self.target_service_ref)
                return

            # Metodo 2: Prova con setCurrentSelection
            if hasattr(self, 'setCurrentSelection'):
                enhanced_log(
                    "Provo con setCurrentSelection",
                    "DEBUG",
                    "ChannelSelector")
                self.setCurrentSelection(self.target_service_ref)
                return

            # Metodo 3: Accesso diretto alla lista
            servicelist = self.servicelist if hasattr(
                self, 'servicelist') else self.get(
                "list", None)
            if servicelist:
                enhanced_log(
                    "Provo con setCurrent sulla lista",
                    "DEBUG",
                    "ChannelSelector")

                # Prima prova direttamente
                if hasattr(servicelist, 'setCurrent'):
                    servicelist.setCurrent(self.target_service_ref)
                    enhanced_log(
                        "setCurrent eseguito",
                        "DEBUG",
                        "ChannelSelector")
                    return

                # Poi prova moveToService
                if hasattr(servicelist, 'moveToService'):
                    servicelist.moveToService(self.target_service_ref)
                    enhanced_log(
                        "moveToService eseguito",
                        "DEBUG",
                        "ChannelSelector")
                    return

            # Se non ha funzionato, riprova
            enhanced_log(
                "Nessun metodo ha funzionato, riprovo...",
                "DEBUG",
                "ChannelSelector")
            self.position_timer.start(200, True)

        except Exception as e:
            enhanced_log(f"Errore: {e}", "ERROR", "ChannelSelector")
            # Riprova in caso di errore
            self.position_timer.start(200, True)

    def debugInfo(self):
        """Mostra informazioni di debug (tasto rosso)"""
        try:
            current = self.getCurrentSelection()
            if current:
                enhanced_log(
                    f"Canale selezionato: {
                        current.toString()[
                            :100]}...",
                    "DEBUG",
                    "ChannelSelector")
                enhanced_log(
                    f"Nome: {
                        current.getName()}",
                    "DEBUG",
                    "ChannelSelector")

            if self.target_service_ref:
                enhanced_log(
                    f"Target: {
                        self.target_service_ref.toString()[
                            :100]}...",
                    "DEBUG",
                    "ChannelSelector")
                enhanced_log(
                    f"Target nome: {
                        self.target_service_ref.getName()}",
                    "DEBUG",
                    "ChannelSelector")

            # Mostra anche attributi disponibili
            enhanced_log(
                f"Attributi disponibili: {
                    dir(self)[
                        :10]}...",
                "DEBUG",
                "ChannelSelector")

            # Forza un altro tentativo
            self.selection_attempts = 0
            self.tryPositionChannel()

        except Exception as e:
            enhanced_log(
                f"Errore in debugInfo: {e}",
                "ERROR",
                "ChannelSelector")

    def get_original_url_from_ref(self, ref):
        """Estrae l'URL originale da un service reference"""
        if not ref or not ref.valid():
            return None

        ref_str = ref.toString()
        parts = ref_str.split(':')

        if len(parts) < 11:
            return None

        url_field = unquote(parts[10])

        try:
            if '127.0.0.1' in url_field and 'proxy/m3u' in url_field:
                parsed = urlparse(url_field)
                query_params = parse_qs(parsed.query)
                original_url = query_params.get('url', [None])[0]
                return original_url.strip() if original_url else None
            return url_field.strip() if url_field else None
        except Exception as e:
            enhanced_log(
                f"Errore estrazione URL originale: {e}",
                "DEBUG",
                "ChannelSelector")
            return None

    def toggleSelection(self):
        """Toggle della selezione per il canale corrente"""
        service = self.getCurrentSelection()
        if not service:
            return

        ref_str = service.toString()
        if ref_str in self.selected:
            self.selected.remove(ref_str)
        else:
            self.selected.append(ref_str)

        self.updateStatus()

    def saveSelection(self):
        """Salva e chiude con i canali selezionati"""
        self.close(self.selected)

    def exit(self):
        """Chiude senza salvare"""
        self.close(None)

    def selectAll(self):
        """Seleziona tutti i canali del bouquet corrente"""
        try:
            servicelist = self.servicelist if hasattr(
                self, 'servicelist') else self.get(
                "list", None)
            if servicelist:
                root = servicelist.getRoot()
                if root:
                    serviceHandler = self.session.nav.getServiceList()
                    if serviceHandler:
                        list = serviceHandler.list(root)
                        if list:
                            count = 0
                            while True:
                                service = list.getNext()
                                if not service.valid():
                                    break

                                ref_str = service.toString()
                                if ref_str not in self.selected:
                                    self.selected.append(ref_str)
                                    count += 1

                            enhanced_log(
                                f"Aggiunti {count} canali", "DEBUG", "ChannelSelector")

            self.updateStatus()
        except Exception as e:
            enhanced_log(
                f"Errore in selectAll: {e}",
                "ERROR",
                "ChannelSelector")

    def setSelectedServices(self, selected):
        """Imposta i servizi già selezionati"""
        self.selected = list(selected) if selected else []
        self.updateStatus()

    def updateStatus(self):
        """Aggiorna il label di stato"""
        count = len(self.selected)
        self["status"].setText(f"Canali selezionati: {count}")

    def searchChannels(self):
        """Filtra i canali in base al testo di ricerca"""
        text = self["search_input"].getText().strip().lower()

        if text == self.last_search:
            return

        self.last_search = text

        if text:
            self["status"].setText(
                f"Ricerca: '{text}' - {len(self.selected)} selezionati")
        else:
            self.updateStatus()

    # Metodi per l'input numerico
    def number1(self):
        self._appendSearch("1")

    def number2(self):
        self._appendSearch("2")

    def number3(self):
        self._appendSearch("3")

    def number4(self):
        self._appendSearch("4")

    def number5(self):
        self._appendSearch("5")

    def number6(self):
        self._appendSearch("6")

    def number7(self):
        self._appendSearch("7")

    def number8(self):
        self._appendSearch("8")

    def number9(self):
        self._appendSearch("9")

    def number0(self):
        self._appendSearch("0")

    def keyBack(self):
        """Cancella l'ultimo carattere dalla ricerca"""
        text = self["search_input"].getText()
        if text:
            self["search_input"].setText(text[:-1])
            self.search_timer.start(300, True)

    def keyDelete(self):
        """Cancella tutto il testo di ricerca"""
        self["search_input"].setText("")
        self.search_timer.start(300, True)

    def _appendSearch(self, char):
        """Aggiunge un carattere al testo di ricerca"""
        current_text = self["search_input"].getText()
        self["search_input"].setText(current_text + char)
        self.search_timer.start(300, True)

    def moveUp(self):
        self["list"].moveUp()

    def moveDown(self):
        self["list"].moveDown()

    def moveLeft(self):
        self["list"].pageUp()

    def moveRight(self):
        self["list"].pageDown()
