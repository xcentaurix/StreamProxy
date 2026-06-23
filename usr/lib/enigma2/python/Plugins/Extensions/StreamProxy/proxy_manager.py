# proxy_manager.py
from .StreamProxyLog import StreamProxyLogger, enhanced_log
from Components.config import config
from enigma import eTimer
from twisted.internet import reactor
from twisted.internet.endpoints import TCP4ServerEndpoint
from twisted.internet.defer import succeed
from twisted.web import server as twisted_server
import socket
import time
from typing import Optional

logger = StreamProxyLogger.getInstance()


class ProxyServer:
    _instance: Optional['ProxyServer'] = None

    @classmethod
    def getInstance(cls) -> 'ProxyServer':
        """Restituisce l'istanza singleton del ProxyServer"""
        if cls._instance is None:
            cls._instance = ProxyServer()
        return cls._instance

    def __init__(self):
        if ProxyServer._instance is not None:
            raise RuntimeError(
                "Usa ProxyServer.getInstance() per ottenere l'istanza")

        self.listening_port = config.plugins.streamproxy.port.value
        self.running = False
        self._retries = 0
        self._max_retries = 3
        self._start_timer = eTimer()
        self._start_timer.callback.append(self._check_server_status)

    def start(self):
        """Avvia il server proxy con gestione errori migliorata"""
        enhanced_log("Avvio server proxy...", "INFO", "proxy_manager")

        try:
            # Verifica se il plugin è abilitato nelle impostazioni
            if not config.plugins.streamproxy.enabled.value:
                enhanced_log(
                    "Plugin disabilitato nelle impostazioni, non avvio il server",
                    "INFO",
                    "proxy_manager")
                return False

            # Verifica se il modulo server è disponibile
            try:
                from . import server
            except ImportError as e:
                enhanced_log(
                    f"Errore importazione modulo server: {
                        str(e)}", "ERROR", "proxy_manager")
                return False

            # Verifica stato porta
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)  # Timeout più breve per il check
                result = sock.connect_ex(('127.0.0.1', self.listening_port))
                if result == 0:
                    self.running = True
                    enhanced_log(
                        f"Server proxy già attivo sulla porta {
                            self.listening_port}", "INFO", "proxy_manager")
                    return True
            except Exception as e:
                enhanced_log(
                    f"Errore verifica porta: {
                        str(e)}",
                    "WARNING",
                    "proxy_manager")
            finally:
                try:
                    sock.close()
                except BaseException:
                    pass

            # Avvia il server
            enhanced_log("Inizializzazione server...", "INFO", "proxy_manager")
            if hasattr(server, 'start_proxy_server'):
                try:
                    # Avvio effettivo del server
                    start_result = server.start_proxy_server(
                        self.listening_port)
                    if not start_result:
                        enhanced_log(
                            "Funzione start_proxy_server ha restituito False",
                            "ERROR",
                            "proxy_manager")
                        return False

                    # Verifica che il server sia effettivamente partito con
                    # timeout progressivo
                    max_attempts = 5
                    for attempt in range(max_attempts):
                        try:
                            sock = socket.socket(
                                socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(1 + attempt)  # Timeout progressivo
                            result = sock.connect_ex(
                                ('127.0.0.1', self.listening_port))
                            if result == 0:
                                self.running = True
                                enhanced_log(
                                    f"✅ Server proxy avviato e verificato (tentativo {
                                        attempt + 1})", "INFO", "proxy_manager")
                                return True
                        except Exception as e:
                            enhanced_log(
                                f"Errore verifica connessione (tentativo {
                                    attempt +
                                    1}): {
                                    str(e)}",
                                "WARNING",
                                "proxy_manager")
                        finally:
                            try:
                                sock.close()
                            except BaseException:
                                pass
                        # Attesa progressiva tra i tentativi
                        wait_time = 0.5 * (attempt + 1)
                        enhanced_log(
                            f"Attesa {wait_time}s prima del prossimo tentativo",
                            "INFO",
                            "proxy_manager")
                        time.sleep(wait_time)

                    enhanced_log(
                        f"Server avviato ma non risponde dopo {max_attempts} tentativi",
                        "ERROR",
                        "proxy_manager")
                    return False

                except Exception as e:
                    enhanced_log(
                        f"Errore avvio server: {
                            str(e)}", "ERROR", "proxy_manager")
                    import traceback
                    enhanced_log(
                        f"Traceback: {
                            traceback.format_exc()}",
                        "ERROR",
                        "proxy_manager")
                    return False
            else:
                enhanced_log(
                    "Funzione start_proxy_server non trovata nel modulo server",
                    "ERROR",
                    "proxy_manager")
                return False

        except Exception as e:
            enhanced_log(
                f"Errore generico avvio server: {
                    str(e)}", "ERROR", "proxy_manager")
            import traceback
            enhanced_log(
                f"Traceback: {
                    traceback.format_exc()}",
                "ERROR",
                "proxy_manager")
            return False

    def _check_server_status(self):
        """Verifica lo stato del server utilizzando eTimer"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', self.listening_port))
                if result == 0:
                    self.running = True
                    enhanced_log(
                        "Server proxy attivo e in ascolto",
                        "INFO",
                        "proxy_manager")
                    return True
            except BaseException:
                pass
            finally:
                sock.close()

            self._retries += 1
            if self._retries < self._max_retries:
                enhanced_log(
                    f"Server non pronto, nuovo tentativo ({
                        self._retries}/{
                        self._max_retries})...",
                    "INFO",
                    "proxy_manager")
                self._start_timer.start(1000, True)
            else:
                enhanced_log(
                    "Server non risponde dopo i tentativi massimi",
                    "ERROR",
                    "proxy_manager")
                return False

        except Exception as e:
            enhanced_log(
                f"Errore verifica server: {
                    str(e)}",
                "ERROR",
                "proxy_manager")


def initialize() -> ProxyServer:
    """Inizializza e restituisce l'istanza del ProxyServer"""
    server = ProxyServer.getInstance()
    logger.log("Proxy manager inizializzato")
    enhanced_log("Proxy manager inizializzato", "INFO", "proxy_manager")
    return server


def get_proxy_server() -> ProxyServer:
    """Restituisce l'istanza del ProxyServer, inizializzandola se necessario"""
    return ProxyServer.getInstance()


def start_proxy() -> bool:
    """Avvia il server proxy se non è già in esecuzione"""
    logger.log("start_proxy() chiamato")
    enhanced_log("🔄 Tentativo di avvio proxy server", "INFO", "proxy_manager")

    try:
        # Verifica se il plugin è abilitato nelle impostazioni
        try:
            if not config.plugins.streamproxy.enabled.value:
                enhanced_log(
                    "Plugin disabilitato nelle impostazioni, non avvio il server",
                    "INFO",
                    "proxy_manager")
                return False
        except Exception as e:
            enhanced_log(
                f"Errore nella verifica delle impostazioni: {
                    str(e)}", "WARNING", "proxy_manager")
            # Continua comunque

        # Ottieni l'istanza del server
        try:
            server = ProxyServer.getInstance()
        except Exception as e:
            enhanced_log(
                f"Errore nell'ottenere l'istanza del server: {
                    str(e)}", "ERROR", "proxy_manager")
            return False

        # Verifica se il server è già in esecuzione
        if hasattr(server, 'running') and server.running:
            enhanced_log(
                "ℹ️ Proxy server già in esecuzione",
                "INFO",
                "proxy_manager")
            return True

        # Avvia il server
        try:
            enhanced_log("Avvio server proxy...", "INFO", "proxy_manager")
            success = server.start()
            if success:
                enhanced_log(
                    "✅ Proxy server avviato correttamente",
                    "INFO",
                    "proxy_manager")
                return True
            else:
                enhanced_log(
                    "❌ Impossibile avviare il proxy server",
                    "ERROR",
                    "proxy_manager")
                return False
        except Exception as e:
            enhanced_log(
                f"Errore durante l'avvio del server: {
                    str(e)}", "ERROR", "proxy_manager")
            return False

    except Exception as e:
        enhanced_log(
            f"❌ Errore critico in start_proxy: {
                str(e)}",
            "ERROR",
            "proxy_manager")
        import traceback
        enhanced_log(
            f"Traceback: {
                traceback.format_exc()}",
            "ERROR",
            "proxy_manager")
        return False


def stop_proxy() -> None:
    """Ferma il server proxy"""
    try:
        logger.log("stop_proxy() chiamato")
        enhanced_log("Arresto del server proxy...", "INFO", "proxy_manager")

        # Ottieni l'istanza del server
        server = ProxyServer.getInstance()
        if server and hasattr(server, 'running') and server.running:
            # Imposta lo stato a non in esecuzione
            server.running = False

            # Usa la funzione stop_proxy_server dal modulo server
            try:
                from . import server as server_module
                if hasattr(server_module, 'stop_proxy_server'):
                    if server_module.stop_proxy_server():
                        enhanced_log(
                            "Server proxy arrestato con successo tramite stop_proxy_server",
                            "INFO",
                            "proxy_manager")
                        return
                    else:
                        enhanced_log(
                            "Errore nell'arresto del server tramite stop_proxy_server",
                            "WARNING",
                            "proxy_manager")
                        # Continua con il metodo di fallback
            except Exception as e:
                enhanced_log(
                    f"Errore nell'utilizzo di stop_proxy_server: {
                        str(e)}", "WARNING", "proxy_manager")
                # Continua con il metodo di fallback

            # Prova a fermare il reactor se possibile
            try:
                from twisted.internet import reactor
                if hasattr(reactor, 'running') and reactor.running:
                    enhanced_log(
                        "Tentativo di arresto del reactor Twisted",
                        "INFO",
                        "proxy_manager")
                    # Non fermiamo il reactor perché potrebbe causare problemi con Enigma2
                    # reactor.stop()
            except Exception as e:
                enhanced_log(
                    f"Errore nell'arresto del reactor: {
                        str(e)}", "WARNING", "proxy_manager")

            # Chiudi eventuali socket aperti sulla porta
            try:
                # Prova a chiudere eventuali connessioni esistenti
                from twisted.internet import reactor
                if hasattr(reactor, 'listenersForPort'):
                    port_listeners = reactor.listenersForPort(
                        server.listening_port)
                    for listener in port_listeners:
                        try:
                            listener.stopListening()
                            enhanced_log(
                                f"Listener sulla porta {
                                    server.listening_port} fermato",
                                "INFO",
                                "proxy_manager")
                        except Exception as e:
                            enhanced_log(
                                f"Errore nell'arresto del listener: {
                                    str(e)}", "WARNING", "proxy_manager")

                # Prova a liberare la porta
                import socket
                temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_socket.settimeout(1)
                temp_socket.bind(('127.0.0.1', server.listening_port))
                temp_socket.close()
                enhanced_log(
                    f"Porta {
                        server.listening_port} liberata",
                    "INFO",
                    "proxy_manager")
            except Exception as e:
                enhanced_log(
                    f"Errore nella chiusura della porta: {
                        str(e)}", "WARNING", "proxy_manager")
                # Prova a forzare la chiusura con un timeout più lungo
                try:
                    import time
                    time.sleep(1)
                    import socket
                    temp_socket = socket.socket(
                        socket.AF_INET, socket.SOCK_STREAM)
                    temp_socket.settimeout(2)
                    temp_socket.bind(('127.0.0.1', server.listening_port))
                    temp_socket.close()
                    enhanced_log(
                        f"Porta {
                            server.listening_port} liberata al secondo tentativo",
                        "INFO",
                        "proxy_manager")
                except Exception as e2:
                    enhanced_log(
                        f"Impossibile liberare la porta anche al secondo tentativo: {
                            str(e2)}", "ERROR", "proxy_manager")

            enhanced_log("Server proxy arrestato", "INFO", "proxy_manager")
        else:
            enhanced_log(
                "Server proxy già arrestato o non in esecuzione",
                "INFO",
                "proxy_manager")

    except Exception as e:
        enhanced_log(
            f"❌ Errore in stop_proxy: {
                str(e)}",
            "ERROR",
            "proxy_manager")
        import traceback
        enhanced_log(
            f"Traceback: {
                traceback.format_exc()}",
            "ERROR",
            "proxy_manager")
