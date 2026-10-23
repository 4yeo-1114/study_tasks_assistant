from typing import Any

from user_profile.repository import UserProfileRepository


class UserProfileService:
    def __init__(self, repository: UserProfileRepository) -> None:
        self._repository = repository

    def get(self, owner_id: int) -> dict[str, Any]:
        return self._repository.get(owner_id)

    def replace(self, owner_id: int, profile: Any) -> dict[str, Any]:
        return self._repository.replace(owner_id, profile.model_dump())

    def delete(self, owner_id: int) -> bool:
        return self._repository.delete(owner_id)
