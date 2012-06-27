class HTTPRequest(object):

    def doCreateXmlHTTPRequest(self):
        return JS("""new ActiveXObject("Msxml2['XMLHTTP']")""")

