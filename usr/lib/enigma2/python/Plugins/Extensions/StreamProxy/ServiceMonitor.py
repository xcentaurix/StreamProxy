# ServiceMonitor.py - Fix posizionamento lista canali al primo accesso (E2/Py3)
from enigma import eServiceReference, eTimer
from Screens.ChannelSelection import ChannelSelection
from urllib.parse import quote, unquote
import os
import json

try:
    from .StreamProxyLog import enhanced_log
except Exception:
    def enhanced_log(msg, level="DEBUG", tag="ServiceMonitor"):
        print("[%s][%s] %s" % (tag, level, msg))


# Import TVTap WMS Manager
try:
    from .tvtap_wms_manager import (
        tvtap_wms_manager,
        is_wms_tvtap_url,
        resolve_wms_tvtap_url,
        get_wms_proxy_url
    )
    TVTAP_WMS_AVAILABLE = True
    enhanced_log("✅ TVTap WMS Manager disponibile", "INFO", "ServiceMonitor")
except ImportError as e:
    TVTAP_WMS_AVAILABLE = False
    enhanced_log(
        f"⚠️ TVTap WMS Manager non disponibile: {e}",
        "WARNING",
        "ServiceMonitor")

# Import Freeshot Extractor
try:
    from .extractor.freeshot_extractor import freeshot_extractor, is_freeshot_link
    FREESHOT_AVAILABLE = True
    enhanced_log("✅ Freeshot Extractor disponibile", "INFO", "ServiceMonitor")
except ImportError as e:
    FREESHOT_AVAILABLE = False

    def is_freeshot_link(*args, **kwargs):
        return False
    enhanced_log(
        f"⚠️ Freeshot Extractor non disponibile: {e}",
        "WARNING",
        "ServiceMonitor")
# Import Sport99 Extractor
try:
    from .extractor.sport99_extractor import is_sport99_link
    SPORT99_AVAILABLE = True
    enhanced_log("Sport99 Extractor disponibile", "INFO", "ServiceMonitor")
except ImportError as e:
    SPORT99_AVAILABLE = False

    def is_sport99_link(*args, **kwargs):
        return False
    enhanced_log(
        f"Sport99 Extractor non disponibile: {e}",
        "WARNING",
        "ServiceMonitor")


class StreamProxyServiceMonitor:
    """
    Monitora i servizi e forza la selezione del canale corretto
    anche al primo accesso alla ChannelSelection quando si usano servizi proxati.
    """

    PROXY_PATTERNS = ("127.0.0.1:7860", "proxy%2Fm3u", "proxy/m3u")

    def __init__(self, session):
        self.session = session
        self.config_file = os.path.join(
            os.path.dirname(__file__), "SPconfig.txt")

        self.proxy_active = False
        self.last_original_ref = None
        self._orig_playService = None
        self._orig_getters = {}
        self._playservice_signature = None  # Cache per la signature del metodo

        self._hook_navigation()
        self._hook_channelselection()
        enhanced_log("✅ ServiceMonitor inizializzato", "INFO")

    # =========================
    # Hook ChannelSelection
    # =========================
    def _hook_channelselection(self):
        """Installa gli hook necessari per la gestione della lista canali."""
        if getattr(ChannelSelection, "_sp_patched", False):
            return

        try:
            # Hook principale: showAllServices (sempre presente in Enigma2)
            orig_show = ChannelSelection.showAllServices

            def _show_wrap(inst, *a, **kw):
                ret = orig_show(inst, *a, **kw)
                try:
                    if self.proxy_active and self.last_original_ref:
                        # Primo timer per il caricamento iniziale
                        timer1 = eTimer()
                        timer1.callback.append(
                            lambda: self._fix_url_channel_selection(inst))
                        timer1.start(50, True)

                        # Secondo timer per assicurarsi che la selezione sia
                        # corretta
                        timer2 = eTimer()
                        timer2.callback.append(
                            lambda: self._fix_url_channel_selection(inst))
                        timer2.start(300, True)
                except Exception as e:
                    enhanced_log(
                        f"Errore hook showAllServices: {e}",
                        "DEBUG",
                        "ServiceMonitor")
                return ret

            ChannelSelection.showAllServices = _show_wrap

            # Hook opzionali per maggiore compatibilità
            for method_name in ['showFavourites', 'pathChanged']:
                if hasattr(ChannelSelection, method_name):
                    orig_method = getattr(ChannelSelection, method_name)

                    def _make_method_wrap(method, name):
                        def _method_wrap(inst, *a, **kw):
                            ret = method(inst, *a, **kw)
                            try:
                                if self.proxy_active and self.last_original_ref:
                                    timer = eTimer()
                                    timer.callback.append(
                                        lambda: self._fix_url_channel_selection(inst))
                                    timer.start(100, True)
                            except Exception as e:
                                enhanced_log(
                                    f"Errore hook {name}: {e}", "DEBUG", "ServiceMonitor")
                            return ret
                        return _method_wrap

                    setattr(
                        ChannelSelection,
                        method_name,
                        _make_method_wrap(
                            orig_method,
                            method_name))
                    enhanced_log(f"✅ Hook aggiunto per {method_name}", "DEBUG")

            ChannelSelection._sp_patched = True
            enhanced_log(
                "✅ Hook ChannelSelection installati correttamente",
                "INFO")

        except Exception as e:
            enhanced_log(
                f"❌ Errore installazione hook ChannelSelection: {e}",
                "ERROR")

    def _fix_url_channel_selection(self, inst):
        """Fix specifico per canali URL/IPTV con proxy attivo e ottimizzato per Enigma2."""
        try:
            if not hasattr(inst, "servicelist"):
                return

            servicelist = inst.servicelist
            if not servicelist:
                return

            # Ottieni il riferimento attualmente in riproduzione
            current_proxy_ref = self.session.nav.getCurrentlyPlayingServiceReference()
            if not current_proxy_ref:
                return

            current_selection = inst.getCurrentSelection()

            # Verifica se siamo nel caso di primo accesso con proxy attivo
            is_first_access = (self.proxy_active and
                               self.last_original_ref and
                               current_selection and
                               servicelist.getCurrentIndex() == 0)

            if is_first_access:
                enhanced_log(
                    "🔍 Rilevato primo accesso con proxy attivo", "DEBUG")

                try:
                    # Usa eServiceCenter per una ricerca più accurata
                    from enigma import eServiceCenter
                    serviceHandler = eServiceCenter.getInstance()

                    root = servicelist.getRoot()
                    if root:
                        services = serviceHandler.list(root)
                        if services:
                            # Prima cerca il riferimento originale
                            original_ref_str = self.last_original_ref.toString()
                            current_proxy_str = current_proxy_ref.toString()

                            # Salva l'indice corrente
                            start_pos = servicelist.getCurrentIndex()

                            # Cerca entrambi i riferimenti
                            servicelist.moveToFirst()
                            found = False

                            while True:
                                service = servicelist.getCurrent()
                                if service:
                                    service_str = service.toString()
                                    if service_str == original_ref_str:
                                        enhanced_log(
                                            "✅ Trovato riferimento originale", "DEBUG")
                                        found = True
                                        break
                                    elif service_str == current_proxy_str:
                                        enhanced_log(
                                            "✅ Trovato riferimento proxy", "DEBUG")
                                        found = True
                                        break

                                if not servicelist.moveToNext():
                                    break

                            if found:
                                # Aspetta un momento per assicurarsi che la UI
                                # sia pronta
                                from enigma import eTimer
                                timer = eTimer()

                                def do_select():
                                    service = servicelist.getCurrent()
                                    if service:
                                        inst.setCurrentSelection(service)
                                        servicelist.refresh()
                                        enhanced_log(
                                            "✅ Selezione canale aggiornata", "DEBUG")

                                timer.callback.append(do_select)
                                timer.start(100, True)
                            else:
                                # Se non trovato, torna alla posizione iniziale
                                servicelist.moveToIndex(start_pos)
                                enhanced_log(
                                    "⚠️ Canale non trovato, mantengo posizione corrente", "WARNING")

                except Exception as e:
                    enhanced_log(
                        f"⚠️ Errore durante la ricerca del canale: {e}", "WARNING")

            elif current_selection and current_selection.toString() != current_proxy_ref.toString():
                # Non è il primo accesso, ma la selezione non è corretta
                inst.setCurrentSelection(current_proxy_ref)
                servicelist.refresh()
                enhanced_log("🔄 Aggiornata selezione canale", "DEBUG")

        except Exception as e:
            enhanced_log(f"❌ Errore fix selezione canale: {e}", "ERROR")

    # =========================
    # Hook navigation
    # =========================
    def _hook_navigation(self):
        nav = getattr(self.session, "nav", None)
        if not nav:
            return

        # Hook playService
        if hasattr(nav, "playService") and not self._orig_playService:
            self._orig_playService = nav.playService
            self._detect_playservice_signature()
            nav.playService = self._interceptPlayService
            enhanced_log("🔗 Hook su playService installato", "INFO")

    # =========================
    # playService interception
    # =========================
    def _interceptPlayService(
            self,
            ref,
            checkParentalControl=True,
            forceRestart=False,
            adjust=True):
        try:
            if not ref or not hasattr(ref, "toString"):
                return self._call_orig_playService(
                    ref, checkParentalControl, forceRestart, adjust)

            ref_str = ref.toString() or ""
            enhanced_log(
                f"🔍 [SERVICEMONITOR] Intercettato playService: {ref_str}",
                "INFO")

            # ✅ GESTIONE URL PROXY DA PLUGIN ESTERNI
            if self._is_proxy_ref_string(ref_str):
                enhanced_log(
                    "🔄 [SERVICEMONITOR] Rilevato servizio già proxy", "DEBUG")

                # Estrai URL originale dal proxy se possibile
                original_url = self._extract_original_url_from_proxy(ref_str)
                if original_url:
                    enhanced_log(
                        f"🔍 [SERVICEMONITOR] URL originale estratto: {original_url[:100]}...", "DEBUG")
                    # Salva riferimento per gestione UI
                    self.last_original_ref = ref
                    self.proxy_active = True
                    # Salva info canale
                    parts = ref_str.split(":")
                    channel_name = ":".join(parts[11:]) if len(
                        parts) > 11 else "External Plugin Stream"
                    self._save_channel_info(
                        ref_str, original_url, channel_name)
                else:
                    enhanced_log(
                        "⚠️ [SERVICEMONITOR] Proxy da plugin esterno senza URL originale",
                        "WARNING")
                    self.proxy_active = True

                return self._call_orig_playService(
                    ref, checkParentalControl, forceRestart)

            parts = ref_str.split(":")
            enhanced_log(
                f"🔍 [SERVICEMONITOR] Parti servizio: {
                    len(parts)} elementi", "DEBUG")

            # ✅ Gestione riferimenti con #EXTVLCOPT
            url_part = ""
            channel_name = ""

            if len(parts) > 10:
                url_part = parts[10]
                # Se parte 10 contiene #EXTVLCOPT, cerca URL nelle parti
                # successive
                if url_part.startswith("#EXTVLCOPT"):
                    enhanced_log(
                        "🔍 [SERVICEMONITOR] Rilevato formato #EXTVLCOPT", "DEBUG")
                    # Cerca URL nelle parti successive (potrebbe essere in 11,
                    # 12, etc)
                    found_url = False
                    for i in range(11, len(parts)):
                        part = unquote(parts[i])
                        # Verifica se la parte contiene un URL valido
                        if part.startswith(
                                "http://") or part.startswith("https://"):
                            url_part = parts[i]
                            channel_name = ":".join(
                                parts[i + 1:]) if i + 1 < len(parts) else ""
                            found_url = True
                            enhanced_log(
                                f"✅ [SERVICEMONITOR] URL trovato in parte {i}", "DEBUG")
                            break

                    if not found_url:
                        # ✅ Riferimento #EXTVLCOPT senza URL - IGNORA e passa oltre
                        enhanced_log(
                            "⚠️ [SERVICEMONITOR] Riferimento #EXTVLCOPT senza URL stream, ignorato",
                            "WARNING")
                        self._reset_proxy_state()
                        return self._call_orig_playService(
                            ref, checkParentalControl, forceRestart, adjust)
                else:
                    channel_name = ":".join(
                        parts[11:]) if len(parts) > 11 else ""

            enhanced_log(
                f"🔍 [SERVICEMONITOR] URL parte: {url_part[:150]}...", "DEBUG")
            enhanced_log(
                f"🔍 [SERVICEMONITOR] Nome canale: {channel_name}",
                "DEBUG")

            if not url_part:
                self._reset_proxy_state()
                return self._call_orig_playService(
                    ref, checkParentalControl, forceRestart, adjust)

            clean_url = unquote(url_part)
            enhanced_log(
                f"🔍 [SERVICEMONITOR] URL decodificato: {clean_url[:150]}...", "INFO")

            # ✅ Verifica se è già un URL proxy (da plugin esterno) - GESTISCI HLS
            if self._is_already_proxy_url(clean_url):
                enhanced_log(
                    "✅ [SERVICEMONITOR] URL già proxy da plugin esterno", "INFO")

                # Estrai URL originale m3u8
                original_url = self._extract_original_url_from_proxy_url(
                    clean_url)
                if original_url:
                    enhanced_log(
                        f"🔍 [SERVICEMONITOR] URL m3u8 originale: {original_url[:100]}...", "DEBUG")

                    # ✅ CREA NUOVO RIFERIMENTO CON URL M3U8 DIRETTO
                    # Il proxy gestirà automaticamente i flussi HLS
                    self.proxy_active = True
                    self.last_original_ref = ref
                    self._save_channel_info(
                        ref_str, original_url, channel_name)

                    # Crea riferimento con URL m3u8 originale per gestione HLS
                    prefix = ":".join(parts[0:10])
                    safe_name = channel_name or "External Plugin Stream"
                    # Usa URL originale m3u8 - il proxy lo intercetterà
                    new_service_str = f"{prefix}:{
                        quote(original_url)}:{safe_name}"
                    m3u8_ref = eServiceReference(new_service_str)

                    enhanced_log(
                        f"🎬 [SERVICEMONITOR] Creato riferimento m3u8 per gestione HLS", "INFO")
                    return self._call_orig_playService(
                        m3u8_ref, checkParentalControl, forceRestart, adjust)
                else:
                    # Fallback: passthrough se non riusciamo a estrarre URL
                    enhanced_log(
                        "⚠️ [SERVICEMONITOR] Impossibile estrarre URL, passthrough",
                        "WARNING")
                    self.proxy_active = True
                    self.last_original_ref = ref
                    self._save_channel_info(ref_str, clean_url, channel_name)
                    return self._call_orig_playService(
                        ref, checkParentalControl, forceRestart, adjust)

            if not self._should_proxy(clean_url):
                enhanced_log(
                    f"🔄 [SERVICEMONITOR] URL non richiede proxy: {clean_url[:100]}...", "DEBUG")
                self._reset_proxy_state()
                return self._call_orig_playService(
                    ref, checkParentalControl, forceRestart, adjust)

            # Log specifico per powerset
            if "powerset" in clean_url.lower():
                enhanced_log(
                    f"🎯 [SERVICEMONITOR] Rilevato canale POWERSET: {clean_url}", "INFO")
                enhanced_log(
                    f"🎯 [SERVICEMONITOR] Nome canale: {channel_name}", "INFO")

            # CRITICO: Pulisci cache quando cambi canale per evitare conflitti
            # Gestione speciale per diversi provider di streaming
            url_lower = clean_url.lower()

            # Gestione VIX (stream audio/video separati)
            if any(
                vix_domain in url_lower for vix_domain in [
                    'vix',
                    'vixcloud',
                    'vixsrc']):
                enhanced_log(
                    f"🎯 [SERVICEMONITOR] Rilevato canale VIX: {clean_url}", "INFO")
                enhanced_log(
                    f"🧹 [SERVICEMONITOR] Pulizia cache per cambio canale VIX", "INFO")
                try:
                    # Import dinamico per evitare dipendenze circolari
                    from .AppCore import clear_stream_cache
                    clear_stream_cache()
                    # Pulizia cache segmenti TS e dati stream
                    self._clear_ts_cache()
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [SERVICEMONITOR] Errore pulizia cache VIX: {e}",
                        "WARNING")

            # Gestione DADDY - pulizia SOLO cache stream locale (NON cache
            # DLHD)
            elif any(d in url_lower for d in ['thedaddy', 'daddy', 'dlhd', 'newkso.ru']):
                enhanced_log(
                    f"🎯 [SERVICEMONITOR] Rilevato canale DADDY: {clean_url}", "INFO")
                try:
                    # ✅ CORREZIONE: NON pulire cache DLHD (troppo aggressivo)
                    # Pulisci solo cache stream locale per evitare conflitti
                    # tra segmenti
                    from .AppCore import clear_stream_cache
                    clear_stream_cache()
                    enhanced_log(
                        "🧹 [SERVICEMONITOR] Cache stream locale pulita", "INFO")
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [SERVICEMONITOR] Errore pulizia cache: {e}", "WARNING")

            # Gestione VAVOO - pulizia aggressiva
            elif 'vavoo' in url_lower:
                enhanced_log(
                    f"🎯 [SERVICEMONITOR] Rilevato canale VAVOO: {clean_url}", "INFO")
                try:
                    from .AppCore import clear_stream_cache, _clear_vavoo_resolved_url_cache, prefetch_vavoo_m3u8
                    clear_stream_cache()
                    _clear_vavoo_resolved_url_cache("cambio canale")
                    # Forza pulizia cache Enigma2
                    self._clear_ts_cache()
                    prefetch_vavoo_m3u8(clean_url)
                    enhanced_log(
                        "🧹 [SERVICEMONITOR] Cache VAVOO pulite e prefetch avviato", "INFO")
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [SERVICEMONITOR] Errore pulizia cache VAVOO: {e}",
                        "WARNING")

            # Gestione DLHD
            elif 'dlhd' in url_lower:
                enhanced_log(
                    f"🎯 [SERVICEMONITOR] Rilevato canale DLHD: {clean_url}", "INFO")
                try:
                    from .AppCore import clear_stream_cache
                    clear_stream_cache()
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [SERVICEMONITOR] Errore pulizia cache DLHD: {e}",
                        "WARNING")

            # Gestione NEWKSO
            elif 'newkso.ru' in url_lower:
                enhanced_log(
                    f"🎯 [SERVICEMONITOR] Rilevato canale NEWKSO: {clean_url}", "INFO")
                try:
                    from .AppCore import clear_stream_cache
                    clear_stream_cache()
                except Exception as e:
                    enhanced_log(
                        f"⚠️ [SERVICEMONITOR] Errore pulizia cache NEWKSO: {e}",
                        "WARNING")

            # Gestione Sport99 / CDNLiveTV
            if SPORT99_AVAILABLE and is_sport99_link(clean_url):
                enhanced_log(
                    f"[SERVICEMONITOR] Rilevato canale Sport99/CDNLiveTV: {clean_url}",
                    "INFO")
                try:
                    from .AppCore import clear_stream_cache
                    clear_stream_cache()
                    enhanced_log(
                        "[SERVICEMONITOR] Cache stream locale pulita per Sport99", "INFO")
                except Exception as e:
                    enhanced_log(
                        f"[SERVICEMONITOR] Errore pulizia cache Sport99: {e}",
                        "WARNING")

            # Gestione Freeshot
            freeshot_proxy_url = None

            try:
                # Gestione canali Freeshot (popcdn.day)
                if FREESHOT_AVAILABLE and is_freeshot_link(clean_url):
                    enhanced_log(
                        f"🎯 [SERVICEMONITOR] Rilevato canale Freeshot: {channel_name}", "INFO")
                    try:
                        resolved_freeshot = freeshot_extractor.extract(
                            clean_url)
                        if resolved_freeshot and resolved_freeshot.get(
                                'resolved_url'):
                            enhanced_log(
                                f"✅ [SERVICEMONITOR] Freeshot risolto: {
                                    resolved_freeshot['resolved_url']}", "INFO")
                            enhanced_log(
                                f"🔍 [SERVICEMONITOR] Headers da extractor: {
                                    resolved_freeshot.get(
                                        'headers', {})}", "DEBUG")

                            # ✅ CORREZIONE: Pulisci cache per Freeshot (usa fMP4, non TS)
                            try:
                                from .AppCore import clear_stream_cache
                                clear_stream_cache()
                                enhanced_log(
                                    "🧹 [SERVICEMONITOR] Cache pulita per Freeshot (fMP4)", "INFO")
                            except Exception as cache_e:
                                enhanced_log(
                                    f"⚠️ [SERVICEMONITOR] Errore pulizia cache Freeshot: {cache_e}", "WARNING")

                            # Crea URL proxy con headers custom
                            headers_query = "&".join(
                                [f"h_{quote(k)}={quote(v)}" for k, v in resolved_freeshot.get('headers', {}).items()])
                            freeshot_proxy_url = f"http://127.0.0.1:7860/proxy/m3u?url={
                                quote(
                                    resolved_freeshot['resolved_url'])}&{headers_query}"
                            enhanced_log(
                                f"✅ [SERVICEMONITOR] URL Freeshot proxy creato (supporto fMP4)", "INFO")
                            enhanced_log(
                                f"🔍 [SERVICEMONITOR] Proxy URL completo: {freeshot_proxy_url}", "DEBUG")
                    except Exception as e:
                        enhanced_log(
                            f"❌ [SERVICEMONITOR] Errore risoluzione Freeshot: {e}", "ERROR")
                        freeshot_proxy_url = None
            except Exception as e:
                enhanced_log(
                    f"❌ [SERVICEMONITOR] Errore gestione Freeshot: {e}",
                    "ERROR")
                freeshot_proxy_url = None

            # Gestione TVTap
            tvtap_proxy_url = None

            try:
                # Gestione canali TVTap WMS (stream.mardio.link con
                # wmsAuthSign)
                if TVTAP_WMS_AVAILABLE and is_wms_tvtap_url(clean_url):
                    enhanced_log(
                        f"🎯 [SERVICEMONITOR] Rilevato canale TVTap WMS: {channel_name}", "INFO")
                    tvtap_proxy_url = get_wms_proxy_url(
                        clean_url, channel_name)
                    if tvtap_proxy_url:
                        enhanced_log(
                            f"✅ [SERVICEMONITOR] URL TVTap WMS risolto", "INFO")
                        resolved_data = resolve_wms_tvtap_url(
                            clean_url, channel_name)
                        if resolved_data and resolved_data.get('decoded_info'):
                            valid_minutes = resolved_data['decoded_info'].get(
                                'valid_minutes', 'N/A')
                            enhanced_log(
                                f"🔑 [SERVICEMONITOR] wmsAuthSign valido per: {valid_minutes} minuti", "DEBUG")

                # Gestione TVTap standard
                elif any(pattern in clean_url.lower() for pattern in ['tvtap', 'rocktalk.net', 'taptube.net', 'authsign=']):
                    enhanced_log(
                        f"🎯 [SERVICEMONITOR] Rilevato URL TVTap standard: {clean_url}", "INFO")
                    tvtap_proxy_url = f"http://127.0.0.1:7860/proxy/m3u?url={
                        quote(clean_url)}"
                    enhanced_log(
                        f"✅ [SERVICEMONITOR] URL TVTap configurato", "INFO")
            except Exception as e:
                enhanced_log(
                    f"❌ [SERVICEMONITOR] Errore gestione TVTap: {e}", "ERROR")
                tvtap_proxy_url = None

            # Salva ref originale
            self.last_original_ref = ref
            self.proxy_active = True
            self._save_channel_info(ref_str, clean_url, channel_name)

            # Usa URL Freeshot risolto se disponibile, altrimenti TVTap,
            # altrimenti determina il tipo di proxy
            if freeshot_proxy_url:
                proxy_url = freeshot_proxy_url
                enhanced_log(
                    f"✅ [SERVICEMONITOR] Usando proxy URL Freeshot: {proxy_url[:100]}...", "INFO")
            elif tvtap_proxy_url:
                proxy_url = tvtap_proxy_url
                enhanced_log(
                    f"✅ [SERVICEMONITOR] Usando proxy URL TVTap: {proxy_url}", "INFO")
            else:
                # Determina il tipo di proxy da usare
                if clean_url.lower().endswith(
                        '.mpd') or '/dash/' in clean_url.lower() or 'browser-dash' in clean_url.lower():
                    # Stream MPD (DASH)
                    enhanced_log(
                        f"🎬 [SERVICEMONITOR] Creando proxy MPD per: {clean_url[:50]}...", "INFO")
                    proxy_url = f"http://127.0.0.1:7860/proxy/mpd?url={
                        quote(clean_url)}"
                else:
                    # Stream M3U8 (HLS) o altri
                    proxy_url = f"http://127.0.0.1:7860/proxy/m3u?url={
                        quote(clean_url)}"
                enhanced_log(
                    f"✅ [SERVICEMONITOR] Creato proxy URL: {proxy_url}", "INFO")

            prefix = ":".join(parts[0:10])
            safe_name = channel_name or "Stream Proxy"
            new_service_str = f"{prefix}:{quote(proxy_url)}:{safe_name}"
            proxy_ref = eServiceReference(new_service_str)
            # Imposta selezione alternativa per compatibilità UI
            self._set_current_selection_alternative(proxy_ref)

            return self._call_orig_playService(
                proxy_ref, checkParentalControl, forceRestart, adjust)

        except Exception as e:
            enhanced_log(f"❌ Errore interceptPlayService: {e}", "ERROR")
            self._reset_proxy_state()
            return self._call_orig_playService(
                ref, checkParentalControl, forceRestart, adjust)

    def _detect_playservice_signature(self):
        """Rileva la signature del metodo playService per Enigma2"""
        if not self._orig_playService:
            return

        try:
            import inspect
            sig = inspect.signature(self._orig_playService)
            param_names = list(sig.parameters.keys())

            # Enigma2 moderno usa sempre 4 parametri
            self._playservice_signature = 4  # ref, checkParentalControl, forceRestart, adjust
            enhanced_log(
                "✅ [SERVICEMONITOR] Configurato per Enigma2 moderno",
                "INFO")

        except Exception as e:
            enhanced_log(
                f"⚠️ [SERVICEMONITOR] Fallback a configurazione standard Enigma2: {e}",
                "WARNING")
            # Fallback alla configurazione più comune per Enigma2
            self._playservice_signature = 4

    def _call_orig_playService(
            self,
            ref,
            checkParentalControl=True,
            forceRestart=False,
            adjust=True):
        """Chiama il metodo playService originale con compatibilità multi-distro"""
        if not self._orig_playService:
            return False

        # Se abbiamo rilevato la signature, usala direttamente
        if self._playservice_signature == 4:
            try:
                return self._orig_playService(
                    ref, checkParentalControl, forceRestart, adjust)
            except Exception as e:
                enhanced_log(
                    f"❌ [SERVICEMONITOR] Errore con signature 4: {e}", "ERROR")
                return False
        elif self._playservice_signature == 3:
            try:
                return self._orig_playService(
                    ref, checkParentalControl, forceRestart)
            except Exception as e:
                enhanced_log(
                    f"❌ [SERVICEMONITOR] Errore con signature 3: {e}", "ERROR")
                return False
        elif self._playservice_signature == 2:
            try:
                return self._orig_playService(ref, checkParentalControl)
            except Exception as e:
                enhanced_log(
                    f"❌ [SERVICEMONITOR] Errore con signature 2: {e}", "ERROR")
                return False
        elif self._playservice_signature == 1:
            try:
                return self._orig_playService(ref)
            except Exception as e:
                enhanced_log(
                    f"❌ [SERVICEMONITOR] Errore con signature 1: {e}", "ERROR")
                return False

        # Fallback dinamico se non abbiamo rilevato la signature
        try:
            # Prova prima con tutti i parametri (OpenATV style)
            return self._orig_playService(
                ref, checkParentalControl, forceRestart)
        except TypeError as e:
            if "unexpected keyword argument" in str(e):
                try:
                    # Fallback: solo ref e checkParentalControl (OpenPLi style)
                    enhanced_log(
                        "🔄 [SERVICEMONITOR] Fallback a playService con 2 parametri", "DEBUG")
                    self._playservice_signature = 2  # Cache per chiamate future
                    return self._orig_playService(ref, checkParentalControl)
                except TypeError:
                    try:
                        # Fallback finale: solo ref (versioni molto vecchie)
                        enhanced_log(
                            "🔄 [SERVICEMONITOR] Fallback a playService con 1 parametro", "DEBUG")
                        self._playservice_signature = 1  # Cache per chiamate future
                        return self._orig_playService(ref)
                    except Exception as final_e:
                        enhanced_log(
                            f"❌ [SERVICEMONITOR] Tutti i fallback falliti: {final_e}", "ERROR")
                        return False
            else:
                enhanced_log(
                    f"❌ [SERVICEMONITOR] Errore playService non gestito: {e}",
                    "ERROR")
                return False
        except Exception as e:
            enhanced_log(
                f"❌ [SERVICEMONITOR] Errore generico playService: {e}",
                "ERROR")
            return False

    # Aggiungi dopo la sezione _interceptPlayService, prima dei metodi helper:

    def _clear_ts_cache(self):
        """Pulisce cache segmenti TS e dati stream"""
        try:
            # Pulizia cache Enigma2 per segmenti TS
            from enigma import eServiceCenter
            serviceCenter = eServiceCenter.getInstance()
            if hasattr(serviceCenter, 'clearCache'):
                serviceCenter.clearCache()
                enhanced_log(
                    "🧹 [SERVICEMONITOR] Cache Enigma2 pulita", "DEBUG")
        except Exception as e:
            enhanced_log(
                f"⚠️ [SERVICEMONITOR] Errore pulizia cache TS: {e}",
                "DEBUG")

    def _set_current_selection_alternative(self, proxy_ref):
        """Imposta selezione alternativa per compatibilità UI"""
        try:
            # Cerca ChannelSelection attiva
            from Screens.InfoBar import InfoBar
            if InfoBar.instance:
                session = InfoBar.instance.session
                if hasattr(session, 'current_dialog'):
                    current = session.current_dialog
                    if hasattr(current, 'setCurrentSelectionAlternative'):
                        current.setCurrentSelectionAlternative(proxy_ref)
                        enhanced_log(
                            "🎯 [SERVICEMONITOR] setCurrentSelectionAlternative impostato", "DEBUG")
        except Exception as e:
            enhanced_log(
                f"⚠️ [SERVICEMONITOR] Errore setCurrentSelectionAlternative: {e}",
                "DEBUG")

    # =========================
    # Helpers
    # =========================

    def _should_proxy(self, url: str) -> bool:
        """Verifica se URL richiede proxy - SOLO domini autorizzati"""
        if not url:
            return False

        url_lower = url.lower()

        # Estrai il dominio dall'URL per controlli più precisi
        domain_part = ""
        try:
            if url_lower.startswith(
                    "http://") or url_lower.startswith("https://"):
                # Rimuovi protocollo
                url_without_protocol = url_lower.split("://", 1)[1]
                # Estrai solo la parte del dominio (prima dello slash)
                domain_part = url_without_protocol.split("/")[0]
        except Exception:
            domain_part = url_lower

        # ✅ DOMINI AUTORIZZATI - Solo questi vengono proxati
        authorized_domains = (
            # DaddyLive e derivati
            "daddy", "dlhd", "thedaddy", "daddylive", "newkso.ru",
            # Vavoo
            "vavoo",
            # SportOnline
            "sportzonline", "sportsonline", "sportonline", "sportssonline",
            # Sport99 / CDNLiveTV
            "cdnlivetv.tv", "streamsports99.su", "sports99", "sport99",
            # TVTap
            "tvtap", "rocktalk.net", "taptube.net", "wmsauthsign", "stream.mardio.link",
            # Mixdrop (tutti i mirror)
            "mixdrop.co", "mixdrop.vip", "m1xdrop.bz", "m1xdrop.net", "mixdrop.ch", "mixdrop.ps", "mixdrop.ag", "mxcontent.net",
            # Maxstream/Uprot
            "uprot.net", "maxstream.video", "stayonline.pro",
            # Freeshot
            "popcdn.day", "freeshot://", "freeshot.live", "lovecdn.ru", "planetary.lovecdn.ru", "beautifulpeople.lovecdn.ru"
        )

        # Domini VIX - controllo specifico solo nel dominio
        vix_domains = ("vix", "vixcloud", "vixsrc")

        # Verifica domini VIX solo nella parte del dominio
        if any(vix_domain in domain_part for vix_domain in vix_domains):
            enhanced_log(
                f"✅ [SERVICEMONITOR] Dominio VIX autorizzato rilevato: {
                    [
                        d for d in vix_domains if d in domain_part][0]}",
                "DEBUG")
            return True

        # Verifica altri domini autorizzati nell'intero URL
        if any(domain in url_lower for domain in authorized_domains):
            enhanced_log(
                f"✅ [SERVICEMONITOR] Dominio autorizzato rilevato in URL: {
                    [
                        d for d in authorized_domains if d in url_lower][0]}",
                "DEBUG")
            return True

        # ❌ Tutti gli altri URL NON vengono proxati
        enhanced_log(
            f"🔄 [SERVICEMONITOR] URL non autorizzato, passthrough diretto",
            "DEBUG")
        return False

    def _is_proxy_ref_string(self, ref_str: str) -> bool:
        return any(p in (ref_str or "") for p in self.PROXY_PATTERNS)

    def _is_already_proxy_url(self, url: str) -> bool:
        """✅ Verifica se URL è già un proxy URL (da plugin esterno)"""
        if not url:
            return False
        url_lower = url.lower()
        return ("127.0.0.1:7860" in url_lower or
                "localhost:7860" in url_lower) and "/proxy" in url_lower

    def _extract_original_url_from_proxy_url(self, proxy_url: str) -> str:
        """✅ Estrae URL originale da proxy URL (formato: http://127.0.0.1:7860/proxy?url=...)"""
        try:
            if "url=" in proxy_url:
                url_start = proxy_url.find("url=") + 4
                url_end = proxy_url.find("&", url_start)
                if url_end == -1:
                    original_url = proxy_url[url_start:]
                else:
                    original_url = proxy_url[url_start:url_end]
                original_url = unquote(original_url)
                return original_url
            return None
        except Exception as e:
            enhanced_log(
                f"❌ [SERVICEMONITOR] Errore estrazione URL da proxy URL: {e}",
                "ERROR")
            return None

    def _extract_original_url_from_proxy(self, ref_str: str) -> str:
        """✅ Estrae URL originale da riferimento proxy (per plugin esterni)"""
        try:
            # Cerca pattern proxy/m3u?url=...
            if "proxy/m3u?url=" in ref_str or "proxy%2Fm3u?url=" in ref_str:
                # Estrai parte URL
                parts = ref_str.split(":")
                if len(parts) > 10:
                    url_part = parts[10]
                    # Decodifica URL
                    decoded = unquote(url_part)
                    # Cerca parametro url=
                    if "url=" in decoded:
                        url_start = decoded.find("url=") + 4
                        # Estrai fino al prossimo & o fine stringa
                        url_end = decoded.find("&", url_start)
                        if url_end == -1:
                            original_url = decoded[url_start:]
                        else:
                            original_url = decoded[url_start:url_end]
                        # Decodifica ulteriormente se necessario
                        original_url = unquote(original_url)
                        enhanced_log(
                            f"✅ [SERVICEMONITOR] URL estratto da proxy: {original_url[:100]}...", "DEBUG")
                        return original_url
            return None
        except Exception as e:
            enhanced_log(
                f"❌ [SERVICEMONITOR] Errore estrazione URL da proxy: {e}",
                "ERROR")
            return None

    def _force_exteplayer3_for_mpd(self, ref, mpd_url):
        """Forza l'uso di exteplayer3 per stream MPD/DASH"""
        try:
            from enigma import eServiceReference
            # Service type 5001 = exteplayer3 DASH
            mpd_ref_str = ref.toString()
            parts = mpd_ref_str.split(':')
            if len(parts) > 0:
                # Cambia service type a 5001 (exteplayer3 DASH)
                parts[0] = '5001'
                new_ref_str = ':'.join(parts)
                enhanced_log(
                    f"✅ [SERVICEMONITOR] Riferimento modificato per exteplayer3 (5001)",
                    "INFO")
                return eServiceReference(new_ref_str)
        except Exception as e:
            enhanced_log(
                f"❌ [SERVICEMONITOR] Errore forzatura exteplayer3: {e}",
                "ERROR")
        return ref

    def _reset_proxy_state(self):
        self.proxy_active = False
        self.last_original_ref = None

    def _save_channel_info(
            self,
            service_str: str,
            url: str,
            channel_name: str):
        try:
            cfg = {"last_service_ref": service_str,
                   "last_channel_name": channel_name or "Stream Proxy"}
            tmp = self.config_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.config_file)
        except Exception as e:
            enhanced_log(f"❌ Errore salvataggio config: {e}", "ERROR")

    # =========================
    # Cleanup
    # =========================
    def cleanup(self):
        nav = getattr(self.session, "nav", None)
        if nav and self._orig_playService:
            nav.playService = self._orig_playService
        for name, fn in self._orig_getters.items():
            if hasattr(nav, name):
                setattr(nav, name, fn)
        self._orig_getters.clear()
        self._orig_playService = None
        self._reset_proxy_state()
        enhanced_log("🧹 Cleanup completato", "INFO")
