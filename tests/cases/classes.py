from pyjs import js

global_hello = "hello"
global_world = global_hello + " world"

@js
class Pass:
    pass

@js
class Base:

    MULTIPLIER = 2
    static_value = global_world + "!"

    def __init__(self, base_number=21):
        local_number = 9
        self._number = base_number * self.MULTIPLIER
        self.things = [
            global_hello,
            local_number,
            self.static_value,
            self._number,
            "thing"
        ]
        print("Base.__init__")
        print(self.things)

    def action(self):
        print(f"Base.action: {self._number}")
        print(f"Base.action: {self.MULTIPLIER}")

    @classmethod
    def class_action(cls):
        print(f"Base.class_action: {cls.MULTIPLIER}")

    @staticmethod
    def static_action():
        print(f"Base.static_action: {Base.MULTIPLIER}")

    def add_thing(self, thing: str):
        self.things.append(thing)
        return self

#    @property
#    def number(self):
#        return self._number
#
#    @number.setter
#    def number(self, number):
#        self._number = number

@js
def make_base():
    return Base()


@js
class SubClass(Base):
    FORTY = "forty"

    def __init__(self, two: str):
        super().__init__()
        self.word = self.FORTY + two
        self.base = make_base()
        print("SubClass.__init__")

    def do_things(self):
        if self.base.things:
            if len(self.base.things) > 1:
                print("more than 1")
            print(self.base.things[0])
        else:
            print("nothing")

    def action(self):
        super().action()
        print(f"SubClass.action: {self.word}")
        print(f"SubClass.action: {self._number}")
        print(f"SubClass.action: {self.FORTY}")
        print(f"SubClass.action: {self.MULTIPLIER}")

    @classmethod
    def class_action(cls):
        super().class_action()
        cls.static_action()
        print(f"SubClass.class_action: {cls.FORTY}")
        print(f"SubClass.class_action: {cls.MULTIPLIER}")

    @staticmethod
    def static_action():
        Base.static_action()
        print(f"SubClass.static_action: {SubClass.FORTY}")
        print(f"SubClass.static_action: {SubClass.MULTIPLIER}")


def main():
    print("Base:")
    b = Base()
    b.action()
    b.class_action()
    b.static_action()

    print("SubClass:")
    sc = SubClass("two")
    sc.do_things()
    sc.action()
    sc.class_action()
    sc.static_action()
    sc.base.static_action()
