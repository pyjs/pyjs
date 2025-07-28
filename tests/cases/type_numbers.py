def main():
    a = 9; print(a)

    # add
    print(1 + 1)
    print(1 + (2 + 3))
    a += 2; print(a)

    # sub
    print(7 - 5)
    print(7 - 5 - 1)
    print(7 - (5 - 1))
    a -= 5; print(a)

    # mult
    print(2 * 3)
    print(0 * 3)
    a *= 2; print(a)

    # pow
    a = 5
    print(5 ** 2)
    a **= 2; print(a)

    # div
    print(5 / 2)
    print(5 // 2)
    a = 5
    a /= 2; print(a)
    a = 5
    a //= 2; print(a)
    print(isinstance(a, int))

    # TODO:
    # JavaScript only has Number type,
    # need to find ergonomic way to replicate
    # python int vs float behavior in JS
    #print(6 / 3)

    # TODO:
    # JavaScript returns Infinite without exception
    #try:
    #    1/0
    #except ZeroDivisionError:
    #    print("zero division error")

    # functions
    a = 11
    print(a)
    print(bin(a))
    print(oct(a))
    print(hex(a))
