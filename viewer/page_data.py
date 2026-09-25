"""Lossless page-only design packing. The shared design file remains decoded."""
import copy
import json

COLLECTIONS = ("buildings", "furniture", "venues", "trees", "stages", "routes", "streets", "bridges")
POINT_COLLECTIONS = ("routes", "streets", "bridges")
SCALES = (1000, 10000, 100000, 1000000)


def compact(value):
    return json.dumps(value, separators=(",", ":"))


def pack_points(points):
    """Use scaled integer differences only when every coordinate round-trips exactly."""
    for scale in SCALES:
        integers = [[round(value * scale) for value in point] for point in points]
        if not all(value == integer / scale
                   for point, row in zip(points, integers)
                   for value, integer in zip(point, row)):
            continue
        codes = integers[0][:]
        for old, new in zip(integers, integers[1:]):
            codes.extend(b - a for a, b in zip(old, new))
        return [scale, codes]
    return points


def unpack_points(value, dimension):
    if not value or not isinstance(value[0], int):
        return value
    scale, codes = value
    if len(codes) % dimension:
        raise ValueError("packed point coordinate count is not divisible by dimension")
    current = [0] * dimension
    points = []
    for i in range(0, len(codes), dimension):
        for k in range(dimension):
            current[k] += codes[i + k]
        points.append([integer / scale for integer in current])
    return points


def pack_records(rows):
    schemas = []
    indexes = {}
    values = []
    for record in rows:
        keys = tuple(record)
        if keys not in indexes:
            indexes[keys] = len(schemas)
            schemas.append(keys)
        values.append([indexes[keys]] + [record[key] for key in keys])
    if len(schemas) == 1:
        values = [row[1:] for row in values]
    return {"s": [list(keys) for keys in schemas], "r": values}


def unpack_records(value):
    schemas, rows = value["s"], value["r"]
    if len(schemas) == 1:
        return [dict(zip(schemas[0], row)) for row in rows]
    return [dict(zip(schemas[row[0]], row[1:])) for row in rows]


def pack_design(design):
    """Return a packed page copy without mutating the full shared design."""
    packed = copy.deepcopy(design)
    for name in POINT_COLLECTIONS:
        for record in packed[name]:
            record["points"] = pack_points(record["points"])
    for name in COLLECTIONS:
        value = packed[name]
        if name == "buildings":
            if list(value) != [str(i) for i in range(len(value))]:
                raise ValueError("building ids are not consecutive from zero")
            rows = list(value.values())
        else:
            rows = value
        if rows:
            packed[name] = pack_records(rows)
    return packed


def unpack_design(packed):
    """Python reference for the browser decoder."""
    design = copy.deepcopy(packed)
    for name in COLLECTIONS:
        value = design[name]
        if isinstance(value, dict) and "s" in value and "r" in value:
            rows = unpack_records(value)
            design[name] = {str(i): record for i, record in enumerate(rows)} if name == "buildings" else rows
    for name in POINT_COLLECTIONS:
        for record in design[name]:
            record["points"] = unpack_points(record["points"], 3 if name == "bridges" else 2)
    return design
