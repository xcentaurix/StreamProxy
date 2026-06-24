# -*- coding: utf-8 -*-
# server.py - HTTP server for StreamProxy (Twisted + native fallback)

from twisted.web import server, resource
from twisted.internet import threads
from .StreamProxyLog import enhanced_log as _enhanced_log
import os
from .http_response import normalize_appcore_result, apply_range

VERBOSE_LOGS = os.environ.get(
    'STREAMPROXY_VERBOSE',
    '0').lower() in (
        '1',
        'true',
        'yes',
    'on')
_native_server = None
_server_thread = None
_server_port = None


def enhanced_log(msg, level="INFO", tag="SERVER"):
    if not VERBOSE_LOGS:
        if level == "DEBUG":
            return
        if tag == "SERVER" and level == "INFO":
            text = str(msg)
            if any(
                marker in text for marker in (
                    "HTTP request",
                    "SEGMENT",
                    "Sending",
                    "RESPONSE SENT",
                    "PROCESSING REQUEST")):
                return
    return _enhanced_log(msg, level, tag)


class ProxyResource(resource.Resource):
    isLeaf = False

    def __init__(self):
        resource.Resource.__init__(self)
        self.putChild(b'ts', ProxyTSResource())
        self.putChild(b'm3u', ProxyM3UResource())
        self.putChild(b'key', ProxyKeyResource())


class ProxyTSResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        enhanced_log(
            "[ProxyTSResource] TS request from Enigma2",
            "INFO",
            "SERVER")

        d = threads.deferToThread(self.handleTSRequest, request)
        d.addCallback(self.sendTSResponse, request)
        d.addErrback(self.sendError, request)
        return server.NOT_DONE_YET

    def handleTSRequest(self, request):
        try:
            from .AppCore import service_monitor_callback

            args = {key.decode(): value[0].decode()
                    for key, value in request.args.items()}

            result = service_monitor_callback('/proxy/ts', **args)
            return result
        except Exception as e:
            enhanced_log("[ERROR] TS error: %s" % e, "ERROR", "SERVER")
            raise

    def sendTSResponse(self, result, request):
        try:
            content, status, content_type = normalize_appcore_result(
                result, "video/mp2t")

            request.setResponseCode(status)
            request.setHeader(
                b'content-type',
                content_type.encode(
                    "ascii",
                    "ignore"))
            request.setHeader(b'cache-control', b'no-cache')
            request.write(content)
            request.finish()

            enhanced_log(
                "[OK] [ProxyTSResource] TS served: %d bytes" % len(content),
                "INFO",
                "SERVER")
        except Exception as e:
            enhanced_log("[ERROR] Error sending TS: %s" % e, "ERROR", "SERVER")
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
        args = {key.decode(): value[0].decode()
                for key, value in request.args.items()}
        return service_monitor_callback('/proxy/m3u', **args)

    def sendM3UResponse(self, result, request):
        if isinstance(result, dict) and result.get("redirect_url"):
            request.setResponseCode(int(result.get("status", 302) or 302))
            request.setHeader(
                b'location', str(
                    result["redirect_url"]).encode(
                    "ascii", "ignore"))
            request.setHeader(b'content-type',
                              str(result.get("content_type",
                                             "video/mp4")).encode("ascii",
                                                                  "ignore"))
            request.finish()
            return
        content, status, content_type = normalize_appcore_result(result)
        request.setResponseCode(status)
        request.setHeader(
            b'content-type',
            content_type.encode(
                "ascii",
                "ignore"))
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
        args = {key.decode(): value[0].decode()
                for key, value in request.args.items()}
        return service_monitor_callback('/proxy/key', **args)

    def sendKeyResponse(self, result, request):
        content, status, content_type = normalize_appcore_result(
            result, "application/octet-stream")
        request.setResponseCode(status)
        request.setHeader(
            b'content-type',
            content_type.encode(
                "ascii",
                "ignore"))
        request.write(content)
        request.finish()


# --- Native HTTP server fallback (for environments without Twisted) ---
def start_simple_server(port=7860):
    """Start a simple HTTP server for Enigma2 (native fallback)."""
    global _server_thread
    from .StreamProxyLog import enhanced_log
    import threading
    try:
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    except ImportError:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from socketserver import ThreadingMixIn

        class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
            daemon_threads = True
    from urllib.parse import urlparse

    def _parse_query_safe(qs):
        """Split on literal & only, preserving %26 inside url value."""
        params = {}
        for part in qs.split('&'):
            if '=' in part:
                k, _, v = part.partition('=')
                params[k] = [v]
        return params

    if _server_thread is not None and _server_thread.is_alive():
        enhanced_log(
            "Native HTTP server already active on port %d" % _server_port,
            "INFO",
            "SERVER")
        return True

    class ProxyHandler(BaseHTTPRequestHandler):
        _last_request = {"url": "", "time": 0}

        def do_GET(self):
            from .StreamProxyLog import enhanced_log
            enhanced_log(
                "HTTP request received: %s" % self.path,
                "INFO",
                "SERVER")
            enhanced_log(
                "[HTTP_HEADERS] Headers: %s" % dict(self.headers),
                "DEBUG",
                "SERVER")

            try:
                parsed = urlparse(self.path)
                enhanced_log(
                    "Path: %s, Query: %s" % (parsed.path, parsed.query),
                    "DEBUG",
                    "SERVER")

                if parsed.path == '/status':
                    content = b"OK"
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return

                if '/proxy/ts' in parsed.path:
                    # Detect if it is fMP4 from parameters
                    params = _parse_query_safe(parsed.query)
                    is_fmp4 = params.get('fmp4', [''])[0] == '1'
                    segment_type = "fMP4" if is_fmp4 else "TS"
                    enhanced_log(
                        "[%s_REQUEST] %s segment request received: %s" %
                        (segment_type, segment_type, parsed.path),
                        "INFO",
                        "SERVER")
                    enhanced_log(
                        "[%s_PARAMS] %s parameters: %s" %
                        (segment_type, segment_type, parsed.query),
                        "DEBUG",
                        "SERVER")
                elif '/proxy/init.hls.fmp4' in parsed.path:
                    enhanced_log(
                        "[INIT_FMP4_REQUEST] Init fMP4 request received: %s" %
                        parsed.path,
                        "INFO",
                        "SERVER")
                    enhanced_log(
                        "[INIT_FMP4_PARAMS] Init fMP4 parameters: %s" %
                        parsed.query,
                        "DEBUG",
                        "SERVER")
                elif '/proxy/m3u' in parsed.path:
                    enhanced_log(
                        "[M3U_REQUEST] M3U8 request #%d" %
                        getattr(
                            self,
                            '_m3u_count',
                            0),
                        "INFO",
                        "SERVER")
                    self._m3u_count = getattr(self, '_m3u_count', 0) + 1
                else:
                    enhanced_log(
                        "[UNKNOWN_REQUEST] Unknown request: %s" % parsed.path,
                        "WARNING",
                        "SERVER")

                if parsed.path.startswith('/proxy/'):
                    enhanced_log(
                        "[SERVER] === START PROXY REQUEST PROCESSING ===",
                        "INFO",
                        "SERVER")

                    params = _parse_query_safe(parsed.query)

                    enhanced_log(
                        "Valid proxy request: %s" % parsed.path,
                        "INFO",
                        "SERVER")

                    from .AppCore import service_monitor_callback

                    # Extract parameters
                    kwargs = {k: v[0] for k, v in params.items()}
                    enhanced_log(
                        "Extracted parameters: %d elements" % len(kwargs),
                        "INFO",
                        "SERVER")
                    enhanced_log(
                        "[SERVER] Parameters detail: %s" % list(kwargs.keys()),
                        "DEBUG",
                        "SERVER")

                    # Call AppCore
                    enhanced_log(
                        "[SERVER] === CALLING APPCORE ===",
                        "INFO",
                        "SERVER")
                    try:
                        result = service_monitor_callback(
                            parsed.path, **kwargs)
                        enhanced_log(
                            "[OK] [SERVER] AppCore response received",
                            "INFO",
                            "SERVER")
                    except Exception as appcore_error:
                        enhanced_log(
                            "[ERROR] [SERVER] APPCORE ERROR: %s: %s" %
                            (type(appcore_error).__name__, str(appcore_error)),
                            "ERROR",
                            "SERVER")
                        self.send_error(
                            500, "AppCore Error: %s" % str(appcore_error))
                        return

                    # Prepare content
                    enhanced_log(
                        "[SERVER] === PREPARING RESPONSE CONTENT ===",
                        "INFO",
                        "SERVER")
                    if isinstance(result, dict) and result.get("redirect_url"):
                        redirect_url = str(result["redirect_url"])
                        response_status = int(result.get("status", 302) or 302)
                        content_type = result.get("content_type", "video/mp4")
                        enhanced_log(
                            "[SERVER] Redirect to direct media: %s..." % redirect_url[:100],
                            "INFO",
                            "SERVER")
                        self.send_response(response_status)
                        self.send_header('Location', redirect_url)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return

                    content, response_status, content_type = normalize_appcore_result(
                        result)
                    enhanced_log(
                        "[SERVER] Normalised content: %d bytes, status=%d" % (
                            len(content), response_status),
                        "INFO",
                        "SERVER")

                    if len(content) == 0:
                        enhanced_log(
                            "[ERROR] [SERVER] EMPTY CONTENT - CRITICAL ERROR",
                            "ERROR",
                            "SERVER")
                        self.send_error(500, "Empty content from AppCore")
                        return

                    # Handle Range requests
                    range_header = self.headers.get('Range')
                    if content_type == 'video/mp2t':
                        range_header = None
                    if range_header:
                        enhanced_log(
                            "[RANGE_REQUEST] Range requested: %s" %
                            range_header,
                            "DEBUG",
                            "SERVER")
                        try:
                            content, range_status, content_range = apply_range(
                                content, range_header)
                            if range_status:
                                self.send_response(range_status)
                                self.send_header(
                                    'Content-Range', content_range)
                            else:
                                self.send_response(response_status)
                        except Exception as e:
                            enhanced_log(
                                "[ERROR] Range parsing error: %s" % e,
                                "ERROR",
                                "SERVER")
                            self.send_response(response_status)
                    else:
                        self.send_response(response_status)

                    # Headers - determine content type from result
                    enhanced_log(
                        "[SERVER] === SETTING RESPONSE HEADERS ===",
                        "INFO",
                        "SERVER")
                    if content_type:
                        self.send_header('Content-Type', content_type)
                        if content_type == 'video/mp4':
                            enhanced_log(
                                "Sending fMP4 segment", "INFO", "SERVER")
                        elif content_type == 'video/mp2t':
                            enhanced_log(
                                "Sending TS segment", "INFO", "SERVER")
                        else:
                            enhanced_log("Sending M3U8", "INFO", "SERVER")
                    elif '/ts' in parsed.path:
                        self.send_header('Content-Type', 'video/mp2t')
                        enhanced_log("Sending TS segment", "INFO", "SERVER")
                    else:
                        self.send_header(
                            'Content-Type', 'application/vnd.apple.mpegurl')
                        enhanced_log("Sending M3U8", "INFO", "SERVER")

                    self.send_header(
                        'Accept-Ranges',
                        'none' if content_type == 'video/mp2t' else 'bytes')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()

                    enhanced_log(
                        "Sending %d bytes" %
                        len(content), "INFO", "SERVER")

                    # Final verification before sending
                    if '/ts' in parsed.path and content_type == 'video/mp2t' and len(
                            content) > 0:
                        first_byte = content[0] if isinstance(
                            content, bytes) else ord(content[0])
                        enhanced_log(
                            "[SERVER] TS first byte: 0x%02x" % first_byte,
                            "DEBUG",
                            "SERVER")
                        if first_byte == 0x47:
                            enhanced_log(
                                "[OK] [SERVER] Valid TS (correct sync byte)",
                                "INFO",
                                "SERVER")
                        else:
                            enhanced_log(
                                "[WARNING] [SERVER] Potentially invalid TS (sync byte: 0x%02x)" %
                                first_byte, "WARNING", "SERVER")

                    self.wfile.write(content)
                    enhanced_log(
                        "[OK] [SERVER] === RESPONSE SENT SUCCESSFULLY ===",
                        "INFO",
                        "SERVER")
                else:
                    enhanced_log(
                        "[ERROR] Invalid path: %s" % parsed.path,
                        "WARNING",
                        "SERVER")
                    self.send_error(404)

            except BrokenPipeError:
                enhanced_log(
                    "[WARNING] [BROKEN_PIPE] Client closed connection",
                    "WARNING",
                    "SERVER")
            except ConnectionResetError:
                enhanced_log(
                    "[WARNING] [CONNECTION_RESET] Connection reset by client",
                    "WARNING",
                    "SERVER")
            except Exception as e:
                enhanced_log(
                    "[ERROR] [SERVER] === CRITICAL HANDLER ERROR ===",
                    "ERROR",
                    "SERVER")
                enhanced_log(
                    "[ERROR] [SERVER] Error: %s: %s" % (
                        type(e).__name__, str(e)),
                    "ERROR",
                    "SERVER")

                import traceback
                enhanced_log(
                    "[SERVER] Stack trace: %s" % traceback.format_exc(),
                    "ERROR",
                    "SERVER")

                try:
                    self.send_error(500, "Server Error: %s" % str(e))
                except Exception as send_error_exc:
                    enhanced_log(
                        "[ERROR] [SERVER] Unable to send error to client: %s" %
                        send_error_exc, "ERROR", "SERVER")

        def log_message(self, format, *args):
            # Disable default HTTP log to avoid spam
            pass

    def run_server():
        global _native_server, _server_port
        try:
            _native_server = ThreadingHTTPServer(
                ('127.0.0.1', port), ProxyHandler)
            _native_server.daemon_threads = True
            _server_port = port
            enhanced_log(
                "[OK] Native HTTP server started on port %d" % port,
                "INFO",
                "SERVER")
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                enhanced_log(
                    "[OK] [CONNECTIVITY] Port %d reachable" % port,
                    "INFO",
                    "SERVER")
            else:
                enhanced_log(
                    "[ERROR] [CONNECTIVITY] Port %d NOT reachable" % port,
                    "ERROR",
                    "SERVER")

            _native_server.serve_forever()
        except Exception as e:
            enhanced_log(
                "[ERROR] Native server error: %s" %
                e, "ERROR", "SERVER")
        finally:
            _native_server = None
            _server_port = None

    _server_thread = threading.Thread(target=run_server, daemon=True)
    _server_thread.start()
    enhanced_log(
        "[INFO] Native HTTP server started in background",
        "INFO",
        "SERVER")
    return True


def start_proxy_server(port=7860):
    """Compatibility wrapper for proxy_manager."""
    return start_simple_server(port)


def stop_proxy_server():
    """Stop the native HTTP server if started by StreamProxy."""
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
        enhanced_log(
            "[ERROR] Error stopping native server: %s" %
            e, "ERROR", "SERVER")
        return False
    finally:
        _native_server = None
        _server_thread = None
        _server_port = None
