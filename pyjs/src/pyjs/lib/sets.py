from __pyjamas__ import JS, INT

class Set:
    def __init__(self, data=None):
        JS("""
        @{{self}}['__object'] = {};
        @{{self}}['update'](@{{data}});
        """)

    def add(self, value):
        JS("""    @{{self}}['__object'][pyjslib['hash'](@{{value}})] = @{{value}};""")

    def clear(self):
        JS("""    @{{self}}['__object'] = {};""")

    def __contains__(self, value):
        JS("""    return (@{{self}}['__object'][pyjslib['hash'](@{{value}})]) ? true : false;""")

    def discard(self, value):
        JS("""    delete @{{self}}['__object'][pyjslib['hash'](@{{value}})];""")

    def issubset(self, items):
        JS("""
        for (var i in @{{self}}['__object']) {
            if (!@{{items}}['__contains__'](i)) return false;
            }
        return true;
        """)

    def issuperset(self, items):
        JS("""
        for (var i in @{{items}}) {
            if (!@{{self}}['__contains__'](i)) return false;
            }
        return true;
        """)

    def __iter__(self):
        JS("""
        var items=new pyjslib['list']();
        for (var key in @{{self}}['__object']) items['append'](@{{self}}['__object'][key]);
        return items['__iter__']();
        """)

    def __len__(self):
        size=0
        JS("""
        for (var i in @{{self}}['__object']) @{{size}}++;
        """)
        return INT(size)

    def pop(self):
        JS("""
        for (var key in @{{self}}['__object']) {
            var value = @{{self}}['__object'][key];
            delete @{{self}}['__object'][key];
            return value;
            }
        """)

    def remove(self, value):
        self.discard(value)

    def update(self, data):
        JS("""
        if (pyjslib['isArray'](@{{data}})) {
            for (var i in @{{data}}) {
                @{{self}}['__object'][pyjslib['hash'](@{{data}}[i])]=@{{data}}[i];
            }
        }
        else if (pyjslib['isIteratable'](@{{data}})) {
            var iter=@{{data}}['__iter__']();
            var i=0;
            try {
                while (true) {
                    var item=iter['next']();
                    @{{self}}['__object'][pyjslib['hash'](item)]=item;
                }
            }
            catch (e) {
                if (e != pyjslib['StopIteration']) throw e;
            }
        }
        """)
