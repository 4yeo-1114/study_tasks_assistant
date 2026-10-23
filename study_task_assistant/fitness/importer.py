import csv
import hashlib
import io
import math
from datetime import date


class FitnessCsvError(ValueError):
    pass


def parse_csv(csv_text: str) -> list[dict]:
    if not csv_text.strip():
        raise FitnessCsvError("csv_text 不能为空")
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"workout_date", "exercise_name", "weight_kg", "reps", "recorded_on"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise FitnessCsvError("CSV 必须包含 workout_date, exercise_name, weight_kg, reps, recorded_on 列")
    rows = []
    for index, raw in enumerate(reader, start=2):
        try:
            has_workout_date = bool(raw.get("workout_date", "").strip())
            has_recorded_on = bool(raw.get("recorded_on", "").strip())
            if has_workout_date and has_recorded_on:
                raise ValueError("workout_date 和 recorded_on 不能同时提供")
            if has_workout_date:
                if not raw.get("exercise_name", "").strip():
                    raise ValueError("exercise_name 不能为空")
                rows.append({"kind": "workout", "workout_date": date.fromisoformat(raw["workout_date"]),
                             "exercise_name": raw["exercise_name"].strip(),
                             "weight_kg": float(raw["weight_kg"]), "reps": int(raw["reps"])})
            elif raw.get("recorded_on", "").strip():
                rows.append({"kind": "weight", "recorded_on": date.fromisoformat(raw["recorded_on"]),
                             "weight_kg": float(raw["weight_kg"])})
            else:
                raise ValueError("必须提供 workout_date 或 recorded_on")
            if not math.isfinite(rows[-1]["weight_kg"]):
                raise ValueError("重量必须是有限数字")
            if rows[-1]["weight_kg"] <= 0 or (rows[-1]["kind"] == "workout" and rows[-1]["reps"] <= 0):
                raise ValueError("重量和次数必须大于 0")
        except (KeyError, TypeError, ValueError) as exc:
            raise FitnessCsvError(f"第 {index} 行无效: {exc}") from exc
    if not rows:
        raise FitnessCsvError("CSV 没有数据行")
    return rows


def import_key(owner_id: int, csv_text: str) -> str:
    return hashlib.sha256(f"{owner_id}:".encode() + csv_text.encode("utf-8")).hexdigest()
