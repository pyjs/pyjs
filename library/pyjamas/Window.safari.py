def getDocumentRoot():
    # Safari does not implement $doc.compatMode.
    # Use a CSS test to determine rendering mode.
    JS("""
        var elem = $doc['createElement']('div');
        elem['style']['cssText'] = "width:0px;width:1";
        return parseInt(elem['style']['width']) != 1 ? $doc['documentElement'] :
                                                 $doc['body'];
        """)
