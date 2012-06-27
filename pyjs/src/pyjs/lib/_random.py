from __pyjamas__ import JS

one = long(1)

class Random(object):
    seed = None

    def getrandbits(self, k):
        s = ""
        JS("""
        var table = new Array();
        for (var i = 0 ; i < @{{k}}/32; i++) {
            table[i] = (Math['random']() * 4294967296)['toString'](32);
        }
        @{{s}} = table['join']("");
""")
        rand = long(s, 32)
        mask = one.__lshift__(k).__sub__(one)
        return rand.__and__(mask)

    def getstate(self):
        raise NotImplementedError("getstate")

    def jumpahead(self, n):
        JS("""
        for (var i = 0 ; i < @{{n}} % 100; i++) Math['random']();
""")

    def random(self):
        if self.seed is None:
            return JS("Math['random']()")
        seed = self.seed
        self.seed = None
        return JS("Math['random'](@{{seed}})")

    def seed(self, n = None):
        self.seed = n

    def setstate(self, state):
        raise NotImplementedError("setstate")
