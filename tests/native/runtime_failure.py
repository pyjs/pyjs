def reject_native_allocations(source):
    # Internal linkage confines fault injection to generated code: never
    # interpose on malloc in the Python process that loads a test library.
    # nobuiltin prevents folding realloc(NULL) or malloc + memset back into
    # an intercepted allocator, which would recurse when recovery is enabled.
    declaration = "declare noalias ptr @malloc(i64)"
    assert source.count(declaration) == 1
    # Collector-only modules do not otherwise need the replacement allocator
    # or zeroing intrinsic used by this confined fault-injection shim.
    for dependency in ("declare ptr @realloc(ptr, i64)",
                       "declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)"):
        if dependency not in source:
            source += "\n" + dependency
    calloc = ""
    calloc_declaration = "declare noalias ptr @calloc(i64, i64)"
    if calloc_declaration in source:
        source = source.replace(calloc_declaration, "")
        calloc = '''
            define internal ptr @calloc(i64 %count, i64 %size) {
            entry:
              %wide.count = zext i64 %count to i128
              %wide.size = zext i64 %size to i128
              %wide.total = mul i128 %wide.count, %wide.size
              %fits = icmp ule i128 %wide.total, 9223372036854775807
              br i1 %fits, label %allocate, label %failed
            allocate:
              %total = trunc i128 %wide.total to i64
              %memory = call ptr @malloc(i64 %total) nobuiltin
              %missing = icmp eq ptr %memory, null
              br i1 %missing, label %failed, label %clear
            clear:
              call void @llvm.memset.p0.i64(ptr %memory, i8 0, i64 %total, i1 false)
              ret ptr %memory
            failed:
              ret ptr null
            }
        '''
    return source.replace(declaration, calloc + '''
        @test_deny_allocations = global i1 true
        @test_allocation_attempts = global i64 0

        define internal ptr @malloc(i64 %size) {
        entry:
          %count = load i64, ptr @test_allocation_attempts
          %next = add i64 %count, 1
          store i64 %next, ptr @test_allocation_attempts
          %deny = load i1, ptr @test_deny_allocations
          br i1 %deny, label %failed, label %allocate
        allocate:
          %memory = call ptr @realloc(ptr null, i64 %size) nobuiltin
          ret ptr %memory
        failed:
          ret ptr null
        }
    ''')
