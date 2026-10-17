"""Application module state used by native import/alias integration tests."""

VALUES: "list[list[str]]" = [["first"]]  # noqa: UP037 - exercise quoted annotation resolution
ALIAS = VALUES
PAIR: tuple[list[int], set[str], frozenset[str]] = ([1], {"fixed"}, frozenset({"frozen"}))
FROZEN: frozenset[str] = frozenset({"ship", "master"})
FROZEN_ALIAS = FROZEN
UNUSED = []


def remember(label: str) -> None:
    VALUES.append([label + "!"])


def unrelated(value):
    raise RuntimeError("must remain unreachable")
