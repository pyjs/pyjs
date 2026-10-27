class Record:
    def __init__(self, value: int):
        self.value = value
        self.weight = value % 7

    def score(self) -> int:
        return self.value * self.weight


def kernel(size: int) -> int:
    records: list[Record] = []
    for i in range(size):
        records.append(Record(i))
    checksum = 0
    for record in records:
        checksum += record.score()
    return checksum
