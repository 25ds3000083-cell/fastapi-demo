from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from uuid import uuid4

app = FastAPI(title="Tasks API")

class TaskCreate(BaseModel):
    title: str
    done: bool = False
    priority: int = 3

class Task(TaskCreate):
    id: str

tasks: dict[str, Task] = {}

@app.get("/tasks", response_model=list[Task])
def list_tasks(done: bool | None = None):
    # /tasks returns all
    # /tasks?done=true returns completed only
    data = list(tasks.values())

    if done is not None:
        data = [task for task in data if task.done == done]

    return data

@app.post("/tasks", response_model=Task, status_code=201)
def create_task(payload: TaskCreate):
    task = Task(id=str(uuid4()), **payload.model_dump())
    tasks[task.id] = task
    return task

@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    return tasks[task_id]

@app.put("/tasks/{task_id}", response_model=Task)
def replace_task(task_id: str, payload: TaskCreate):
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")

    tasks[task_id] = Task(id=task_id, **payload.model_dump())
    return tasks[task_id]

@app.patch("/tasks/{task_id}", response_model=Task)
def mark_done(task_id: str, done: bool):
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")

    old = tasks[task_id]
    tasks[task_id] = Task(
        id=old.id,
        title=old.title,
        priority=old.priority,
        done=done
    )
    return tasks[task_id]

@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")

    del tasks[task_id]
    # 204 should not return a body

@app.get("/")
def root():
    return {"message": "FastAPI is running"}

@app.get("/health")
def health():
    return {"status": "ok"}
