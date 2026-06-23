from Screens.ChannelSelection import ChannelSelection
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Button import Button
from Components.Input import Input
from enigma import eTimer
from .StreamProxyLog import enhanced_log
from urllib.parse import unquote, urlparse, parse_qs


class ChannelSelector(ChannelSelection):
    skin = """
        <screen name="ChannelSelector" position="center,center" size="1200,900" title="Select channels">
            <eLabel text="Select the channels to use for Stream Proxy" position="20,10" size="1160,40" font="Regular;24" halign="center" />
            <widget name="list" position="20,60" size="1160,700" scrollbarMode="showOnDemand" />
            <eLabel text="Search:" position="20,770" size="60,40" font="Regular;22" />
            <widget name="search_input" position="90,770" size="500,40" font="Regular;22" />
            <widget name="status" position="20,820" size="1160,40" font="Regular;22" halign="center" />
            <widget name="selectAllButton" position="600,770" size="200,40" font="Regular;22" />
            <eLabel text="OK = Select/Deselect, GREEN = Save, YELLOW = Select All" position="20,870" size="1160,30" font="Regular;20" halign="center" />
        </screen>
    """

    def __init__(self, session, selected=None):
        enhanced_log("__init__ called", "DEBUG", "ChannelSelector")

        # Save the reference BEFORE everything else
        self.target_service_ref = session.nav.getCurrentlyPlayingServiceReference()
        if self.target_service_ref:
            enhanced_log(
                "Service ref saved: %s..." %
                self.target_service_ref.toString()[
                    :100], "DEBUG", "ChannelSelector")

        # Initialise the parent class
        ChannelSelection.__init__(self, session)

        self.setTitle("Select channels for Stream Proxy")
        self.selected = selected or []
        self.setSelectionMode(ChannelSelection.SelectionModeMultiple)

        # Attempt counter
        self.selection_attempts = 0
        self.max_attempts = 10

        # Widgets
        self["status"] = Label(
            "OK: Select/Deselect, Green: Save, Yellow: Select All")
        self["search_input"] = Input(text="", maxSize=False, type=Input.TEXT)
        self["selectAllButton"] = Button("Select All")

        # Timer for search
        self.search_timer = eTimer()
        self.search_timer.callback.append(self.searchChannels)
        self.last_search = ""

        # Timer for delayed positioning
        self.position_timer = eTimer()
        self.position_timer.callback.append(self.tryPositionChannel)

        # Set selected services if provided
        if selected:
            self.setSelectedServices(selected)

        # Actions
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "ChannelSelectBaseActions",
                                     "DirectionActions", "KeyboardInputActions"], {
            "ok": self.toggleSelection,
            "cancel": self.exit,
            "green": self.saveSelection,
            "yellow": self.selectAll,
            "red": self.debugInfo,  # Debug with red button
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

        # Start positioning after a short delay
        self.onFirstExecBegin.append(self.startPositioning)

    def startPositioning(self):
        """Start the positioning process"""
        enhanced_log("startPositioning called", "DEBUG", "ChannelSelector")
        # Wait 500ms before the first attempt
        self.position_timer.start(500, True)

    def tryPositionChannel(self):
        """Try to position on the current channel"""
        self.selection_attempts += 1
        enhanced_log(
            "Attempt %d/%d" % (self.selection_attempts, self.max_attempts),
            "DEBUG",
            "ChannelSelector")

        if self.selection_attempts > self.max_attempts:
            enhanced_log(
                "Reached maximum attempts",
                "DEBUG",
                "ChannelSelector")
            return

        if not self.target_service_ref or not self.target_service_ref.valid():
            enhanced_log(
                "No valid service reference",
                "DEBUG",
                "ChannelSelector")
            return

        try:
            # Method 1: Try zap2Service (most direct)
            if hasattr(self, 'zap2Service'):
                enhanced_log("Trying zap2Service", "DEBUG", "ChannelSelector")
                self.zap2Service(self.target_service_ref)
                return

            # Method 2: Try setCurrentSelection
            if hasattr(self, 'setCurrentSelection'):
                enhanced_log(
                    "Trying setCurrentSelection",
                    "DEBUG",
                    "ChannelSelector")
                self.setCurrentSelection(self.target_service_ref)
                return

            # Method 3: Direct access to the list
            servicelist = self.servicelist if hasattr(
                self, 'servicelist') else self.get(
                "list", None)
            if servicelist:
                enhanced_log(
                    "Trying setCurrent on the list",
                    "DEBUG",
                    "ChannelSelector")

                # First try directly
                if hasattr(servicelist, 'setCurrent'):
                    servicelist.setCurrent(self.target_service_ref)
                    enhanced_log(
                        "setCurrent executed",
                        "DEBUG",
                        "ChannelSelector")
                    return

                # Then try moveToService
                if hasattr(servicelist, 'moveToService'):
                    servicelist.moveToService(self.target_service_ref)
                    enhanced_log(
                        "moveToService executed",
                        "DEBUG",
                        "ChannelSelector")
                    return

            # If nothing worked, try again
            enhanced_log(
                "No method worked, retrying...",
                "DEBUG",
                "ChannelSelector")
            self.position_timer.start(200, True)

        except Exception as e:
            enhanced_log("Error: %s" % e, "ERROR", "ChannelSelector")
            # Retry on error
            self.position_timer.start(200, True)

    def debugInfo(self):
        """Show debug information (red button)"""
        try:
            current = self.getCurrentSelection()
            if current:
                enhanced_log(
                    "Selected channel: %s..." % current.toString()[:100],
                    "DEBUG",
                    "ChannelSelector")
                enhanced_log(
                    "Name: %s" % current.getName(),
                    "DEBUG",
                    "ChannelSelector")

            if self.target_service_ref:
                enhanced_log(
                    "Target: %s..." % self.target_service_ref.toString()[:100],
                    "DEBUG",
                    "ChannelSelector")
                enhanced_log(
                    "Target name: %s" % self.target_service_ref.getName(),
                    "DEBUG",
                    "ChannelSelector")

            # Show available attributes
            enhanced_log(
                "Available attributes: %s..." % str(dir(self)[:10]),
                "DEBUG",
                "ChannelSelector")

            # Force another attempt
            self.selection_attempts = 0
            self.tryPositionChannel()

        except Exception as e:
            enhanced_log(
                "Error in debugInfo: %s" %
                e, "ERROR", "ChannelSelector")

    def get_original_url_from_ref(self, ref):
        """Extract the original URL from a service reference"""
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
                "Error extracting original URL: %s" %
                e, "DEBUG", "ChannelSelector")
            return None

    def toggleSelection(self):
        """Toggle selection for the current channel"""
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
        """Save and close with selected channels"""
        self.close(self.selected)

    def exit(self):
        """Close without saving"""
        self.close(None)

    def selectAll(self):
        """Select all channels in the current bouquet"""
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
                                "Added %d channels" %
                                count, "DEBUG", "ChannelSelector")

            self.updateStatus()
        except Exception as e:
            enhanced_log(
                "Error in selectAll: %s" %
                e, "ERROR", "ChannelSelector")

    def setSelectedServices(self, selected):
        """Set already selected services"""
        self.selected = list(selected) if selected else []
        self.updateStatus()

    def updateStatus(self):
        """Update the status label"""
        count = len(self.selected)
        self["status"].setText("Selected channels: %d" % count)

    def searchChannels(self):
        """Filter channels based on search text"""
        text = self["search_input"].getText().strip().lower()

        if text == self.last_search:
            return

        self.last_search = text

        if text:
            self["status"].setText(
                "Search: '%s' - %d selected" %
                (text, len(
                    self.selected)))
        else:
            self.updateStatus()

    # Numeric input methods
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
        """Delete the last character from the search"""
        text = self["search_input"].getText()
        if text:
            self["search_input"].setText(text[:-1])
            self.search_timer.start(300, True)

    def keyDelete(self):
        """Delete all search text"""
        self["search_input"].setText("")
        self.search_timer.start(300, True)

    def _appendSearch(self, char):
        """Append a character to the search text"""
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
