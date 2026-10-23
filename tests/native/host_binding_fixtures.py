"""Source implementations used to exercise per-compilation host selection."""


class Service:
    def label(self, value: int) -> str:
        return "default:" + str(value + 1)


class EquivalentService:
    def label(self, value: int) -> str:
        return "default:" + str(1 + value)


class AlternateService:
    def label(self, value: int) -> str:
        return "alternate:" + str(value + 1)


class IncompleteService:
    pass
