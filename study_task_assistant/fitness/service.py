from fitness.repository import FitnessRepository
from fitness.importer import import_key, parse_csv


class FitnessService:
    def __init__(self, repository: FitnessRepository):
        self._repository = repository

    def create_workout(self, owner_id, workout):
        return self._repository.create_workout(owner_id, workout.workout_date, workout.notes, [item.model_dump() for item in workout.sets])

    def add_weight(self, owner_id, record):
        return self._repository.add_weight(owner_id, record.recorded_on, record.weight_kg)

    def progress(self, owner_id):
        return self._repository.progress(owner_id)

    def preview_import(self, csv_text):
        rows = parse_csv(csv_text)
        return {"row_count": len(rows), "workout_count": sum(row["kind"] == "workout" for row in rows),
                "weight_count": sum(row["kind"] == "weight" for row in rows), "rows": rows}

    def commit_import(self, owner_id, csv_text):
        rows = parse_csv(csv_text)
        return self._repository.commit_import(owner_id, import_key(owner_id, csv_text), rows)
