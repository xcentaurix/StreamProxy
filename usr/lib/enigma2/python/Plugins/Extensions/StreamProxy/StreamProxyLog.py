# StreamProxyLog.py
import os
import time
import sys
from collections import deque
import traceback
import threading


CONSOLE_LOGS = os.environ.get("STREAMPROXY_CONSOLE_LOGS", "0").lower() in ("1", "true", "yes", "on")
FSYNC_LOGS = os.environ.get("STREAMPROXY_FSYNC_LOGS", "0").lower() in ("1", "true", "yes", "on")


def _safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_message = str(message).encode(encoding, "backslashreplace").decode(encoding, "replace")
        print(safe_message)


class StreamProxyLogger:
    _instance = None
    LOG_FILE = "/usr/lib/enigma2/python/Plugins/Extensions/StreamProxy/streamLogs.txt"
    MAX_LOG_SIZE = 2 * 1024 * 1024  # 2MB massimo
    MAX_LINES = 5000  # Massimo 5000 righe

    @staticmethod
    def getInstance():
        if StreamProxyLogger._instance is None:
            StreamProxyLogger._instance = StreamProxyLogger()
        return StreamProxyLogger._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self._log_file = None
        self._lock = threading.RLock()

        try:
            # Assicurati che la directory esista con i permessi corretti
            log_dir = os.path.dirname(self.LOG_FILE)
            if not os.path.exists(log_dir):
                try:
                    os.makedirs(log_dir, mode=0o755)
                except Exception as e:
                    _safe_print(f"[ERROR] Impossibile creare directory log: {e}")
                    return

            # Imposta i permessi del file se esiste
            if os.path.exists(self.LOG_FILE):
                try:
                    os.chmod(self.LOG_FILE, 0o644)
                except Exception as e:
                    _safe_print(f"[ERROR] Impossibile impostare i permessi del file: {e}")

            # Apri il file in modalit[?] write per pulirlo
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("")
                f.flush()

            # Imposta i permessi corretti
            os.chmod(self.LOG_FILE, 0o644)

            # Apri il file in append con buffering minimo
            self._log_file = open(self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
            self._write_log("=== LOG INIZIALIZZATO ===", True)

        except Exception as e:
            _safe_print(f"[ERROR] Errore inizializzazione logger: {str(e)}\n{traceback.format_exc()}")
            self._log_file = None

    def _write_log(self, message, add_timestamp=True):
        """Scrittura effettiva del log con gestione errori migliorata"""
        with self._lock:
            # Controlla dimensione file prima di scrivere
            self._check_and_rotate_log()
            if not self._log_file:
                try:
                    self._log_file = open(self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
                except Exception as e:
                    _safe_print(f"[ERROR] Impossibile aprire il file di log: {e}")
                    return False

            try:
                if add_timestamp:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    entry = f"[{timestamp}] {message}\n"
                else:
                    entry = f"{message}\n"

                self._log_file.write(entry)
                self._log_file.flush()
                if FSYNC_LOGS:
                    os.fsync(self._log_file.fileno())
                if CONSOLE_LOGS:
                    _safe_print(f"[DEBUG] Log scritto: {entry.strip()}")
                return True

            except IOError as e:
                _safe_print(f"[ERROR] Errore I/O durante la scrittura del log: {e}")
                # Prova a riaprire il file
                try:
                    if self._log_file:
                        self._log_file.close()
                    self._log_file = open(self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
                except Exception as e2:
                    _safe_print(f"[ERROR] Impossibile riaprire il file: {e2}")
                return False

            except Exception as e:
                _safe_print(f"[ERROR] Errore generico durante la scrittura del log: {e}")
                return False
    
    def _check_and_rotate_log(self):
        """Controlla la dimensione del log e lo ruota se necessario"""
        try:
            if not os.path.exists(self.LOG_FILE):
                return
            
            file_size = os.path.getsize(self.LOG_FILE)
            if file_size > self.MAX_LOG_SIZE:
                self._rotate_log()
        except Exception as e:
            _safe_print(f"[ERROR] Errore controllo dimensione log: {e}")
    
    def _rotate_log(self):
        """Ruota il log mantenendo solo le ultime righe"""
        try:
            _safe_print(f"[INFO] Rotazione log - dimensione attuale: {os.path.getsize(self.LOG_FILE)} bytes")
            
            # Chiudi il file corrente
            if self._log_file:
                self._log_file.close()
                self._log_file = None
            
            # Leggi le ultime righe
            with open(self.LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Mantieni solo le ultime MAX_LINES righe
            if len(lines) > self.MAX_LINES:
                lines = lines[-self.MAX_LINES:]
            
            # Riscrivi il file con le righe mantenute
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("=== LOG RUOTATO ===\n")
                f.writelines(lines)
                f.flush()
                if FSYNC_LOGS:
                    os.fsync(f.fileno())
            
            # Riapri il file in append
            self._log_file = open(self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
            _safe_print(f"[INFO] Log ruotato - mantenute {len(lines)} righe")
            
        except Exception as e:
            _safe_print(f"[ERROR] Errore rotazione log: {e}")
            # Fallback: pulisci completamente il log
            try:
                with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                    f.write("=== LOG RIPULITO DOPO ERRORE ===\n")
                self._log_file = open(self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
            except:
                pass

    def log(self, message, add_timestamp=True):
        """Metodo pubblico per il logging"""
        if CONSOLE_LOGS:
            _safe_print(f"[DEBUG] Richiesta log: {message}")
        if isinstance(message, str):
            lines = message.split('\n')
        else:
            lines = [str(message)]

        for line in lines:
            self._write_log(line, add_timestamp)

    def clear_log(self):
        """Pulisce il file di log"""
        try:
            if CONSOLE_LOGS:
                _safe_print("[DEBUG] Richiesta pulizia log")
            # Chiudi il file se [?] aperto
            if hasattr(self, '_log_file') and self._log_file:
                self._log_file.close()
                self._log_file = None

            # Sovrascrivi il file
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("")
                f.flush()
                if FSYNC_LOGS:
                    os.fsync(f.fileno())

            # Riapri il file in append
            self._log_file = open(self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
            if CONSOLE_LOGS:
                _safe_print("[DEBUG] File di log pulito e riaperto")
            self._write_log("=== LOG INIZIALIZZATO ===")
            return True
        except Exception as e:
            _safe_print(f"[ERROR] Errore pulizia log: {e}")
            # Prova a riaprire il file anche in caso di errore
            if not hasattr(self, '_log_file') or not self._log_file:
                try:
                    self._log_file = open(self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
                except:
                    pass
            return False

    def __del__(self):
        """Chiude il file di log quando l'oggetto viene distrutto"""
        if hasattr(self, '_log_file') and self._log_file:
            try:
                self._log_file.close()
                if CONSOLE_LOGS:
                    _safe_print("[DEBUG] File di log chiuso")
            except:
                pass


def enhanced_log(message, level="INFO", component="CORE"):
    """Funzione di logging migliorata con supporto per componenti e livelli."""
    # Importa la variabile globale DEBUG_ENABLED
    try:
        from .plugin import DEBUG_ENABLED
        if not DEBUG_ENABLED:
            return  # Non scrive nulla se debug [?] disabilitato
    except:
        pass  # Se non riesce a importare, continua con il logging normale

    if CONSOLE_LOGS:
        _safe_print(f"[DEBUG] enhanced_log chiamato: [{level}] [{component}] {message}")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] [{level}] [{component}] {message}"
    logger = StreamProxyLogger.getInstance()
    logger.log(formatted_message, add_timestamp=False)

