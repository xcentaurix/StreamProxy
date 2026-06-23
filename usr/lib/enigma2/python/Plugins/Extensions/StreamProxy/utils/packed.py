# utils/packed.py - Unpacker per JavaScript packed (adattato per Enigma2)
# Basato su EasyProxy/utils/packed.py

import re
import logging

logger = logging.getLogger(__name__)


def detect(source):
    """Rileva se il codice JavaScript è packed"""
    if "eval(function(p,a,c,k,e,d)" in source:
        return True
    return False


def unpack(source):
    """Unpacks P.A.C.K.E.R. packed js code."""
    payload, symtab, radix, count = _filterargs(source)

    if count != len(symtab):
        raise UnpackingError("Malformed p.a.c.k.e.r. symtab.")

    try:
        unbase = Unbaser(radix)
    except TypeError:
        raise UnpackingError("Unknown p.a.c.k.e.r. encoding.")

    def lookup(match):
        """Look up symbols in the synthetic symtab."""
        word = match.group(0)
        return symtab[unbase(word)] or word

    payload = payload.replace("\\\\", "\\").replace("\\'", "'")
    source = re.sub(r"\b\w+\b", lookup, payload)
    return _replacestrings(source)


def _filterargs(source):
    """Juice from a source file the four args needed by decoder."""
    juicers = [
        (r"}\\('(.*)', *(\\d+|\\[\\]), *(\\d+), *'(.*)'\\.split\\('\\|'\\), *(\\d+), *(.*)\\)\\)"),
        (r"}\\('(.*)', *(\\d+|\\[\\]), *(\\d+), *'(.*)'\\.split\\('\\|'\\)"),
    ]
    for juicer in juicers:
        args = re.search(juicer, source, re.DOTALL)
        if args:
            a = args.groups()
            if a[1] == "[]":
                a = list(a)
                a[1] = 62
                a = tuple(a)
            try:
                return a[0], a[3].split("|"), int(a[1]), int(a[2])
            except ValueError:
                raise UnpackingError("Corrupted p.a.c.k.e.r. data.")

    raise UnpackingError(
        "Could not make sense of p.a.c.k.e.r data (unexpected code structure)")


def _replacestrings(source):
    """Strip string lookup table (list) and replace values in source."""
    match = re.search(r'var *(_\\w+)\\=\\["(.*?)"\\];', source, re.DOTALL)

    if match:
        varname, strings = match.groups()
        startpoint = len(match.group(0))
        lookup = strings.split('","')
        variable = "%s[%%d]" % varname
        for index, value in enumerate(lookup):
            source = source.replace(variable % index, '"%s"' % value)
        return source[startpoint:]
    return source


class Unbaser(object):
    """Functor for a given base. Will efficiently convert strings to natural numbers."""

    ALPHABET = {
        62: "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        95: (
            " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "[\\\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
        ),
    }

    def __init__(self, base):
        self.base = base

        if 36 < base < 62:
            if not hasattr(self.ALPHABET, self.ALPHABET[62][:base]):
                self.ALPHABET[base] = self.ALPHABET[62][:base]

        if 2 <= base <= 36:
            self.unbase = lambda string: int(string, base)
        else:
            try:
                self.dictionary = dict(
                    (cipher, index) for index, cipher in enumerate(
                        self.ALPHABET[base]))
            except KeyError:
                raise TypeError("Unsupported base encoding.")

            self.unbase = self._dictunbaser

    def __call__(self, string):
        return self.unbase(string)

    def _dictunbaser(self, string):
        """Decodes a value to an integer."""
        ret = 0
        for index, cipher in enumerate(string[::-1]):
            ret += (self.base ** index) * self.dictionary[cipher]
        return ret


class UnpackingError(Exception):
    """Badly packed source or general error."""
    pass
