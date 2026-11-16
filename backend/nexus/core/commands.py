"""Comandos del chat (como los «/» de GALA en Primitivo). Fuerzan la ruta: el propietario decide, no el clasificador."""
ROUTES = {"/fuentes": "knowledge_query", "/recuerda": "memory_update"}
HELP = ("Comandos disponibles:\n"
        "- /resumir: resume esta conversación\n"
        "- /fuentes <pregunta>: responde solo con tus documentos y la memoria confirmada, citando la fuente\n"
        "- /recuerda <dato>: lo anota en la memoria como sugerencia\n"
        "- /ayuda: esta lista")
SUMMARY_NOTE = ("Resume la conversación anterior en pocas viñetas: temas, decisiones y pendientes. "
                "Solo lo que se dijo; no añadas nada.")


def parse(text: str) -> tuple[str | None, str]:
    """('/cmd', resto) si el mensaje empieza por un comando; (None, texto) si no."""
    t = text.strip()
    if not t.startswith("/"):
        return None, text
    cmd, _, rest = t.partition(" ")
    return cmd.lower(), rest.strip()
