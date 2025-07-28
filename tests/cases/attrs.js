// tests.cases.attrs


class A {

    constructor() {
        this.text = 'alpha';
    }
}

class B {

    constructor() {
        this.a = new A();
        this.beta = 'beta';
    }
}

class C {

    constructor() {
        this.b = new B();
        this.ceta = 'ceta';
    }
}

class D extends C {

    constructor() {
        super();
        this.c = new C();
        this.deta = 'deta';
    }
}

function main() {
    var d = new D();
    console.log(d.deta);
    console.log(d.ceta);
    console.log(d.c.ceta);
    console.log(d.c.b.beta);
    console.log(d.c.b.a.text);
    console.log(d.b.a.text);
}
