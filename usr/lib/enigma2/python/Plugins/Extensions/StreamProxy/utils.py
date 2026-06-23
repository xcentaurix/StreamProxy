# -*- coding: utf-8 -*-
# utils.py - Utility functions for StreamProxy plugin management

import os
import sys
import time
import socket


def check_server_status(port=None):
    """Check the status of the proxy server."""
    try:
        from .StreamProxyLog import enhanced_log
        from .config import config

        # Get the port from config if not specified
        if port is None:
            port = config.plugins.streamproxy.port.value

        # Check if the port is listening
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()

        if result == 0:
            # Verify that it is our server
            try:
                import urllib.request
                test_url = "http://127.0.0.1:%d/status" % port
                with urllib.request.urlopen(test_url, timeout=2) as response:
                    if response.getcode() == 200:
                        enhanced_log(
                            "Proxy server active on port %d" % port,
                            "INFO",
                            "UTILS")
                        return True
            except BaseException:
                enhanced_log(
                    "Port %d is in use but does not respond as a proxy server" %
                    port, "WARNING", "UTILS")
                return False

        enhanced_log(
            "Proxy server not listening on port %d" % port,
            "WARNING",
            "UTILS")
        return False
    except Exception as e:
        print("Error while checking the server: %s" % str(e))
        return False


def restart_server():
    """Restart the proxy server."""
    try:
        from .StreamProxyLog import enhanced_log
        from . import proxy_manager

        enhanced_log("Restarting the proxy server...", "INFO", "UTILS")

        # Stop the server if it is running
        proxy_manager.stop_proxy()
        time.sleep(1)  # Wait for the server to stop

        # Restart the server
        if proxy_manager.start_proxy():
            enhanced_log(
                "[OK] Proxy server restarted successfully",
                "INFO",
                "UTILS")

            # Verify that the server is actually listening
            time.sleep(1)
            if check_server_status():
                enhanced_log(
                    "[OK] Proxy server verified after restart",
                    "INFO",
                    "UTILS")
                return True
            else:
                enhanced_log(
                    "[FAIL] Proxy server does not respond after restart",
                    "ERROR",
                    "UTILS")
                return False
        else:
            enhanced_log(
                "[FAIL] Error restarting the proxy server",
                "ERROR",
                "UTILS")
            return False
    except Exception as e:
        print("Error while restarting the server: %s" % str(e))
        return False


def wait_for_server_start(max_attempts=5, delay=1):
    """Wait for the proxy server to be fully started."""
    from .StreamProxyLog import enhanced_log
    from .config import config

    proxy_port = config.plugins.streamproxy.port.value

    for attempt in range(max_attempts):
        try:
            # Check TCP connection
            with socket.create_connection(("127.0.0.1", proxy_port), timeout=2):
                # Check HTTP
                try:
                    import urllib.request
                    test_url = "http://127.0.0.1:%d/status" % proxy_port
                    with urllib.request.urlopen(test_url, timeout=2) as response:
                        if response.getcode() == 200:
                            enhanced_log(
                                "Proxy server started (attempt %d/%d)" %
                                (attempt + 1, max_attempts), "INFO", "UTILS")
                            return True
                except BaseException:
                    pass
        except BaseException:
            pass

        enhanced_log(
            "Waiting for the server... (%d/%d)" % (attempt + 1, max_attempts),
            "INFO",
            "UTILS")
        time.sleep(delay)

    return False


# Main function for command-line use
if __name__ == "__main__":
    # Add the current directory to the path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    # Handle command-line arguments
    import argparse
    parser = argparse.ArgumentParser(description='StreamProxy Utilities')
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check server status')
    parser.add_argument(
        '--restart',
        action='store_true',
        help='Restart the server')
    args = parser.parse_args()

    if args.check:
        if check_server_status():
            print("Proxy server is active and working")
        else:
            print("Proxy server is not active")

    if args.restart:
        if restart_server():
            print("Proxy server restarted successfully")
        else:
            print("Error restarting the proxy server")
