# Tutor Académico

Tutor con IA (Claude) que guía en vez de resolver: método socrático, respuestas ancladas a tu propio material (con citas) y gestor de tareas con plan de trabajo.

## Funciones del MVP
- **Cursos con perfil**: `Ciencias Bíblicas`, `Programación` y `General`.
- **Tutor socrático** con historial por curso.
- **Material**: sube PDF/TXT/MD; el tutor responde citando fragmentos `[1]`, `[2]`… (búsqueda FTS5, sin servicios externos).
- **Tareas**: fecha de entrega y "Plan con IA" que divide la tarea en pasos.
- **Quiz** de autoevaluación generado desde tu material.

## Ejecutar
```bash
cd tutor-academico
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # pon tu ANTHROPIC_API_KEY
uvicorn app.main:app --reload
# abre http://127.0.0.1:8000
```
Pruebas: `pytest` (no requieren API key).

## Añadir otra materia (p. ej. un curso de programación)
Edita `app/profiles.py` y agrega una entrada a `PROFILES` con `name` y `prompt`. Aparece sola en el selector. No hay que tocar nada más.

## Estructura
- `app/profiles.py` – pedagogía por materia
- `app/tutor.py` – prompts y llamada a Claude
- `app/rag.py` – ingesta y recuperación
- `app/main.py` – API FastAPI · `app/static/` – interfaz web

## Hacia multiusuario (siguientes pasos)
Login, aislar datos por usuario, migrar SQLite→Postgres, streaming de respuestas, límites de uso por usuario, embeddings para mejor recuperación, y exportar/importar el plan al calendario.
