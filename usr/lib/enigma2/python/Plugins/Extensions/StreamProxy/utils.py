#!/usr/bin/python
# utils.py - Utilità per la gestione del plugin StreamProxy

import os
import sys
import time
import socket
import traceback


def check_server_status(port=None):
    """Verifica lo stato del server proxy"""
    try:
        # Importa i moduli necessari
        from .StreamProxyLog import enhanced_log
        from .config import config

        # Ottieni la porta dal config se non specificata
        if port is None:
            port = config.plugins.streamproxy.port.value

        # Verifica se la porta è in ascolto
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()

        if result == 0:
            # Verifica che sia il nostro server
            try:
                import urllib.request
                test_url = f"http://127.0.0.1:{port}/status"
                with urllib.request.urlopen(test_url, timeout=2) as response:
                    if response.getcode() == 200:
                        enhanced_log(
                            f"Server proxy attivo sulla porta {port}", "INFO", "UTILS")
                        return True
            except BaseException:
                enhanced_log(
                    f"La porta {port} è in uso ma non risponde come server proxy",
                    "WARNING",
                    "UTILS")
                return False

        enhanced_log(
            f"Server proxy non in ascolto sulla porta {port}",
            "WARNING",
            "UTILS")
        return False
    except Exception as e:
        print(f"Errore durante la verifica del server: {str(e)}")
        return False


def restart_server():
    """Riavvia il server proxy"""
    try:
        from .StreamProxyLog import enhanced_log
        from . import proxy_manager

        enhanced_log("Riavvio del server proxy in corso...", "INFO", "UTILS")

        # Ferma il server se è in esecuzione
        proxy_manager.stop_proxy()
        time.sleep(1)  # Attendi che il server si fermi

        # Riavvia il server
        if proxy_manager.start_proxy():
            enhanced_log(
                "✅ Server proxy riavviato con successo",
                "INFO",
                "UTILS")

            # Verifica che il server sia effettivamente in ascolto
            time.sleep(1)
            if check_server_status():
                enhanced_log(
                    "✅ Server proxy verificato dopo il riavvio",
                    "INFO",
                    "UTILS")
                return True
            else:
                enhanced_log(
                    "❌ Server proxy non risponde dopo il riavvio",
                    "ERROR",
                    "UTILS")
                return False
        else:
            enhanced_log(
                "❌ Errore nel riavvio del server proxy",
                "ERROR",
                "UTILS")
            return False
    except Exception as e:
        print(f"Errore durante il riavvio del server: {str(e)}")
        return False


def wait_for_server_start(max_attempts=5, delay=1):
    """Attende che il server proxy sia completamente avviato"""
    from .StreamProxyLog import enhanced_log
    from .config import config

    proxy_port = config.plugins.streamproxy.port.value

    for attempt in range(max_attempts):
        try:
            # Verifica connessione TCP
            with socket.create_connection(("127.0.0.1", proxy_port), timeout=2):
                # Verifica HTTP
                try:
                    import urllib.request
                    test_url = f"http://127.0.0.1:{proxy_port}/status"
                    with urllib.request.urlopen(test_url, timeout=2) as response:
                        if response.getcode() == 200:
                            enhanced_log(
                                f"Server proxy avviato (tentativo {
                                    attempt + 1})", "INFO", "UTILS")
                            return True
                except BaseException:
                    pass
        except BaseException:
            pass

        enhanced_log(
            f"In attesa del server... ({
                attempt + 1}/{max_attempts})",
            "INFO",
            "UTILS")
        time.sleep(delay)

    return False


# Funzione principale per l'uso da riga di comando
if __name__ == "__main__":
    # Aggiungi la directory corrente al path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    # Gestisci i parametri da riga di comando
    import argparse
    parser = argparse.ArgumentParser(description='Utilità StreamProxy')
    parser.add_argument(
        '--check',
        action='store_true',
        help='Verifica lo stato del server')
    parser.add_argument(
        '--restart',
        action='store_true',
        help='Riavvia il server')
    args = parser.parse_args()

    if args.check:
        if check_server_status():
            print("Server proxy attivo e funzionante")
        else:
            print("Server proxy non attivo")

    if args.restart:
        if restart_server():
            print("Server proxy riavviato con successo")
        else:
            print("Errore nel riavvio del server proxy")
