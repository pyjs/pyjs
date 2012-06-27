def buttonClick(button):
    JS("""
        var doc = @{{button}}['ownerDocument'];
        if (doc != null) {
            var evt = doc['createEvent']('MouseEvents');
            evt['initMouseEvent']('click', true, true, null, 0, 0,
                                0, 0, 0, false, false, false, false, 0, null);
            @{{button}}['dispatchEvent'](evt);
        }
    """)

def compare(elem1, elem2):
    JS("""
    if (!@{{elem1}} && !@{{elem2}}) {
        return true;
    } else if (!@{{elem1}} || !@{{elem2}}) {
        return false;
    }
	if (!@{{elem1}}['isSameNode']) {
		return (@{{elem1}} == @{{elem2}});
	}
    return (@{{elem1}}['isSameNode'](@{{elem2}}));
    """)

def eventGetType(event):
    etype = event.type
    if etype == 'DOMMouseScroll':
        return 'mousewheel'
    return etype

def eventGetButton(evt):
    JS("""
    var button = @{{evt}}['which'];
    if(button == 2) {
        return 4;
    } else if (button == 3) {
        return 2;
    } else {
        return button || 0;
    }
    """)

# This is what is in GWT 1.5 for getAbsoluteLeft.  err...
#"""
#    // We cannot use DOMImpl here because offsetLeft/Top return erroneous
#    // values when overflow is not visible.  We have to difference screenX
#    // here due to a change in getBoxObjectFor which causes inconsistencies
#    // on whether the calculations are inside or outside of the element's
#    // border.
#    try {
#      return $doc.getBoxObjectFor(elem).screenX
#          - $doc.getBoxObjectFor($doc.documentElement).screenX;
#    } catch (e) {
#      // This works around a bug in the FF3 betas. The bug
#      // should be fixed before they release, so this can
#      // be removed at a later date.
#      // https://bugzilla.mozilla.org/show_bug.cgi?id=409111
#      // DOMException.WRONG_DOCUMENT_ERR == 4
#      if (e.code == 4) {
#        return 0;
#      }
#      throw e;
#    }
#"""
def getAbsoluteLeft(elem):
    JS("""
    // Firefox 3 expects getBoundingClientRect
    // getBoundingClientRect can be float: 73['1'] instead of 74, see
    // gwt's workaround at user/src/com/google/gwt/dom/client/DOMImplMozilla['java']:47
    // Please note, their implementation has 1px offset.
    if (   typeof @{{elem}}['getBoundingClientRect'] == 'function'  ) {
        var left = Math['ceil'](@{{elem}}['getBoundingClientRect']()['left']);

        return left  + $doc['body']['scrollLeft'] + $doc['documentElement']['scrollLeft'];
    }
    // Older Firefox can use getBoxObjectFor
    else {
        var left = $doc['getBoxObjectFor'](@{{elem}})['x'];
        var parent = @{{elem}}['parentNode'];
        while (parent) {
            if (parent['scrollLeft'] > 0) {
                left = left -  parent['scrollLeft'];
            }
            parent = parent['parentNode'];
        }

        return left + $doc['body']['scrollLeft'] + $doc['documentElement']['scrollLeft'];
    }
    """)

# This is what is in GWT 1.5 for getAbsoluteTop.  err...
#"""
#    // We cannot use DOMImpl here because offsetLeft/Top return erroneous
#    // values when overflow is not visible.  We have to difference screenY
#    // here due to a change in getBoxObjectFor which causes inconsistencies
#    // on whether the calculations are inside or outside of the element's
#    // border.
#    try {
#      return $doc.getBoxObjectFor(elem).screenY
#          - $doc.getBoxObjectFor($doc.documentElement).screenY;
#    } catch (e) {
#      // This works around a bug in the FF3 betas. The bug
#      // should be fixed before they release, so this can
#      // be removed at a later date.
#      // https://bugzilla.mozilla.org/show_bug.cgi?id=409111
#      // DOMException.WRONG_DOCUMENT_ERR == 4
#      if (e.code == 4) {
#        return 0;
#      }
#      throw e;
#    }
#"""
def getAbsoluteTop(elem):
    JS("""
    // Firefox 3 expects getBoundingClientRect
    if (   typeof @{{elem}}['getBoundingClientRect'] == 'function'  ) {
        var top = Math['ceil'](@{{elem}}['getBoundingClientRect']()['top']);
        return top + $doc['body']['scrollTop'] + $doc['documentElement']['scrollTop'];
    }
    // Older Firefox can use getBoxObjectFor
    else {
        var top = $doc['getBoxObjectFor'](@{{elem}})['y'];
        var parent = @{{elem}}['parentNode'];
        while (parent) {
            if (parent['scrollTop'] > 0) {
                top -= parent['scrollTop'];
            }
            parent = parent['parentNode'];
        }

        return top + $doc['body']['scrollTop'] + $doc['documentElement']['scrollTop'];
    }
    """)

def getChildIndex(parent, child):
    JS("""
    var count = 0, current = @{{parent}}['firstChild'];
    while (current) {
		if (! current['isSameNode']) {
			if (current == @{{child}}) {
			return count;
			}
		}
		else if (current['isSameNode'](@{{child}})) {
            return count;
        }
        if (current['nodeType'] == 1) {
            ++count;
        }
        current = current['nextSibling'];
    }
    return -1;
    """)

def isOrHasChild(parent, _child):
    JS("""
    var child = @{{_child}};
    while (child) {
        if ((!@{{parent}}['isSameNode'])) {
			if (@{{parent}} == child) {
				return true;
			}
		}
		else if (@{{parent}}['isSameNode'](child)) {
            return true;
        }
        try {
            child = child['parentNode'];
        } catch(e) {
          // Give up on 'Permission denied to get property
          // HTMLDivElement['parentNode']'
          // See https://bugzilla['mozilla']['org']/show_bug['cgi']?id=208427
          return false;
        }
        if (child && (child['nodeType'] != 1)) {
          child = null;
        }
      }
    return false;
    """)

def releaseCapture(elem):
    JS("""
    if ((@{{sCaptureElem}} != null) && @{{compare}}(@{{elem}}, @{{sCaptureElem}}))
        @{{sCaptureElem}} = null;

	if (!@{{elem}}['isSameNode']) {
		if (@{{elem}} == $wnd['__captureElem']) {
			$wnd['__captureElem'] = null;
		}
	}
	else if (@{{elem}}['isSameNode']($wnd['__captureElem'])) {
        $wnd['__captureElem'] = null;
    }
    """)

def eventGetMouseWheelVelocityY(evt):
    JS("""
    return @{{evt}}['detail'] || 0;
    """)

def sinkEventsMozilla(element, bits):
    JS("""
    if (@{{bits}} & 0x40000) {
        @{{element}}['addEventListener']("DOMMouseScroll", $wnd['__dispatchEvent'],
                                    false);
    } else {
        @{{element}}['removeEventListener']("DOMMouseScroll", $wnd['__dispatchEvent'],
                                    false);
    }
    if (@{{bits}} & 0x80000) {
        @{{element}}['addEventListener']("input", $wnd['__dispatchEvent'],
                                    false);
    } else {
        @{{element}}['removeEventListener']("input", $wnd['__dispatchEvent'],
                                    false);
    }
    """)
