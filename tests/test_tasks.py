import pytest
from legacy.main import add_task,list_tasks

def test_add_rejects_bad_priority():
    tasks = []
    with pytest.raises(ValueError):
        add_task(tasks,"标题","urgent")
    assert tasks == []


def test_list_empty_filter_prints_message(capsys):
       tasks = [{"id": 1, "title": "a", "status": "pending", "priority":
 "medium"}]
       list_tasks(tasks, "high")
       captured = capsys.readouterr()
       assert "暂无任务" in captured.out
