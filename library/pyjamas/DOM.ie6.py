# Copyright (C) 2006 James Tauber and contributors
# Copyright (C) 2009, 2010, 2012 Luke Kenneth Casson Leighton <lkcl@lkcl.net>
# Copyright (C) 2011 Rasiel@fliper.cc

def init():
    JS("""
    // Set up event dispatchers.
    $wnd['__dispatchEvent'] = function() {
        if ($wnd['event']['returnValue'] == null) {
            $wnd['event']['returnValue'] = true;
            if (!@{{previewEvent}}($wnd['event']))
                return;
        }

        var listener, curElem = this;
        while (curElem && !(listener = curElem['__listener']))
            curElem = curElem['parentElement'];

        if (listener)
            @{{dispatchEvent}}($wnd['event'], curElem, listener);
    };

    $wnd['__dispatchDblClickEvent'] = function() {
        var newEvent = $doc['createEventObject']();
        this['fireEvent']('onclick', newEvent);
        if (this['__eventBits'] & 2)
            $wnd['__dispatchEvent']['call'](this);
    };

    $doc['body']['onclick']       =
    $doc['body']['onmousedown']   =
    $doc['body']['onmouseup']     =
    $doc['body']['onmousemove']   =
    $doc['body']['onkeydown']     =
    $doc['body']['onkeypress']    =
    $doc['body']['onkeyup']       =
    $doc['body']['onfocus']       =
    $doc['body']['onblur']        =
    $doc['body']['onselectstart'] =
    $doc['body']['ondblclick']    = $wnd['__dispatchEvent'];
    """)

def compare(elem1, elem2):
    JS("""
    if (!@{{elem1}} && !@{{elem2}})
        return true;
    else if (!@{{elem1}} || !@{{elem2}})
        return false;
    return (@{{elem1}}['uniqueID'] == @{{elem2}}['uniqueID']);
    """)

def createInputRadio(group):
    JS("""
    ua = navigator['userAgent']['toLowerCase']();
    if (ua['indexOf']('msie 9['0']') != -1) {
        var elem = $doc['createElement']("INPUT");
        elem['type'] = 'radio';
        elem['name'] = @{{group}};
        return elem
    }

    return $doc['createElement']("<INPUT type='RADIO' name='" + @{{group}} + "'>");
    """)

def eventGetType(event):
    etype = event.type
    if etype == 'propertychange':
        return 'input'
    return etype

def eventGetCurrentTarget(event):
    return event.currentEventTarget

def eventGetTarget(evt):
    JS("""
    var elem = @{{evt}}['srcElement'];
    return elem ? elem : null;
    """)

def eventGetToElement(evt):
    JS("""
    return @{{evt}}['toElement'] ? @{{evt}}['toElement'] : null;
    """)

def eventPreventDefault(evt):
    JS("""
    @{{evt}}['returnValue'] = false;
    """)

def eventToString(evt):
    JS("""
    if (@{{evt}}['toString']) return @{{evt}}['toString']();
    return "[object Event]";
    """)

def getBodyOffsetTop():
    JS("""
    return $doc['body']['parentElement']['clientTop'];
    """)

def getBodyOffsetLeft():
    JS("""
    return $doc['body']['parentElement']['clientLeft'];
    """)

def getAbsoluteLeft(elem):
    JS("""
    // getBoundingClientRect() throws a JS exception if the elem is not attached
    // to the document, so we wrap it in a try/catch block
    var zoomMultiple = $doc['body']['parentElement']['offsetWidth'] /
                       $doc['body']['offsetWidth'];
    try {
        return Math['floor']((@{{elem}}['getBoundingClientRect']()['left'] / zoomMultiple) +
                            $doc['body']['parentElement']['scrollLeft'] );
    } catch (e) {
        return 0;
    }
    """)

def getAbsoluteTop(elem):
    JS("""
    // getBoundingClientRect() throws a JS exception if the elem is not attached
    // to the document, so we wrap it in a try/catch block
    var zoomMultiple = $doc['body']['parentElement']['offsetWidth'] /
                       $doc['body']['offsetWidth'];
    try {
        var scrollTop = $doc['parent'] ? $doc['parent']['body']['scrollTop'] : 0;
        scrollTop += $doc['body']['scrollTop'];
        return Math['floor']((@{{elem}}['getBoundingClientRect']()['top'] / zoomMultiple) +
                            scrollTop);
    } catch (e) {
        return 0;
    }
    """)


def getChild(elem, index):
    JS("""
    var child = @{{elem}}['children'][@{{index}}];
    return child ? child : null;
    """)

def getChildCount(elem):
    JS("""
    return @{{elem}}['children']['length'];
    """)

def getChildIndex(parent, child):
    JS("""
    var count = @{{parent}}['children']['length'];
    for (var i = 0; i < count; ++i) {
        if (@{{child}}['uniqueID'] == @{{parent}}['children'][i]['uniqueID'])
            return i;
    }
    return -1;
    """)

def getFirstChild(elem):
    JS("""
    var child = @{{elem}}['firstChild'];
    return child ? child : null;
    """)

def getInnerText(elem):
    JS("""
    var ret = @{{elem}}['innerText'];
    return (ret == null) ? null : ret;
    """)

def getNextSibling(elem):
    JS("""
    var sib = @{{elem}}['nextSibling'];
    return sib ? sib : null;
    """)

def getParent(elem):
    JS("""
    var parent = @{{elem}}['parentElement'];
    return parent ? parent : null;
    """)

def insertChild(parent, child, index):
    JS("""
    if (@{{index}} == @{{parent}}['children']['length'])
        @{{parent}}['appendChild'](@{{child}});
    else
        @{{parent}}['insertBefore'](@{{child}}, @{{parent}}['children'][@{{index}}]);
    """)

def insertListItem(select, text, value, index):
    JS("""
    var newOption = document['createElement']("Option");
    if(@{{index}}==-1) {
        @{{select}}['add'](newOption);
    } else {
        @{{select}}['add'](newOption,@{{index}});
    }
    newOption['text']=@{{text}};
    newOption['value']=@{{value}};
    """)

def isOrHasChild(parent, _child):
    JS("""
    var child = @{{_child}};
    while (child) {
        if (@{{parent}}['uniqueID'] == child['uniqueID'])
            return true;
        child = child['parentElement'];
    }
    return false;
    """)

def releaseCapture_impl(elem):
    JS("""
    @{{elem}}['releaseCapture']();
    """)

def setCapture_impl(elem):
    JS("""
    @{{elem}}['setCapture']();
    """)

def setInnerText(elem, text):
    JS("""
    if (!@{{text}})
        @{{elem}}['innerText'] = '';
    else
        @{{elem}}['innerText'] = @{{text}};
    """)

def toString(elem):
    JS("""
    return @{{elem}}['outerHTML'];
    """)

def eventStopPropagation(evt):
    eventCancelBubble(evt,True)

def eventGetMouseWheelVelocityY(evt):
    JS("""
    return Math['round'](-@{{evt}}['wheelDelta'] / 40) || 0;
    """)
