#!/usr/bin/env python3
"""
Script per installare le dipendenze ottimali per StreamProxy su decoder Enigma2
"""

import subprocess
import sys
import os

def install_package(package):
    """Installa un pacchetto Python"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✅ {package} installato con successo")
        return True
    except subprocess.CalledProcessError:
        print(f"❌ Errore installazione {package}")
        return False

def check_package(package):
    """Controlla se un pacchetto è già installato"""
    try:
        __import__(package)
        print(f"✅ {package} già installato")
        return True
    except ImportError:
        print(f"⚠️ {package} non trovato")
        return False

def main():
    print("🚀 Installazione dipendenze StreamProxy per decoder Enigma2")
    print("=" * 60)
    
    # Lista delle dipendenze opzionali per ottimizzazione
    optional_packages = [
        ("psutil", "Monitoraggio memoria RAM per cache intelligente"),
        ("requests", "Libreria HTTP (dovrebbe essere già presente)"),
    ]
    
    print("\n📦 Controllo dipendenze opzionali...")
    
    for package, description in optional_packages:
        print(f"\n🔍 Controllo {package} - {description}")
        
        if not check_package(package):
            print(f"📥 Installazione {package}...")
            if install_package(package):
                print(f"✅ {package} installato e pronto")
            else:
                print(f"⚠️ {package} non installato - funzionalità ridotte")
                if package == "psutil":
                    print("   → Cache userà configurazione minima per sicurezza")
        else:
            print(f"✅ {package} già disponibile")
    
    print("\n" + "=" * 60)
    print("🎯 Configurazione completata!")
    print("\n📊 Configurazione cache ottimizzata:")
    
    # Test configurazione cache
    try:
        import psutil
        available_ram_mb = psutil.virtual_memory().available / (1024 * 1024)
        print(f"   🧠 RAM disponibile: {available_ram_mb:.1f} MB")
        
        if available_ram_mb < 128:
            print("   📦 Configurazione: MINIMA (decoder con poca RAM)")
            print("   🎞️ Cache TS: 5 segmenti, max 10MB")
            print("   📋 Cache M3U8: 3 playlist")
        elif available_ram_mb < 256:
            print("   📦 Configurazione: MEDIA")
            print("   🎞️ Cache TS: 10 segmenti, max 20MB")
            print("   📋 Cache M3U8: 5 playlist")
        else:
            print("   📦 Configurazione: OTTIMALE")
            print("   🎞️ Cache TS: 20 segmenti, max 40MB")
            print("   📋 Cache M3U8: 10 playlist")
            
    except ImportError:
        print("   📦 Configurazione: SICURA (psutil non disponibile)")
        print("   🎞️ Cache TS: 3 segmenti, max 5MB")
        print("   📋 Cache M3U8: 2 playlist")
    
    print("\n🔧 Ottimizzazioni attive:")
    print("   ✅ Cache intelligente con gestione memoria")
    print("   ✅ Monitoraggio RAM automatico")
    print("   ✅ Garbage collection forzato quando necessario")
    print("   ✅ Dimensioni cache dinamiche")
    print("   ✅ Timeout ridotti per decoder lenti")
    print("   ✅ Chunking ottimizzato per memoria limitata")
    
    print("\n🚀 StreamProxy pronto per decoder Enigma2!")

if __name__ == "__main__":
    main()