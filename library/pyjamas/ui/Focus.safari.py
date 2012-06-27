# FocusImplOld

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
    input['tabIndex'] = -1;
    input['style']['opacity'] = 0;
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

def blur(elem):
    JS("""
    // Attempts to blur elements from within an event callback will
    // generally be unsuccessful, so we invoke blur() from outside of
    // the callback.
    $wnd['setTimeout'](function() {
                                   @{{elem}}['blur']();
                    },
                    0);
    """)

def focus(elem):
    JS("""
    // Attempts to focus elements from within an event callback will
    // generally be unsuccessful, so we invoke focus() from outside of
    // the callback.
    $wnd['setTimeout'](function() {
                                   @{{elem}}['focus']();
                    },
                    0);
    """)

