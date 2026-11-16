"""Identidad (Doc 03 §3.5): nombre de la IA y del propietario. Datos estables, no memoria: no salen de hechos."""
import sqlalchemy as sa

DEFAULT_NAME = "NEXUS"


def get(conn, owner: str) -> dict:
    row = conn.execute(sa.text("SELECT assistant_name, owner_name FROM identity WHERE owner_id=:o"),
                       {"o": owner}).first()
    name, who = (row.assistant_name, row.owner_name) if row else (DEFAULT_NAME, None)
    return {"assistant_name": name, "owner_name": who, "configured": who is not None}


def put(conn, owner: str, assistant_name: str, owner_name: str) -> dict:
    conn.execute(sa.text(
        "INSERT INTO identity (owner_id, assistant_name, owner_name) VALUES (:o, :a, :n) "
        "ON CONFLICT (owner_id) DO UPDATE SET assistant_name=:a, owner_name=:n, updated_at=now()"),
        {"o": owner, "a": assistant_name, "n": owner_name})
    return get(conn, owner)


def prompt(conn, owner: str) -> str:
    i = get(conn, owner)
    who = f" El propietario se llama {i['owner_name']}." if i["owner_name"] else ""
    return f"Te llamas {i['assistant_name']}.{who}"
