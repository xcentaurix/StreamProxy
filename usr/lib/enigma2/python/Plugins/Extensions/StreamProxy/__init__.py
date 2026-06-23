# __init__.py
print("[StreamProxy] Plugin inizializzato")
try:
    from Crypto.Cipher import AES
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    #enhanced_log("⚠️ Crypto non disponibile - decrittazione AES disabilitata", "WARNING", "AppCore")