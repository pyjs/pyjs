#
# Warning: this is an alpha module and might be removed/renamed in
# later pyjamas versions
#
from __pyjamas__ import wnd, doc, JS, setCompilerOptions
from __javascript__ import ActiveXObject, XMLHttpRequest
from pyjamas import DOM
from __pyjamas__ import debugger
import sys

setCompilerOptions("noSourceTracking", "noLineTracking", "noStoreSource")

class AjaxError(RuntimeError):
    pass

def createHttpRequest():
    if JS("""typeof $wnd['XMLHttpRequest'] != 'undefined'"""):
        # IE7+, Mozilla, Safari, ...
       return JS("""new XMLHttpRequest()""")

    # Check for IE6/ActiveX
    try:
        res = JS("""new ActiveXObject("Msxml2['XMLHTTP']")""")
        return res
    except:
        pass
    return None

#
#  load(url)
#
#  @param url                   URL to load
#  @param onreadystatechange    function to be used for onreadystatechange
#  @param on_load_fn            function to be called on succes, with parameters event, request
#  @param async                 request mode
#  @returns                     async == False: request object, async == True: None
#

def load(url, onreadystatechange=None, on_load_fn=None, async=False):
    setCompilerOptions("noDebug")
    wnd().status = ('Loading ' + url)
    req = createHttpRequest()

    if onreadystatechange is None:
        def onreadystatechange(evnt):
            if req.readyState==4 and (req.status == 200 or req.status == 0):
                str = req.responseText
                wnd().status = ('Loaded ' + url)
                if not on_load_fn is None:
                    on_load_fn(evnt, req)

    # next line is in JS() for IE6
    JS("@{{req}}['onreadystatechange'] = @{{onreadystatechange}};")
    req.open("GET", url , async)
    try:
        req.send(None)
        if async:
            return None
        while True:
            if (    req.status == 200
                 or (req.status == 0 and req.responseText)
               ):
                if not on_load_fn is None:
                    on_load_fn(None, req)
                return req
            if req.status != 0 or req.responseText != "":
                break
    except:
        pass
    raise AjaxError("Synchronous error", req.status)

def inject(values, namespace = None, names=None):
    if namespace is None:
        from __pyjamas__ import JS
        namespace = JS("$pyjs['global_namespace']")
    values = dict(values)
    if names is None:
        for k in values:
            v = values[k]
            JS("""@{{namespace}}[@{{k}}] = @{{v}};""")
    else:
        for k in names:
            v = values[k]
            JS("""@{{namespace}}[@{{k}}] = @{{v}};""")

#
#  activate_css(str)
#
#  looks for any < link > in the input and sets up a corresponding link node
#  in the main document.
#

def activate_css(targetnode):
    scriptnodes = list(targetnode.getElementsByTagName('link'))
    for LC in range(len(scriptnodes)):
        sn = scriptnodes[LC]
        sn.parentNode.removeChild(sn)

        fileref = DOM.createElement('link')

        if hassattr(sn, "href"):
            fileref.href = sn.href
        else:
            fileref.text = sn.text

        fileref.rel = "stylesheet"
        fileref.type = "text/css"

        doc().getElementsByTagName("head").item(0).appendChild(fileref)

#
#  activate_javascript(str)
#
#  looks for any < script > in the input text and sets up a corresponding
#  script node in the main document.
#

def activate_javascript(txt):
    fileref = DOM.createElement('script')

    fileref.text = txt
    fileref.type = "text/javascript"
    fileref.language = "javascript"
    #fileref.defer = True

    #debug = DOM.createElement('pre')
    #debug.innerHTML = 'test'
    #debug.innerHTML += "href:" + sn.src + " text:" + fileref.text
    #var bodyels = doc().getElementsByTagName("body")
    #bodyels[bodyels.length-1].appendChild(debug)

    fileref = fileref.cloneNode(True)

    doc().getElementsByTagName("head").item(0).appendChild(fileref)

def eval(str):
    from __javascript__ import eval
    return eval(str)

#
#  ajax_eval(url)
#
#  @param url   load and activate url
#  @returns     readyState
#

def ajax_eval(url, on_load_fn, async):
    setCompilerOptions("noDebug")
    def onready(evnt, req):
        str = req.responseText
        activate_javascript(str)
        if not on_load_fn is None:
            on_load_fn()

    load(url, None, onready, async)

__imported__ = {}
def ajax_import(url, namespace=None, names=None):
    setCompilerOptions("noDebug")
    if __imported__.has_key(url):
        module = __imported__[url]
    else:
        req = load(url, None, None, False)
        module = None
        name_getter = []
        if names is None:
            names = []
        for name in names:
            name_getter.append("$pyjs$moduleObject['%s'] = %s;" % (name, name))

        script = """(function ( ) {
$pyjs$moduleObject={};
%s;
%s
return $pyjs$moduleObject;
})();""" % (req.responseText, "\n".join(name_getter))
        try:
            module = eval(script)
        except:
            e = sys.exc_info()
            raise AjaxError("Error in %s: %s" % (url, e.message))
        __imported__[url] = module
    inject(module, namespace, names)


# From here, just converted from dynamicajax.js

#
#  pyjs_load_script
#
#  @param url      load script url
#  @param module   module name
#  @param onload   text of function to be eval/executed on successful load
#

def load_script(url, onload, async):
    wnd().status = ('Loading ' + url)

    def onload_fn():
        wnd().status = ('Loaded ' + url)
        if not onload is None:
            eval(onload)
        return True

    e = DOM.createElement("script")
    e.src = url
    e.type="text/javascript"
    e.language = "javascript"
    e.defer = async
    e.onload = onload_fn
    doc().getElementsByTagName("head")[0].appendChild(e)


#
#  ajax_dlink_refresh(oj,url)
#
#  @param id    id of element for insert
#  @param url   load url
#  @param timeout   refresh timeout period, ms
#  @returns     readyState
#

# use these to overrun an existing timeout, so that
# we don't end up with several of them!

running_timeout = 0
timeout_idname = None
timeout_url = None
timeout_on_load_fn = None
redo_timeout = None
timeout_id = None

def ajax_dlink_refresh(idname, url, on_load_fn, timeout):
    global running_timeout, timeout_idname, timeout_url, timeout_on_load_fn, redo_timeout, timeout_id
    timeout_idname = idname
    timeout_url = url
    timeout_on_load_fn = on_load_fn
    redo_timeout = timeout
    if running_timeout > 0:
        return
    # FIXME: should use pyjamas.Timer.Timer
    from __javascript__ import setTimeout
    timeout_id = setTimeout(do_ajax_dlink_refresh, timeout)
    running_timeout = 1


def do_ajax_dlink_refresh():
    global running_timeout, timeout_id
    if ajax_dlink(timeout_idname, timeout_url, timeout_on_load_fn) == 0:
        timeout_id = None
        running_timeout = 0
        return
    timeout_id = None
    running_timeout = 0
    ajax_dlink_refresh(timeout_idname, timeout_url, timeout_on_load_fn,
                       redo_timeout)


#
#  ajax_dlink(oj,url)
#
#  @param id    id of element for insert
#  @param url   load url
#  @returns     readyState
#

def ajax_dlink(idname, url, on_load_fn):
    global running_timeout, timeout_idname, timeout_url, timeout_on_load_fn, redo_timeout, timeout_id
    from __pyjamas__ import doc
    body = doc().body

    from __javascript__ import clearTimeout
    if timeout_id:
        clearTimeout(timeout_id) # really important - get into a mess otherwise

    def onreadystatechange():
        if xhtoj.readyState == 4:
            jsnode = 0
            if xhtoj.status == 200:
                txt = xhtoj.responseText

                jsnode = None

                if idname:
                    jsnode = DOM.getElementById(idname)

                if jsnode is None:
                    jsnode = DOM.createElement('script')

                #tst = DOM.createElement('html')
                #tst.innerHTML = str

                activate_javascript(txt)
                if not on_load_fn is None:
                    wnd().alert(on_load_fn)
                    # eval(on_load_fn)
                    test_fn()

                return 1
            else:
                jsnode = DOM.getElementById(idname)

                if not jsnode is None:
                    jsnode.innerHTML = xhtoj.status

    xhtoj = createHttpRequest()
    xhtoj.onreadystatechange = onreadystatechange
    xhtoj.open("GET", url , True )
    xhtoj.send("")

    return 0



