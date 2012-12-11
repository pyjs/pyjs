# encoding: utf-8
"""
    (C) 2012 by Maho (?ukasz Mach)

    License: GPL


    Poor man's i18n support for Pyjamas.

    _("identifier") returns you translated version of "identifier". If you want
    original (English) version, just do nothing. If you want other language
    (eg. PL), please import translation_pl in your project, when it's content
    is:

    from pyjamas.locale import msgs

    msgs["Week"] = "Tydzień"
    msgs["Jan"] = "Sty"
    msgs["January"] = "Styczeń"
    msgs["Other eng identifier you'd like to translate"] = "Inny ang. identyfikator który chciałbyś przetłumaczyć"

"""

msgs = {}

def _(identifier):
    return msgs.get(identifier,identifier)
