"""
SCM Planning Intelligence API.

Ask a question in plain English. A Gemini model decides which tool to use:

  query_planning_db  writes a SQL query, checked by sql_guard and run as a
                     read-only database user (numbers, counts, rankings)
  search_documents   searches the policy documents by meaning with pgvector
                     (rules, thresholds, procedures)

It can use one or both, then answers in plain English with sources.

Run:
    py -m uvicorn app:app --reload
Then open http://127.0.0.1:8000/docs

Environment variables:
    GEMINI_API_KEY   your Google AI Studio key
    DATABASE_URL_RO  connection string for the read-only planner_ro user
    GEMINI_MODELS    optional, comma separated, tried in order
    EMBED_MODEL      optional, embedding model name
"""

import json
import os
import time
from contextlib import closing
from datetime import date, timedelta
from typing import Any

import psycopg2
from fastapi import FastAPI, HTTPException
from google.genai import errors, types
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from embeddings import EmbeddingError
from gemini import get_client
from retrieval import search_documents
from sql_guard import UnsafeSQL, validate_sql

# ----------------------------------------------------------------- config

MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-flash-lite-latest,gemini-2.5-flash-lite,gemini-3.1-flash-lite",
    ).split(",")
    if m.strip()
]
MAX_STEPS = 5            # the agent may call the model at most this many times
MAX_ROWS = 200           # hard cap on rows pulled from the database
ROWS_TO_MODEL = 50       # rows the model gets to see
RETRIES_PER_MODEL = 2    # for temporary 5xx errors

SQL_TOOL = "query_planning_db"
DOC_TOOL = "search_documents"


# ----------------------------------------------------------------- models

class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class ToolCall(BaseModel):
    tool: str
    input: str
    row_count: int = 0
    error: str | None = None


class Source(BaseModel):
    doc_title: str
    section: str
    score: float


class AskResponse(BaseModel):
    answer: str
    model: str
    latency_ms: int
    tool_calls: list[ToolCall]
    sources: list[Source]
    rows: list[dict[str, Any]]


# ----------------------------------------------------------------- prompt

SCHEMA = """
Tables (PostgreSQL, schema public). Weeks always start on a Monday.

items(item_id, item_number, description, product_family, abc_class, unit_cost,
      lead_time_days, safety_stock_qty, min_order_qty, planner_code)
  abc_class is 'A', 'B' or 'C'. item_number looks like SKU-1001.
locations(location_id, location_code, location_name, region, location_type)
  location_type is PLANT, DC or FORWARD_STOCK.
demand_forecast(item_id, location_id, week_start, forecast_version, forecast_qty)
actual_demand(item_id, location_id, week_start, actual_qty)
  only exists for weeks in the past.
supply_plan(item_id, location_id, week_start, planned_receipt_qty,
            planned_order_qty, source_type)
  source_type is BUY, MAKE or TRANSFER.
inventory_position(item_id, location_id, week_start, opening_on_hand_qty,
                   projected_available_qty)
  a negative projected_available_qty means a shortage.
plan_exceptions(exception_id, item_id, location_id, week_start, exception_type,
                severity, quantity_impact, message)
  exception_type is SHORTAGE, BELOW_SAFETY_STOCK, EXCESS or NO_SUPPLY.
  severity is HIGH, MEDIUM or LOW.

Join on item_id and location_id. Join items to get item_number and
product_family, join locations to get location_code and region.
The data covers about 26 weeks in the past and 25 weeks into the future.
""".strip()


def build_system_prompt() -> str:
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    return f"""You are a supply chain planning analyst assistant.
You have two tools:

1. {SQL_TOOL}: run one read-only SQL SELECT query. Use it for numbers, counts,
   rankings, trends and anything about specific items or locations.
2. {DOC_TOOL}: search the company planning policy documents. Use it for rules,
   thresholds, targets, approval limits, response times and procedures.

Use both when a question mixes data and policy, for example "is this item's
shortage serious enough to escalate": first get the numbers, then find the rule,
then compare them.

Today is {today.isoformat()}. The current planning week starts {this_monday.isoformat()}.

{SCHEMA}

Rules:
- SQL: only SELECT queries (a leading WITH is fine). No comments, no semicolons
  except at the very end, no system tables. Add LIMIT 50 unless the query
  returns a handful of aggregate rows. Always include item_number when you
  mention items. If the tool returns an error, fix the query and try again.
- Documents: base policy statements only on passages the tool returns. Each
  passage has a score from 0 to 1 for how closely it matches. If the passages
  do not actually answer the question, say the policies do not cover it. Do not
  fill the gap from general knowledge.
- Never invent numbers. Every figure must come from a query result or a passage.
- When you state a policy rule, name the document it came from, for example
  (Source: Shortage Escalation Policy).
- Final answer: plain English, lead with the answer, include the key numbers,
  keep it short. Do not show the SQL unless the user asks for it.
"""


TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name=SQL_TOOL,
            description=(
                "Run one read-only SQL SELECT query against the supply chain "
                "planning database and return the rows."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "sql": types.Schema(
                        type=types.Type.STRING,
                        description="A single PostgreSQL SELECT query.",
                    )
                },
                required=["sql"],
            ),
        ),
        types.FunctionDeclaration(
            name=DOC_TOOL,
            description=(
                "Search the company planning policy documents by meaning and "
                "return the most relevant passages. Use for rules, thresholds, "
                "targets, approval limits and procedures."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "What to look up, phrased as a short question or "
                            "topic, for example 'safety stock target for class A'."
                        ),
                    )
                },
                required=["query"],
            ),
        ),
    ]
)


# ----------------------------------------------------------------- database

def run_query(sql: str) -> list[dict[str, Any]]:
    """Validate, then run as the read-only user. Always capped at MAX_ROWS."""
    url = os.environ.get("DATABASE_URL_RO")
    if not url:
        raise RuntimeError("DATABASE_URL_RO is not set")

    clean = validate_sql(sql)
    wrapped = f"SELECT * FROM ({clean}) AS q LIMIT {MAX_ROWS}"

    with closing(psycopg2.connect(url, connect_timeout=10)) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(wrapped)
            return [dict(r) for r in cur.fetchall()]


def to_jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dates and Decimals become strings so the model can read them."""
    return json.loads(json.dumps(rows, default=str))


# ----------------------------------------------------------------- model

def call_model(client, contents, config):
    """Try each model in turn. Retry temporary overloads, skip exhausted quotas."""
    last_error = None
    for model in MODELS:
        for attempt in range(RETRIES_PER_MODEL):
            try:
                return model, client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except errors.APIError as e:
                last_error = e
                if e.code in (500, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if e.code in (404, 429):
                    break  # model missing or quota used up: try the next one
                raise
    raise HTTPException(
        status_code=503,
        detail=f"All models are busy or out of quota right now. Last error: {last_error}",
    )


# ----------------------------------------------------------------- tools

def first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0]


def use_sql_tool(args: dict, state: dict) -> dict:
    sql = str(args.get("sql", ""))
    try:
        rows = run_query(sql)
        state["rows"] = rows
        state["calls"].append(ToolCall(tool=SQL_TOOL, input=sql, row_count=len(rows)))
        return {"row_count": len(rows), "rows": to_jsonable(rows[:ROWS_TO_MODEL])}
    except UnsafeSQL as e:
        msg = f"Rejected by safety check: {e}"
    except psycopg2.Error as e:
        msg = f"Database error: {first_line(e)}"
    state["calls"].append(ToolCall(tool=SQL_TOOL, input=sql, error=msg))
    return {"error": msg}


def use_doc_tool(args: dict, state: dict) -> dict:
    query = str(args.get("query", ""))
    try:
        hits = search_documents(query)
    except (EmbeddingError, RuntimeError) as e:
        msg = f"Document search failed: {e}"
    except psycopg2.Error as e:
        msg = f"Database error: {first_line(e)}"
    else:
        state["calls"].append(ToolCall(tool=DOC_TOOL, input=query, row_count=len(hits)))
        for h in hits:
            key = (h["doc_title"], h["section"])
            best = state["sources"].get(key, 0.0)
            state["sources"][key] = max(best, h["score"])
        return {
            "results": [
                {
                    "source": f"{h['doc_title']} > {h['section']}",
                    "score": h["score"],
                    "text": h["content"],
                }
                for h in hits
            ]
        }
    state["calls"].append(ToolCall(tool=DOC_TOOL, input=query, error=msg))
    return {"error": msg}


TOOLS = {SQL_TOOL: use_sql_tool, DOC_TOOL: use_doc_tool}


# ----------------------------------------------------------------- agent

def answer_question(question: str) -> AskResponse:
    started = time.time()
    client = get_client()
    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(),
        tools=[TOOL],
        temperature=0.1,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]

    state: dict[str, Any] = {"calls": [], "rows": [], "sources": {}}
    model_used = MODELS[0]

    def build(answer: str) -> AskResponse:
        sources = [
            Source(doc_title=t, section=s, score=score)
            for (t, s), score in sorted(state["sources"].items(), key=lambda kv: -kv[1])
        ]
        return AskResponse(
            answer=answer,
            model=model_used,
            latency_ms=int((time.time() - started) * 1000),
            tool_calls=state["calls"],
            sources=sources,
            rows=state["rows"][:ROWS_TO_MODEL],
        )

    for _ in range(MAX_STEPS):
        model_used, response = call_model(client, contents, config)
        function_calls = response.function_calls or []

        if not function_calls:
            text = (response.text or "").strip()
            if not text:
                text = "I could not produce an answer. Try rephrasing the question."
            return build(text)

        contents.append(response.candidates[0].content)
        reply_parts = []
        for fc in function_calls:
            handler = TOOLS.get(fc.name)
            if handler is None:
                payload = {"error": f"Unknown tool {fc.name}"}
                state["calls"].append(ToolCall(tool=str(fc.name), input="", error=payload["error"]))
            else:
                payload = handler(dict(fc.args or {}), state)
            reply_parts.append(
                types.Part.from_function_response(name=fc.name, response=payload)
            )
        contents.append(types.Content(role="user", parts=reply_parts))

    return build("I reached the step limit before finishing. Try a more specific question.")


# ----------------------------------------------------------------- api

app = FastAPI(
    title="SCM Planning Intelligence API",
    version="0.3.0",
    description="Ask questions about supply chain planning data and policies in plain English.",
)


@app.get("/health")
def health():
    return {"status": "ok", "models": MODELS}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    return answer_question(request.question)
