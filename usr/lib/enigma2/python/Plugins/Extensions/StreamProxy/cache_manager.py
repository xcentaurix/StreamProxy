# cache_manager.py - Gestione centralizzata delle cache per StreamProxy
import time
import threading
from .StreamProxyLog import enhanced_log

class SimpleTTLCache(dict):
    """Cache con Time-To-Live per i file M3U8"""
    def __init__(self, maxsize=100, ttl=5, cleanup_interval=30, max_memory_mb=50):
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl
        self._timestamps = {}
        self._sizes = {}  # Traccia la dimensione di ogni elemento
        self._total_size = 0  # Dimensione totale in bytes
        self._max_memory = max_memory_mb * 1024 * 1024  # Limite di memoria in bytes
        self._lock = threading.RLock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True)
        self._cleanup_thread.start()

    def __setitem__(self, key, value):
        with self._lock:
            # Calcola la dimensione del valore
            value_size = len(value) if isinstance(value, (bytes, str)) else 512  # Dimensione stimata per oggetti non stringhe
            
            # Se l'elemento esiste già, sottrai la sua dimensione attuale
            if dict.__contains__(self, key):
                self._total_size -= self._sizes.get(key, 0)
                
            # Verifica se l'aggiunta supererebbe il limite di memoria
            if self._total_size + value_size > self._max_memory:
                self._evict_by_memory(value_size)
                
            # Verifica se l'aggiunta supererebbe il limite di elementi
            if len(self) >= self.maxsize and not dict.__contains__(self, key):
                self._evict_oldest()
                
            # Aggiorna cache, timestamp e dimensione
            super().__setitem__(key, value)
            self._timestamps[key] = time.time()
            self._sizes[key] = value_size
            self._total_size += value_size
            
    def _evict_by_memory(self, needed_space):
        # Rimuovi elementi fino a liberare lo spazio necessario
        while self._total_size + needed_space > self._max_memory * 0.9 and self:  # Mantieni 10% di margine
            oldest = min(self._timestamps, key=self._timestamps.get) if self._timestamps else None
            if not oldest:
                break
            self._safe_remove(oldest)
            
    def __getitem__(self, key):
        with self._lock:
            # Verifica se la chiave esiste e non è scaduta
            if dict.__contains__(self, key) and (time.time() - self._timestamps.get(key, 0)) < self.ttl:
                return dict.__getitem__(self, key)
            # Se la chiave è scaduta o non esiste, rimuovila e solleva KeyError
            self._safe_remove(key)
            raise KeyError(key)
            
    def __contains__(self, key):
        with self._lock:
            # Verifica se la chiave esiste e non è scaduta
            if dict.__contains__(self, key) and (time.time() - self._timestamps.get(key, 0)) < self.ttl:
                return True
            # Se la chiave è scaduta, rimuovila
            self._safe_remove(key)
            return False
            
    def _evict_oldest(self):
        # Rimuove gli elementi più vecchi o scaduti
        expired = [k for k, t in self._timestamps.items() if (time.time() - t) >= self.ttl]
        for k in expired:
            self._safe_remove(k)
        # Se ancora necessario, rimuovi il più vecchio
        if len(self) >= self.maxsize and self._timestamps:
            oldest = min(self._timestamps, key=self._timestamps.get)
            self._safe_remove(oldest)
            
    def _safe_remove(self, key):
        # Rimuove in sicurezza una chiave e aggiorna la dimensione totale
        if dict.__contains__(self, key):
            self._total_size -= self._sizes.pop(key, 0)
            dict.pop(self, key, None)
            self._timestamps.pop(key, None)
            
    def _periodic_cleanup(self):
        """Esegue la pulizia periodica della cache in un thread separato."""
        while True:
            try:
                time.sleep(self._cleanup_interval)
                with self._lock:
                    # Rimuove gli elementi scaduti
                    now = time.time()
                    expired = [k for k, t in self._timestamps.items() if (now - t) >= self.ttl]
                    for k in expired:
                        self._safe_remove(k)
                    
                    # Controlla se la memoria è oltre il 90% del limite
                    if self._total_size > self._max_memory * 0.9:
                        # Rimuovi elementi fino a scendere sotto l'80% del limite
                        while self._total_size > self._max_memory * 0.8 and self._timestamps:
                            oldest = min(self._timestamps, key=self._timestamps.get)
                            self._safe_remove(oldest)
                    
                    # Controlla se il numero di elementi è oltre il limite
                    while len(self) > self.maxsize and self._timestamps:
                        oldest = min(self._timestamps, key=self._timestamps.get)
                        self._safe_remove(oldest)
            except Exception as e:
                # Cattura eventuali eccezioni per evitare che il thread di pulizia si interrompa
                enhanced_log(f"Errore durante la pulizia della cache TTL: {str(e)}", "ERROR", "CACHE")
                # Breve pausa prima di riprovare
                time.sleep(5)

class SimpleLRUCache(dict):
    """Cache LRU (Least Recently Used) per segmenti TS e chiavi"""
    def __init__(self, maxsize=1000, cleanup_interval=120):
        super().__init__()
        self.maxsize = maxsize
        self._order = []
        self._lock = threading.RLock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True)
        self._cleanup_thread.start()

    def __setitem__(self, key, value):
        with self._lock:
            if dict.__contains__(self, key):
                self._order.remove(key)
            elif len(self) >= self.maxsize:
                # Rimuovi elementi non più in cache per consistenza prima dell'evizione
                self._order = [k for k in self._order if k in self]
                if self._order: # Solo se ci sono elementi rimossi correttamente
                    oldest = self._order.pop(0)
                    self.pop(oldest, None)
                else: # Se la cache è vuota e tentiamo di evincere, evitiamo KeyError
                    pass
            dict.__setitem__(self, key, value)
            self._order.append(key)

    def __getitem__(self, key):
        with self._lock:
            if dict.__contains__(self, key):
                self._order.remove(key)
                self._order.append(key)
                return dict.__getitem__(self, key)
            raise KeyError(key)

    def __contains__(self, key):
        with self._lock:
            return dict.__contains__(self, key)

    def _periodic_cleanup(self):
        while True:
            time.sleep(self._cleanup_interval)
            with self._lock:
                # Rimuove eventuali chiavi orfane nell'ordine
                self._order = [k for k in self._order if k in self]
                # Se la cache è troppo grande, evict
                while len(self) > self.maxsize:
                    if not self._order: # Evita errore se l'ordine è vuoto
                        break
                    oldest = self._order.pop(0)
                    self.pop(oldest, None)

# Istanze globali delle cache
M3U8_CACHE = SimpleTTLCache(maxsize=200, ttl=5)
TS_CACHE = SimpleLRUCache(maxsize=1000)
KEY_CACHE = SimpleLRUCache(maxsize=200)
CACHE_ENABLED = True
