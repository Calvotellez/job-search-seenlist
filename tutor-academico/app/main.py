import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, rag, tutor
from .profiles import PROFILES

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 25 * 1024 * 1024


def _load_env() -> None:
    env = Path(__file__).parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


@asynccontextmanager
async def lifespan(_: FastAPI):
    _load_env()
    db.init()
    yield


app = FastAPI(title="Tutor Académico", lifespan=lifespan)


class CourseIn(BaseModel):
    name: str
    profile: str = "general"
    notes: str = ""


class ChatIn(BaseModel):
    message: str


class TaskIn(BaseModel):
    title: str
    description: str = ""
    due: str | None = None


class TaskPatch(BaseModel):
    done: bool


class QuizIn(BaseModel):
    topic: str = ""
    n: int = 5


def get_course(course_id: int) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Curso no encontrado")
    return dict(row)


def llm(fn, *args):
    try:
        return fn(*args)
    except tutor.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # errores de la API
        raise HTTPException(502, f"Error del modelo: {e}")


@app.get("/api/profiles")
def list_profiles():
    return [{"id": k, "name": v["name"]} for k, v in PROFILES.items()]


@app.get("/api/courses")
def list_courses():
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM courses ORDER BY id")]


@app.post("/api/courses")
def create_course(body: CourseIn):
    if not body.name.strip():
        raise HTTPException(422, "El nombre es obligatorio")
    if body.profile not in PROFILES:
        raise HTTPException(422, "Perfil desconocido")
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO courses (name, profile, notes) VALUES (?, ?, ?)",
            (body.name.strip(), body.profile, body.notes),
        )
        return {"id": cur.lastrowid, **body.model_dump()}


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: int):
    get_course(course_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    return {"ok": True}


# --- Material ---
@app.get("/api/courses/{course_id}/materials")
def list_materials(course_id: int):
    get_course(course_id)
    with db.connect() as conn:
        return [
            dict(r)
            for r in conn.execute("SELECT * FROM materials WHERE course_id = ? ORDER BY id", (course_id,))
        ]


@app.post("/api/courses/{course_id}/materials")
async def upload_material(course_id: int, file: UploadFile = File(...)):
    get_course(course_id)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Archivo demasiado grande (máx. 25 MB)")
    try:
        material_id = rag.add_material(course_id, file.filename or "sin_nombre", data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": material_id, "filename": file.filename}


@app.delete("/api/materials/{material_id}")
def remove_material(material_id: int):
    rag.delete_material(material_id)
    return {"ok": True}


# --- Chat ---
@app.get("/api/courses/{course_id}/messages")
def get_messages(course_id: int):
    get_course(course_id)
    with db.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT role, content FROM messages WHERE course_id = ? ORDER BY id", (course_id,)
            )
        ]


@app.post("/api/courses/{course_id}/chat")
def chat(course_id: int, body: ChatIn):
    course = get_course(course_id)
    if not body.message.strip():
        raise HTTPException(422, "Mensaje vacío")
    with db.connect() as conn:
        history = [
            dict(r)
            for r in conn.execute(
                "SELECT role, content FROM messages WHERE course_id = ? ORDER BY id", (course_id,)
            )
        ]
    answer, fragments = llm(tutor.chat, course, history, body.message)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO messages (course_id, role, content) VALUES (?, 'user', ?)",
            (course_id, body.message),
        )
        conn.execute(
            "INSERT INTO messages (course_id, role, content) VALUES (?, 'assistant', ?)",
            (course_id, answer),
        )
    sources = [{"n": i, "filename": f["filename"], "page": f["page"]} for i, f in enumerate(fragments, 1)]
    return {"answer": answer, "sources": sources}


@app.delete("/api/courses/{course_id}/messages")
def clear_messages(course_id: int):
    get_course(course_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM messages WHERE course_id = ?", (course_id,))
    return {"ok": True}


# --- Tareas ---
@app.get("/api/courses/{course_id}/tasks")
def list_tasks(course_id: int):
    get_course(course_id)
    with db.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM tasks WHERE course_id = ? ORDER BY done, due IS NULL, due, id",
                (course_id,),
            )
        ]


@app.post("/api/courses/{course_id}/tasks")
def create_task(course_id: int, body: TaskIn):
    get_course(course_id)
    if not body.title.strip():
        raise HTTPException(422, "El título es obligatorio")
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (course_id, title, description, due) VALUES (?, ?, ?, ?)",
            (course_id, body.title.strip(), body.description, body.due or None),
        )
        return {"id": cur.lastrowid}


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: int, body: TaskPatch):
    with db.connect() as conn:
        conn.execute("UPDATE tasks SET done = ? WHERE id = ?", (int(body.done), task_id))
    return {"ok": True}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    with db.connect() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return {"ok": True}


@app.post("/api/tasks/{task_id}/plan")
def plan(task_id: int):
    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Tarea no encontrada")
    course = get_course(task["course_id"])
    text = llm(tutor.plan_task, course, task["title"], task["description"], task["due"])
    with db.connect() as conn:
        conn.execute("UPDATE tasks SET plan = ? WHERE id = ?", (text, task_id))
    return {"plan": text}


# --- Quiz ---
@app.post("/api/courses/{course_id}/quiz")
def quiz(course_id: int, body: QuizIn):
    course = get_course(course_id)
    return {"quiz": llm(tutor.make_quiz, course, body.topic, max(1, min(body.n, 15)))}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
