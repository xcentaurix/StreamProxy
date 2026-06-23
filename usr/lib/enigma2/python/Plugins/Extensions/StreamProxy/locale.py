# locale.py
# Sistema di localizzazione semplice per StreamProxy

class Locale:
    # Dizionario delle traduzioni
    _translations = {
        'it': {
            'plugin_name': 'Stream Proxy',
            'plugin_description': 'Proxy per migliorare la riproduzione dei flussi streaming',
            'Inizializzazione...': 'Inizializzazione...',
            'Chiudi': 'Chiudi',
            'Configurazione': 'Configurazione',
            'proxy_status': 'Stato del proxy: {}',
            'enabled': 'Abilitato',
            'disabled': 'Disabilitato',
            'save': 'Salva',
            'cancel': 'Annulla',
            'select_channels': 'Seleziona Canali',
            'enable_proxy': 'Abilita Stream Proxy',
            'enable_filter': 'Abilita filtro canali',
            'port': 'Porta',
            'settings_saved': 'Impostazioni salvate',
            'restart_required': 'Riavvio richiesto per applicare le modifiche'
        },
        'en': {
            'plugin_name': 'Stream Proxy',
            'plugin_description': 'Proxy to improve streaming playback',
            'Inizializzazione...': 'Initializing...',
            'Chiudi': 'Close',
            'Configurazione': 'Settings',
            'proxy_status': 'Proxy status: {}',
            'enabled': 'Enabled',
            'disabled': 'Disabled',
            'save': 'Save',
            'cancel': 'Cancel',
            'select_channels': 'Select Channels',
            'enable_proxy': 'Enable Stream Proxy',
            'enable_filter': 'Enable channel filter',
            'port': 'Port',
            'settings_saved': 'Settings saved',
            'restart_required': 'Restart required to apply changes'
        }
    }
    
    # Lingua corrente (default: italiano)
    _current_language = 'it'
    
    @classmethod
    def set_language(cls, language_code):
        """Imposta la lingua corrente"""
        if language_code in cls._translations:
            cls._current_language = language_code
            return True
        return False
    
    @classmethod
    def _(cls, text):
        """Traduce un testo nella lingua corrente"""
        # Se la chiave esiste nella lingua corrente, restituisci la traduzione
        if text in cls._translations.get(cls._current_language, {}):
            return cls._translations[cls._current_language][text]
        # Altrimenti restituisci il testo originale
        return text