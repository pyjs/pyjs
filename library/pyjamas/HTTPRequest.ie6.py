class HTTPRequest(object):

    def doCreateXmlHTTPRequest(self):
        try:
            return JS("""new ActiveXObject("Msxml2['XMLHTTP']")""")
        except:
            try:
                return JS("""new ActiveXObject("Microsoft.XMLHTTP")""")
            except:
                return JS("""new window.XMLHttpRequest()""")

