#!/usr/bin/env python3
# diagnostics.py - Diagnostica completa del sistema StreamProxy

import sys
import os
import time
import requests
import traceback

def check_server_status():
    """Verifica lo stato del server HTTP"""
    print("🔍 CONTROLLO SERVER HTTP")
    print("-" * 40)
    
    ports_to_check = [7860, 8081, 8088]  # Porte comuni
    
    for port in ports_to_check:
        try:
            url = f"http://127.0.0.1:{port}/"
            response = requests.get(url, timeout=2)
            print(f"✅ Porta {port}: ATTIVA (Status: {response.status_code})")
            
            # Test endpoint specifici
            endpoints = ["/proxy/m3u?test=1", "/proxy/resolve?test=1"]
            for endpoint in endpoints:
                try:
                    test_url = f"http://127.0.0.1:{port}{endpoint}"
                    test_response = requests.get(test_url, timeout=2)
                    print(f"   └─ {endpoint}: {test_response.status_code}")
                except:
                    print(f"   └─ {endpoint}: ❌ NON RISPONDE")
                    
        except Exception as e:
            print(f"❌ Porta {port}: NON ATTIVA ({str(e)})")
    
    print()

def check_appcore_integration():
    """Verifica integrazione AppCore"""
    print("🔧 CONTROLLO APPCORE")
    print("-" * 40)
    
    try:
        # Aggiungi il percorso corrente
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        
        from AppCore import service_monitor_callback, AppCore
        print("✅ AppCore importato correttamente")
        
        # Test callback
        try:
            result = service_monitor_callback('/proxy/m3u', url='test', test='1')
            print(f"✅ Callback funzionante: {type(result)}")
        except Exception as e:
            print(f"❌ Errore callback: {str(e)}")
        
        # Test istanza AppCore
        try:
            app = AppCore()
            print("✅ Istanza AppCore creata")
        except Exception as e:
            print(f"❌ Errore istanza AppCore: {str(e)}")
            
    except Exception as e:
        print(f"❌ Errore importazione AppCore: {str(e)}")
        traceback.print_exc()
    
    print()

def check_service_monitor():
    """Verifica ServiceMonitor (simulato)"""
    print("📡 CONTROLLO SERVICE MONITOR")
    print("-" * 40)
    
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
            
        # Test import
        from ServiceMonitor import StreamProxyServiceMonitor
        print("✅ ServiceMonitor importato correttamente")
        
        # Verifica metodi critici
        methods_to_check = ['_proxy_play_service', '_ensure_server_running', 'notify_m3u']
        for method in methods_to_check:
            if hasattr(StreamProxyServiceMonitor, method):
                print(f"✅ Metodo {method}: PRESENTE")
            else:
                print(f"❌ Metodo {method}: MANCANTE")
                
    except Exception as e:
        print(f"❌ Errore ServiceMonitor: {str(e)}")
        traceback.print_exc()
    
    print()

def check_pipeline():
    """Verifica Pipeline"""
    print("🔄 CONTROLLO PIPELINE")
    print("-" * 40)
    
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
            
        from Pipeline import Pipeline, process_content
        print("✅ Pipeline importata correttamente")
        
        # Test istanza
        pipeline = Pipeline()
        print("✅ Istanza Pipeline creata")
        
        # Test processing con contenuto fittizio
        test_content = "#EXTM3U\n#EXTINF:10.0,\ntest.ts\n"
        result = process_content(test_content, "application/vnd.apple.mpegurl", "test_url")
        print(f"✅ Test processing: {result}")
        
    except Exception as e:
        print(f"❌ Errore Pipeline: {str(e)}")
        traceback.print_exc()
    
    print()

def check_file_structure():
    """Verifica struttura file"""
    print("📁 CONTROLLO STRUTTURA FILE")
    print("-" * 40)
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    required_files = [
        'server.py',
        'http_response.py',
        'AppCore.py', 
        'ServiceMonitor.py',
        'Pipeline.py',
        'plugin.py',
        'StreamProxyLog.py'
    ]
    
    for file in required_files:
        file_path = os.path.join(current_dir, file)
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            print(f"✅ {file}: PRESENTE ({size} bytes)")
        else:
            print(f"❌ {file}: MANCANTE")
    
    print()

def test_url_processing():
    """Test processing URL completo"""
    print("🌐 TEST PROCESSING URL")
    print("-" * 40)
    
    test_urls = [
        "https://vavoo.to/play/875922788/index.m3u8",
        "http://example.com/stream.m3u8",
        "https://daddylive.sx/stream/123.php"
    ]
    
    for url in test_urls:
        print(f"Test URL: {url}")
        try:
            # Test creazione URL proxy
            from urllib.parse import quote
            proxy_url = f"http://127.0.0.1:7860/proxy/m3u?url={quote(url)}"
            print(f"  └─ URL Proxy: {proxy_url[:80]}...")
            
            # Test richiesta (se server attivo)
            try:
                response = requests.get(proxy_url, timeout=5)
                print(f"  └─ Risposta: {response.status_code}")
            except:
                print(f"  └─ Risposta: ❌ Server non risponde")
                
        except Exception as e:
            print(f"  └─ Errore: {str(e)}")
    
    print()

def main():
    """Esegue tutti i controlli diagnostici"""
    print("=" * 50)
    print("🔧 DIAGNOSTICA STREAMPROXY")
    print("=" * 50)
    print()
    
    check_file_structure()
    check_server_status()
    check_appcore_integration()
    check_service_monitor()
    check_pipeline()
    test_url_processing()
    
    print("=" * 50)
    print("✅ DIAGNOSTICA COMPLETATA")
    print("=" * 50)

if __name__ == "__main__":
    main()
