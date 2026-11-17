import math


def field_constraints(field):
    from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen

    names = {Ge: "ge", Gt: "gt", Le: "le", Lt: "lt",
             MinLen: "min_length", MaxLen: "max_length"}
    constraints = {}
    for metadata in field.metadata:
        name = names.get(type(metadata))
        if name is None:
            continue
        bound = getattr(metadata, name)
        if type(bound) not in (int, float) or (type(bound) is float and not math.isfinite(bound)):
            raise TypeError("Client model constraints require finite numeric bounds")
        constraints[name] = bound
    return constraints
