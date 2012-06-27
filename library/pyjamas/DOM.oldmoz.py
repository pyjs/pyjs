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

def eventGetButton(evt):
    JS("""
    var button = @{{evt}}['button'];
    if(button == 0) {
        return 1;
    } else if (button == 1) {
        return 4;
    } else {
        return button;
    }
    """)

def getAbsoluteLeft(_elem):
    JS("""
    var left = 0;
    var elem = @{{_elem}};
    var parent = elem;

    while (parent) {
        if (parent['scrollLeft'] > 0) {
            left = left -  parent['scrollLeft'];
        }
        parent = parent['parentNode'];
    }
    while (elem) {
        left = left + elem['offsetLeft'];
        elem = elem['offsetParent'];
    }

    return left + $doc['body']['scrollLeft'] + $doc['documentElement']['scrollLeft'];
    """)

def getAbsoluteTop(_elem):
    JS("""
    var top = 0;
    var elem = @{{_elem}};
    var parent = elem;
    while (parent) {
        if (parent['scrollTop'] > 0) {
            top -= parent['scrollTop'];
        }
        parent = parent['parentNode'];
    }

    while (elem) {
        top += elem['offsetTop'];
        elem = elem['offsetParent'];
    }
    return top + $doc['body']['scrollTop'] + $doc['documentElement']['scrollTop'];
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
