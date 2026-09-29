import pytest
from fastapi.testclient import TestClient

from app import main, rag, tutor


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTOR_DB", str(tmp_path / "t.db"))
    calls = {}

    def fake_complete(system, messages, max_tokens=1500):
        calls["system"], calls["messages"] = system, messages
        return "respuesta simulada"

    monkeypatch.setattr(tutor, "complete", fake_complete)
    with TestClient(main.app) as c:
        c.calls = calls
        yield c


def make_course(client, profile="biblicas"):
    return client.post("/api/courses", json={"name": "Pentateuco", "profile": profile}).json()["id"]


def test_profiles_include_biblicas_and_programacion(client):
    ids = {p["id"] for p in client.get("/api/profiles").json()}
    assert {"general", "biblicas", "programacion"} <= ids


def test_invalid_profile_rejected(client):
    r = client.post("/api/courses", json={"name": "X", "profile": "nope"})
    assert r.status_code == 422


def test_upload_and_chat_uses_material_and_citations(client):
    cid = make_course(client)
    text = "El libro del Génesis narra la creación del mundo y el pacto con Abraham.\n\nÉxodo trata de la liberación."
    r = client.post(f"/api/courses/{cid}/materials", files={"file": ("apuntes.txt", text.encode())})
    assert r.status_code == 200

    r = client.post(f"/api/courses/{cid}/chat", json={"message": "¿Qué pacto hay con Abraham?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "respuesta simulada"
    assert body["sources"][0]["filename"] == "apuntes.txt"
    assert "Ciencias Bíblicas" in client.calls["system"]
    assert "pacto con Abraham" in client.calls["system"]
    assert len(client.get(f"/api/courses/{cid}/messages").json()) == 2


def test_material_is_isolated_per_course(client):
    a, b = make_course(client), make_course(client, "programacion")
    client.post(f"/api/courses/{a}/materials", files={"file": ("a.txt", b"Genesis creacion")})
    assert rag.search(b, "creacion") == []
    assert rag.search(a, "creacion")


def test_unsupported_file(client):
    cid = make_course(client)
    r = client.post(f"/api/courses/{cid}/materials", files={"file": ("x.exe", b"zzz")})
    assert r.status_code == 422


def test_tasks_and_plan(client):
    cid = make_course(client)
    tid = client.post(f"/api/courses/{cid}/tasks", json={"title": "Exégesis de Gn 1", "due": "2026-10-10"}).json()["id"]
    assert client.post(f"/api/tasks/{tid}/plan").json()["plan"] == "respuesta simulada"
    client.patch(f"/api/tasks/{tid}", json={"done": True})
    t = client.get(f"/api/courses/{cid}/tasks").json()[0]
    assert t["done"] == 1 and t["plan"] == "respuesta simulada"


def test_quiz(client):
    cid = make_course(client)
    client.post(f"/api/courses/{cid}/materials", files={"file": ("a.txt", b"Genesis creacion")})
    assert client.post(f"/api/courses/{cid}/quiz", json={"topic": "creacion"}).json()["quiz"]


def test_missing_api_key_gives_503(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTOR_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(main.app) as c:
        cid = c.post("/api/courses", json={"name": "X"}).json()["id"]
        r = c.post(f"/api/courses/{cid}/chat", json={"message": "hola"})
        assert r.status_code == 503


def test_delete_course_cascades(client):
    cid = make_course(client)
    client.post(f"/api/courses/{cid}/materials", files={"file": ("a.txt", b"Genesis creacion")})
    client.delete(f"/api/courses/{cid}")
    assert rag.search(cid, "creacion") == []


def test_chunking_long_text():
    chunks = rag.chunk_text("palabra " * 1000)
    assert len(chunks) > 1 and all(len(c) <= 1300 for c in chunks)
