# -*- coding: utf-8 -*-
"""
TVTap WMS Manager - Gestione specifica per canali TVTap con wmsAuthSign
Gestisce canali TVTap che usano stream.mardio.link con wmsAuthSign
"""

import re
import time
import base64
import json
import threading
import hashlib
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote, quote
from datetime import datetime, timedelta

try:
    from .StreamProxyLog import enhanced_log
    import requests
except ImportError:
    def enhanced_log(message, level="INFO", component="TVTAP_WMS"):
        print(f"[{level}] [{component}] {message}")
    import requests


class TVTapWMSManager:
    """
    Gestore specializzato per canali TVTap con wmsAuthSign.
    
    Caratteristiche:
    - Decodifica wmsAuthSign per estrarre scadenza
    - Refresh automatico prima della scadenza
    - Cache intelligente per URL
    - Gestione domini dinamici stream.mardio.link
    """
    
    def __init__(self):
        self.url_cache = {}       # {original_url: cached_data}
        self.domain_cache = {}    # {domain: last_seen}
        
        # Lock per thread safety
        self.lock = threading.RLock()
        
        # Configurazione timing
        self.default_validity = 1200  # 20 minuti validità default
        self.refresh_before_expiry = 120  # Refresh 2 minuti prima scadenza
        
        # Pattern per rilevare canali WMS TVTap
        self.wms_patterns = [
            r'stream\.mardio\.link',
            r'wmsAuthSign=',
            r'wmsauthsign='
        ]
        
        enhanced_log("TVTap WMS Manager inizializzato", "INFO")
    
    def is_wms_tvtap_url(self, url):
        """Verifica se un URL è un canale TVTap WMS."""
        if not url:
            return False
        
        url_lower = url.lower()
        return any(re.search(pattern, url_lower) for pattern in self.wms_patterns)
    
    def decode_wms_authsign(self, authsign):
        """
        Decodifica wmsAuthSign per estrarre informazioni.
        
        Args:
            authsign (str): wmsAuthSign codificato in base64
            
        Returns:
            dict: Informazioni decodificate o None
        """
        try:
            # Decodifica base64
            decoded_bytes = base64.b64decode(authsign)
            decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
            
            enhanced_log(f"wmsAuthSign decodificato: {decoded_str}", "DEBUG")
            
            # Estrai informazioni
            info = {}
            
            # Cerca timestamp server
            server_time_match = re.search(r'server_time=([^&]+)', decoded_str)
            if server_time_match:
                info['server_time'] = server_time_match.group(1)
            
            # Cerca validminutes
            valid_minutes_match = re.search(r'validminutes=(\d+)', decoded_str)
            if valid_minutes_match:
                info['valid_minutes'] = int(valid_minutes_match.group(1))
            
            # Cerca hash_value
            hash_match = re.search(r'hash_value=([^&]+)', decoded_str)
            if hash_match:
                info['hash_value'] = hash_match.group(1)
            
            # Cerca id
            id_match = re.search(r'id=(\d+)', decoded_str)
            if id_match:
                info['id'] = id_match.group(1)
            
            return info
            
        except Exception as e:
            enhanced_log(f"Errore decodifica wmsAuthSign: {e}", "ERROR")
            return None
    
    def calculate_expiry_from_authsign(self, authsign):
        """Calcola scadenza dall'authSign decodificato."""
        try:
            decoded_info = self.decode_wms_authsign(authsign)
            if not decoded_info:
                return datetime.now() + timedelta(seconds=self.default_validity)

            # Verifica se c'è server_time per calcolare scadenza reale
            if 'server_time' in decoded_info and 'valid_minutes' in decoded_info:
                server_time_str = decoded_info['server_time'].strip()
                valid_minutes = decoded_info['valid_minutes']

                # Parsing manuale per evitare problemi con locale
                server_time = None
                try:
                    # Normalizza spazi multipli
                    server_time_str = ' '.join(server_time_str.split())
                    
                    # Parsing manuale: "11/2/2025 5:15:28 PM"
                    import re
                    match = re.match(r'(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+)\s+(AM|PM)', server_time_str)
                    if match:
                        month, day, year, hour, minute, second, ampm = match.groups()
                        hour = int(hour)
                        if ampm == 'PM' and hour != 12:
                            hour += 12
                        elif ampm == 'AM' and hour == 12:
                            hour = 0
                        
                        server_time = datetime(int(year), int(month), int(day), hour, int(minute), int(second))
                        enhanced_log(f"✅ Server time parsed: {server_time}", "DEBUG")
                    else:
                        raise ValueError("Formato data non valido")
                        
                except (ValueError, AttributeError) as e:
                    # Parsing fallito - token probabilmente non valido
                    enhanced_log(f"❌ Parsing server_time fallito: {e}, token non valido", "ERROR")
                    return datetime.now()  # Forza refresh immediato

                # Calcola scadenza - server usa UTC, sistema usa ora locale
                now = datetime.now()
                real_expires_at = server_time + timedelta(minutes=valid_minutes)
                
                # ✅ CORREZIONE FUSO ORARIO: Aggiungi 1 ora (UTC+1 per Italia)
                real_expires_at = real_expires_at + timedelta(hours=1)
                
                enhanced_log(f"🕐 Server time: {server_time} UTC, Now: {now}, Expires: {real_expires_at}", "DEBUG")

                # ✅ VERIFICA SE wmsAuthSign È TROPPO VECCHIO (>1 giorno)
                age_hours = (now - server_time).total_seconds() / 3600
                if age_hours > 24:
                    enhanced_log(f"❌ wmsAuthSign TROPPO VECCHIO! Age: {age_hours:.1f}h, forzo refresh", "WARNING")
                    return now

                # Verifica se è già scaduto
                if real_expires_at <= now:
                    enhanced_log(f"⚠️ wmsAuthSign SCADUTO! Scadenza: {real_expires_at}, Ora: {now}", "WARNING")
                    return now
                
                enhanced_log(f"✅ wmsAuthSign valido fino a: {real_expires_at}", "DEBUG")
                return real_expires_at

            # Fallback: usa validminutes da ora corrente
            if 'valid_minutes' in decoded_info:
                valid_minutes = decoded_info['valid_minutes']
                expires_at = datetime.now() + timedelta(minutes=valid_minutes)
                enhanced_log(f"Scadenza calcolata da validminutes (fallback): {expires_at} ({valid_minutes} min)", "DEBUG")
                return expires_at

            # Fallback su validità default
            return datetime.now() + timedelta(seconds=self.default_validity)

        except Exception as e:
            enhanced_log(f"Errore calcolo scadenza: {e}", "ERROR")
            return datetime.now() + timedelta(seconds=self.default_validity)

    
    def resolve_wms_tvtap_url(self, original_url, channel_name=None):
        """
        Risolve un URL TVTap WMS SEMPRE rigenerando (NO CACHE).
        
        Args:
            original_url (str): URL originale del canale
            channel_name (str, optional): Nome del canale
            
        Returns:
            dict: {
                'resolved_url': str,
                'expires_at': datetime,
                'domain': str,
                'authsign': str,
                'decoded_info': dict
            }
        """
        enhanced_log(f"Risoluzione URL TVTap WMS: {original_url[:100]}...", "INFO")
        
        with self.lock:
            # ✅ NO CACHE - SEMPRE RIGENERA
            cache_key = self._get_cache_key(original_url)
            return self._resolve_fresh_wms_url(original_url, channel_name, cache_key)
    
    def _resolve_fresh_wms_url(self, original_url, channel_name, cache_key):
        """Risolve un nuovo URL TVTap WMS verificando prima se wmsAuthSign è valido."""
        enhanced_log(f"Risoluzione fresh URL TVTap WMS: {original_url}", "INFO")
        
        try:
            # ✅ VERIFICA PRIMA SE wmsAuthSign ESISTENTE È VALIDO
            parsed_url = urlparse(original_url)
            query_params = parse_qs(parsed_url.query)
            
            existing_authsign = None
            if 'wmsAuthSign' in query_params:
                existing_authsign = query_params['wmsAuthSign'][0]
            
            # Se esiste wmsAuthSign, verifica se è ancora valido
            if existing_authsign:
                decoded_info = self.decode_wms_authsign(existing_authsign)
                expires_at = self.calculate_expiry_from_authsign(existing_authsign)
                
                now = datetime.now()
                time_to_expiry = (expires_at - now).total_seconds()
                
                # Se valido per più di 2 minuti, usalo
                if time_to_expiry > 120:
                    enhanced_log(f"✅ wmsAuthSign esistente valido per {time_to_expiry/60:.1f} min, uso quello", "INFO")
                    
                    cache_data = {
                        'resolved_url': original_url,
                        'original_url': original_url,
                        'expires_at': expires_at,
                        'domain': parsed_url.netloc,
                        'authsign': existing_authsign,
                        'decoded_info': decoded_info,
                        'channel_name': channel_name,
                        'created_at': datetime.now(),
                        'access_count': 0,
                        'was_refreshed': False
                    }
                    
                    self.url_cache[cache_key] = cache_data
                    self.domain_cache[parsed_url.netloc] = datetime.now()
                    
                    return cache_data
                else:
                    enhanced_log(f"⚠️ wmsAuthSign scade tra {time_to_expiry/60:.1f} min, rigenero", "WARNING")
            
            # ✅ RIGENERA wmsAuthSign tramite API TVTap
            enhanced_log("🔄 Forzo rigenerazione wmsAuthSign tramite API TVTap", "INFO")
            
            # Estrai nome canale
            channel_to_search = self._extract_channel_name_from_url(original_url, channel_name)
            
            if not channel_to_search:
                enhanced_log("❌ Impossibile determinare nome canale", "ERROR")
                return None
            
            # ✅ USA API TVTap per ottenere stream fresco
            fresh_stream_url = self._get_fresh_tvtap_stream(channel_to_search)
            
            if not fresh_stream_url or not self.is_wms_tvtap_url(fresh_stream_url):
                enhanced_log("❌ Impossibile ottenere stream da API TVTap", "ERROR")
                return None
            
            enhanced_log(f"✅ Stream fresco ottenuto da API TVTap", "INFO")
            
            # Analizza nuovo URL
            parsed_url = urlparse(fresh_stream_url)
            query_params = parse_qs(parsed_url.query)
            
            # Estrai wmsAuthSign fresco
            wms_authsign = None
            if 'wmsAuthSign' in query_params:
                wms_authsign = query_params['wmsAuthSign'][0]
            
            if not wms_authsign:
                enhanced_log("❌ Nuovo URL non contiene wmsAuthSign", "ERROR")
                return None
            
            # Decodifica e calcola scadenza
            decoded_info = self.decode_wms_authsign(wms_authsign)
            expires_at = self.calculate_expiry_from_authsign(wms_authsign)
            
            now = datetime.now()
            needs_refresh = False
            # ✅ USA SEMPRE URL FRESCO
            resolved_url = fresh_stream_url
            domain = parsed_url.netloc
            
            enhanced_log(f"🔑 wmsAuthSign fresco: {wms_authsign[:20]}..., scadenza: {expires_at}", "INFO")
            
            # Crea dati cache
            cache_data = {
                'resolved_url': resolved_url,
                'original_url': original_url,
                'expires_at': expires_at,
                'domain': domain,
                'authsign': wms_authsign,
                'decoded_info': decoded_info,
                'channel_name': channel_name,
                'created_at': datetime.now(),
                'access_count': 0,
                'was_refreshed': True
            }
            
            # Salva in cache
            self.url_cache[cache_key] = cache_data
            
            # Aggiorna cache domini
            self.domain_cache[domain] = datetime.now()
            
            enhanced_log(f"URL TVTap WMS risolto: {domain}", "INFO")
            enhanced_log(f"Scadenza: {expires_at}", "DEBUG")
            if decoded_info:
                enhanced_log(f"Info decodificate: {decoded_info}", "DEBUG")
            
            return cache_data
            
        except Exception as e:
            enhanced_log(f"Errore risoluzione URL TVTap WMS: {e}", "ERROR")
            return None
    
    def _is_cache_valid(self, cache_data):
        """Verifica se i dati in cache sono ancora validi."""
        if not cache_data or 'expires_at' not in cache_data:
            return False
        
        return datetime.now() < cache_data['expires_at']
    
    def _needs_proactive_refresh(self, cache_data):
        """Verifica se serve un refresh proattivo."""
        if not cache_data or 'expires_at' not in cache_data:
            return True
        
        time_to_expiry = (cache_data['expires_at'] - datetime.now()).total_seconds()
        return time_to_expiry <= self.refresh_before_expiry
    
    def _start_background_refresh(self, original_url, channel_name, cache_key):
        """Avvia refresh in background con rigenerazione wmsAuthSign."""
        def refresh_worker():
            try:
                enhanced_log(f"Background refresh URL TVTap WMS: {original_url[:50]}...", "DEBUG")
                time.sleep(5)  # Piccolo delay
                
                # Rimuovi dalla cache per forzare rigenerazione
                with self.lock:
                    if cache_key in self.url_cache:
                        del self.url_cache[cache_key]
                        enhanced_log("Cache TVTap WMS rimossa per refresh proattivo", "DEBUG")
                
                # Forza rigenerazione chiamando resolve_wms_tvtap_url
                # Questo attiverà la logica di verifica e rigenerazione wmsAuthSign
                refreshed_data = self.resolve_wms_tvtap_url(original_url, channel_name)
                if refreshed_data and refreshed_data.get('was_refreshed'):
                    enhanced_log("✅ Background refresh completato con successo", "INFO")
                else:
                    enhanced_log("⚠️ Background refresh non ha rigenerato wmsAuthSign", "WARNING")
                
            except Exception as e:
                enhanced_log(f"Errore background refresh WMS: {e}", "ERROR")
        
        thread = threading.Thread(target=refresh_worker, daemon=True)
        thread.start()
    
    def _extract_channel_name_from_url(self, url, provided_name=None):
        """Estrae il nome del canale dall'URL con fallback multipli."""
        if provided_name:
            return provided_name.strip()
        
        try:
            parsed = urlparse(url)
            path_parts = parsed.path.split('/')
            
            # Tentativo 1: Pattern it-*.stream
            for part in path_parts:
                if part.startswith('it-') and '.stream' in part:
                    channel_name = part.replace('it-', '').replace('.stream', '')
                    channel_name = channel_name.replace('-', ' ').title()
                    enhanced_log(f"Nome canale estratto (pattern it-): {channel_name}", "DEBUG")
                    return channel_name
            
            # Tentativo 2: Nome file senza estensione
            if path_parts:
                filename = path_parts[-1].replace('.m3u8', '').replace('playlist', '').replace('.stream', '')
                filename = filename.strip('-').strip('_').strip()
                if filename and len(filename) > 2:
                    channel_name = filename.replace('-', ' ').replace('_', ' ').title()
                    enhanced_log(f"Nome canale estratto (filename): {channel_name}", "DEBUG")
                    return channel_name
            
            # Tentativo 3: Match con lista statica
            try:
                from .extractor.tvtap_extractor import get_static_italian_channels
                channels = get_static_italian_channels()
                url_lower = url.lower()
                
                for ch in channels:
                    ch_name_lower = ch['name'].lower().replace(' ', '')
                    if ch_name_lower in url_lower:
                        enhanced_log(f"Nome canale trovato (match statico): {ch['name']}", "DEBUG")
                        return ch['name']
            except Exception as e:
                enhanced_log(f"Fallback lista statica fallito: {e}", "DEBUG")
            
            enhanced_log("Impossibile estrarre nome canale dall'URL", "WARNING")
            return None
            
        except Exception as e:
            enhanced_log(f"Errore estrazione nome canale: {e}", "ERROR")
            return None
    
    def _get_fresh_tvtap_stream(self, channel_name):
        """Ottiene un nuovo stream URL da tvtap_extractor con logging dettagliato."""
        try:
            from .extractor.tvtap_extractor import get_tvtap_channels, find_channel_by_name, get_tvtap_stream

            enhanced_log(f"🔄 Ricerca nuovo stream per canale: {channel_name}", "INFO")

            # Ottieni lista canali
            enhanced_log("📡 Richiesta lista canali TVTap API...", "DEBUG")
            channels = get_tvtap_channels()
            if not channels:
                enhanced_log("❌ Nessun canale disponibile da TVTap API", "ERROR")
                return None
            
            enhanced_log(f"✅ Ricevuti {len(channels)} canali da TVTap API", "DEBUG")

            # Trova canale per nome
            enhanced_log(f"🔍 Ricerca canale '{channel_name}' nella lista...", "DEBUG")
            found_channel = find_channel_by_name(channel_name, channels)
            if not found_channel:
                enhanced_log(f"❌ Canale '{channel_name}' non trovato nella lista TVTap", "WARNING")
                # Log primi 5 canali per debug
                sample = [ch.get('name', 'N/A') for ch in channels[:5]]
                enhanced_log(f"📋 Canali disponibili (sample): {sample}", "DEBUG")
                return None

            channel_id = found_channel.get('id')
            if not channel_id:
                enhanced_log(f"❌ ID non trovato per canale '{channel_name}'", "ERROR")
                return None

            enhanced_log(f"✅ Canale trovato: {found_channel.get('name')} (ID: {channel_id})", "INFO")

            # Ottieni stream URL
            enhanced_log(f"📡 Richiesta stream URL per ID {channel_id}...", "DEBUG")
            stream_url = get_tvtap_stream(channel_id)
            if stream_url:
                enhanced_log(f"✅ Nuovo stream URL ottenuto: {stream_url[:80]}...", "INFO")
                return stream_url
            else:
                enhanced_log(f"❌ Impossibile ottenere stream URL per {channel_name}", "ERROR")
                return None

        except ImportError as e:
            enhanced_log(f"❌ tvtap_extractor non disponibile: {e}", "ERROR")
            return None
        except Exception as e:
            enhanced_log(f"❌ Errore ottenimento stream TVTap: {e}", "ERROR")
            import traceback
            enhanced_log(f"Stack trace: {traceback.format_exc()}", "DEBUG")
            return None


    
    def _get_cache_key(self, url):
        """Genera chiave cache per URL."""
        # Rimuovi parametri variabili per chiave consistente
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return hashlib.md5(base_url.encode()).hexdigest()
    
    def get_proxy_url_for_wms_url(self, original_url, channel_name=None, base_proxy_url="http://127.0.0.1:7860"):
        """
        Genera URL proxy per un URL TVTap WMS.
        
        Args:
            original_url (str): URL originale
            channel_name (str, optional): Nome canale
            base_proxy_url (str): URL base del proxy
            
        Returns:
            str: URL proxy o None se errore
        """
        if not self.is_wms_tvtap_url(original_url):
            return None
        
        # Risolvi URL con authSign aggiornato
        resolved_data = self.resolve_wms_tvtap_url(original_url, channel_name)
        if not resolved_data:
            return None
        
        resolved_url = resolved_data.get('resolved_url')
        if not resolved_url:
            return None
        
        # Genera URL proxy
        proxy_url = f"{base_proxy_url}/proxy/m3u?url={quote(resolved_url)}"
        
        enhanced_log(f"Proxy URL TVTap WMS generato per: {channel_name or 'Unknown'}", "DEBUG")
        return proxy_url
    
    def cleanup_expired_cache(self):
        """Pulisce cache scadute."""
        with self.lock:
            expired_keys = []
            
            for key, data in self.url_cache.items():
                if not self._is_cache_valid(data):
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.url_cache[key]
            
            if expired_keys:
                enhanced_log(f"Pulite {len(expired_keys)} cache TVTap WMS scadute", "INFO")
    
    def get_stats(self):
        """Restituisce statistiche del manager."""
        with self.lock:
            total_cached = len(self.url_cache)
            valid_cached = sum(1 for data in self.url_cache.values() 
                             if self._is_cache_valid(data))
            
            return {
                'total_cached_urls': total_cached,
                'valid_cached_urls': valid_cached,
                'expired_cached_urls': total_cached - valid_cached,
                'known_domains': len(self.domain_cache)
            }
    
    def force_refresh_all(self):
        """Forza refresh di tutti gli URL in cache."""
        with self.lock:
            # Per ora, semplicemente pulisce tutta la cache
            old_count = len(self.url_cache)
            self.url_cache.clear()
            enhanced_log(f"Cache TVTap WMS pulita: {old_count} URL rimossi", "INFO")


# Istanza globale del manager
tvtap_wms_manager = TVTapWMSManager()


def is_wms_tvtap_url(url):
    """
    Verifica se un URL è un canale TVTap WMS.
    
    Args:
        url (str): URL da verificare
        
    Returns:
        bool: True se è TVTap WMS
    """
    return tvtap_wms_manager.is_wms_tvtap_url(url)


def resolve_wms_tvtap_url(original_url, channel_name=None):
    """
    Risolve URL TVTap WMS con gestione wmsAuthSign dinamico.
    
    Args:
        original_url (str): URL originale
        channel_name (str, optional): Nome canale
        
    Returns:
        dict: Dati risoluzione o None
    """
    return tvtap_wms_manager.resolve_wms_tvtap_url(original_url, channel_name)


def get_wms_proxy_url(original_url, channel_name=None, base_proxy_url="http://127.0.0.1:7860"):
    """
    Ottiene URL proxy per un URL TVTap WMS.
    
    Args:
        original_url (str): URL originale
        channel_name (str, optional): Nome canale
        base_proxy_url (str): URL base proxy
        
    Returns:
        str: URL proxy o None
    """
    return tvtap_wms_manager.get_proxy_url_for_wms_url(original_url, channel_name, base_proxy_url)


def cleanup_wms_cache():
    """Pulisce cache TVTap WMS scadute."""
    tvtap_wms_manager.cleanup_expired_cache()


def get_wms_stats():
    """Restituisce statistiche TVTap WMS."""
    return tvtap_wms_manager.get_stats()


if __name__ == "__main__":
    # Test del WMS manager
    print("=== Test TVTap WMS Manager ===")
    
    # Test URL di esempio
    test_url = "http://stream.mardio.link:8081/live/it-babytv.stream/playlist.m3u8?wmsAuthSign=c2VydmVyX3RpbWU9OS82LzIwMjUgNToyNjozMyBBTSZoYXNoX3ZhbHVlPVRQc3lHcFIzRkUyajZSSTVzV1BJY1E9PSZ2YWxpZG1pbnV0ZXM9MjAmaWQ9MTc1NzEzNjM5MzQyNg=="
    
    print(f"Test URL: {test_url}")
    print(f"È WMS TVTap: {is_wms_tvtap_url(test_url)}")
    
    if is_wms_tvtap_url(test_url):
        resolved = resolve_wms_tvtap_url(test_url, "Baby TV")
        if resolved:
            print(f"Risolto: {resolved['resolved_url']}")
            print(f"Dominio: {resolved['domain']}")
            print(f"AuthSign: {resolved.get('authsign', 'N/A')[:20]}...")
            print(f"Scade: {resolved['expires_at']}")
            print(f"Info decodificate: {resolved.get('decoded_info', {})}")
        else:
            print("Risoluzione fallita")
    
    # Statistiche
    stats = get_wms_stats()
    print(f"Statistiche: {stats}")
    
    print("\n=== Test completato ===")
