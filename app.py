import json
import time
import pandas as pd
import streamlit as st
from googleapiclient.errors import HttpError
from src.llm.deepseek_client import get_deepseek_client
from src.llm.tools import TOOLS, SYSTEM_PROMPT, VALID_MODULES
from src.sheets.executor import SheetsExecutor
from src.sheets.column_map import resolve_column, get_column_map_json



# ── Orchestration ─────────────────────────────────────────────────────────────
#
# Three-step flow, each step visible to the user:
#
#   1. deepseek-reasoner  — intent parsing + tool selection  (blocking, ~5 s)
#   2. Sheets API         — tool execution                   (blocking, varies)
#   3. deepseek-chat      — response composition             (streamed live)
#
# Step 3 uses deepseek-chat instead of deepseek-reasoner: composing a friendly
# sentence from a JSON result needs no chain-of-thought — chat is 3-5× faster.
# Streaming it means text appears word-by-word, so the user never sees a freeze.

_TOOL_LABELS = {
    "get_row":     "Reading row…",
    "update_cell": "Updating cell…",
    "format_row":  "Formatting row…",
    "add_row":     "Adding row…",
    "bulk_update": "Running bulk update…",
    "search_rows": "Searching sheet…",
    "summarize":   "Running report…",
}

def _stream_chunks(stream):
    """Yield text tokens from an OpenAI streaming response."""
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

def _handle(messages: list, executor: SheetsExecutor) -> str:
    client = get_deepseek_client()

    # ── Step 1: intent parsing + tool selection ──────────────────────────────
    with st.spinner("Analysing your request…"):
        response = client.chat.completions.create(
            model="deepseek-reasoner",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1024,
        )
    msg = response.choices[0].message

    # No tool call → DeepSeek is asking for clarification; stream it directly
    if not msg.tool_calls:
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            stream=True,
            max_tokens=256,
        )
        return st.write_stream(_stream_chunks(stream))

    # ── Step 2: tool execution ───────────────────────────────────────────────
    tool_results = []
    for tc in msg.tool_calls:
        label = _TOOL_LABELS.get(tc.function.name, f"Running {tc.function.name}…")
        args  = json.loads(tc.function.arguments)
        with st.spinner(label):
            result = _dispatch_tool(tc.function.name, args, executor)
        tool_results.append({
            "tool_call_id": tc.id,
            "role":         "tool",
            "content":      json.dumps(result),
        })

    # ── Step 3: stream the human-readable reply ──────────────────────────────
    stream = client.chat.completions.create(
        model="deepseek-chat",          # ← no reasoning needed here
        messages=[*messages, msg.model_dump(), *tool_results],
        stream=True,
        max_tokens=256,
    )
    return st.write_stream(_stream_chunks(stream))


def _dispatch_tool(name: str, args: dict, executor: SheetsExecutor) -> dict:
    try:
        if name == "get_row":
            return executor.get_row(**args)

        if name == "update_cell":
            results = []
            for upd in args.get("updates", []):
                col = resolve_column(upd["field"]) or upd["field"]
                results.append(
                    executor.update_cell(args["ricefw_id"], col, upd["value"])
                )
            return {"updates": results}

        if name == "format_row":
            return executor.format_row(**args)

        if name == "add_row":
            next_id = executor.next_ricefw_id(args["module"])
            return executor.add_row(next_id, **args)

        if name == "bulk_update":
            args["set_field"] = resolve_column(args["set_field"]) or args["set_field"]
            if args.get("filter_by") and args["filter_by"].get("field"):
                args["filter_by"]["field"] = (
                    resolve_column(args["filter_by"]["field"])
                    or args["filter_by"]["field"]
                )
            return executor.bulk_update(**args)

        if name == "search_rows":
            return executor.search_rows(**args)

        if name == "summarize":
            return executor.summarize(**args)

        return {"ok": False, "error": f"Unknown tool: {name}"}

    except Exception as ex:
        return {"ok": False, "error": str(ex)}


# ── Sidebar report rendering ──────────────────────────────────────────────────

def _run_sidebar_report(report_type: str, scope_module: str | None,
                        executor: SheetsExecutor) -> None:
    if report_type == "Count by Dev Status":
        _render_count_report(executor.summarize(
            "count_by_field", group_by_field="Dev Status", scope_module=scope_module
        ))
    elif report_type == "Count by Module":
        _render_count_report(executor.summarize(
            "count_by_field", group_by_field="Module"
        ))
    elif report_type == "Count by Assigned To":
        _render_count_report(executor.summarize(
            "count_by_field", group_by_field="Assigned To", scope_module=scope_module
        ))
    elif report_type == "Completion Rate (Migrate?)":
        _render_completion_report(executor.summarize(
            "completion_rate", completion_field="Migrate?",
            completion_value="Yes", scope_module=scope_module
        ))
    elif report_type == "Blank Dev Status":
        _render_blank_report(executor.summarize(
            "blank_fields", blank_field="Dev Status", scope_module=scope_module
        ))
    elif report_type == "Overdue Items":
        _render_overdue_report(executor.summarize("overdue", scope_module=scope_module))


def _render_count_report(data: dict) -> None:
    if not data.get("ok"):
        st.error(data.get("error", "Unknown error"))
        return
    st.caption(f"**{data['field']}** — {data['scope']} — {data['total_rows']} rows")
    rows = data.get("breakdown", [])
    if rows:
        df = pd.DataFrame(rows)
        df.columns = [data["field"], "Count"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No data.")


def _render_completion_report(data: dict) -> None:
    if not data.get("ok"):
        st.error(data.get("error", "Unknown error"))
        return
    pct = data["completion_pct"]
    st.metric(
        label=f"{data['field']} = '{data['target_value']}'",
        value=f"{pct}%",
        delta=f"{data['completed']} of {data['total_rows']} rows",
    )
    st.progress(int(pct))


def _render_blank_report(data: dict) -> None:
    if not data.get("ok"):
        st.error(data.get("error", "Unknown error"))
        return
    st.metric(
        label=f"Blank '{data['field']}'",
        value=f"{data['blank_count']} rows",
        delta=f"{data['blank_pct']}% of {data['total_rows']}",
    )
    if data["ids"]:
        st.caption("IDs missing this field:")
        st.code(", ".join(data["ids"][:20]))


def _render_overdue_report(data: dict) -> None:
    if not data.get("ok"):
        st.error(data.get("error", "Unknown error"))
        return
    st.metric(
        label="Overdue items",
        value=data["overdue_count"],
        delta=f"of {data['total_rows']} in scope",
    )
    items = data.get("items", [])
    if items:
        df = pd.DataFrame(items).rename(columns={
            "id":           "RICEFW ID",
            "go_live_date": "Go-Live",
            "dev_status":   "Status",
            "days_overdue": "Days Late",
        })
        st.dataframe(
            df.sort_values("Days Late", ascending=False),
            use_container_width=True,
            hide_index=True,
        )



# ── Page config (must be first Streamlit call) ───────────────────────────────

st.set_page_config(
    page_title="MigrationBot",
    page_icon="🤖",
    layout="centered",
)

# ── Logo ──────────────────────────────────────────────────────────────────────
# Drop your logo file into the repo root and set the filename below.
# st.logo() pins it to the top of the sidebar (Streamlit ≥ 1.36).
# Recommended: PNG or SVG, ~200 × 60 px, transparent background.
try:
    st.logo("logo.png", size="large")
except Exception:
    pass  # logo file not present yet — no crash, no noise

# ── Auth gate ────────────────────────────────────────────────────────────────

if not st.user.is_logged_in:
    st.title("🤖 MigrationBot")
    st.markdown(
        "Your AI assistant for the **S/4HANA WRICEF Migration Control Sheet**. "
        "Read, update, search, and report — all in plain English."
    )
    st.button("🔑 Sign in with Google", on_click=st.login, type="primary")
    st.stop()

# ── Token expiry guard ───────────────────────────────────────────────────────
# Google access tokens live ~3600 s. We log the user out after 55 min
# (5 min buffer) so the token never silently starts returning 401s mid-session.

TOKEN_LIFETIME_SECS = 55 * 60

if "token_issued_at" not in st.session_state:
    st.session_state.token_issued_at = time.time()

if time.time() - st.session_state.token_issued_at > TOKEN_LIFETIME_SECS:
    st.warning("Your session has expired. Please sign in again.")
    st.session_state.clear()
    st.logout()
    st.stop()

access_token = st.user.tokens["access"]

# ── Executor — cached so header/row caches survive reruns ────────────────────
# Rebuilt only when the access token changes.

if (
    "executor" not in st.session_state
    or st.session_state.get("executor_token") != access_token
):
    st.session_state.executor       = SheetsExecutor(access_token)
    st.session_state.executor_token = access_token

executor: SheetsExecutor = st.session_state.executor

# ── Chat history ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.success("✅ Authenticated")
    st.markdown(f"**Connected as:**  \n{st.user.email}")
    st.button("Sign out", on_click=st.logout)

    st.divider()
    st.subheader("📊 Quick Reports")

    report_type = st.selectbox(
        "Report type",
        options=[
            "Count by Dev Status",
            "Count by Module",
            "Count by Assigned To",
            "Completion Rate (Migrate?)",
            "Blank Dev Status",
            "Overdue Items",
        ],
        label_visibility="collapsed",
    )
    scope = st.selectbox(
        "Module scope",
        options=["All modules", "FI", "MM", "SD", "PM", "QM",
                 "PP", "TRM", "HCM", "IM", "CO", "FM", "PS"],
        label_visibility="collapsed",
    )
    scope_module = None if scope == "All modules" else scope

    if st.button("Run Report", use_container_width=True):
        with st.spinner("Fetching…"):
            try:
                _run_sidebar_report(report_type, scope_module, executor)
            except HttpError as e:
                if e.status_code == 401:
                    st.error("Session expired — please sign in again.")
                    st.session_state.clear()
                    st.logout()
                else:
                    st.error(f"Sheets API error: {e}")
            except Exception as e:
                st.error(f"Report error: {e}")

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🤖 MigrationBot")
st.caption("S/4HANA WRICEF Migration Tracker · powered by DeepSeek")

# ── Welcome screen (shown only before the first message) ─────────────────────

EXAMPLE_PROMPTS = [
    "What's the dev status of MM-001?",
    "Set IM-001 status to Ready for Dev",
    "Show me all MM objects with no dev status",
    "Highlight MM-005 red",
    "How many items are in each dev status?",
    "Which MM items are past their go-live date?",
    "Mark MM-001 and MM-002 as migrated",
    "What's our completion rate for Migrate? = Yes?",
]

if not st.session_state.messages:
    first_name = (st.user.name or "").split()[0] or "there"
    st.markdown(f"### Welcome back, {first_name} 👋")
    st.markdown(
        "Ask me anything about the migration tracker in plain English — "
        "I can read rows, update cells, search, bulk-edit, and run reports."
    )
    st.markdown("**Try one of these to get started:**")

    cols = st.columns(2)
    for i, prompt in enumerate(EXAMPLE_PROMPTS):
        if cols[i % 2].button(prompt, key=f"eg_{i}", use_container_width=True):
            st.session_state.prefill = prompt
            st.rerun()

    st.divider()

# ── Render existing chat history ──────────────────────────────────────────────

for msg in st.session_state.messages:
    if msg["role"] in ("user", "assistant"):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ── Handle new input (typed OR from welcome screen example button) ────────────

prefill    = st.session_state.pop("prefill", None)
user_input = st.chat_input("Ask about any WRICEF object…") or prefill

if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)

    system_msg = {
        "role": "system",
        "content": SYSTEM_PROMPT.format(
            valid_modules=VALID_MODULES,
            column_map_json=get_column_map_json(),
        ),
    }
    history  = st.session_state.messages[-12:]
    messages = [system_msg, *history, {"role": "user", "content": user_input}]

    with st.chat_message("assistant"):
        try:
            # _handle streams the final response live via st.write_stream —
            # no outer spinner or st.markdown needed here.
            reply = _handle(messages, executor)
        except HttpError as e:
            if e.status_code == 401:
                st.error("Your session has expired. Signing you out…")
                st.session_state.clear()
                st.logout()
                st.stop()
            else:
                reply = f"⚠️ Sheets API error ({e.status_code}): {e.reason}"
                st.markdown(reply)

    st.session_state.messages.append({"role": "user",      "content": user_input})
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()

