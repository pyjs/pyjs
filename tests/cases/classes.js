// tests.cases.classes
const global_hello = 'hello';
class Base {
  static MULTIPLIER = 2;
  static static_value = 'hello world!';
  constructor(base_number) {
    var local_number = 9;
    this._number = (base_number * Base.MULTIPLIER);
    this.things = [global_hello, local_number, Base.static_value, this._number];
    console.log('Base.__init__');
    console.log(this.things);
  }

  action() {
    console.log('Base.action: '+this._number);
    console.log('Base.action: '+Base.MULTIPLIER);
  }

  static class_action() {
    console.log('Base.class_action: '+Base.MULTIPLIER);
  }

  static static_action() {
    console.log('Base.static_action: '+Base.MULTIPLIER);
  }

}


function make_base() {
  return new Base();
}

class SubClass extends Base {
  static FORTY = 'forty';
  constructor(two) {
    super();
    this.word = (SubClass.FORTY + two);
    this.base = make_base();
    console.log('SubClass.__init__');
  }

  do_things() {
    if (this.base.things.length) {
      if ((this.base.things.length > 1)) {
        console.log('more than 1');
      }
      console.log(this.base.things[0]);
    } else {
      console.log('nothing');
    }
  }

  action() {
    super.action();
    console.log('SubClass.action: '+this.word);
    console.log('SubClass.action: '+this._number);
    console.log('SubClass.action: '+SubClass.FORTY);
    console.log('SubClass.action: '+Base.MULTIPLIER);
  }

  static class_action() {
    super.class_action();
    SubClass.static_action();
    console.log('SubClass.class_action: '+SubClass.FORTY);
    console.log('SubClass.class_action: '+Base.MULTIPLIER);
  }

  static static_action() {
    Base.static_action();
    console.log('SubClass.static_action: '+SubClass.FORTY);
    console.log('SubClass.static_action: '+Base.MULTIPLIER);
  }

}


function main() {
  console.log('Base:');
  var b = new Base();
  b.action();
  Base.class_action();
  Base.static_action();
  console.log('SubClass:');
  var sc = new SubClass('two');
  sc.do_things();
  sc.action();
  SubClass.class_action();
  SubClass.static_action();
  Base.static_action();
}

