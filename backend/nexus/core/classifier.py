"""Intent classifier (Doc 02 §4). Es una señal de enrutamiento, nunca autorización.

Híbrido (T1): si hay un modelo propio ACTIVO (entrenado, evaluado y promovido por el propietario,
nexus.learning) y está seguro, decide él; si se abstiene, deciden las reglas explícitas; si tampoco
aplican, `conversation` (la vía segura: sin herramientas). Idea de corroboración tomada de
Primitivo `source_router.py` (allí con LLM; aquí con un modelo propio y medible).
"""
import re

from nexus.contracts import RequestClass

RULES: list[tuple[RequestClass, str]] = [
    ("rule_proposal", r"\b(cada vez que|siempre que|nunca (?:hagas|permitas))\b"),
    ("memory_update", r"\b(recuerda que|guarda que|mi nombre es|prefiero)\b"),
    ("knowledge_query", r"\b(seg[uú]n (?:mis|los|tus) (?:documentos|notas)|en mis (?:documentos|notas)"
                        r"|documentaci[oó]n|qu[eé] dice|busca en|qu[eé] sabes (?:de|sobre))\b"),
    ("task_request", r"\b(recuérdame|recuerdame|programa|ejecuta|crea|envía|envia|haz"
                     r"|qu[eé] hora|qu[eé] d[ií]a|fecha de hoy)\b"),
    ("agent_request", r"\b(github|repositorios?|correos?|e-?mails?|youtube)\b"),
]

ROUTING_PHRASES = re.compile(
    r"(?i)\b(seg[uú]n (?:mis|los|tus) (?:documentos|notas)|en mis (?:documentos|notas)"
    r"|busca en (?:mis )?(?:documentos|notas)|qu[eé] sabes (?:de|sobre))\b[\s,:]*")

_model = None  # IntentModel activo (nexus.learning.registry.activate_intent)


def set_model(model) -> None:
    global _model
    _model = model


def active_model():
    return _model


def strip_routing(text: str) -> str:
    """Quita las frases que solo enrutan ("según mis documentos"): no son contenido a buscar."""
    return ROUTING_PHRASES.sub("", text).strip() or text


def _too_short(text: str) -> bool:
    return len(re.findall(r"\w", text)) < 2


def _rule(text: str) -> RequestClass | None:
    t = text.lower()
    return next((label for label, pattern in RULES if re.search(pattern, t)), None)


def rules_classify(text: str) -> RequestClass:
    """Línea base de reglas (la que un modelo nuevo debe superar para promoverse)."""
    if _too_short(text):
        return "unknown"
    return _rule(text) or "conversation"


def classify(text: str) -> RequestClass:
    if _too_short(text):
        return "unknown"  # sin señal suficiente: abstenerse y preguntar
    if _model is not None:
        label, _confidence = _model.predict(text)
        if label is not None:
            return label
    return _rule(text) or "conversation"
