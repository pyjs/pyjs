import sys
import re

tag_re = re.compile("<.*?>")

def write(text):
    pass

def writebr(text):
    pass


data = ""

def write_web(text):
    global data
    from __pyjamas__ import JS
    data += text
    JS(" $m['element']['innerHTML'] = $m['data']; ")

def writebr_web(text):
    write(text + "<br />\n")

def init_web():
    from __pyjamas__ import JS
    JS(""" $m['element'] = $doc['createElement']("div");
           $doc['body']['appendChild']($m['element']); """)

def write_std(text):
    text = tag_re.sub("",text)
    print text,

def writebr_std(text):
    text = tag_re.sub("",text)
    print text

if sys.platform in ['mozilla', 'ie6', 'opera', 'oldmoz', 'safari']:
    init_web()
    write = write_web
    writebr = writebr_web
else:
    write = write_std
    writebr = writebr_std
