from datetime import date

from database import Database
from migration import upgrade_database
from models import User
from repository import TaskRepository


def test_repository_crud_uses_sessions_and_persists(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'repo.db').as_posix()}"
    upgrade_database(url)
    database = Database(url)
    repository = TaskRepository(database.sessions)

    with database.sessions.begin() as session:
        user = User(username="repo_test", password_hash="unused-in-repository-test")
        session.add(user)
        session.flush()
        user_id = user.id

    created = repository.create_task(
        user_id=user_id,
        title="迁移 Repository",
        priority="high",
        due_date=date(2026, 9, 30),
    )

    assert created == {
        "id": 1,
        "title": "迁移 Repository",
        "status": "pending",
        "priority": "high",
        "due_date": "2026-09-30",
    }
    assert repository.get_task(user_id, 1) == created
    assert repository.list_tasks(user_id, priority="high") == [created]
    assert repository.update_task_status(user_id, 1, "completed")["status"] == "completed"
    assert repository.delete_task(user_id, 1) is True
    assert repository.get_task(user_id, 1) is None
    database.dispose()
