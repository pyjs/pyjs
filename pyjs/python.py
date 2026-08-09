from pyjs import js


@js(inline="{values}.splice({start}, {delete_count}, ...{replacement})")
def splice(
    values: list[object],
    start: int,
    delete_count: int,
    replacement: list[object],
) -> None: ...


@js(inline="{mapping}.delete({key})")
def delete_mapping_item(mapping: dict[object, object], key: object) -> None: ...


@js(
    inline=(
        "typeof {key} === 'string' ? \"'\" + {key} + \"'\" : String({key})"
    )
)
def key_error_message(key: object) -> str:
    return repr(key)


@js
def slice_indices(
    length: int,
    start: int | None,
    stop: int | None,
    step: int | None,
) -> list[int]:
    actual_step = 1 if step is None else step
    if actual_step == 0:
        raise ValueError("slice step cannot be zero")
    forward = actual_step > 0

    if start is None:
        actual_start = 0 if forward else length - 1
    else:
        actual_start = start
        if actual_start < 0:
            actual_start += length
        if forward:
            if actual_start < 0:
                actual_start = 0
            elif actual_start > length:
                actual_start = length
        elif actual_start < -1:
            actual_start = -1
        elif actual_start >= length:
            actual_start = length - 1

    if stop is None:
        actual_stop = length if forward else -1
    else:
        actual_stop = stop
        if actual_stop < 0:
            actual_stop += length
        if forward:
            if actual_stop < 0:
                actual_stop = 0
            elif actual_stop > length:
                actual_stop = length
        elif actual_stop < -1:
            actual_stop = -1
        elif actual_stop >= length:
            actual_stop = length - 1

    return [actual_start, actual_stop, actual_step]


@js
def slice_list(
    values: list[object],
    start: int | None,
    stop: int | None,
    step: int | None,
) -> list[object]:
    bounds = slice_indices(len(values), start, stop, step)
    result: list[object] = []
    index = bounds[0]
    while index < bounds[1] if bounds[2] > 0 else index > bounds[1]:
        result.append(values[index])
        index += bounds[2]
    return result


@js
def slice_string(
    value: str,
    start: int | None,
    stop: int | None,
    step: int | None,
) -> str:
    bounds = slice_indices(len(value), start, stop, step)
    result: list[str] = []
    index = bounds[0]
    while index < bounds[1] if bounds[2] > 0 else index > bounds[1]:
        result.append(value[index])
        index += bounds[2]
    return "".join(result)


@js
def set_list_slice(
    target: list[object],
    values: list[object],
    start: int | None,
    stop: int | None,
    step: int | None,
) -> None:
    copied: list[object] = []
    for value in values:
        copied.append(value)

    bounds = slice_indices(len(target), start, stop, step)
    actual_start = bounds[0]
    actual_stop = bounds[1]
    actual_step = bounds[2]
    if actual_step == 1:
        delete_count = actual_stop - actual_start
        if delete_count < 0:
            delete_count = 0
        splice(target, actual_start, delete_count, copied)
        return

    indexes: list[int] = []
    index = actual_start
    while index < actual_stop if actual_step > 0 else index > actual_stop:
        indexes.append(index)
        index += actual_step
    if len(indexes) != len(copied):
        raise ValueError(
            f"attempt to assign sequence of size {len(copied)} "
            f"to extended slice of size {len(indexes)}"
        )
    offset = 0
    while offset < len(indexes):
        target[indexes[offset]] = copied[offset]
        offset += 1


@js
def delete_list_slice(
    target: list[object],
    start: int | None,
    stop: int | None,
    step: int | None,
) -> None:
    bounds = slice_indices(len(target), start, stop, step)
    actual_start = bounds[0]
    actual_stop = bounds[1]
    actual_step = bounds[2]
    if actual_step == 1:
        delete_count = actual_stop - actual_start
        if delete_count < 0:
            delete_count = 0
        splice(target, actual_start, delete_count, [])
        return

    indexes: list[int] = []
    index = actual_start
    while index < actual_stop if actual_step > 0 else index > actual_stop:
        indexes.append(index)
        index += actual_step
    offset = len(indexes) - 1 if actual_step > 0 else 0
    while 0 <= offset and offset < len(indexes):
        target.pop(indexes[offset])
        offset += -1 if actual_step > 0 else 1


@js
def delete_list_item(target: list[object], index: int) -> None:
    actual_index = index + len(target) if index < 0 else index
    if actual_index < 0 or actual_index >= len(target):
        raise ValueError("list assignment index out of range")
    target.pop(actual_index)


@js
def delete_dict_item(mapping: dict[object, object], key: object) -> None:
    if key not in mapping:
        raise ValueError(key_error_message(key))
    delete_mapping_item(mapping, key)
