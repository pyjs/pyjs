def kernel(size: int) -> int:
    text = "aé😀z" * size
    checksum = 0
    for character in text:
        if character == "a":
            checksum += 1
        elif character == "é":
            checksum += 2
        elif character == "😀":
            checksum += 3
        else:
            checksum += 4
    return checksum
