def main():
    # bools are ints
    print(False + 1)
    print(1 + False)
    print(True - 1)
    print(1 - True)
    print(False + False)
    print(True + True)
    print(True + False)
    print(True * 3)
    print((False+1) * 3)

    # truth is truthy
    print(True is True)
    print(False is False)
    print(True == True)
    print(True == 1)
    print(True is bool(1))
    print(False == False)
    print(False == 0)
    print(False is bool(0))
    print(True != False)
    print(True is not False)
    print(False is not True)

    a = False
    print(a)
    print(bin(a))
    print(oct(a))
    print(hex(a))

    a = True
    print(a)
    print(bin(a))
    print(oct(a))
    print(hex(a))

    if a:
        print("a is true")

    if not a:
        print("should not print")
    else:
        print("else a is true")
