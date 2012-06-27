def init():
    JS("""
    // Check for existence of the history frame.
    var historyFrame = $doc['getElementById']('__pygwt_historyFrame');
    if (!historyFrame)
        return false;

    // Get the initial token from the url's hash component.
    var hash = $wnd['location']['hash'];
    if (hash['length'] > 0)
        $wnd['__historyToken'] = decodeURI(hash['substring'](1))['replace']("%23", "#");
    else
        $wnd['__historyToken'] = '';

    // Initialize the history iframe.  If '__historyToken' already exists, then
    // we're probably backing into the app, so _don't_ set the iframe's location.
    var tokenElement = null;
    if (historyFrame['contentWindow']) {
        var doc = historyFrame['contentWindow']['document'];
        tokenElement = doc ? doc['getElementById']('__historyToken') : null;
    }

    if (tokenElement)
        $wnd['__historyToken'] = tokenElement['value'];
    else
        historyFrame['src'] = 'history.html?' + encodeURI($wnd['__historyToken'])['replace']("#", "%23");

    // Create the timer that checks the browser's url hash every 1/4 s.
    $wnd['__checkHistory'] = function() {
        var token = '', hash = $wnd['location']['hash'];
        if (hash['length'] > 0)
            token = decodeURI(hash['substring'](1))['replace']("%23", "#");

        if (token != $wnd['__historyToken']) {
            $wnd['__historyToken'] = token;

            @{{newItem}}(token);
            @{{onHistoryChanged}}(token);
        }

        $wnd['setTimeout']('__checkHistory()', 250);
    };

    // Kick off the timer.
    $wnd['__checkHistory']();

    return true;
    """)


def newItem(historyToken):
    JS("""
    // Safari gets into a weird state (issue 2905) when setting the hash
    // component of the url to an empty string, but works fine as long as you
    // at least add a '#' to the end of the url. So we get around this by
    // recreating the url, rather than just setting location['hash'].

    $wnd['location'] = $wnd['location']['href']['split']('#')[0] + '#' +
                   encodeURI(@{{historyToken}})['replace']("#", "%23");

    """)

