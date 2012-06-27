# This is the gtk-dependent History module.
# For the pyjamas/javascript version, see platform/HistoryPyJS.py

from __pyjamas__ import JS, doc, wnd
import pyjd
if pyjd.is_desktop:
    from __pyjamas__ import get_main_frame

global historyToken
historyToken = ''

historyListeners = []


"""
    Simple History management class for back/forward button support.

    This class allows your AJAX application to use a history.  Each time you
    call newItem(), a new item is added to the history and the history
    listeners are notified.  If the user clicks the browser's forward or back
    buttons, the appropriate item (a string passed to newItem) is fetched
    from the history and the history listeners are notified.

    The address bar of the browser contains the current token, using
    the "#" seperator (for implementation reasons, not because we love
    the # mark).

    You may want to check whether the hash already contains a history
    token when the page loads and use that to show appropriate content;
    this allows users of the site to store direct links in their
    bookmarks or send them in emails.

    To make this work properly in all browsers, you must add a specially
    named iframe to your html page, like this:

    <iframe id='__pygwt_historyFrame' style='width:0;height:0;border:0' />
"""


def addHistoryListener(listener):
    print "add listener", listener
    historyListeners.append(listener)


def back():
    wnd().history.back()


def forward():
    wnd().history.forward()


def getToken():
    global historyToken
    return historyToken


def newItem(ht):
    global historyToken
    if historyToken == ht:
        return
    onHistoryChanged(ht)
    return

    JS("""
    if(@{{historyToken}} == "" || @{{historyToken}} == null){
        @{{historyToken}} = "#";
    }
    $wnd['location']['hash'] = encodeURI(@{{historyToken}})['replace']('#','%23');
    """)


# TODO - fireHistoryChangedAndCatch not implemented
def onHistoryChanged(ht):
    fireHistoryChangedImpl(ht)


# TODO
def fireHistoryChangedAndCatch():
    pass


def fireHistoryChangedImpl(ht):
    global historyToken
    if historyToken == ht:
        return
    historyToken = ht
    for listener in historyListeners:
        listener.onHistoryChanged(ht)


def removeHistoryListener(listener):
    historyListeners.remove(listener)

def _first_notify():
    print "first notify", historyToken
    onHistoryChanged(historyToken)

def init():
    print "init", get_main_frame(), pyjd.is_desktop
    if get_main_frame() is None:
        if pyjd.is_desktop:
            pyjd.add_setup_callback(init)
#            pyjd.add_pre_run_callback(_first_notify)
        return

    global historyToken
    historyToken = ''
    hash = wnd().location.hash

    if hash and len(hash) > 0:
        historyToken = hash[1:]

init()
