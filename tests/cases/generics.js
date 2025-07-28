class Counter__list__int:

    def __init__(items: list[int]):
        self.items = items

    def add(num: int):
        return len(self.items) + num

    def multiply(num: int):
        return len(self.items) * num

class Counter__dict__str_strUint:

    def __init__(items: dict[str, str | int]):
        self.items = items

    def add(num: int):
        return len(self.items) + num

    def multiply(num: int):
        return len(self.items) * num

def main():
    inferred_list: Counter[list[int]] = Counter__list__int([1, 2])
    print(inferred_list.add(3))
    explicit_list: Counter[list[int]] = Counter__list__int([])
    print(explicit_list.add(5))
    inferred_dict: Counter[dict[str, str | int]] = Counter__dict__str_strUint({'one': 'two', 'three': 4})
    print(inferred_dict.multiply(2))
    explicit_dict: Counter[dict[str, str | int]] = Counter__dict__str_strUint({})
    print(explicit_dict.multiply(4))
