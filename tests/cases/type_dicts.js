// tests.cases.type_dicts
function main() {
  var empty = new Map([]);
  console.log(empty);
  var three = new Map([['one', 1], ['two', 2], ['three', 3]]);
  console.log(three);
  var dict_of_dicts = new Map([['one', new Map([['a', 1]])], ['two', new Map([['b', 2]])], ['three', new Map([['c', 3]])]]);
  console.log(dict_of_dicts);
  console.log(...dict_of_dicts.keys());
  console.log(...dict_of_dicts.values());
  console.log(...dict_of_dicts.entries());
  console.log(three.size);
  for (var [key, val] of dict_of_dicts.entries()) {
    for (var subkey of val) {
      console.log('item: '+key+' '+subkey+' '+val[subkey]);
    }
  }
}
