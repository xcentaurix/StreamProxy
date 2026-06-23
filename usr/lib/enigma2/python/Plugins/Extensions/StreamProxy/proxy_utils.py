# proxy_utils.py - Utilità per la gestione dei proxy
import os
import random
import time
import requests
import socket
import threading
from urllib.parse import urlparse
from .StreamProxyLog import enhanced_log

# Configurazione iniziale
VERIFY_SSL = os.environ.get('VERIFY_SSL', 'false').lower() not in ('false', '0', 'no')
if not VERIFY_SSL:
    enhanced_log("ATTENZIONE: Verifica SSL disabilitata", "WARNING", "PROXY")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Timeout per le richieste HTTP in secondi
REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', 15))

# Lista dei proxy disponibili
PROXY_LIST = []

def setup_proxies():
    """Carica la lista di proxy SOCKS5 dalla variabile d'ambiente."""
    global PROXY_LIST
    proxy_list_str = os.environ.get('SOCKS5_PROXY')
    if proxy_list_str:
        raw_proxy_list = [p.strip() for p in proxy_list_str.split(',') if p.strip()]

        if not raw_proxy_list:
            enhanced_log("Nessun proxy SOCKS5 valido trovato nella variabile d'ambiente.", "WARNING", "PROXY")
            PROXY_LIST = []
            return

        enhanced_log(f"Trovati {len(raw_proxy_list)} proxy SOCKS5.", "INFO", "PROXY")
        for proxy in raw_proxy_list:
            # Riconosce e converte automaticamente a socks5h per la risoluzione DNS remota
            final_proxy_url = proxy
            if proxy.startswith('socks5://'):
                final_proxy_url = 'socks5h' + proxy[len('socks5'):]
                enhanced_log(f"Proxy convertito per garantire la risoluzione DNS remota.", "INFO", "PROXY")
            elif not proxy.startswith('socks5h://'):
                enhanced_log(f"ATTENZIONE: L'URL del proxy non è un formato SOCKS5 valido.", "WARNING", "PROXY")
            PROXY_LIST.append(final_proxy_url)

        enhanced_log("Assicurati di aver installato la dipendenza necessaria: 'pip install PySocks'", "INFO", "PROXY")
    else:
        PROXY_LIST = []
        enhanced_log("Nessun proxy SOCKS5 configurato.", "INFO", "PROXY")

def get_proxy_for_url(url):
    """Seleziona proxy specifici per DaddyLive o proxy generali per altri domini"""
    no_proxy_domains = ['github.com']  # Domini che non usano proxy
    
    # Controlla se è un URL DaddyLive
    is_daddylive = (
        'newkso.ru' in url.lower() or 
        '/stream-' in url.lower() or
        'daddylive' in url.lower() or
        'daddy' in url.lower()
    )
    
    # Se è DaddyLive, usa i proxy specifici
    if is_daddylive:
        enhanced_log(f"URL DaddyLive rilevato: {url}", "DEBUG", "PROXY")
        return get_daddy_proxy_list()
    
    # Altrimenti usa i proxy generali
    if not PROXY_LIST:
        return None
    
    try:
        parsed_url = urlparse(url)
        if any(domain in parsed_url.netloc for domain in no_proxy_domains):
            return None
    except Exception:
        pass
    
    chosen_proxy = random.choice(PROXY_LIST)
    return {'http': chosen_proxy, 'https': chosen_proxy}

def get_daddy_proxy_list():
    """Carica la lista di proxy specifici per DaddyLive."""
    daddy_proxy_value = os.environ.get('DADDY_PROXY', '')
    daddy_proxies = []

    if daddy_proxy_value and daddy_proxy_value.strip():
        proxy_list = [p.strip() for p in daddy_proxy_value.split(',') if p.strip()]
        
        for proxy in proxy_list:
            if proxy.startswith('socks5://'):
                final_proxy_url = 'socks5h' + proxy[len('socks5'):]
                enhanced_log(f"Proxy DaddyLive SOCKS5 convertito", "INFO", "PROXY")
            elif proxy.startswith('socks5h://'):
                final_proxy_url = proxy
                enhanced_log(f"Proxy DaddyLive SOCKS5H configurato", "INFO", "PROXY")
            elif proxy.startswith('http://') or proxy.startswith('https://'):
                final_proxy_url = proxy
                enhanced_log(f"Proxy DaddyLive HTTP/HTTPS configurato", "INFO", "PROXY")
            else:
                final_proxy_url = f"http://{proxy}"
                enhanced_log(f"Proxy DaddyLive convertito in HTTP", "INFO", "PROXY")
            
            daddy_proxies.append(final_proxy_url)
        
        enhanced_log(f"Trovati {len(daddy_proxies)} proxy DaddyLive", "INFO", "PROXY")
    
    if daddy_proxies:
        chosen_proxy = random.choice(daddy_proxies)
        return {'http': chosen_proxy, 'https': chosen_proxy}
    return get_random_proxy()

def get_random_proxy():
    """Seleziona un proxy casuale dalla lista e lo formatta per la libreria requests."""
    if not PROXY_LIST:
        return None
    chosen_proxy = random.choice(PROXY_LIST)
    return {'http': chosen_proxy, 'https': chosen_proxy}

def create_robust_session():
    """Crea una sessione requests robusta e compatibile con Enigma2."""
    session = requests.Session()

    # Parametri di keep-alive (valori compatibili con sistemi embedded)
    KEEP_ALIVE_TIMEOUT = 10  # secondi
    MAX_KEEP_ALIVE_REQUESTS = 10
    session.headers.update({
        'Connection': 'keep-alive',
        'Keep-Alive': f'timeout={KEEP_ALIVE_TIMEOUT}, max={MAX_KEEP_ALIVE_REQUESTS}'
    })

    # Configurazione retry semplice
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry_strategy = Retry(
            total=2,
            read=1,
            connect=1,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=5,
            pool_maxsize=10,
            pool_block=False
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    except Exception:
        # Su Enigma2 può mancare urllib3.util.retry: fallback senza retry avanzato
        pass

    return session

# Pool di sessioni persistenti
SESSION_POOL = {}
SESSION_LOCK = threading.Lock()

def get_persistent_session(proxy_url=None, max_age=300):
    """Ottiene una sessione persistente dal pool o ne crea una nuova con controllo età"""
    global SESSION_POOL, SESSION_LOCK
    pool_key = proxy_url if proxy_url else 'default'
    current_time = time.time()
    
    with SESSION_LOCK:
        # Controlla se la sessione esiste e non è troppo vecchia
        if pool_key in SESSION_POOL:
            session_data = SESSION_POOL[pool_key]
            session_age = current_time - session_data.get('created_at', 0)
            
            # Se la sessione è troppo vecchia, creane una nuova
            if session_age > max_age:
                enhanced_log(f"Sessione troppo vecchia ({session_age}s), creazione nuova", "INFO", "PROXY")
                session = create_robust_session()
                if proxy_url:
                    session.proxies.update({'http': proxy_url, 'https': proxy_url})
                SESSION_POOL[pool_key] = {
                    'session': session,
                    'created_at': current_time,
                    'requests_count': 0
                }
            else:
                # Incrementa il contatore di richieste
                session_data['requests_count'] += 1
                return session_data['session']
        else:
            # Crea una nuova sessione
            session = create_robust_session()
            if proxy_url:
                session.proxies.update({'http': proxy_url, 'https': proxy_url})
            SESSION_POOL[pool_key] = {
                'session': session,
                'created_at': current_time,
                'requests_count': 0
            }
            
        # Limita il numero di sessioni nel pool
        if len(SESSION_POOL) > 20:  # Numero massimo di sessioni
            # Rimuovi la sessione più vecchia
            oldest_key = min(SESSION_POOL.keys(), key=lambda k: SESSION_POOL[k]['created_at'])
            del SESSION_POOL[oldest_key]
            
        return SESSION_POOL[pool_key]['session']

def make_persistent_request(url, headers=None, timeout=None, proxy_url=None, **kwargs):
    """Effettua una richiesta usando connessioni persistenti (compatibile Enigma2)"""
    session = get_persistent_session(proxy_url)
    # Parametri di keep-alive
    KEEP_ALIVE_TIMEOUT = 10  # secondi
    MAX_KEEP_ALIVE_REQUESTS = 10
    request_headers = {
        'Connection': 'keep-alive',
        'Keep-Alive': f'timeout={KEEP_ALIVE_TIMEOUT}, max={MAX_KEEP_ALIVE_REQUESTS}'
    }
    if headers:
        request_headers.update(headers)
    try:
        response = session.get(
            url,
            headers=request_headers,
            timeout=timeout or REQUEST_TIMEOUT,
            verify=VERIFY_SSL,
            **kwargs
        )
        return response
    except Exception as e:
        enhanced_log(f"Errore nella richiesta persistente: {e}", "ERROR", "PROXY")
        # In caso di errore, rimuovi la sessione dal pool
        with SESSION_LOCK:
            pool_key = proxy_url if proxy_url else 'default'
            if pool_key in SESSION_POOL:
                del SESSION_POOL[pool_key]
        raise

def get_dynamic_timeout(url, base_timeout=None):
    """Calcola timeout dinamico basato sul tipo di risorsa."""
    if base_timeout is None:
        base_timeout = 8  # Timeout base ridotto
    url_l = url.lower() if isinstance(url, str) else ""
    if ".ts" in url_l:
        return 5  # Timeout fisso breve per TS
    elif ".m3u8" in url_l:
        return 8
    else:
        return base_timeout

# Inizializza i proxy all'importazione del modulo
setup_proxies()