from pyjs import js

@js
class A:
    def __init__(self):
        self.text = "alpha"

@js
class B:
    def __init__(self):
        self.a = A()
        self.beta = "beta"

@js
class C:
    def __init__(self):
        self.b = B()
        self.ceta = "ceta"

@js
class D(C):
    def __init__(self):
        super().__init__()
        self.c = C()
        self.deta = "deta"


def main():
    d = D()
    print(d.deta)
    print(d.ceta)
    print(d.c.ceta)
    print(d.c.b.beta)
    print(d.c.b.a.text)
    print(d.b.a.text)
