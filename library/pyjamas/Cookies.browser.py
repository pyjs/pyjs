def getCookie(cookie_name):
	JS("""
	var results = document['cookie']['match'] ( '(^|;) ?' +
                        @{{cookie_name}} + '=([^;]*)(;|$)' );

	if ( results )
		return ( decodeURIComponent ( results[2] ) );
	else
		return null;

    """)

# expires can be int or Date
def setCookie(name, value, expires, domain=None, path=None, secure=False):
    JS("""
    if (@{{expires}} instanceof Date) @{{expires}} = @{{expires}}['getTime']();
    if (@{{isUndefined}}(@{{domain}})) @{{domain}} = null;
    if (@{{isUndefined}}(@{{path}})) @{{path}} = null;
    if (@{{isUndefined}}(@{{secure}})) @{{secure}} = false;

    var today = new Date();
    var expiration = new Date();
    if (!@{{expires}}) @{{expires}} = 0;
    expiration['setTime'](today['getTime']() + @{{expires}});

    var c = encodeURIComponent(@{{name}}) + '=' + encodeURIComponent(@{{value}});
    c += ';expires=' + expiration['toGMTString']();

    if (@{{domain}})
        c += ';domain=' + @{{domain}};
    if (@{{path}})
        c += ';path=' + @{{path}};
    if (@{{secure}})
        c += ';secure';

    $doc['cookie'] = c;
    """)

def loadCookies():
    JS("""
    var cookies = {};

    var docCookie = $doc['cookie'];

    if (docCookie && docCookie != '') {
        var crumbs = docCookie['split'](';');
        for (var i = 0; i < crumbs['length']; ++i) {
			alert(crumbs['length']);
            var name, value;

            var eqIdx = crumbs[i]['indexOf']('=');
            if (eqIdx == -1) {
                name = crumbs[i];
                value = '';
            } else {
                name = crumbs[i]['substring'](0, eqIdx);
                value = crumbs[i]['substring'](eqIdx + 1);
            }

			alert(name);
			alert(value);

        cookies[decodeURIComponent(name)] = decodeURIComponent(value);
        }
    }

    return cookies;
    """)
