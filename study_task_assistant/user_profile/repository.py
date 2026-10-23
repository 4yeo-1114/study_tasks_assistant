from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from storage.models import UserProfile


class UserProfileNotFoundError(LookupError):
    pass


class UserProfileRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, owner_id: int) -> dict[str, Any]:
        with self._sessions() as session:
            profile = session.scalar(
                select(UserProfile).where(UserProfile.owner_id == owner_id)
            )
            if profile is None:
                raise UserProfileNotFoundError("尚未创建用户档案")
            return _profile_to_dict(profile)

    def replace(self, owner_id: int, values: dict[str, Any]) -> dict[str, Any]:
        with self._sessions.begin() as session:
            profile = session.scalar(
                select(UserProfile).where(UserProfile.owner_id == owner_id)
            )
            if profile is None:
                profile = UserProfile(owner_id=owner_id, revision=1, **values)
                session.add(profile)
            else:
                for field, value in values.items():
                    setattr(profile, field, value)
                profile.revision += 1
            session.flush()
            return _profile_to_dict(profile)

    def delete(self, owner_id: int) -> bool:
        with self._sessions.begin() as session:
            profile = session.scalar(
                select(UserProfile).where(UserProfile.owner_id == owner_id)
            )
            if profile is None:
                return False
            session.delete(profile)
            return True


def _profile_to_dict(profile: UserProfile) -> dict[str, Any]:
    return {
        "learning_goal": profile.learning_goal,
        "training_days_per_week": profile.training_days_per_week,
        "preferences": profile.preferences,
        "limitations": profile.limitations,
        "daily_minutes": profile.daily_minutes,
        "revision": profile.revision,
        "plan_version": profile.plan_version,
    }
