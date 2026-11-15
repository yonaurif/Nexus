"""Fase M0 (Doc 03 §17, Doc 02 §13): migraciones, tareas persistidas, eventos append-only, registry en DB."""
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from nexus.contracts import ToolManifest
from nexus.core.state import InvalidTransition, TaskStatus
from nexus.core import task_store
from nexus.gateway.registry import GatewayError, SqlToolRegistry

from tests.test_c0_g0 import MANIFEST


def test_pgvector_extension_installed(conn):
    assert conn.scalar(sa.text("SELECT extversion FROM pg_extension WHERE extname='vector'"))


def test_m0_tables_exist(conn):
    names = set(sa.inspect(conn).get_table_names())
    assert {"tasks", "plans", "plan_steps", "tool_executions", "execution_events",
            "audit_events", "memory_sources", "tools"} <= names


def test_task_lifecycle_persists_and_emits_events(conn):
    tid = task_store.create_task(conn, owner_id="owner", goal="g", correlation_id="corr_1")
    task_store.set_status(conn, tid, TaskStatus.classifying)
    task_store.set_status(conn, tid, TaskStatus.context_building)
    assert task_store.get_status(conn, tid) is TaskStatus.context_building
    events = conn.execute(sa.text(
        "SELECT event_type, correlation_id, payload->>'to' FROM execution_events "
        "WHERE entity_id=:t ORDER BY id"), {"t": tid}).all()
    assert [e[2] for e in events] == ["created", "classifying", "context_building"]
    assert all(e[0] == "task.status.changed" and e[1] == "corr_1" for e in events)


def test_invalid_transition_does_not_write(conn):
    tid = task_store.create_task(conn, owner_id="owner", goal="g", correlation_id="c")
    with pytest.raises(InvalidTransition):
        task_store.set_status(conn, tid, TaskStatus.completed)
    assert task_store.get_status(conn, tid) is TaskStatus.created


def test_events_are_append_only(conn):
    tid = task_store.create_task(conn, owner_id="owner", goal="g", correlation_id="c")
    for stmt in ["UPDATE execution_events SET event_type='x' WHERE entity_id=:t",
                 "DELETE FROM execution_events WHERE entity_id=:t"]:
        with pytest.raises(DBAPIError, match="append-only"):
            with conn.begin_nested():
                conn.execute(sa.text(stmt), {"t": tid})


def test_sql_registry_requires_approval_and_detects_changes(conn):
    reg = SqlToolRegistry(conn)
    reg.register(ToolManifest(**MANIFEST))
    with pytest.raises(GatewayError, match="TOOL_NOT_ALLOWED"):
        reg.resolve("example.repository.get")
    reg.approve("example.repository.get")
    assert reg.resolve("example.repository.get").tool_id == "example.repository.get"
    reg.register(ToolManifest(**{**MANIFEST, "description": "ahora también borra"}))
    with pytest.raises(GatewayError, match="TOOL_DEFINITION_CHANGED"):
        reg.resolve("example.repository.get")


def test_plan_validator_uses_sql_registry(conn):
    from nexus.core.plan_validator import PlanRejected, validate_plan
    from tests.test_c0_g0 import make_plan, tool_step

    reg = SqlToolRegistry(conn)
    reg.register(ToolManifest(**MANIFEST))
    with pytest.raises(PlanRejected, match="TOOL_NOT_ALLOWED"):
        validate_plan(make_plan([tool_step("a")]), reg)
    reg.approve("example.repository.get")
    validate_plan(make_plan([tool_step("a")]), reg)
