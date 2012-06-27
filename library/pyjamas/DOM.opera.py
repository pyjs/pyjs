def eventGetButton(evt):
    JS("""
    var button = @{{evt}}['button'];
    if(button == 0){
        return 1;
    } else {
        return button;
    }
    """)
def getAbsoluteLeft(_elem):
    JS("""
    var left = 0;
    var elem = @{{_elem}};
    var curr = elem['parentNode'];
    // This intentionally excludes body
    while (curr && curr != $doc['body']) {

      // see https://bugs['opera']['com']/show_bug['cgi']?id=249965
      // The net effect is that TR and TBODY elemnts report the scroll offsets
      // of the BODY and HTML elements instead of 0.
      if (curr['tagName'] != 'TR' && curr['tagName'] != 'TBODY') {
        left -= curr['scrollLeft'];
      }
      curr = curr['parentNode'];
    }

    while (elem) {
      left += elem['offsetLeft'];
      elem = elem['offsetParent'];
    }
    return left;
    """)

def getAbsoluteTop(_elem):
    JS("""
    var top = 0;
    var elem = @{{_elem}};

    // This intentionally excludes body
    var curr = elem['parentNode'];
    while (curr && curr != $doc['body']) {
      // see getAbsoluteLeft()
      if (curr['tagName'] != 'TR' && curr['tagName'] != 'TBODY') {
        top -= curr['scrollTop'];
      }
      curr = curr['parentNode'];
    }

    while (elem) {
      top += elem['offsetTop'];
      elem = elem['offsetParent'];
    }
    return top;
    """)

def eventGetMouseWheelVelocityY(evt):
    JS("""
    return @{{evt}}['detail'] * 4 || 0;
    """)

