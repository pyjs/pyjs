data = ""
global element

from __pyjamas__ import doc

def escape(s):
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    return s

def display_log_output():
    global element
    global data
    element = doc().createElement("div")
    doc().body.appendChild(element)
    element.innerHTML = data

def write(text, do_escape=True):
    global data
    if do_escape:
        text = escape(text)
    data += text

    print "data", data

def writebr(text, do_escape=True):
    write(text + "<br />\n", do_escape)

write_web=writebr
