
def addWindowCloseListener(listener):
    closingListeners.append(listener)

def addWindowResizeListener(listener):
    resizeListeners.append(listener)

def getTitle():
    return JS('$doc["title"]')

def getLocation():
    global location
    if not location:
        l = JS('$wnd["location"]')
        location = Location.Location(l)
    return location

def setLocation(url):
    w = JS('$wnd')
    w.location = url

def getClientHeight():
    return JS('$wnd["innerHeight"]')

def getClientWidth():
    return JS('$wnd["innerWidth"]')

def setOnError(onError):
    if (not callable(onError)):
        raise TypeError("object is not callable")
    JS("""\
    $wnd['onerror']=function(msg, url, linenumber){
        return @{{onError}}(msg, url, linenumber);
    }
    """)

def fireClosingImpl():
    ret = None
    for listener in closingListeners:
        msg = listener.onWindowClosing()
        if ret is None:
            ret = msg
    return ret

def fireResizedAndCatch(handler):
    # FIXME - need implementation
    pass

def fireResizedImpl():
    for listener in resizeListeners:
        listener.onWindowResized(getClientWidth(), getClientHeight())

# TODO: call fireClosedAndCatch
def onClosed():
    fireClosedImpl()

# TODO: call fireClosingAndCatch
def onClosing():
    return fireClosingImpl()

# TODO: call fireResizedAndCatch
def onResize():
    fireResizedImpl()

def fireClosedAndCatch(handler):
    # FIXME - need implementation
    pass

def fireClosedImpl():
    for listener in closingListeners:
        listener.onWindowClosed()

def fireClosingAndCatch(handler):
    # FIXME - need implementation
    pass

def resize(width, height):
    wnd().resizeTo(width, height)

def onError(msg, url, linenumber):
    dialog=doc().createElement("div")
    dialog.className='errordialog'
    # Note: $pyjs.trackstack is a global javascript array
    # XXX: we should not have a sys dependency here!
    tracestr = sys.trackstackstr(JS("$pyjs['trackstack']['slice'](0,-1)"))
    tracestr = tracestr.replace("\n", "<br />\n&nbsp;&nbsp;&nbsp;")
    dialog.innerHTML="""\
&nbsp;<b style="color:red">JavaScript Error: </b>
%s at line number %d. Please inform webmaster.
<br />&nbsp;&nbsp;&nbsp;%s
""" % (msg, linenumber, tracestr)
    doc().body.appendChild(dialog)
    return True

def alert(msg):
    wnd().alert(msg)

def confirm(msg):
    return wnd().confirm(msg)

def prompt(msg, defaultReply=""):
    return wnd().prompt(msg, defaultReply)

def init_listeners():
    global closingListeners
    global resizeListeners
    if not closingListeners:
        closingListeners = []
    if not resizeListeners:
        resizeListeners = []

def init():
    global sys
    import sys

    init_listeners()
    JS("""
    $wnd['__pygwt_initHandlers'](
        function() {
            @{{onResize}}();
        },
        function() {
            return @{{onClosing}}();
        },
        function() {
            @{{onClosed}}();
            /*$wnd['onresize'] = null;
            $wnd['onbeforeclose'] = null;
            $wnd['onclose'] = null;*/
        }
    );
    """)
    setOnError(onError)


