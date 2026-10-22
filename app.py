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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from google.genai import errors, types
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from embeddings import EmbeddingError
from gemini import get_client
from ratelimit import Limiter
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
    input_tokens: int = 0
    output_tokens: int = 0


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
- Plain text only. Do not use markdown such as ** or #. Short lines starting
  with a dash are fine for lists.
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

    state: dict[str, Any] = {"calls": [], "rows": [], "sources": {}, "tin": 0, "tout": 0}
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
            input_tokens=state["tin"],
            output_tokens=state["tout"],
        )

    for _ in range(MAX_STEPS):
        model_used, response = call_model(client, contents, config)
        usage = getattr(response, "usage_metadata", None)
        state["tin"] += int(getattr(usage, "prompt_token_count", 0) or 0)
        state["tout"] += int(getattr(usage, "candidates_token_count", 0) or 0)
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

LIMITER = Limiter(
    per_ip=int(os.environ.get("LIMIT_PER_MINUTE", "6")),
    per_day=int(os.environ.get("LIMIT_PER_DAY", "200")),
)
STATS = {"requests": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "latencies_ms": []}

app = FastAPI(
    title="SCM Planning Intelligence API",
    version="0.4.0",
    description="Ask questions about supply chain planning data and policies in plain English.",
)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SCM Planning Intelligence</title>
<style>
body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#111}
textarea{width:100%;height:4.5rem;font:inherit;padding:.5rem;box-sizing:border-box}
button{font:inherit;padding:.5rem 1rem;margin:.25rem .25rem .25rem 0;cursor:pointer}
.ex button{font-size:.85rem;padding:.25rem .6rem}
#out{margin-top:1rem;white-space:pre-wrap}.meta{color:#555;font-size:.85rem;margin-top:.5rem}
table{border-collapse:collapse;font-size:.85rem;margin-top:.5rem}td,th{border:1px solid #ccc;padding:.2rem .5rem}
</style></head><body>
<h1>Supply Chain Planning Intelligence</h1>
<p>Ask in plain English about a synthetic planning database (200 items, 5 locations) and company planning policies.
Answers come from SQL queries and policy search, with sources shown.</p>
<div class="ex">
<button>Which class A items have the most SHORTAGE exceptions?</button>
<button>How quickly must we act on a HIGH shortage for a class A item?</button>
<button>How many class B items are there, and what MAPE target applies to class B?</button>
<button>What are our supplier payment terms?</button>
</div>
<textarea id="q" placeholder="Type a question"></textarea><br>
<button id="go">Ask</button>
<div id="out"></div><div class="meta" id="meta"></div><div id="tbl"></div>
<script>
const q=document.getElementById('q'),out=document.getElementById('out'),meta=document.getElementById('meta'),tbl=document.getElementById('tbl');
document.querySelectorAll('.ex button').forEach(b=>b.onclick=()=>{q.value=b.textContent;go()});
document.getElementById('go').onclick=go;
async function go(){
  const text=q.value.trim(); if(text.length<3)return;
  out.textContent='Thinking...';meta.textContent='';tbl.textContent='';
  try{
    const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text})});
    const d=await r.json();
    if(!r.ok){out.textContent=typeof d.detail==='string'?d.detail:'Request failed.';return}
    out.textContent=d.answer;
    const tools=d.tool_calls.map(t=>t.tool+(t.error?' (error)':'')).join(', ')||'none';
    const src=d.sources.map(s=>s.doc_title+' > '+s.section).join('; ')||'none';
    meta.textContent='Tools: '+tools+' | Sources: '+src+' | '+(d.latency_ms/1000).toFixed(1)+'s | '+(d.input_tokens+d.output_tokens)+' tokens | '+d.model;
    if(d.rows.length){
      const cols=Object.keys(d.rows[0]);const t=document.createElement('table');
      const h=t.insertRow();cols.forEach(c=>{const th=document.createElement('th');th.textContent=c;h.appendChild(th)});
      d.rows.slice(0,10).forEach(row=>{const tr=t.insertRow();cols.forEach(c=>{tr.insertCell().textContent=row[c]})});
      tbl.appendChild(t);
    }
  }catch(e){out.textContent='Something went wrong. Please try again.'}
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return PAGE


@app.get("/health")
def health():
    return {"status": "ok", "models": MODELS}


@app.get("/stats")
def stats():
    lat = sorted(STATS["latencies_ms"])
    return {
        "requests": STATS["requests"],
        "errors": STATS["errors"],
        "input_tokens": STATS["input_tokens"],
        "output_tokens": STATS["output_tokens"],
        "median_latency_ms": lat[len(lat) // 2] if lat else None,
        "p95_latency_ms": lat[int(len(lat) * 0.95) - 1] if len(lat) >= 20 else None,
    }


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request):
    blocked = LIMITER.check(client_ip(request))
    if blocked:
        raise HTTPException(status_code=429, detail=blocked)
    STATS["requests"] += 1
    try:
        result = answer_question(body.question)
    except Exception:
        STATS["errors"] += 1
        raise
    STATS["input_tokens"] += result.input_tokens
    STATS["output_tokens"] += result.output_tokens
    STATS["latencies_ms"] = (STATS["latencies_ms"] + [result.latency_ms])[-500:]
    print(json.dumps({"event": "ask", "latency_ms": result.latency_ms, "model": result.model,
                      "tools": [c.tool for c in result.tool_calls],
                      "tokens": result.input_tokens + result.output_tokens}), flush=True)
    return result
