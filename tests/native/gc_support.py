"""Observe real heap allocations at compiled collection points, not pin counts."""

from pyjs import llvm


@llvm.inline("load i64, ptr @test.live")
def live() -> int:
    raise RuntimeError("live counts require the instrumented native collector")


def observe_collections(source: str) -> str:
    call = "call i1 @pyjs.gc.try.collect("
    assert call in source, "collector observer must intercept the current runtime ABI"
    return source.replace(call, "call i1 @test.collect(") + '''
@test.live = private global i64 0
define private i1 @test.collect(ptr %heap) {
  %success = call i1 @pyjs.gc.try.collect(ptr %heap)
  %field = getelementptr %pyjs.gc, ptr %heap, i32 0, i32 3
  %count = load i64, ptr %field
  store i64 %count, ptr @test.live
  ret i1 %success
}
'''
