// tests.cases.type_numbers
function main() {
  var a = 9;
  console.log(a);
  console.log((1 + 1));
  console.log((1 + (2 + 3)));
  var a = (a + 2);
  console.log(a);
  console.log((7 - 5));
  console.log(((7 - 5) - 1));
  console.log((7 - (5 - 1)));
  var a = (a - 5);
  console.log(a);
  console.log((2 * 3));
  console.log((0 * 3));
  var a = (a * 2);
  console.log(a);
  var a = 5;
  console.log((5 ** 2));
  var a = (a ** 2);
  console.log(a);
  console.log((5 / 2));
  console.log(Math.floor(5 / 2));
  var a = 5;
  var a = (a / 2);
  console.log(a);
  var a = 5;
  var a = Math.floor(a / 2);
  console.log(a);
  console.log(Number.isInteger(a));
  var a = 11;
  console.log(a);
  console.log(('0b'+(a).toString(2)));
  console.log(('0o'+(a).toString(8)));
  console.log(('0x'+(a).toString(16)));
}

