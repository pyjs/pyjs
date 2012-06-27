class RichTextAreaImplStandard (RichTextAreaImpl):

    def hookEvents(self):
        elem = self.elem;
        wnd = elem.contentWindow;

        JS("""
    var elem = @{{elem}};
    var wnd = @{{wnd}};

    elem['__gwt_handler'] = function(evt) {
      if (elem['__listener']) {
          @{{DOM.dispatchEvent}}(evt, elem, elem['__listener']);
        }
    };

    elem['__gwt_focusHandler'] = function(evt) {
      if (elem['__gwt_isFocused']) {
        return;
      }

      elem['__gwt_isFocused'] = true;
      elem['__gwt_handler'](evt);
    };

    elem['__gwt_blurHandler'] = function(evt) {
      if (!elem['__gwt_isFocused']) {
        return;
      }

      elem['__gwt_isFocused'] = false;
      elem['__gwt_handler'](evt);
    };

    wnd['addEventListener']('keydown', elem['__gwt_handler'], true);
    wnd['addEventListener']('keyup', elem['__gwt_handler'], true);
    wnd['addEventListener']('keypress', elem['__gwt_handler'], true);
    wnd['addEventListener']('mousedown', elem['__gwt_handler'], true);
    wnd['addEventListener']('mouseup', elem['__gwt_handler'], true);
    wnd['addEventListener']('mousemove', elem['__gwt_handler'], true);
    wnd['addEventListener']('mouseover', elem['__gwt_handler'], true);
    wnd['addEventListener']('mouseout', elem['__gwt_handler'], true);
    wnd['addEventListener']('click', elem['__gwt_handler'], true);

    wnd['addEventListener']('focus', elem['__gwt_focusHandler'], true);
    wnd['addEventListener']('blur', elem['__gwt_blurHandler'], true);
  """)

