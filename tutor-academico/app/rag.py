"""Ingesta de material y recuperación por búsqueda de texto completo (SQLite FTS5)."""
import io
import re

from .db import connect

CHUNK_SIZE = 1200
STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "y", "o", "que",
    "en", "por", "para", "con", "se", "su", "sus", "es", "son", "lo", "como", "qué", "cual",
    "cuál", "me", "mi", "te", "a", "ese", "esa", "este", "esta",
}


def extract_pages(filename: str, data: bytes) -> list[tuple[int, str]]:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    if name.endswith((".txt", ".md")):
        return [(1, data.decode("utf-8", errors="replace"))]
    raise ValueError("Formato no soportado. Usa PDF, TXT o MD.")


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        while len(para) > size:  # párrafos gigantes
            cut = para.rfind(" ", 0, size)
            if cut <= 0:
                cut = size
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def add_material(course_id: int, filename: str, data: bytes) -> int:
    pages = extract_pages(filename, data)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO materials (course_id, filename) VALUES (?, ?)", (course_id, filename)
        )
        material_id = cur.lastrowid
        n = 0
        for page, text in pages:
            for chunk in chunk_text(text):
                conn.execute(
                    "INSERT INTO chunks (content, course_id, material_id, filename, page) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (chunk, course_id, material_id, filename, page),
                )
                n += 1
    if n == 0:
        delete_material(material_id)
        raise ValueError("No se pudo extraer texto (¿PDF escaneado?).")
    return material_id


def delete_material(material_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM chunks WHERE material_id = ?", (material_id,))
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))


def _fts_query(question: str) -> str:
    words = [w for w in re.findall(r"\w+", question.lower()) if w not in STOPWORDS and len(w) > 1]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def search(course_id: int, question: str, k: int = 5) -> list[dict]:
    q = _fts_query(question)
    if not q:
        return []
    with connect() as conn:
        rows = conn.execute(
            "SELECT content, filename, page FROM chunks "
            "WHERE chunks MATCH ? AND course_id = ? ORDER BY bm25(chunks) LIMIT ?",
            (q, course_id, k),
        ).fetchall()
    return [dict(r) for r in rows]


def sample(course_id: int, k: int = 8) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT content, filename, page FROM chunks WHERE course_id = ? LIMIT ?",
            (course_id, k),
        ).fetchall()
    return [dict(r) for r in rows]


def format_fragments(fragments: list[dict]) -> str:
    if not fragments:
        return "(No hay fragmentos relevantes en el material del curso.)"
    return "\n\n".join(
        f"[{i}] ({f['filename']}, p. {f['page']})\n{f['content']}"
        for i, f in enumerate(fragments, 1)
    )
