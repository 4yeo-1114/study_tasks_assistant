from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from storage.models import BodyWeightRecord, ExerciseSet, FitnessImport, WorkoutSession


class FitnessRepository:
    def __init__(self, sessions):
        self._sessions = sessions

    def create_workout(self, owner_id: int, workout_date: date, notes: str | None, sets: list[dict]) -> dict:
        with self._sessions.begin() as session:
            workout = WorkoutSession(owner_id=owner_id, workout_date=workout_date, notes=notes)
            session.add(workout)
            session.flush()
            for item in sets:
                session.add(ExerciseSet(session_id=workout.id, **item))
            session.flush()
            return self._workout_dict(workout.id, owner_id, session)

    def add_weight(self, owner_id: int, recorded_on: date, weight_kg: float) -> dict:
        with self._sessions.begin() as session:
            row = session.scalar(select(BodyWeightRecord).where(
                BodyWeightRecord.owner_id == owner_id,
                BodyWeightRecord.recorded_on == recorded_on,
            ))
            if row is None:
                row = BodyWeightRecord(owner_id=owner_id, recorded_on=recorded_on, weight_kg=weight_kg)
                session.add(row)
            else:
                row.weight_kg = weight_kg
            session.flush()
            return {"id": row.id, "recorded_on": row.recorded_on, "weight_kg": row.weight_kg}

    def progress(self, owner_id: int) -> dict:
        with self._sessions() as session:
            rows = session.execute(select(ExerciseSet.exercise_name, ExerciseSet.weight_kg, ExerciseSet.reps)
                .join(WorkoutSession, WorkoutSession.id == ExerciseSet.session_id)
                .where(WorkoutSession.owner_id == owner_id)).all()
            volume = defaultdict(float)
            personal_record = {}
            for name, weight, reps in rows:
                volume[name] += weight * reps
                personal_record[name] = max(personal_record.get(name, 0), weight)
            weights = session.scalars(select(BodyWeightRecord).where(BodyWeightRecord.owner_id == owner_id)).all()
            by_week = defaultdict(list)
            for row in weights:
                iso = row.recorded_on.isocalendar()
                by_week[f"{iso.year}-W{iso.week:02d}"].append(row.weight_kg)
            return {"volume_by_exercise": dict(volume), "exercise_pr": personal_record,
                    "weekly_weight": {key: sum(values) / len(values) for key, values in by_week.items()}}

    def commit_import(self, owner_id: int, import_key: str, rows: list[dict]) -> dict:
        try:
            with self._sessions.begin() as session:
                previous = session.scalar(select(FitnessImport).where(
                    FitnessImport.owner_id == owner_id, FitnessImport.import_key == import_key))
                if previous is not None:
                    return {**self._import_dict(previous), "created": False}
                workouts = {}
                weight_rows = 0
                for row in rows:
                    if row["kind"] == "workout":
                        workouts.setdefault(row["workout_date"], []).append(row)
                    else:
                        existing = session.scalar(select(BodyWeightRecord).where(
                            BodyWeightRecord.owner_id == owner_id,
                            BodyWeightRecord.recorded_on == row["recorded_on"]))
                        if existing is None:
                            session.add(BodyWeightRecord(owner_id=owner_id, recorded_on=row["recorded_on"], weight_kg=row["weight_kg"]))
                        else:
                            existing.weight_kg = row["weight_kg"]
                        weight_rows += 1
                for workout_date, items in workouts.items():
                    workout = WorkoutSession(owner_id=owner_id, workout_date=workout_date)
                    session.add(workout)
                    session.flush()
                    for row in items:
                        session.add(ExerciseSet(session_id=workout.id, exercise_name=row["exercise_name"], weight_kg=row["weight_kg"], reps=row["reps"]))
                record = FitnessImport(owner_id=owner_id, import_key=import_key, row_count=len(rows), workout_count=len(workouts), weight_count=weight_rows)
                session.add(record)
                session.flush()
                return {**self._import_dict(record), "created": True}
        except IntegrityError:
            # A concurrent request won the unique owner/import_key race. Its
            # transaction is now committed, so read the canonical ledger row.
            with self._sessions() as session:
                previous = session.scalar(select(FitnessImport).where(
                    FitnessImport.owner_id == owner_id, FitnessImport.import_key == import_key))
                if previous is None:
                    raise
                return {**self._import_dict(previous), "created": False}

    @staticmethod
    def _import_dict(record):
        return {"row_count": record.row_count, "workout_count": record.workout_count, "weight_count": record.weight_count}

    @staticmethod
    def _workout_dict(workout_id, owner_id, session):
        workout = session.scalar(select(WorkoutSession).where(WorkoutSession.id == workout_id, WorkoutSession.owner_id == owner_id))
        sets = session.scalars(select(ExerciseSet).where(ExerciseSet.session_id == workout_id).order_by(ExerciseSet.id)).all()
        payload = [{"exercise_name": row.exercise_name, "weight_kg": row.weight_kg, "reps": row.reps} for row in sets]
        return {"id": workout.id, "workout_date": workout.workout_date, "notes": workout.notes,
                "sets": payload, "volume": sum(row["weight_kg"] * row["reps"] for row in payload)}
