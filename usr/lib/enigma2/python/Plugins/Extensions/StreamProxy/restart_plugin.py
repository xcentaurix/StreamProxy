# -*- coding: utf-8 -*-
# proxy_manager.py - Proxy server management for StreamProxy

from .StreamProxyLog import StreamProxyLogger, enhanced_log
from Components.config import config
from enigma import eTimer
import socket
import time
from typing import Optional

logger = StreamProxyLogger.getInstance()


class ProxyServer:
    _instance: Optional['ProxyServer'] = None

    @classmethod
    def getInstance(cls) -> 'ProxyServer':
        """Return the singleton instance of ProxyServer."""
        if cls._instance is None:
            cls._instance = ProxyServer()
        return cls._instance

    def __init__(self):
        if ProxyServer._instance is not None:
            raise RuntimeError(
                "Use ProxyServer.getInstance() to obtain the instance")

        self.listening_port = config.plugins.streamproxy.port.value
        self.running = False
        self._retries = 0
        self._max_retries = 3
        self._start_timer = eTimer()
        self._start_timer.callback.append(self._check_server_status)

    def start(self):
        """Start the proxy server with improved error handling."""
        enhanced_log("Starting proxy server...", "INFO", "proxy_manager")

        try:
            # Check if the plugin is enabled in settings
            if not config.plugins.streamproxy.enabled.value:
                enhanced_log(
                    "Plugin disabled in settings, not starting the server",
                    "INFO",
                    "proxy_manager")
                return False

            # Check if the server module is available
            try:
                from . import server
            except ImportError as e:
                enhanced_log(
                    "Error importing server module: %s" % str(e),
                    "ERROR",
                    "proxy_manager")
                return False

            # Check port status
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)  # Shorter timeout for the check
                result = sock.connect_ex(('127.0.0.1', self.listening_port))
                if result == 0:
                    self.running = True
                    enhanced_log(
                        "Proxy server already active on port %d" %
                        self.listening_port, "INFO", "proxy_manager")
                    return True
            except Exception as e:
                enhanced_log(
                    "Port check error: %s" % str(e),
                    "WARNING",
                    "proxy_manager")
            finally:
                try:
                    sock.close()
                except BaseException:
                    pass

            # Start the server
            enhanced_log("Initialising server...", "INFO", "proxy_manager")
            if hasattr(server, 'start_proxy_server'):
                try:
                    # Actual server startup
                    start_result = server.start_proxy_server(
                        self.listening_port)
                    if not start_result:
                        enhanced_log(
                            "start_proxy_server function returned False",
                            "ERROR",
                            "proxy_manager")
                        return False

                    # Verify that the server has actually started with
                    # progressive timeout
                    max_attempts = 5
                    for attempt in range(max_attempts):
                        try:
                            sock = socket.socket(
                                socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(1 + attempt)  # Progressive timeout
                            result = sock.connect_ex(
                                ('127.0.0.1', self.listening_port))
                            if result == 0:
                                self.running = True
                                enhanced_log(
                                    "[OK] Proxy server started and verified (attempt %d/%d)" %
                                    (attempt + 1, max_attempts), "INFO", "proxy_manager")
                                return True
                        except Exception as e:
                            enhanced_log(
                                "Connection check error (attempt %d/%d): %s" %
                                (attempt + 1, max_attempts, str(e)), "WARNING", "proxy_manager")
                        finally:
                            try:
                                sock.close()
                            except BaseException:
                                pass
                        # Progressive wait between attempts
                        wait_time = 0.5 * (attempt + 1)
                        enhanced_log(
                            "Waiting %ds before next attempt" % wait_time,
                            "INFO",
                            "proxy_manager")
                        time.sleep(wait_time)

                    enhanced_log(
                        "Server started but not responding after %d attempts" %
                        max_attempts, "ERROR", "proxy_manager")
                    return False

                except Exception as e:
                    enhanced_log(
                        "Server startup error: %s" % str(e),
                        "ERROR",
                        "proxy_manager")
                    import traceback
                    enhanced_log(
                        "Traceback: %s" % traceback.format_exc(),
                        "ERROR",
                        "proxy_manager")
                    return False
            else:
                enhanced_log(
                    "start_proxy_server function not found in server module",
                    "ERROR",
                    "proxy_manager")
                return False

        except Exception as e:
            enhanced_log(
                "Generic server startup error: %s" % str(e),
                "ERROR",
                "proxy_manager")
            import traceback
            enhanced_log(
                "Traceback: %s" % traceback.format_exc(),
                "ERROR",
                "proxy_manager")
            return False

    def _check_server_status(self):
        """Check the server status using eTimer."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', self.listening_port))
                if result == 0:
                    self.running = True
                    enhanced_log(
                        "Proxy server active and listening",
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
                    "Server not ready, retrying (%d/%d)..." %
                    (self._retries, self._max_retries), "INFO", "proxy_manager")
                self._start_timer.start(1000, True)
            else:
                enhanced_log(
                    "Server not responding after maximum attempts",
                    "ERROR",
                    "proxy_manager")
                return False

        except Exception as e:
            enhanced_log(
                "Server status check error: %s" % str(e),
                "ERROR",
                "proxy_manager")


def initialize() -> ProxyServer:
    """Initialise and return the ProxyServer instance."""
    server = ProxyServer.getInstance()
    logger.log("Proxy manager initialised")
    enhanced_log("Proxy manager initialised", "INFO", "proxy_manager")
    return server


def get_proxy_server() -> ProxyServer:
    """Return the ProxyServer instance, initialising it if necessary."""
    return ProxyServer.getInstance()


def start_proxy() -> bool:
    """Start the proxy server if it is not already running."""
    logger.log("start_proxy() called")
    enhanced_log(
        "[PROXY] Attempting to start proxy server",
        "INFO",
        "proxy_manager")

    try:
        # Check if the plugin is enabled in settings
        try:
            if not config.plugins.streamproxy.enabled.value:
                enhanced_log(
                    "Plugin disabled in settings, not starting the server",
                    "INFO",
                    "proxy_manager")
                return False
        except Exception as e:
            enhanced_log(
                "Error checking settings: %s" % str(e),
                "WARNING",
                "proxy_manager")
            # Continue anyway

        # Get the server instance
        try:
            server = ProxyServer.getInstance()
        except Exception as e:
            enhanced_log(
                "Error getting server instance: %s" % str(e),
                "ERROR",
                "proxy_manager")
            return False

        # Check if the server is already running
        if hasattr(server, 'running') and server.running:
            enhanced_log(
                "Proxy server already running",
                "INFO",
                "proxy_manager")
            return True

        # Start the server
        try:
            enhanced_log("Starting proxy server...", "INFO", "proxy_manager")
            success = server.start()
            if success:
                enhanced_log(
                    "[OK] Proxy server started successfully",
                    "INFO",
                    "proxy_manager")
                return True
            else:
                enhanced_log(
                    "[FAIL] Unable to start the proxy server",
                    "ERROR",
                    "proxy_manager")
                return False
        except Exception as e:
            enhanced_log(
                "Error starting the server: %s" % str(e),
                "ERROR",
                "proxy_manager")
            return False

    except Exception as e:
        enhanced_log(
            "[FAIL] Critical error in start_proxy: %s" % str(e),
            "ERROR",
            "proxy_manager")
        import traceback
        enhanced_log(
            "Traceback: %s" % traceback.format_exc(),
            "ERROR",
            "proxy_manager")
        return False


def stop_proxy() -> None:
    """Stop the proxy server."""
    try:
        logger.log("stop_proxy() called")
        enhanced_log("Stopping proxy server...", "INFO", "proxy_manager")

        # Get the server instance
        server = ProxyServer.getInstance()
        if server and hasattr(server, 'running') and server.running:
            # Set state to not running
            server.running = False

            # Use stop_proxy_server from the server module
            try:
                from . import server as server_module
                if hasattr(server_module, 'stop_proxy_server'):
                    if server_module.stop_proxy_server():
                        enhanced_log(
                            "Proxy server stopped successfully via stop_proxy_server",
                            "INFO",
                            "proxy_manager")
                        return
                    else:
                        enhanced_log(
                            "Error stopping server via stop_proxy_server",
                            "WARNING",
                            "proxy_manager")
                        # Continue with fallback method
            except Exception as e:
                enhanced_log(
                    "Error using stop_proxy_server: %s" % str(e),
                    "WARNING",
                    "proxy_manager")
                # Continue with fallback method

            # Try to stop the reactor if possible
            try:
                from twisted.internet import reactor
                if hasattr(reactor, 'running') and reactor.running:
                    enhanced_log(
                        "Attempting to stop Twisted reactor",
                        "INFO",
                        "proxy_manager")
                    # Do not stop the reactor because it may cause issues with Enigma2
                    # reactor.stop()
            except Exception as e:
                enhanced_log(
                    "Error stopping the reactor: %s" % str(e),
                    "WARNING",
                    "proxy_manager")

            # Close any open sockets on the port
            try:
                # Try to close any existing connections
                from twisted.internet import reactor
                if hasattr(reactor, 'listenersForPort'):
                    port_listeners = reactor.listenersForPort(
                        server.listening_port)
                    for listener in port_listeners:
                        try:
                            listener.stopListening()
                            enhanced_log(
                                "Listener on port %d stopped" %
                                server.listening_port, "INFO", "proxy_manager")
                        except Exception as e:
                            enhanced_log(
                                "Error stopping listener: %s" % str(e),
                                "WARNING",
                                "proxy_manager")

                # Try to free the port
                import socket
                temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_socket.settimeout(1)
                temp_socket.bind(('127.0.0.1', server.listening_port))
                temp_socket.close()
                enhanced_log(
                    "Port %d freed" % server.listening_port,
                    "INFO",
                    "proxy_manager")
            except Exception as e:
                enhanced_log(
                    "Error closing port: %s" % str(e),
                    "WARNING",
                    "proxy_manager")
                # Try to force close with a longer timeout
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
                        "Port %d freed on second attempt" %
                        server.listening_port, "INFO", "proxy_manager")
                except Exception as e2:
                    enhanced_log(
                        "Unable to free port even on second attempt: %s" %
                        str(e2), "ERROR", "proxy_manager")

            enhanced_log("Proxy server stopped", "INFO", "proxy_manager")
        else:
            enhanced_log(
                "Proxy server already stopped or not running",
                "INFO",
                "proxy_manager")

    except Exception as e:
        enhanced_log(
            "[FAIL] Error in stop_proxy: %s" % str(e),
            "ERROR",
            "proxy_manager")
        import traceback
        enhanced_log(
            "Traceback: %s" % traceback.format_exc(),
            "ERROR",
            "proxy_manager")
