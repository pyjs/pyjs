
def toString(elem):
    # need to override because safari does not like '' as inner
    # html. just leave it out so far, don't know what this should do
    # anyways
    JS("""
    var temp = @{{elem}}['cloneNode'](true);
    var tempDiv = $doc['createElement']("DIV");
    tempDiv['appendChild'](temp);
    var outer = tempDiv['innerHTML'];
    //temp['innerHTML'] = " ";
    return outer;
    """)

def getAbsoluteLeft(_elem):
    JS("""
    // Unattached elements and elements (or their ancestors) with style
    // 'display: none' have no offsetLeft.
    var elem = @{{_elem}};
    if (elem['offsetLeft'] == null) {
      return 0;
    }

    var left = 0;
    var curr = elem['parentNode'];
    if (curr) {
      // This intentionally excludes body which has a null offsetParent.
      while (curr['offsetParent']) {
        left -= curr['scrollLeft'];
        curr = curr['parentNode'];
      }
    }

    while (elem) {
      left += elem['offsetLeft'];

      // Safari bug: a top-level absolutely positioned element includes the
      // body's offset position already.
      var parent = elem['offsetParent'];
      if (parent && (parent['tagName'] == 'BODY') &&
          (elem['style']['position'] == 'absolute')) {
        break;
      }

      elem = parent;
    }
    return left;
    """)

def getAbsoluteTop(_elem):
    JS("""
    // Unattached elements and elements (or their ancestors) with style
    // 'display: none' have no offsetTop.
    var elem = @{{_elem}};
    if (elem['offsetTop'] == null) {
      return 0;
    }

    var top = 0;
    var curr = elem['parentNode'];
    if (curr) {
      // This intentionally excludes body which has a null offsetParent.
      while (curr['offsetParent']) {
        top -= curr['scrollTop'];
        curr = curr['parentNode'];
      }
    }

    while (elem) {
      top += elem['offsetTop'];

      // Safari bug: a top-level absolutely positioned element includes the
      // body's offset position already.
      var parent = elem['offsetParent'];
      if (parent && (parent['tagName'] == 'BODY') &&
          (elem['style']['position'] == 'absolute')) {
        break;
      }

      elem = parent;
    }
    return top;
    """)

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

def buttonClick(elem):
    JS("""
        var evt = $doc['createEvent']('MouseEvents');
        evt['initMouseEvent']('click', true, true, null, 1, 0,
                    0, 0, 0, false, false, false, false, 0, null);

        @{{elem}}['dispatchEvent'](evt);
    """)

def eventGetMouseWheelVelocityY(evt):
    JS("""
    return Math['round'](-@{{evt}}['wheelDelta'] / 40) || 0;
    """)


