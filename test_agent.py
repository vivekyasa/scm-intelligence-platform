"""
Tests for the agent loop using a fake model and a fake database,
so they run offline, instantly and for free.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types

import app as app_module
from sql_guard import UnsafeSQL


def make_response(text=None, sql=None, name="query_planning_db"):
    """Build an object shaped like a Gemini response."""
    if sql is not None:
        part = types.Part.from_function_call(name=name, args={"sql": sql})
        content = types.Content(role="model", parts=[part])
        fc = SimpleNamespace(name=name, args={"sql": sql})
        return SimpleNamespace(
            function_calls=[fc], text=None,
            candidates=[SimpleNamespace(content=content)],
        )
    content = types.Content(role="model", parts=[types.Part.from_text(text=text)])
    return SimpleNamespace(
        function_calls=None, text=text,
        candidates=[SimpleNamespace(content=content)],
    )


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(app_module.time, "sleep", lambda s: None)


def use(monkeypatch, script, rows=None, run_query=None):
    client = FakeClient(script)
    monkeypatch.setattr(app_module, "get_client", lambda: client)
    monkeypatch.setattr(
        app_module, "run_query",
        run_query or (lambda sql: rows if rows is not None else []),
    )
    return client


def test_answer_without_tool(monkeypatch):
    use(monkeypatch, [make_response(text="Hello")])
    r = app_module.answer_question("hi there")
    assert r.answer == "Hello"
    assert r.tool_calls == []


def test_tool_call_then_answer(monkeypatch):
    rows = [{"item_number": "SKU-1052", "lead_time_days": 45}]
    use(monkeypatch, [
        make_response(sql="SELECT item_number FROM items LIMIT 1"),
        make_response(text="SKU-1052 has the longest lead time at 45 days."),
    ], rows=rows)
    r = app_module.answer_question("longest lead time?")
    assert "45 days" in r.answer
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].row_count == 1
    assert r.rows == rows


def test_unsafe_sql_is_rejected_and_model_recovers(monkeypatch):
    def rq(sql):
        if "DROP" in sql:
            raise UnsafeSQL("Only SELECT queries are allowed.")
        return [{"n": 5}]

    use(monkeypatch, [
        make_response(sql="DROP TABLE items"),
        make_response(sql="SELECT COUNT(*) AS n FROM items"),
        make_response(text="There are 5 items."),
    ], run_query=rq)
    r = app_module.answer_question("count items")
    assert r.answer == "There are 5 items."
    assert r.tool_calls[0].error and "Rejected" in r.tool_calls[0].error
    assert r.tool_calls[1].error is None


def test_step_cap(monkeypatch):
    use(monkeypatch,
        [make_response(sql="SELECT 1") for _ in range(app_module.MAX_STEPS)],
        rows=[{"x": 1}])
    r = app_module.answer_question("loop forever")
    assert "step limit" in r.answer
    assert len(r.tool_calls) == app_module.MAX_STEPS


def test_falls_back_to_next_model_on_overload(monkeypatch):
    busy = errors.ServerError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}}, None)
    client = use(monkeypatch, [busy, busy, make_response(text="ok from second model")])
    r = app_module.answer_question("anything")
    assert r.answer == "ok from second model"
    assert client.calls[0] == app_module.MODELS[0]
    assert client.calls[-1] == app_module.MODELS[1]
    assert r.model == app_module.MODELS[1]


def test_skips_model_when_quota_exhausted(monkeypatch):
    quota = errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}, None)
    client = use(monkeypatch, [quota, make_response(text="fine")])
    r = app_module.answer_question("anything")
    assert r.answer == "fine"
    assert client.calls == [app_module.MODELS[0], app_module.MODELS[1]]


def test_all_models_down_returns_503(monkeypatch):
    busy = errors.ServerError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}}, None)
    use(monkeypatch, [busy] * (len(app_module.MODELS) * app_module.RETRIES_PER_MODEL))
    client = TestClient(app_module.app)
    resp = client.post("/ask", json={"question": "anything at all"})
    assert resp.status_code == 503


def test_endpoint_validates_input():
    client = TestClient(app_module.app)
    assert client.post("/ask", json={"question": "a"}).status_code == 422
    assert client.post("/ask", json={}).status_code == 422
    assert client.get("/health").json()["status"] == "ok"


def test_endpoint_end_to_end(monkeypatch):
    use(monkeypatch, [make_response(text="Fine.")])
    client = TestClient(app_module.app)
    resp = client.post("/ask", json={"question": "how are things?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Fine."
    assert set(body) == {"answer", "model", "latency_ms", "tool_calls", "rows"}
