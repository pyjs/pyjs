export function main() {
    var a = 'foo';
    console.log(a);
    console.log([...a].length);
    a = a + 'bar';
    console.log(a);
    console.log(a + 'baz');
    console.log(('a: '+a));
}
