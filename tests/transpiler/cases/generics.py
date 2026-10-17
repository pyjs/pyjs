from pyjs import js

@js
class Counter[T]:
    def __init__(self, items: T):
        self.items = items

    def add(self, num: int):
        return len(self.items) + num

    def multiply(self, num: int):
        return len(self.items) * num


def main():
    inferred_list = Counter([1,2])
    print(inferred_list.add(3))
    explicit_list = Counter[list[int]]([])
    print(explicit_list.add(5))
    inferred_dict = Counter({"one": "two", "three": 4})
    print(inferred_dict.multiply(2))
    explicit_dict = Counter[dict[str,str|int]]({})
    print(explicit_dict.multiply(4))