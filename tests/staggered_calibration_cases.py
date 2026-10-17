def heights() -> list[int]:
    return [20, 101, 38, 91, 22, 1100, 42, 80]


def outer_tops(columns: int) -> list[int]:
    if columns == 2:
        return [0, 20, 20, 72, 177, 199, 199, 255]
    return [0, 20, 20, 20, 135, 157, 157, 157]


def spans(columns: int) -> list[int]:
    if columns == 2:
        return [0, 0, 1, 1, 0, 0, 1, 1]
    return [0, 0, 1, 2, 0, 0, 1, 2]
