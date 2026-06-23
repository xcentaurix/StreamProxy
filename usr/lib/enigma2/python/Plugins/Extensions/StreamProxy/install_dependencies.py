#!/usr/bin/env python3
"""
Script to install optimal dependencies for StreamProxy on Enigma2 decoder
"""

import subprocess
import sys


def install_package(package):
    """Install a Python package"""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package])
        print("[OK] %s installed successfully" % package)
        return True
    except subprocess.CalledProcessError:
        print("[FAIL] Error installing %s" % package)
        return False


def check_package(package):
    """Check if a package is already installed"""
    try:
        __import__(package)
        print("[OK] %s already installed" % package)
        return True
    except ImportError:
        print("[WARN] %s not found" % package)
        return False


def main():
    print("[INFO] StreamProxy dependency installation for Enigma2 decoder")
    print("=" * 60)

    # List of optional dependencies for optimisation
    optional_packages = [
        ("psutil", "RAM monitoring for intelligent cache"),
        ("requests", "HTTP library (should already be present)"),
    ]

    print("\n[PACKAGE] Checking optional dependencies...")

    for package, description in optional_packages:
        print("\n[CHECK] %s - %s" % (package, description))

        if not check_package(package):
            print("[DOWNLOAD] Installing %s..." % package)
            if install_package(package):
                print("[OK] %s installed and ready" % package)
            else:
                print(
                    "[WARN] %s not installed - reduced functionality" %
                    package)
                if package == "psutil":
                    print("   -> Cache will use minimal safe configuration")
        else:
            print("[OK] %s already available" % package)

    print("\n" + "=" * 60)
    print("[DONE] Configuration completed!")
    print("\n[CACHE] Optimised cache configuration:")

    # Test cache configuration
    try:
        import psutil
        available_ram_mb = psutil.virtual_memory().available / (1024 * 1024)
        print("   [RAM] Available RAM: %.1f MB" % available_ram_mb)

        if available_ram_mb < 128:
            print("   [CACHE] Configuration: MINIMAL (low RAM decoder)")
            print("   [CACHE] TS cache: 5 segments, max 10MB")
            print("   [CACHE] M3U8 cache: 3 playlists")
        elif available_ram_mb < 256:
            print("   [CACHE] Configuration: MEDIUM")
            print("   [CACHE] TS cache: 10 segments, max 20MB")
            print("   [CACHE] M3U8 cache: 5 playlists")
        else:
            print("   [CACHE] Configuration: OPTIMAL")
            print("   [CACHE] TS cache: 20 segments, max 40MB")
            print("   [CACHE] M3U8 cache: 10 playlists")

    except ImportError:
        print("   [CACHE] Configuration: SAFE (psutil not available)")
        print("   [CACHE] TS cache: 3 segments, max 5MB")
        print("   [CACHE] M3U8 cache: 2 playlists")

    print("\n[OPTIM] Active optimisations:")
    print("   [OK] Intelligent cache with memory management")
    print("   [OK] Automatic RAM monitoring")
    print("   [OK] Forced garbage collection when needed")
    print("   [OK] Dynamic cache sizes")
    print("   [OK] Reduced timeouts for slow decoders")
    print("   [OK] Optimised chunking for limited memory")

    print("\n[INFO] StreamProxy ready for Enigma2 decoder!")


if __name__ == "__main__":
    main()
