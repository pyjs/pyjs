
def ensureFocusHandler():
    JS("""
    return (focusHandler !== null) ? focusHandler : (focusHandler =
            @{{createFocusHandler}}());
    """)

def createFocusHandler():
    JS("""
    return function(evt) {
      // This function is called directly as an event handler, so 'this' is
      // set up by the browser to be the input on which the event is fired. We
      // call focus() in a timeout or the element may be blurred when this event
      // ends.
      var div = this['parentNode'];
      if (div['onfocus']) {
        $wnd['setTimeout'](function() {
          div['focus']();
        }, 0);
      }
    };
    """)

def createFocusable0(focusHandler):
    JS("""
    var div = $doc['createElement']('div');
    div['tabIndex'] = 0;

    var input = $doc['createElement']('input');
    input['type'] = 'text';
    input['style']['opacity'] = 0;
    input['tabIndex'] = -1;
    input['style']['zIndex'] = -1;
    input['style']['width'] = '1px';
    input['style']['height'] = '1px';
    input['style']['overflow'] = 'hidden';
    input['style']['position'] = 'absolute';

    input['addEventListener']( 'focus', focusHandler, false);

    div['appendChild'](input);
    return div;
    """)

def createFocusable():
    return createFocusable0(ensureFocusHandler())

