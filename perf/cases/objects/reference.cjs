class Record {
    constructor(value) {
        this.value = value;
        this.weight = value % 7;
    }
    score() { return this.value * this.weight; }
}

function kernel(size) {
    const records = [];
    for (let i = 0; i < size; i++) records.push(new Record(i));
    let checksum = 0;
    for (const record of records) checksum += record.score();
    return checksum;
}
