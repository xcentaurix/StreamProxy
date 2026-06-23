#!/usr/bin/python
# restart_plugin.py - Script per riavviare il plugin StreamProxy

import os
import sys
import time
import traceback

# Aggiungi la directory corrente al path per importare i moduli del plugin
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    # Importa i moduli necessari
    from StreamProxyLog import StreamProxyLogger, enhanced_log
    from config import initConfig, config
    import proxy_manager
    from ServiceMonitor import StreamProxyServiceMonitor

    # Inizializza il logger
    logger = StreamProxyLogger.getInstance()
    enhanced_log(
        "============ INIZIO RIAVVIO PLUGIN ============",
        "INFO",
        "RESTART")

    # Ferma il proxy server se è in esecuzione
    enhanced_log("Arresto del server proxy in corso...", "INFO", "RESTART")
    proxy_manager.stop_proxy()
    time.sleep(1)  # Attendi che il server si fermi

    # Riavvia il server proxy
    enhanced_log("Avvio del server proxy in corso...", "INFO", "RESTART")
    if proxy_manager.start_proxy():
        enhanced_log("✅ Server proxy avviato con successo", "INFO", "RESTART")
    else:
        enhanced_log(
            "❌ Errore nell'avvio del server proxy",
            "ERROR",
            "RESTART")

    # Verifica che il server sia effettivamente in ascolto
    server = proxy_manager.get_proxy_server()
    if server and server.running:
        enhanced_log(
            f"Server proxy in ascolto sulla porta {
                server.listening_port}",
            "INFO",
            "RESTART")
    else:
        enhanced_log("Server proxy non in ascolto", "WARNING", "RESTART")

    enhanced_log("Riavvio completato", "INFO", "RESTART")
    print("Plugin riavviato con successo")

except Exception as e:
    error_msg = f"Errore durante il riavvio del plugin: {str(e)}"
    print(error_msg)
    print(traceback.format_exc())
    try:
        enhanced_log(error_msg, "ERROR", "RESTART")
        enhanced_log(traceback.format_exc(), "ERROR", "RESTART")
    except BaseException:
        pass
