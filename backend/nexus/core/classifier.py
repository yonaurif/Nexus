"""Intent classifier simple de C1 (Doc 02 §4). Es una señal de enrutamiento, nunca autorización.

ponytail: reglas por palabras clave en orden; se sustituye por TF-IDF + LogisticRegression
con abstención calibrada en T1 (Text Learning §4.3).
"""
import re

from nexus.contracts import RequestClass

RULES: list[tuple[RequestClass, str]] = [
    ("rule_proposal", r"\b(cada vez que|siempre que|nunca (?:hagas|permitas))\b"),
    ("memory_update", r"\b(recuerda que|guarda que|mi nombre es|prefiero)\b"),
    ("task_request", r"\b(recuérdame|recuerdame|programa|ejecuta|crea|envía|envia|haz)\b"),
    ("agent_request", r"\b(github|repositorios?|correos?|e-?mails?|youtube)\b"),
    ("knowledge_query", r"\b(documentaci[oó]n|qué dice|que dice|busca en)\b"),
]


def classify(text: str) -> RequestClass:
    t = text.lower()
    if len(re.findall(r"\w", t)) < 2:
        return "unknown"  # sin señal suficiente: abstenerse y preguntar
    for label, pattern in RULES:
        if re.search(pattern, t):
            return label
    return "conversation"
