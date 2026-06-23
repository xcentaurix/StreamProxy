# -*- coding: utf-8 -*-
# StreamProxyLog.py - Logging module for StreamProxy

import os
import time
import sys
import traceback
import threading


CONSOLE_LOGS = os.environ.get(
    "STREAMPROXY_CONSOLE_LOGS", "0").lower() in (
        "1", "true", "yes", "on")
FSYNC_LOGS = os.environ.get(
    "STREAMPROXY_FSYNC_LOGS", "0").lower() in (
        "1", "true", "yes", "on")


def _safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_message = str(message).encode(
            encoding, "backslashreplace").decode(
            encoding, "replace")
        print(safe_message)


class StreamProxyLogger:
    _instance = None
    LOG_FILE = "/usr/lib/enigma2/python/Plugins/Extensions/StreamProxy/streamLogs.txt"
    MAX_LOG_SIZE = 2 * 1024 * 1024  # 2MB maximum
    MAX_LINES = 5000  # Maximum 5000 lines

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
            # Ensure the log directory exists with correct permissions
            log_dir = os.path.dirname(self.LOG_FILE)
            if not os.path.exists(log_dir):
                try:
                    os.makedirs(log_dir, mode=0o755)
                except Exception as e:
                    _safe_print(
                        "[ERROR] Unable to create log directory: %s" % e)
                    return

            # Set file permissions if it exists
            if os.path.exists(self.LOG_FILE):
                try:
                    os.chmod(self.LOG_FILE, 0o644)
                except Exception as e:
                    _safe_print(
                        "[ERROR] Unable to set file permissions: %s" % e)

            # Open the file in write mode to clear it
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("")
                f.flush()

            # Set correct permissions
            os.chmod(self.LOG_FILE, 0o644)

            # Open the file in append mode with minimal buffering
            self._log_file = open(
                self.LOG_FILE,
                'a',
                encoding='utf-8',
                buffering=1)
            self._write_log("=== LOG INITIALISED ===", True)

        except Exception as e:
            _safe_print(
                "[ERROR] Logger initialisation error: %s\n%s" % (
                    str(e), traceback.format_exc()))
            self._log_file = None

    def _write_log(self, message, add_timestamp=True):
        """Actual log writing with improved error handling."""
        with self._lock:
            # Check file size before writing
            self._check_and_rotate_log()
            if not self._log_file:
                try:
                    self._log_file = open(
                        self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
                except Exception as e:
                    _safe_print(
                        "[ERROR] Unable to open log file: %s" % e)
                    return False

            try:
                if add_timestamp:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    entry = "[%s] %s\n" % (timestamp, message)
                else:
                    entry = "%s\n" % message

                self._log_file.write(entry)
                self._log_file.flush()
                if FSYNC_LOGS:
                    os.fsync(self._log_file.fileno())
                if CONSOLE_LOGS:
                    _safe_print("[DEBUG] Log written: %s" % entry.strip())
                return True

            except IOError as e:
                _safe_print(
                    "[ERROR] I/O error during log write: %s" % e)
                # Try to reopen the file
                try:
                    if self._log_file:
                        self._log_file.close()
                    self._log_file = open(
                        self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
                except Exception as e2:
                    _safe_print("[ERROR] Unable to reopen file: %s" % e2)
                return False

            except Exception as e:
                _safe_print(
                    "[ERROR] Generic error during log write: %s" % e)
                return False

    def _check_and_rotate_log(self):
        """Check log file size and rotate if necessary."""
        try:
            if not os.path.exists(self.LOG_FILE):
                return

            file_size = os.path.getsize(self.LOG_FILE)
            if file_size > self.MAX_LOG_SIZE:
                self._rotate_log()
        except Exception as e:
            _safe_print("[ERROR] Log size check error: %s" % e)

    def _rotate_log(self):
        """Rotate the log file, keeping only the last lines."""
        try:
            _safe_print(
                "[INFO] Log rotation - current size: %d bytes" %
                os.path.getsize(
                    self.LOG_FILE))

            # Close the current file
            if self._log_file:
                self._log_file.close()
                self._log_file = None

            # Read the last lines
            with open(self.LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Keep only the last MAX_LINES lines
            if len(lines) > self.MAX_LINES:
                lines = lines[-self.MAX_LINES:]

            # Rewrite the file with the kept lines
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("=== LOG ROTATED ===\n")
                f.writelines(lines)
                f.flush()
                if FSYNC_LOGS:
                    os.fsync(f.fileno())

            # Reopen the file in append mode
            self._log_file = open(
                self.LOG_FILE,
                'a',
                encoding='utf-8',
                buffering=1)
            _safe_print("[INFO] Log rotated - kept %d lines" % len(lines))

        except Exception as e:
            _safe_print("[ERROR] Log rotation error: %s" % e)
            # Fallback: completely clear the log
            try:
                with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                    f.write("=== LOG CLEARED AFTER ERROR ===\n")
                self._log_file = open(
                    self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
            except BaseException:
                pass

    def log(self, message, add_timestamp=True):
        """Public method for logging."""
        if CONSOLE_LOGS:
            _safe_print("[DEBUG] Log request: %s" % message)
        if isinstance(message, str):
            lines = message.split('\n')
        else:
            lines = [str(message)]

        for line in lines:
            self._write_log(line, add_timestamp)

    def clear_log(self):
        """Clear the log file."""
        try:
            if CONSOLE_LOGS:
                _safe_print("[DEBUG] Log clear request")
            # Close the file if it is open
            if hasattr(self, '_log_file') and self._log_file:
                self._log_file.close()
                self._log_file = None

            # Overwrite the file
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("")
                f.flush()
                if FSYNC_LOGS:
                    os.fsync(f.fileno())

            # Reopen the file in append mode
            self._log_file = open(
                self.LOG_FILE,
                'a',
                encoding='utf-8',
                buffering=1)
            if CONSOLE_LOGS:
                _safe_print("[DEBUG] Log file cleared and reopened")
            self._write_log("=== LOG INITIALISED ===")
            return True
        except Exception as e:
            _safe_print("[ERROR] Log clear error: %s" % e)
            # Try to reopen the file even on error
            if not hasattr(self, '_log_file') or not self._log_file:
                try:
                    self._log_file = open(
                        self.LOG_FILE, 'a', encoding='utf-8', buffering=1)
                except BaseException:
                    pass
            return False

    def __del__(self):
        """Close the log file when the object is destroyed."""
        if hasattr(self, '_log_file') and self._log_file:
            try:
                self._log_file.close()
                if CONSOLE_LOGS:
                    _safe_print("[DEBUG] Log file closed")
            except BaseException:
                pass


def enhanced_log(message, level="INFO", component="CORE"):
    """Enhanced logging function with support for components and levels."""
    # Import the global DEBUG_ENABLED variable
    try:
        from .plugin import DEBUG_ENABLED
        if not DEBUG_ENABLED:
            return  # Do not write anything if debug is disabled
    except BaseException:
        pass  # If import fails, continue with normal logging

    if CONSOLE_LOGS:
        _safe_print(
            "[DEBUG] enhanced_log called: [%s] [%s] %s" %
            (level, component, message))
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = "[%s] [%s] [%s] %s" % (
        timestamp, level, component, message)
    logger = StreamProxyLogger.getInstance()
    logger.log(formatted_message, add_timestamp=False)
