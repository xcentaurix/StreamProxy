# -*- coding: utf-8 -*-
"""
TVTap Resolver per StreamViX MFP
Basato sul codice originale funzionante, ottimizzato per Python 3.
"""

# ==============================================================================
# 1. IMPORTS
# ==============================================================================

import sys
import json
import argparse
import re
from base64 import b64decode, b64encode
from binascii import a2b_hex
import os


# Aggiungi la directory 'libs' del plugin al sys.path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
libs_dir = os.path.join(os.path.dirname(plugin_dir), 'libs')
if libs_dir not in sys.path:
    sys.path.insert(0, libs_dir)

# Gestione dipendenze terze parti
try:
    import requests
except ImportError:
    sys.exit(
        "FATAL: Libreria 'requests' non trovata. Installare con: pip install requests")

try:
    from Crypto.Cipher import PKCS1_v1_5 as Cipher_PKCS1_v1_5
    from Crypto.PublicKey import RSA
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

try:
    from pyDes import des, PAD_PKCS5
    HAVE_DES = True
except ImportError:
    HAVE_DES = False

# Import del logger custom
try:
    from ..StreamProxyLog import enhanced_log
except ImportError:
    # Fallback a un logger semplice se eseguito come script standalone
    def enhanced_log(message, level="INFO", component="FALLBACK"):
        print(f"[{level}] [{component}] {message}", file=sys.stderr)

# ==============================================================================
# 2. COSTANTI
# ==============================================================================

# -- API Endpoints --
API_BASE_URL = "https://rocktalk.net/tv/index.php"
CHANNELS_ENDPOINT = f"{API_BASE_URL}?case=get_all_channels"
STREAM_ENDPOINT = f"{API_BASE_URL}?case=get_channel_link_with_token_latest"

# -- Credenziali e Headers --
USER_AGENT = 'USER-AGENT-tvtap-APP-V2'
APP_TOKEN = '37a6259cc0c1dae299a7866489dff0bd'
USERNAME = "603803577"
REQUEST_TIMEOUT = 15

HEADERS_CHANNELS = {
    'User-Agent': USER_AGENT,
    'app-token': APP_TOKEN,
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Host': 'taptube.net',
}
HEADERS_STREAM = {
    'User-Agent': USER_AGENT,
    'app-token': APP_TOKEN,
}

# -- Costanti di crittografia --
RSA_PUBKEY_HEX = (
    "30819f300d06092a864886f70d010101050003818d003081890281"
    "8100bfa5514aa0550688ffde568fd95ac9130fcdd8825bdecc46f1"
    "8f6c6b440c3685cc52ca03111509e262dba482d80e977a938493ae"
    "aa716818efe41b84e71a0d84cc64ad902e46dbea2ec61071958826"
    "4093e20afc589685c08f2d2ae70310b92c04f9b4c27d79c8b5dbb9"
    "bd8f2003ab6a251d25f40df08b1c1588a4380a1ce8030203010001"
)
RSA_MSG_HEX = (
    "7b224d4435223a22695757786f45684237686167747948392b58563052513d3d5c6e222c22534"
    "84131223a2242577761737941713841327678435c2f5450594a74434a4a544a66593d5c6e227d"
)
DES_KEY = b"98221122"

# ==============================================================================
# 3. FUNZIONI DI UTILITY
# ==============================================================================


def check_dependencies():
    """Controlla le dipendenze critiche e termina se non soddisfatte."""
    if not HAVE_CRYPTO:
        sys.exit(
            "FATAL: Libreria 'pycryptodome' non trovata. Installare con: pip install pycryptodome")
    if not HAVE_DES:
        sys.exit(
            "FATAL: Libreria 'pyDes' non trovata. Installare con: pip install pyDes")

# ==============================================================================
# 4. LOGICA PRINCIPALE
# ==============================================================================


def generate_payload():
    """Genera il payload crittografato per le richieste API."""
    if not HAVE_CRYPTO:
        enhanced_log(
            "pycryptodome non disponibile, impossibile generare il payload.",
            level="ERROR",
            component="TVTAP")
        raise ImportError("pycryptodome non è installato.")

    pubkey = RSA.importKey(a2b_hex(RSA_PUBKEY_HEX))
    msg = a2b_hex(RSA_MSG_HEX)
    cipher = Cipher_PKCS1_v1_5.new(pubkey)
    return b64encode(cipher.encrypt(msg))


def get_tvtap_channels():
    """Ottiene la lista dei canali italiani da TVTap."""
    enhanced_log(
        "Tentativo di ottenere la lista canali dall'API...",
        level="DEBUG",
        component="TVTAP")
    try:
        payload_data = generate_payload()
        data = {"payload": payload_data, "username": USERNAME}

        r = requests.post(
            CHANNELS_ENDPOINT,
            headers=HEADERS_CHANNELS,
            data=data,
            timeout=REQUEST_TIMEOUT)
        r.raise_for_status()  # Solleva un'eccezione per status code non 2xx

        response_json = r.json()
        msg = response_json.get("msg")

        if not isinstance(msg, dict) or "channels" not in msg:
            enhanced_log(
                f"Struttura della risposta non valida: {response_json}",
                level="WARNING",
                component="TVTAP")
            return get_static_italian_channels()

        channels = msg["channels"]
        italian_channels = [
            {
                "id": ch.get("pk_id"),
                "name": ch.get("channel_name"),
                "country": ch.get("country"),
                "thumbnail": ch.get("img")
            }
            for ch in channels if isinstance(ch, dict) and ch.get("country") == "IT"
        ]

        enhanced_log(
            f"Trovati {
                len(italian_channels)} canali italiani dall'API.",
            level="DEBUG",
            component="TVTAP")
        return italian_channels if italian_channels else get_static_italian_channels()

    except (requests.RequestException, json.JSONDecodeError, ImportError) as e:
        enhanced_log(
            f"Errore API o parsing: {e}. Fallback sulla lista statica.",
            level="WARNING",
            component="TVTAP")
        return get_static_italian_channels()


def get_tvtap_stream(channel_id):
    """Ottiene lo URL dello stream per un dato ID di canale."""
    enhanced_log(
        f"Richiesta stream per il canale ID: {channel_id}",
        level="DEBUG",
        component="TVTAP")
    try:
        payload_data = generate_payload()
        data = {
            "payload": payload_data,
            "channel_id": channel_id,
            "username": USERNAME}

        r = requests.post(
            STREAM_ENDPOINT,
            headers=HEADERS_STREAM,
            data=data,
            timeout=REQUEST_TIMEOUT)
        r.raise_for_status()

        response_json = r.json()
        msg_res = response_json.get("msg")

        if not isinstance(msg_res, dict) or "channel" not in msg_res:
            enhanced_log(
                f"Risposta per lo stream non valida: {msg_res}",
                level="WARNING",
                component="TVTAP")
            return None

        jch = msg_res["channel"][0]
        d = des(DES_KEY)

        for key, value in jch.items():
            if "stream" in key or "chrome_cast" in key:
                decrypted = d.decrypt(b64decode(value), padmode=PAD_PKCS5)
                if decrypted:
                    link = decrypted.decode("utf-8", errors="ignore")
                    if link and link != "dummytext":
                        enhanced_log(
                            f"Stream trovato per canale {channel_id}",
                            level="DEBUG",
                            component="TVTAP")
                        return link

        enhanced_log(
            "Nessun link stream valido trovato nella risposta.",
            level="DEBUG",
            component="TVTAP")
        return None

    except (requests.RequestException, json.JSONDecodeError, ImportError, IndexError) as e:
        enhanced_log(
            f"Errore durante il recupero dello stream: {e}",
            level="ERROR",
            component="TVTAP")
        return None


def normalize_channel_name(name):
    """Normalizza il nome del canale per un matching flessibile."""
    if not name:
        return ""
    name = name.strip().upper()
    name = re.sub(r'\s+(HD|FHD|4K|\.A|\.B|\.C)$', '', name)
    name = re.sub(r'[^\w\s]', '', name)
    return name


def find_channel_by_name(channel_name, channels):
    """Trova un canale per nome con vari livelli di matching."""
    if not channel_name or not channels:
        return None

    normalized_search = normalize_channel_name(channel_name)
    enhanced_log(
        f"Ricerca normalizzata per: '{normalized_search}'",
        level="DEBUG",
        component="TVTAP")

    # 1. Matching esatto
    for channel in channels:
        if normalize_channel_name(
            channel.get(
                "name",
                "")) == normalized_search:
            enhanced_log(
                f"Match esatto trovato: {
                    channel.get('name')}",
                level="DEBUG",
                component="TVTAP")
            return channel

    # 2. Matching parziale
    for channel in channels:
        normalized_channel = normalize_channel_name(channel.get("name", ""))
        if normalized_search in normalized_channel or normalized_channel in normalized_search:
            enhanced_log(
                f"Match parziale trovato: {
                    channel.get('name')}",
                level="DEBUG",
                component="TVTAP")
            return channel

    enhanced_log(
        f"Nessun match trovato per: {channel_name}",
        level="DEBUG",
        component="TVTAP")
    return None


def get_static_italian_channels():
    """Restituisce una lista statica di canali italiani come fallback."""
    enhanced_log(
        "Restituzione della lista statica dei canali.",
        level="DEBUG",
        component="TVTAP")
    return [
        {"id": "813", "name": "Baby TV", "country": "IT"},
        {"id": "812", "name": "Boomerang", "country": "IT"},
        {"id": "438", "name": "Canale 5", "country": "IT"},
        {"id": "439", "name": "Cartoon Network", "country": "IT"},
        {"id": "810", "name": "Classica", "country": "IT"},
        {"id": "700", "name": "Discovery", "country": "IT"},
        {"id": "731", "name": "Discovery Real Time", "country": "IT"},
        {"id": "737", "name": "Discovery Science", "country": "IT"},
        {"id": "713", "name": "Discovery Travel & Living", "country": "IT"},
        {"id": "830", "name": "Dazn 1", "country": "IT"},
        {"id": "819", "name": "Dazn 10", "country": "IT"},
        {"id": "820", "name": "Dazn 11", "country": "IT"},
        {"id": "768", "name": "Dazn 2", "country": "IT"},
        {"id": "769", "name": "Dazn 3", "country": "IT"},
        {"id": "770", "name": "Dazn 4", "country": "IT"},
        {"id": "771", "name": "Dazn 5", "country": "IT"},
        {"id": "815", "name": "Dazn 6", "country": "IT"},
        {"id": "816", "name": "Dazn 7", "country": "IT"},
        {"id": "817", "name": "Dazn 8", "country": "IT"},
        {"id": "818", "name": "Dazn 9", "country": "IT"},
        {"id": "811", "name": "Dea Kids", "country": "IT"},
        {"id": "711", "name": "Euro Sport", "country": "IT"},
        {"id": "712", "name": "Euro Sport 2", "country": "IT"},
        {"id": "442", "name": "History", "country": "IT"},
        {"id": "739", "name": "Inter Tv", "country": "IT"},
        {"id": "443", "name": "Italia 1", "country": "IT"},
        {"id": "466", "name": "La 7", "country": "IT"},
        {"id": "794", "name": "Lazio Style", "country": "IT"},
        {"id": "718", "name": "Mediaset 2", "country": "IT"},
        {"id": "749", "name": "Mediaset Extra", "country": "IT"},
        {"id": "797", "name": "MediaSet Focus", "country": "IT"},
        {"id": "729", "name": "Milan tv", "country": "IT"},
        {"id": "801", "name": "Nove", "country": "IT"},
        {"id": "791", "name": "Nicklodean", "country": "IT"},
        {"id": "426", "name": "Rai 1", "country": "IT"},
        {"id": "427", "name": "Rai 2", "country": "IT"},
        {"id": "428", "name": "Rai 3", "country": "IT"},
        {"id": "429", "name": "Rai 4", "country": "IT"},
        {"id": "430", "name": "Rai 5", "country": "IT"},
        {"id": "800", "name": "Rai Movie", "country": "IT"},
        {"id": "698", "name": "Rai news 24", "country": "IT"},
        {"id": "784", "name": "Rai Premium", "country": "IT"},
        {"id": "465", "name": "Rete 4", "country": "IT"},
        {"id": "792", "name": "TG Com 24", "country": "IT"},
        {"id": "809", "name": "TV 2000", "country": "IT"},
        {"id": "798", "name": "TV8", "country": "IT"},
        {"id": "776", "name": "Comedy Central", "country": "IT"},
        {"id": "710", "name": "Sky Atlantic", "country": "IT"},
        {"id": "582", "name": "Sky Calcio 1", "country": "IT"},
        {"id": "583", "name": "Sky Calcio 2", "country": "IT"},
        {"id": "706", "name": "Sky Calcio 3", "country": "IT"},
        {"id": "707", "name": "Sky Calcio 4", "country": "IT"},
        {"id": "708", "name": "Sky Calcio 5", "country": "IT"},
        {"id": "709", "name": "Sky Calcio 6", "country": "IT"},
        {"id": "876", "name": "Sky Calcio 7", "country": "IT"},
        {"id": "877", "name": "Sky Calcio 8", "country": "IT"},
        {"id": "878", "name": "Sky Calcio 9", "country": "IT"},
        {"id": "590", "name": "Sky Cinema Action", "country": "IT"},
        {"id": "589", "name": "Sky Cinema Collection", "country": "IT"},
        {"id": "586", "name": "Sky Cinema Comedy", "country": "IT"},
        {"id": "587", "name": "Sky Cinema Due", "country": "IT"},
        {"id": "588", "name": "Sky Cinema Family", "country": "IT"},
        {"id": "591", "name": "Sky Cinema Romance", "country": "IT"},
        {"id": "584", "name": "Sky Cinema UNO", "country": "IT"},
        {"id": "629", "name": "Sky Sport 24", "country": "IT"},
        {"id": "579", "name": "Sky Sport Arena", "country": "IT"},
        {"id": "705", "name": "Sky Sport Calcio", "country": "IT"},
        {"id": "581", "name": "Sky Sport F1", "country": "IT"},
        {"id": "580", "name": "Sky Sport Football", "country": "IT"},
        {"id": "668", "name": "Sky Sport Motogp", "country": "IT"},
        {"id": "704", "name": "Sky Sport NBA", "country": "IT"},
        {"id": "578", "name": "Sky Sport Uno", "country": "IT"},
        {"id": "592", "name": "Sky TG24", "country": "IT"},
        {"id": "593", "name": "Sky Uno", "country": "IT"}
    ]

# ==============================================================================
# 5. ESECUZIONE DA RIGA DI COMANDO
# ==============================================================================


def main():
    """Punto di ingresso principale per l'esecuzione da riga di comando."""
    parser = argparse.ArgumentParser(
        description="Resolver per canali TVTap.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Argomenti principali (mutuamente esclusivi)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "channel_name",
        nargs="?",
        default=None,
        help="Nome del canale da risolvere (es. 'Rai 1').")
    group.add_argument(
        "--dump-channels",
        action="store_true",
        help="Mostra la lista completa dei canali italiani in formato JSON.")
    group.add_argument(
        "--build-cache",
        metavar="FILE_PATH",
        nargs="?",
        const="tvtap_cache.json",
        help="Genera un file cache JSON dei canali. (default: tvtap_cache.json)")

    # Opzioni aggiuntive
    parser.add_argument(
        "--original-link",
        action="store_true",
        help="Restituisce il link nel formato 'tvtap://<ID>' invece dello stream URL.")

    args = parser.parse_args()

    # -- Gestione Azioni --

    if args.dump_channels:
        check_dependencies()
        channels = get_tvtap_channels()
        print(json.dumps(channels, ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.build_cache:
        check_dependencies()
        enhanced_log(
            "Creazione della cache dei canali...",
            level="INFO",
            component="TVTAP")
        channels = get_tvtap_channels()
        cache = {ch.get("name", "").strip(): ch.get("id", "")
                 for ch in channels if ch.get("name") and ch.get("id")}

        try:
            with open(args.build_cache, "w", encoding="utf-8") as f:
                json.dump({"channels": cache}, f, ensure_ascii=False, indent=2)
            print(
                f"Cache TVTap generata con successo in '{
                    args.build_cache}'!")
            sys.exit(0)
        except IOError as e:
            enhanced_log(
                f"Impossibile scrivere il file cache: {e}",
                level="ERROR",
                component="TVTAP")
            sys.exit(1)

    # -- Risoluzione Canale (azione di default) --
    if not args.channel_name:
        parser.error("Il nome del canale è richiesto.")

    check_dependencies()

    # Gestione ID diretto (es. tvtap_id:123)
    if args.channel_name.startswith("tvtap_id:"):
        channel_id = args.channel_name.split(":", 1)[1]
        enhanced_log(
            f"ID TVTap diretto rilevato: {channel_id}",
            level="DEBUG",
            component="TVTAP")
    else:
        # Ricerca per nome
        channels = get_tvtap_channels()
        if not channels:
            enhanced_log(
                "Nessun canale recuperato.",
                level="ERROR",
                component="TVTAP")
            sys.exit(2)

        found_channel = find_channel_by_name(args.channel_name, channels)
        if not found_channel:
            enhanced_log(
                f"Canale '{
                    args.channel_name}' non trovato.",
                level="WARNING",
                component="TVTAP")
            sys.exit(3)

        channel_id = found_channel.get("id")
        if not channel_id:
            enhanced_log(
                f"Nessun ID trovato per il canale '{
                    args.channel_name}'.",
                level="ERROR",
                component="TVTAP")
            sys.exit(4)

        enhanced_log(
            f"Canale trovato: {
                found_channel.get('name')} (ID: {channel_id})",
            level="INFO",
            component="TVTAP")

    # Restituzione del link richiesto
    if args.original_link:
        print(f"tvtap://{channel_id}")
    else:
        stream_url = get_tvtap_stream(channel_id)
        if stream_url:
            print(stream_url)
        else:
            enhanced_log(
                "Impossibile ottenere lo URL dello stream.",
                level="ERROR",
                component="TVTAP")
            sys.exit(5)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        enhanced_log(
            f"Errore non gestito: {e}",
            level="CRITICAL",
            component="TVTAP")
        sys.exit(1)
