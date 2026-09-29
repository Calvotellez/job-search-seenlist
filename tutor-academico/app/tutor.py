"""Capa de IA: construye los prompts y llama a Claude."""
import os

from . import rag
from .profiles import system_prompt

HISTORY_TURNS = 12


class LLMUnavailable(RuntimeError):
    pass


def complete(system: str, messages: list[dict], max_tokens: int = 1500) -> str:
    """Única función que toca la API; los tests la reemplazan."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailable("Falta ANTHROPIC_API_KEY en el archivo .env")
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=os.environ.get("TUTOR_MODEL", "claude-sonnet-5-5"),
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def chat(course: dict, history: list[dict], question: str) -> tuple[str, list[dict]]:
    fragments = rag.search(course["id"], question)
    system = (
        system_prompt(course["profile"], course["notes"])
        + f"\nCurso: {course['name']}\n\nFRAGMENTOS DEL MATERIAL:\n"
        + rag.format_fragments(fragments)
    )
    messages = history[-HISTORY_TURNS:] + [{"role": "user", "content": question}]
    return complete(system, messages), fragments


def plan_task(course: dict, title: str, description: str, due: str | None) -> str:
    fragments = rag.search(course["id"], f"{title} {description}", k=4)
    system = (
        system_prompt(course["profile"], course["notes"])
        + "\nTu tarea ahora: crear un PLAN DE TRABAJO para una tarea académica. "
        "Devuelve una lista numerada de 4 a 8 pasos concretos, cada uno con una "
        "estimación de tiempo. No resuelvas la tarea; indica qué hacer y qué preguntas "
        "responder en cada paso. Si hay fecha de entrega, reparte los pasos hasta esa fecha.\n\n"
        "FRAGMENTOS DEL MATERIAL:\n" + rag.format_fragments(fragments)
    )
    prompt = f"Tarea: {title}\nDescripción: {description or '(sin descripción)'}\nEntrega: {due or 'sin fecha'}"
    return complete(system, [{"role": "user", "content": prompt}], max_tokens=1000)


def make_quiz(course: dict, topic: str, n: int = 5) -> str:
    fragments = rag.search(course["id"], topic, k=6) if topic.strip() else rag.sample(course["id"])
    system = (
        system_prompt(course["profile"], course["notes"])
        + f"\nTu tarea ahora: crear un QUIZ de {n} preguntas para que el estudiante se autoevalúe, "
        "mezclando preguntas abiertas y de opción múltiple, basadas en los fragmentos. "
        "Escribe primero SOLO las preguntas numeradas y después, bajo el encabezado "
        "'## Respuestas', las respuestas modelo breves.\n\nFRAGMENTOS DEL MATERIAL:\n"
        + rag.format_fragments(fragments)
    )
    prompt = f"Tema: {topic or 'general del curso'}"
    return complete(system, [{"role": "user", "content": prompt}], max_tokens=1500)
