from pyjamas.JSONService import JSONProxy
from pyjamas.HTTPRequest import HTTPRequest
from __pyjamas__ import JS

class PyjamasExternalProxy(JSONProxy):
    singleton = None

    def __init__(self):
        JSONProxy.__init__(self, "/obj/handler", ["call","methods"], True)

    @staticmethod
    def instance():
        if not PyjamasExternalProxy.singleton:
            PyjamasExternalProxy.singleton = PyjamasExternalProxy()
        return PyjamasExternalProxy.singleton


class PyjamasExternalModule:
    PyjamasExternalModule.http = HTTPRequest()

    def __init__(self, mod_name):
        self.base = 'http://'+JS('''__location['host']''')
        req = '{"method":"methods","params":["%s"],"id":1}'%(mod_name)
        res = PyjamasExternalModule.http.syncPost(self.base+'/obj/handler',req)
        self.methods = self.__parseJSON(res)['result']
        self.module = mod_name

        for method in self.methods:
            self.__createMethod(method)

    def __encodeJSON(self, obj):
        JS('''
        var t = typeof(@{{obj}});
        if(@{{obj}}==null) {
            return 'null';
        }else if(t=='number') {
            return ''+@{{obj}};
        }else if(t=='string'){
            return '"'+@{{obj}}+'"'
        }else if(@{{isinstance}}([@{{obj}},@{{list}}],{})) {
            var parts = [];
            for(var i=0; i<@{{obj}}['length']; i++) {
                parts['append']([ @{{self}}['__encodeJSON']([@{{obj}}[i]],{}) ],{});
            }
            return "[" + ','['join']([parts],{}) + "]";
        }else{
            throw "Dicts and Objectss can not be jsoned !";
        }
        ''')

    def __parseJSON(self, str):
        JS(r"""
        try {
            return (/^("(\\.|[^"\\\n\r])*?"|[,:{}\[\]0-9.\-+Eaeflnr-u \n\r\t])+?$/.test(@{{str}})) &&
                eval('(' + @{{str}} + ')');
        } catch (e) {
            return false;
        }
        """)

    def __createMethod(self, method):
        def inner(*args, **kargs):
            params = self.__encodeJSON(args)
            req = '{"method":"call","params":["%s", "%s", %s],"id":2}'%(self.module,method,params)
            res = PyjamasExternalModule.http.syncPost(self.base+'/obj/handler',req)
            return self.__parseJSON(res)['result']
        JS("""
        @{{self}}[@{{method}}] = @{{inner}};
        """)
