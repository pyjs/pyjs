const [size, loops, warmups, samples] = process.argv.slice(2).map(Number);
for (let i = 0; i < warmups + samples; i++) {
  const start = process.hrtime.bigint();
  const result = __pyjsEntry__.main(size, loops);
  const elapsed = process.hrtime.bigint() - start;
  console.log(i < warmups ? "warmup" : "sample", result, elapsed.toString());
}
