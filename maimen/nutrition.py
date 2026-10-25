"""Parse the observed MCP text table; match names exactly after typography normalization."""
import csv
import io
import math
import re
import unicodedata

FIELDS = ["productName", "nutritionDescription", "energyKj", "energyKcal", "protein",
          "fat", "carbohydrate", "sodium", "calcium"]


def normalized_name(name):
    return "".join(unicodedata.normalize("NFKC", name).split())


def parse_nutrition(text):
    if not isinstance(text, str):
        raise ValueError("unsupported_nutrition_format")
    header, _, body = text.partition("\n")
    match = re.fullmatch(r"\[(\d+)\]\{([^}]+)\}:", header.strip())
    if not match or match[2].split(",") != FIELDS:
        raise ValueError("unexpected_nutrition_header")
    rows = list(csv.reader(io.StringIO(body), skipinitialspace=True))
    rows = [row for row in rows if row]
    if len(rows) != int(match[1]):
        raise ValueError("nutrition_count_mismatch")
    index = {}
    for row in rows:
        if len(row) != len(FIELDS):
            raise ValueError("nutrition_column_mismatch")
        name = normalized_name(row[0])
        numbers = [float(value) for value in row[2:]]
        if not name or any(not math.isfinite(x) or x < 0 for x in numbers):
            raise ValueError("invalid_nutrition_value")
        # Duplicate names may represent distinct specifications. Do not guess.
        value = dict(zip(FIELDS[2:], numbers))
        index[name] = value if name not in index else None
    return index


def summarize_nutrition(components, index):
    totals = {"energy_kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0,
              "carbohydrate_g": 0.0, "sodium_mg": 0.0}
    fields = dict(zip(totals, ["energyKcal", "protein", "fat", "carbohydrate", "sodium"]))
    unmatched = []
    for item in components:
        value = index.get(normalized_name(item["name"]))
        if value is None:
            unmatched.append(item["name"])
            continue
        for target, source in fields.items():
            totals[target] += value[source] * item["quantity"]
    return {"status": "exact_name_match" if not unmatched else "incomplete", "unmatched": unmatched,
            "totals": {key: round(value, 2) for key, value in totals.items()} if not unmatched else None,
            "basis": "MCP标准配方，名称和规格精确匹配；非实际餐品检测值"}
