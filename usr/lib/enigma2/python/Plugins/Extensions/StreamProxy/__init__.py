# -*- coding: utf-8 -*-

from __future__ import absolute_import
import importlib.util

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


CRYPTO_AVAILABLE = importlib.util.find_spec("Crypto.Cipher.AES") is not None
print("[StreamProxy] Plugin init")
