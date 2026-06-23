# server.py - VERSIONE COMPLETA
from twisted.internet import reactor
from twisted.web import server, resource
from twisted.internet import threads
from .StreamProxyLog import enhanced_log as _enhanced_log
import os
from .http_response import normalize_appcore_result, apply_range

VERBOSE_LOGS = os.environ.get('STREAMPROXY_VERBOSE', '0').lower() in ('1', 'true', 'yes', 'on')
_native_server = None
_server_thread = None
_server_port = None


def enhanced_log(msg, level="INFO", tag="SERVER"):
    if not VERBOSE_LOGS:
        if level == "DEBUG":
            return
        if tag == "SERVER" and level == "INFO":
            text = str(msg)
            if any(marker in text for marker in ("Richiesta HTTP", "SEGMENTO", "Invio", "RISPOSTA INVIATA", "PROCESSAMENTO RICHIESTA")):
                return
    return _enhanced_log(msg, level, tag)


class ProxyResource(resource.Resource):
    isLeaf = False

    def __init__(self):
        resource.Resource.__init__(self)
        # Aggiungi child resources
        self.putChild(b'ts', ProxyTSResource())
        self.putChild(b'm3u', ProxyM3UResource())
        self.putChild(b'key', ProxyKeyResource())


class ProxyTSResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        enhanced_log("ðŸŽžï¸ [ProxyTSResource] Richiesta TS da Enigma2", "INFO", "SERVER")

        # Processo asincrono per non bloccare Twisted
        d = threads.deferToThread(self.handleTSRequest, request)
        d.addCallback(self.sendTSResponse, request)
        d.addErrback(self.sendError, request)
        return server.NOT_DONE_YET

    def handleTSRequest(self, request):
        try:
            from .AppCore import service_monitor_callback

            # Estrai parametri
            args = {key.decode(): value[0].decode() for key, value in request.args.items()}

            # Chiama AppCore
            result = service_monitor_callback('/proxy/ts', **args)
            return result
        except Exception as e:
            enhanced_log(f"âŒ Errore TS: {e}", "ERROR", "SERVER")
            raise

    def sendTSResponse(self, result, request):
        try:
            content, status, content_type = normalize_appcore_result(result, "video/mp2t")

            request.setResponseCode(status)
            request.setHeader(b'content-type', content_type.encode("ascii", "ignore"))
            request.setHeader(b'cache-control', b'no-cache')
            request.write(content)
            request.finish()

            enhanced_log(f"âœ… [ProxyTSResource] TS servito: {len(content)} bytes", "INFO", "SERVER")
        except Exception as e:
            enhanced_log(f"âŒ Errore invio TS: {e}", "ERROR", "SERVER")
            self.sendError(e, request)

    def sendError(self, error, request):
        request.setResponseCode(500)
        request.write(b'Error')
        request.finish()


class ProxyM3UResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        d = threads.deferToThread(self.handleM3URequest, request)
        d.addCallback(self.sendM3UResponse, request)
        d.addErrback(self.sendError, request)
        return server.NOT_DONE_YET

    def handleM3URequest(self, request):
        from .AppCore import service_monitor_callback
        args = {key.decode(): value[0].decode() for key, value in request.args.items()}
        return service_monitor_callback('/proxy/m3u', **args)

    def sendM3UResponse(self, result, request):
        if isinstance(result, dict) and result.get("redirect_url"):
            request.setResponseCode(int(result.get("status", 302) or 302))
            request.setHeader(b'location', str(result["redirect_url"]).encode("ascii", "ignore"))
            request.setHeader(b'content-type', str(result.get("content_type", "video/mp4")).encode("ascii", "ignore"))
            request.finish()
            return
        content, status, content_type = normalize_appcore_result(result)
        request.setResponseCode(status)
        request.setHeader(b'content-type', content_type.encode("ascii", "ignore"))
        request.write(content)
        request.finish()

    def sendError(self, error, request):
        request.setResponseCode(500)
        request.write(b'Error')
        request.finish()


class ProxyKeyResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        d = threads.deferToThread(self.handleKeyRequest, request)
        d.addCallback(self.sendKeyResponse, request)
        return server.NOT_DONE_YET

    def handleKeyRequest(self, request):
        from .AppCore import service_monitor_callback
        args = {key.decode(): value[0].decode() for key, value in request.args.items()}
        return service_monitor_callback('/proxy/key', **args)

    def sendKeyResponse(self, result, request):
        content, status, content_type = normalize_appcore_result(result, "application/octet-stream")
        request.setResponseCode(status)
        request.setHeader(b'content-type', content_type.encode("ascii", "ignore"))
        request.write(content)
        request.finish()


# server.py - ALTERNATIVA CON HTTP SERVER NATIVO
def start_simple_server(port=7860):
    """Avvia server HTTP semplice per Enigma2"""
    global _native_server, _server_thread, _server_port
    from .StreamProxyLog import enhanced_log
    import threading
    import time
    try:
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    except ImportError:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from socketserver import ThreadingMixIn

        class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
            daemon_threads = True
    from urllib.parse import urlparse, parse_qs

    if _server_thread is not None and _server_thread.is_alive():
        enhanced_log(f"Server HTTP nativo gia attivo su porta {_server_port}", "INFO", "SERVER")
        return True

    class ProxyHandler(BaseHTTPRequestHandler):
        _last_request = {"url": "", "time": 0}

        def do_GET(self):
            from .StreamProxyLog import enhanced_log
            enhanced_log(f"ðŸŒ Richiesta HTTP ricevuta: {self.path}", "INFO", "SERVER")
            enhanced_log(f"ðŸŒ [HTTP_HEADERS] Headers: {dict(self.headers)}", "DEBUG", "SERVER")

            try:
                parsed = urlparse(self.path)
                enhanced_log(f"ðŸ“ Path: {parsed.path}, Query: {parsed.query}", "DEBUG", "SERVER")

                if parsed.path == '/status':
                    content = b"OK"
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return

                if '/proxy/ts' in parsed.path:
                    # Rileva se Ã¨ fMP4 dai parametri
                    params = parse_qs(parsed.query)
                    is_fmp4 = params.get('fmp4', [''])[0] == '1'
                    segment_type = "fMP4" if is_fmp4 else "TS"
                    enhanced_log(f"ðŸŽ¯ [{segment_type}_REQUEST] Richiesta segmento {segment_type} ricevuta: {parsed.path}", "INFO", "SERVER")
                    enhanced_log(f"ðŸŽ¯ [{segment_type}_PARAMS] Parametri {segment_type}: {parsed.query}", "DEBUG", "SERVER")
                elif '/proxy/init.hls.fmp4' in parsed.path:
                    enhanced_log(f"ðŸŽ¬ [INIT_FMP4_REQUEST] Richiesta init fMP4 ricevuta: {parsed.path}", "INFO", "SERVER")
                    enhanced_log(f"ðŸŽ¬ [INIT_FMP4_PARAMS] Parametri init fMP4: {parsed.query}", "DEBUG", "SERVER")
                elif '/proxy/m3u' in parsed.path:
                    enhanced_log(f"ðŸ”„ [M3U_REQUEST] Richiesta M3U8 #{getattr(self, '_m3u_count', 0)}", "INFO", "SERVER")
                    self._m3u_count = getattr(self, '_m3u_count', 0) + 1
                else:
                    enhanced_log(f"â“ [UNKNOWN_REQUEST] Richiesta sconosciuta: {parsed.path}", "WARNING", "SERVER")

                if parsed.path.startswith('/proxy/'):
                    enhanced_log(f"ðŸŽ¯ [SERVER] === INIZIO PROCESSAMENTO RICHIESTA PROXY ===", "INFO", "SERVER")
                    
                    params = parse_qs(parsed.query)


                    enhanced_log(f"ðŸŽ¯ Richiesta proxy valida: {parsed.path}", "INFO", "SERVER")

                    from .AppCore import service_monitor_callback

                    # Estrai parametri
                    kwargs = {k: v[0] for k, v in params.items()}
                    enhanced_log(f"ðŸ“‹ Parametri estratti: {len(kwargs)} elementi", "INFO", "SERVER")
                    enhanced_log(f"ðŸ” [SERVER] Parametri dettaglio: {list(kwargs.keys())}", "DEBUG", "SERVER")

                    # Chiama AppCore con timeout
                    enhanced_log(f"ðŸ”„ [SERVER] === CHIAMATA APPCORE ===", "INFO", "SERVER")
                    try:
                        result = service_monitor_callback(parsed.path, **kwargs)
                        enhanced_log(f"âœ… [SERVER] AppCore risposta ricevuta", "INFO", "SERVER")
                    except Exception as appcore_error:
                        enhanced_log(f"âŒ [SERVER] ERRORE APPCORE: {type(appcore_error).__name__}: {str(appcore_error)}", "ERROR", "SERVER")
                        self.send_error(500, f"AppCore Error: {str(appcore_error)}")
                        return

                    # Prepara content
                    enhanced_log(f"ðŸ“¦ [SERVER] === PREPARAZIONE CONTENUTO RISPOSTA ===", "INFO", "SERVER")
                    if isinstance(result, dict) and result.get("redirect_url"):
                        redirect_url = str(result["redirect_url"])
                        response_status = int(result.get("status", 302) or 302)
                        content_type = result.get("content_type", "video/mp4")
                        enhanced_log(f"ðŸŽ¬ [SERVER] Redirect a media diretto: {redirect_url[:100]}...", "INFO", "SERVER")
                        self.send_response(response_status)
                        self.send_header('Location', redirect_url)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return

                    content, response_status, content_type = normalize_appcore_result(result)
                    enhanced_log(f"ðŸ“‹ [SERVER] Contenuto normalizzato: {len(content)} bytes, status={response_status}", "INFO", "SERVER")
                    
                    # Verifica contenuto non vuoto
                    if len(content) == 0:
                        enhanced_log(f"âŒ [SERVER] CONTENUTO VUOTO - PROBLEMA CRITICO", "ERROR", "SERVER")
                        self.send_error(500, "Empty content from AppCore")
                        return

                    # Gestisci Range requests
                    range_header = self.headers.get('Range')
                    if content_type == 'video/mp2t':
                        range_header = None
                    if range_header:
                        enhanced_log(f"ðŸ” [RANGE_REQUEST] Range richiesto: {range_header}", "DEBUG", "SERVER")
                        try:
                            content, range_status, content_range = apply_range(content, range_header)
                            if range_status:
                                self.send_response(range_status)
                                self.send_header('Content-Range', content_range)
                            else:
                                self.send_response(response_status)
                        except Exception as e:
                            enhanced_log(f"âŒ Errore parsing Range: {e}", "ERROR", "SERVER")
                            self.send_response(response_status)
                    else:
                        self.send_response(response_status)

                    # Headers - determina content type dal risultato
                    enhanced_log(f"ðŸ“ [SERVER] === IMPOSTAZIONE HEADERS RISPOSTA ===", "INFO", "SERVER")
                    if content_type:
                        self.send_header('Content-Type', content_type)
                        if content_type == 'video/mp4':
                            enhanced_log("ðŸŽ¬ Invio segmento fMP4", "INFO", "SERVER")
                        elif content_type == 'video/mp2t':
                            enhanced_log("ðŸ“º Invio segmento TS", "INFO", "SERVER")
                        else:
                            enhanced_log("ðŸ“„ Invio M3U8", "INFO", "SERVER")
                    elif '/ts' in parsed.path:
                        self.send_header('Content-Type', 'video/mp2t')
                        enhanced_log("ðŸ“º Invio segmento TS", "INFO", "SERVER")
                    else:
                        self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                        enhanced_log("ðŸ“„ Invio M3U8", "INFO", "SERVER")

                    self.send_header('Accept-Ranges', 'none' if content_type == 'video/mp2t' else 'bytes')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()

                    enhanced_log(f"ðŸ“¤ Invio {len(content)} bytes", "INFO", "SERVER")
                    
                    # Verifica finale prima dell'invio
                    if '/ts' in parsed.path and content_type == 'video/mp2t' and len(content) > 0:
                        first_byte = content[0] if isinstance(content, bytes) else ord(content[0])
                        enhanced_log(f"ðŸ” [SERVER] Primo byte TS: 0x{first_byte:02x}", "DEBUG", "SERVER")
                        if first_byte == 0x47:
                            enhanced_log(f"âœ… [SERVER] TS valido (sync byte corretto)", "INFO", "SERVER")
                        else:
                            enhanced_log(f"âš ï¸ [SERVER] TS potenzialmente invalido (sync byte: 0x{first_byte:02x})", "WARNING", "SERVER")
                    
                    self.wfile.write(content)
                    enhanced_log(f"âœ… [SERVER] === RISPOSTA INVIATA CON SUCCESSO ===", "INFO", "SERVER")
                else:
                    enhanced_log(f"âŒ Path non valido: {parsed.path}", "WARNING", "SERVER")
                    self.send_error(404)

            except BrokenPipeError:
                # Client ha chiuso la connessione - non Ã¨ un errore critico
                enhanced_log("âš ï¸ [BROKEN_PIPE] Client ha chiuso la connessione", "WARNING", "SERVER")
            except ConnectionResetError:
                # Connessione resettata dal client
                enhanced_log("âš ï¸ [CONNECTION_RESET] Connessione resettata dal client", "WARNING", "SERVER")
            except Exception as e:
                enhanced_log(f"âŒ [SERVER] === ERRORE CRITICO HANDLER ===", "ERROR", "SERVER")
                enhanced_log(f"âŒ [SERVER] Errore: {type(e).__name__}: {str(e)}", "ERROR", "SERVER")
                
                # Log stack trace per debug
                import traceback
                enhanced_log(f"ðŸ” [SERVER] Stack trace: {traceback.format_exc()}", "ERROR", "SERVER")
                
                try:
                    self.send_error(500, f"Server Error: {str(e)}")
                except Exception as send_error_exc:
                    # Se anche send_error fallisce, ignora silenziosamente
                    enhanced_log(f"âŒ [SERVER] Impossibile inviare errore al client: {send_error_exc}", "ERROR", "SERVER")

        def log_message(self, format, *args):
            # Disabilita log HTTP standard per evitare spam
            pass

    def run_server():
        global _native_server, _server_port
        try:
            _native_server = ThreadingHTTPServer(('127.0.0.1', port), ProxyHandler)
            _native_server.daemon_threads = True
            _server_port = port
            enhanced_log(f"âœ… Server HTTP nativo avviato su porta {port}", "INFO", "SERVER")
            # Test di connettivitÃ 
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                enhanced_log(f"âœ… [CONNECTIVITY] Porta {port} raggiungibile", "INFO", "SERVER")
            else:
                enhanced_log(f"âŒ [CONNECTIVITY] Porta {port} NON raggiungibile", "ERROR", "SERVER")

            _native_server.serve_forever()
        except Exception as e:
            enhanced_log(f"âŒ Errore server nativo: {e}", "ERROR", "SERVER")
        finally:
            _native_server = None
            _server_port = None

    # Avvia in thread separato
    _server_thread = threading.Thread(target=run_server, daemon=True)
    _server_thread.start()
    enhanced_log("ðŸš€ Server HTTP nativo avviato in background", "INFO", "SERVER")
    return True


def start_proxy_server(port=7860):
    """Wrapper di compatibilita per proxy_manager."""
    return start_simple_server(port)


def stop_proxy_server():
    """Arresta il server HTTP nativo se avviato tramite StreamProxy."""
    global _native_server, _server_thread, _server_port
    try:
        if _native_server is None:
            return True
        _native_server.shutdown()
        _native_server.server_close()
        if _server_thread is not None:
            _server_thread.join(2)
        return True
    except Exception as e:
        enhanced_log(f"Errore arresto server nativo: {e}", "ERROR", "SERVER")
        return False
    finally:
        _native_server = None
        _server_thread = None
        _server_port = None
