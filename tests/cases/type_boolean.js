// tests.cases.type_boolean
function main() {
  console.log((false + 1));
  console.log((1 + false));
  console.log((true - 1));
  console.log((1 - true));
  console.log((false + false));
  console.log((true + true));
  console.log((true + false));
  console.log((true * 3));
  console.log(((false + 1) * 3));
  console.log((true === true));
  console.log((false === false));
  console.log((true === true));
  console.log((true === 1));
  console.log((true === Boolean(1)));
  console.log((false === false));
  console.log((false === 0));
  console.log((false === Boolean(0)));
  console.log((true !== false));
  console.log((true !== false));
  console.log((false !== true));
  var a = false;
  console.log(a);
  console.log(('0b'+(a).toString(2)));
  console.log(('0o'+(a).toString(8)));
  console.log(('0x'+(a).toString(16)));
  var a = true;
  console.log(a);
  console.log(('0b'+(a).toString(2)));
  console.log(('0o'+(a).toString(8)));
  console.log(('0x'+(a).toString(16)));
  if (a) {
    console.log('a is true');
  }
  if (!a) {
    console.log('should not print');
  } else {
    console.log('else a is true');
  }
}

