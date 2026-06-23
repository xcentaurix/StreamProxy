# utils/header_manager.py - Gestore headers per propagazione corretta tra M3U8 e segmenti TS

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class HeaderManager:
    """Gestisce la propagazione corretta degli headers tra M3U8 e segmenti TS"""
    
    def __init__(self):
        self.stream_headers = {}  # stream_id -> headers
        
    def save_stream_headers(self, stream_id: str, headers: Dict[str, str]):
        """Salva gli headers per uno stream specifico"""
        if not stream_id or not headers:
            return
            
        # Headers essenziali per l'autenticazione
        essential_headers = [
            'Authorization', 'X-Channel-Key', 'X-Client-Token', 
            'Heartbeat-Url', 'User-Agent', 'Referer', 'Origin', 'Cookie'
        ]
        
        # Filtra solo gli headers essenziali
        filtered_headers = {}
        for key, value in headers.items():
            if key in essential_headers:
                filtered_headers[key] = value
        
        if filtered_headers:
            self.stream_headers[stream_id] = filtered_headers
            logger.info(f"💾 [HEADER_MANAGER] Salvati {len(filtered_headers)} headers per stream {stream_id}")
            logger.debug(f"📝 [HEADER_MANAGER] Headers: {list(filtered_headers.keys())}")
    
    def get_stream_headers(self, stream_id: str) -> Dict[str, str]:
        """Ottiene gli headers salvati per uno stream"""
        return self.stream_headers.get(stream_id, {})
    
    def combine_headers(self, stream_id: str, query_headers: Dict[str, str]) -> Dict[str, str]:
        """Combina headers dal query string con quelli salvati per lo stream"""
        saved_headers = self.get_stream_headers(stream_id)
        
        # Gli headers dal query string hanno priorità
        combined = saved_headers.copy()
        combined.update(query_headers)
        
        # Verifica headers critici mancanti
        critical_headers = ['Authorization', 'X-Channel-Key', 'X-Client-Token']
        missing_critical = [h for h in critical_headers if h not in combined]
        
        if missing_critical:
            logger.warning(f"⚠️ [HEADER_MANAGER] Headers critici mancanti per {stream_id}: {missing_critical}")
        
        return combined
    
    def clear_stream(self, stream_id: str):
        """Rimuove gli headers per uno stream specifico"""
        if stream_id in self.stream_headers:
            del self.stream_headers[stream_id]
            logger.debug(f"🗑️ [HEADER_MANAGER] Rimossi headers per stream {stream_id}")
    
    def clear_all(self):
        """Rimuove tutti gli headers salvati"""
        count = len(self.stream_headers)
        self.stream_headers.clear()
        if count > 0:
            logger.info(f"🧹 [HEADER_MANAGER] Rimossi headers per {count} stream")

# Istanza globale
header_manager = HeaderManager()