# ID 从 1 开始递增；删除任务后也不复用，所以不能看列表最后一项。
import os
import sqlite3
from datetime import date, datetime


_next_task_id = 1


def _normalize_due_date(due_date):
    # 空表示没有截止日期；有值则必须是真实存在的 YYYY-MM-DD。
    if due_date is None:
        return None
    if not isinstance(due_date, str):
        raise ValueError("日期不合法，必须是 YYYY-MM-DD")
    text = due_date.strip()
    if not text:
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError("日期不合法，必须是 YYYY-MM-DD") from None
    return text


def add_task(tasks_list:list[dict],title:str,priority="medium",due_date=None):
    global _next_task_id
    if not isinstance(title,str) or not title.strip():
        raise ValueError("title必须是非空字符串")
    priority = (priority or "medium").strip()
    if priority not in ("high", "medium", "low"):
        raise ValueError("priority必须是high medium 或者 low")
    due_date = _normalize_due_date(due_date)

    tasks_list.append(
        {
            "id": _next_task_id,
            "title": title.strip(),
            "status": "pending",
            "priority": priority,
            "due_date": due_date,
        }
    )
    _next_task_id += 1


def list_tasks(tasks_list:list,priority=""):
    priority = (priority or "").strip()
    if priority and priority not in ("high", "medium", "low"):
        raise ValueError("priority必须是high medium 或者 low")
    shown = 0
    for task in tasks_list:
        if priority and task.get("priority") != priority:
            continue
        print(f"task_id:{task.get('id')}\ntask_title:{task.get('title')}\ntask_status:{task.get('status')}\ntask_priority:{task.get('priority')}\ntask_due_date:{task.get('due_date') or '-'}")
        print("---"*10)
        shown += 1
    if shown == 0:
        print("暂无任务")


# 今天到期不算逾期；没有截止日期不算；已完成即使过期也不算。
def overdue(tasks_list:list):
    shown = 0
    today = date.today().isoformat()
    for task in tasks_list:
        due = task.get("due_date")
        if due and due < today and task.get("status") != "completed":
            print(f"task_id:{task.get('id')}\ntask_title:{task.get('title')}\ntask_status:{task.get('status')}\ntask_priority:{task.get('priority')}\ntask_due_date:{due}")
            print("---"*10)
            shown += 1
    if shown == 0:
        print("暂时无逾期任务")



def _require_task_id(task_id):
    if not isinstance(task_id,int) or isinstance(task_id,bool) or task_id < 1:
        raise ValueError("task_id必须是正整数")


def get_task(tasks_list,task_id):
    _require_task_id(task_id)
    for task in tasks_list:
        if task.get("id") == task_id:
            return task
    raise LookupError("找不到该task")


def complete_task(tasks_list,task_id):
    #复用之前写的get_task函数不用再手写循环了
    task = get_task(tasks_list,task_id)
    if task.get("status") == "completed":
        print("该任务状态已经修改")
        return
    task["status"] = "completed"


def delete_task(tasks_list,task_id):
    task = get_task(tasks_list,task_id)
    tasks_list.remove(task)


# 搜索忽略大小写；标题包含关键词即命中。
def search_tasks(tasks_list,keyword):
    if not isinstance(keyword,str) or not keyword.strip():
        raise ValueError("keyword必须是非空字符串")

    keyword = keyword.strip().lower()
    result = []
    for task in tasks_list:
        title = str(task.get("title","")).lower()
        if keyword in title:
            result.append(task)

    if not result:
        print("找不到结果")
        return
    list_tasks(result)


def _ensure_tasks_table(conn):
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            due_date TEXT
        )"""
    )
    cur.execute("PRAGMA table_info(tasks)")
    columns = {row[1] for row in cur.fetchall()}
    if "priority" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'medium'")
    if "due_date" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
    conn.commit()


def save_tasks(tasks_list,path):
    conn = sqlite3.connect(path)
    _ensure_tasks_table(conn)
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks")
    for task in tasks_list:
        cur.execute(
            "INSERT INTO tasks (id, title, status, priority, due_date) VALUES (?, ?, ?, ?, ?)",
            (
                task.get("id"),
                task.get("title"),
                task.get("status"),
                task.get("priority") or "medium",
                task.get("due_date") or None,
            ),
        )
    conn.commit()
    conn.close()


def load_tasks(path):
    global _next_task_id
    conn = sqlite3.connect(path)
    _ensure_tasks_table(conn)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, title, status, priority, due_date FROM tasks ORDER BY id"
    ).fetchall()
    conn.close()

    data = []
    for row in rows:
        data.append(
            {
                "id": row[0],
                "title": row[1],
                "status": row[2],
                "priority": row[3] or "medium",
                "due_date": row[4] or None,
            }
        )

    if not data:
        _next_task_id = 1
        return []

    # 不能看列表最后一项：删掉最大 id 后再 load，last+1 会复用。
    _next_task_id = max(task["id"] for task in data) + 1
    return data



if __name__ == "__main__":
    # 文件位置跟着 main.py，不跟着在哪个目录运行。
    data_path = os.path.join(os.path.dirname(__file__), "tasks.db")
    tasks_list = load_tasks(data_path)
    print("输入help查看命令")

    while True:
        line = input("task> ").strip()
        if not line:
            continue

        parts = line.split(maxsplit=1)
        command = parts[0]
        argument = parts[1] if len(parts) == 2 else ""

        try:
            if command == "list":
                list_tasks(tasks_list,argument)

            elif command == "add":
                add_task(tasks_list, argument)
                save_tasks(tasks_list, data_path)

            elif command == "get":
                task = get_task(tasks_list, int(argument))
                print(task)

            elif command == "complete":
                complete_task(tasks_list, int(argument))
                save_tasks(tasks_list, data_path)

            elif command == "delete":
                delete_task(tasks_list, int(argument))
                save_tasks(tasks_list, data_path)

            elif command == "search":
                search_tasks(tasks_list,argument)

            elif command == "overdue":
                overdue(tasks_list)

            elif command == "help":
                print("add <标题> | list | get <编号> | complete <编号> | delete <编号> | overdue | quit | search <关键词>")






            elif command == "quit":
                break

            else:
                print("未知命令 输入help查看")
        except ValueError as e:
            print("输入错误:", e)
        except LookupError as e:
            print("找不到任务:", e)
