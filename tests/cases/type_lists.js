// tests.cases.type_lists
function main() {
  var empty = [];
  console.log(empty);
  var ints = [1, 2, 3];
  console.log(ints);
  var strs = ['one', 'two', 'three'];
  console.log(strs);
  strs.push('str');
  console.log(strs);
  console.log(strs.pop());
  console.log(strs);
  strs.splice(2, 0, 'blah');
  console.log(strs);
  var both = ints.concat(strs);
  console.log(both);
  var list_of_lists = [empty, ints, strs];
  for (var item of list_of_lists) {
    for (var subitem of item) {
      console.log('item: '+subitem);
    }
  }
  console.log(empty.length);
  console.log(list_of_lists.length);
}

