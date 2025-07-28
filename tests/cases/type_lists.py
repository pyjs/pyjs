def main():
    empty = []
    print(empty)
    ints = [1, 2, 3]
    print(ints)
    strs = ["one", "two", "three"]
    print(strs)

    strs.append('str')
    print(strs)

    print(strs.pop())
    print(strs)

    strs.insert(2, "blah")
    print(strs)

    both = ints + strs
    print(both)

    list_of_lists = [empty, ints, strs]

    for item in list_of_lists:
        for subitem in item:
            print(f"item: {subitem}")

    print(len(empty))
    print(len(list_of_lists))
