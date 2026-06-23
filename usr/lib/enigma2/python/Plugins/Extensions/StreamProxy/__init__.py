# -*- coding: utf-8 -*-

from __future__ import absolute_import

try:
    from Crypto.Cipher import AES
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

print("[StreamProxy] Plugin init")

__license__ = "GPL-v2"
__version__ = "1.0_beta"

import os
import gettext

from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS

PluginLanguageDomain = "streamproxy"
PluginLanguagePath = "Extensions/StreamProxy/locale"


def localeInit():
    lang = language.getLanguage()[:2]  # es. "it", "en"
    os.environ["LANGUAGE"] = lang
    gettext.bindtextdomain(
        PluginLanguageDomain,
        resolveFilename(
            SCOPE_PLUGINS,
            PluginLanguagePath))


def _(txt):
    return gettext.dgettext(PluginLanguageDomain, txt) if txt else ""


localeInit()
language.addCallback(localeInit)
