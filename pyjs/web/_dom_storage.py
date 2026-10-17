"""Sparse CPython storage shared by DOM elements, builders, and SSR.

Keeping these views outside the generated WebIDL modules makes their private
server-side representation explicit without adding it to the browser API.
Parent links are weak, while a materialized Attr and its owner retain each
other until the attribute is detached or cyclic garbage collection runs.
"""

import html

_ATTRIBUTE_NODES = object()


class _DefaultCollector(dict):
    __slots__ = ("owner", "properties")

    def __init__(self, owner, properties=()):
        self.owner = owner
        self.properties = properties


def _data_attribute_name(name):
    return "data-" + "".join(
        "-" + character.lower() if "A" <= character <= "Z" else character
        for character in name
    )


def _dataset_name(attribute):
    name = attribute[5:]
    result = []
    index = 0
    while index < len(name):
        character = name[index]
        if (
            character == "-"
            and index + 1 < len(name)
            and "a" <= name[index + 1] <= "z"
        ):
            index += 1
            character = name[index].upper()
        result.append(character)
        index += 1
    return "".join(result)


class _DatasetMap:
    __slots__ = ("_element",)

    def __init__(self, element):
        self._element = element

    def __getitem__(self, name):
        value = self._element.getAttribute(_data_attribute_name(name))
        if value is None:
            raise KeyError(name)
        return value

    def __setitem__(self, name, value):
        self._element.setAttribute(_data_attribute_name(name), value)

    def __delitem__(self, name):
        attribute = _data_attribute_name(name)
        if not self._element.hasAttribute(attribute):
            raise KeyError(name)
        self._element.removeAttribute(attribute)

    def __iter__(self):
        # Iterating element.attributes materializes every Attr and switches the
        # compact store into synchronization mode merely to enumerate names.
        for attribute in self._element.getAttributeNames():
            if attribute.startswith("data-"):
                yield _dataset_name(attribute)

    def __len__(self):
        return sum(1 for _ in self)

    def items(self):
        for name in self:
            yield (name, self[name])


def _get_parts(element):
    try:
        return object.__getattribute__(element, "_pyjs_parts")
    except AttributeError:
        return None


def _parts(element):
    parts = _get_parts(element)
    if parts is None:
        parts = [0]
        object.__setattr__(element, "_pyjs_parts", parts)
    return parts


def _child_offset(parts):
    return 1 + abs(parts[0])


def _element_text_content(element, text_type):
    """Read descendant text without materializing views or recursing.

    RawHTML is an opaque SSR string, not a parsed subtree; like other stored
    strings its unparsed contents are returned by this CPython fallback.
    """
    pending = [element]
    result = []
    while pending:
        child = pending.pop()
        if isinstance(child, str):
            result.append(child)
        elif isinstance(child, text_type):
            result.append(child.data)
        else:
            parts = _get_parts(child)
            if parts is not None:
                pending.extend(reversed(parts[_child_offset(parts):]))
    return "".join(result)


def _set_element_text_content(element, value):
    # Convert before touching the tree: __str__ can raise or mutate it. It can
    # also return a str subclass, so strip any RawHTML marker from its result.
    value = "" if value is None else str.__str__(str(value))
    parts = _parts(element)
    offset = _child_offset(parts)
    removed = parts[offset:]
    parts[offset:] = [value] if value else []
    for child in removed:
        if not isinstance(child, str):
            try:
                parent = object.__getattribute__(child, "_pyjs_parent")
                if parent() is element:
                    object.__delattr__(child, "_pyjs_parent")
            except AttributeError:
                pass


def _attribute_name(fragment):
    return fragment[1 : fragment.index("=")]


def _attribute_value(fragment):
    return html.unescape(fragment[fragment.index("=") + 2 : -1])


def _serialize_attribute(name, value):
    value = str(value)
    if (
        "&" in value
        or "<" in value
        or ">" in value
        or '"' in value
        or "'" in value
    ):
        value = html.escape(value, quote=True)
    return f' {name}="{value}"'


def _set_serialized_attribute(parts, name, value):
    fragment = _serialize_attribute(name, value)
    stop = _child_offset(parts)
    prefix = f' {name}="'
    for index in range(1, stop):
        if parts[index].startswith(prefix):
            parts[index] = fragment
            return
    parts.insert(stop, fragment)
    count = abs(parts[0]) + 1
    parts[0] = -count if parts[0] < 0 else count


def _attribute_nodes(element, create=False):
    if element is None:
        return None
    data = object.__getattribute__(element, "__dict__")
    nodes = data.get(_ATTRIBUTE_NODES)
    if nodes is None and create:
        nodes = {}
        data[_ATTRIBUTE_NODES] = nodes
    return nodes


def _sync_attribute_nodes(element, parts):
    nodes = _attribute_nodes(element)
    if nodes is None:
        return
    attributes = _AttributeItems(parts, element)
    for name, attribute in nodes.items():
        index = attributes._index(name)
        if index >= 0:
            parts[index] = _serialize_attribute(name, attribute.value)


class _AttributeItems:
    __slots__ = ("_owner", "_parts")

    def __init__(self, parts, owner=None):
        self._parts = parts
        self._owner = owner

    def _index(self, name):
        parts = self._parts
        stop = _child_offset(parts)
        prefix = f' {name}="'
        for index in range(1, stop):
            if parts[index].startswith(prefix):
                return index
        return -1

    def __contains__(self, name):
        return self._index(name) >= 0

    def __delitem__(self, name):
        index = self._index(name)
        if index < 0:
            raise KeyError(name)
        del self._parts[index]
        nodes = _attribute_nodes(self._owner)
        if nodes is not None:
            nodes.pop(name, None)
        count = abs(self._parts[0]) - 1
        self._parts[0] = -count if count and nodes else count

    def __getitem__(self, name):
        index = self._index(name)
        if index < 0:
            raise KeyError(name)
        nodes = _attribute_nodes(self._owner)
        if nodes is not None:
            attribute = nodes.get(name)
            if attribute is not None:
                return attribute
        return _attribute_value(self._parts[index])

    def __iter__(self):
        parts = self._parts
        stop = _child_offset(parts)
        for index in range(1, stop):
            yield _attribute_name(parts[index])

    def __len__(self):
        return abs(self._parts[0])

    def __setitem__(self, name, value):
        parts = self._parts
        index = self._index(name)
        nodes = _attribute_nodes(self._owner)
        if hasattr(value, "ownerElement"):
            value.ownerElement = self._owner
            nodes = _attribute_nodes(self._owner, create=True)
            nodes[name] = value
            serialized = _serialize_attribute(name, value.value)
            if parts[0] > 0:
                parts[0] = -parts[0]
        else:
            if nodes is not None and name in nodes:
                nodes[name].value = str(value)
            serialized = _serialize_attribute(name, value)
        if index >= 0:
            parts[index] = serialized
            return
        offset = _child_offset(parts)
        parts.insert(offset, serialized)
        count = abs(parts[0]) + 1
        parts[0] = -count if nodes else count

    def get(self, name, default=None):
        index = self._index(name)
        return default if index < 0 else self[name]

    def items(self):
        for name in self:
            yield name, self[name]

    def pop(self, name, default=None):
        index = self._index(name)
        if index < 0:
            return default
        value = self[name]
        del self._parts[index]
        nodes = _attribute_nodes(self._owner)
        if nodes is not None:
            nodes.pop(name, None)
        count = abs(self._parts[0]) - 1
        self._parts[0] = -count if count and nodes else count
        return value


class _ElementItems:
    __slots__ = ("_element_type", "_parts")

    def __init__(self, parts, element_type):
        self._parts = parts
        self._element_type = element_type

    def __getitem__(self, index):
        if index < 0:
            index += len(self)
        for item_index, node in enumerate(self):
            if item_index == index:
                return node
        raise IndexError(index)

    def __iter__(self):
        parts = self._parts
        for index in range(_child_offset(parts), len(parts)):
            node = parts[index]
            if isinstance(node, self._element_type):
                yield node

    def __len__(self):
        parts = self._parts
        return sum(
            isinstance(parts[index], self._element_type)
            for index in range(_child_offset(parts), len(parts))
        )

    def append(self, item):
        self._parts.append(item)

    def clear(self):
        parts = self._parts
        offset = _child_offset(parts)
        parts[offset:] = [
            node
            for node in parts[offset:]
            if not isinstance(node, self._element_type)
        ]

    def pop(self, index=-1):
        item = self[index]
        self.remove(item)
        return item

    def remove(self, item):
        parts = self._parts
        index = parts.index(item, _child_offset(parts))
        del parts[index]


class _ChildNodeItems:
    __slots__ = ("_parent", "_parts", "_text_type")

    def __init__(self, parts, parent, text_type):
        self._parts = parts
        self._parent = parent
        self._text_type = text_type

    def _materialize(self, index):
        parts = self._parts
        offset = _child_offset(parts)
        child_count = len(parts) - offset
        if index < 0:
            index += child_count
        if index < 0 or index >= child_count:
            raise IndexError(index)
        index += offset
        value = parts[index]
        if isinstance(value, str):
            value = self._text_type(value)
            value.parentNode = self._parent
            parts[index] = value
        return value

    def __getitem__(self, index):
        return self._materialize(index)

    def __iter__(self):
        index = 0
        while index < len(self):
            yield self._materialize(index)
            index += 1

    def __len__(self):
        return len(self._parts) - _child_offset(self._parts)

    def append(self, item):
        self._parts.append(item)

    def clear(self):
        parts = self._parts
        del parts[_child_offset(parts) :]

    def pop(self, index=-1):
        value = self._materialize(index)
        parts = self._parts
        offset = _child_offset(parts)
        if index < 0:
            index += len(parts) - offset
        parts.pop(offset + index)
        return value

    def remove(self, item):
        parts = self._parts
        index = parts.index(item, _child_offset(parts))
        del parts[index]
