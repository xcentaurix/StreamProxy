# locale.py - Versione inglese (sostituisce il vecchio sistema di traduzione)
def _(text):
    """Funzione fittizia per la traduzione. Restituisce il testo così com'è."""
    return text

# (Opzionale) Se vuoi mantenere la compatibilità con il vecchio codice,
# puoi anche definire una classe Locale con un metodo statico _.


class Locale:
    @staticmethod
    def _(text):
        return text
