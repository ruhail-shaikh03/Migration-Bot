import json
import asyncio
import streamlit as st
from difflib import get_close_matches

from src.llm.deepseek_client import get_deepseek_client
from src.llm.tools import TOOLS, SYSTEM_PROMPT, VALID_MODULES
from src.sheets.executor import SheetsExecutor
from src.sheets.column_map import resolve_column, get_column_map_json



# ── Core orchestration (async, called via asyncio.run) ───────────────────────

def _dispatch_tool(name: str, args: dict, executor: SheetsExecutor) -> dict:
    try:
        if name == "get_row":
            return executor.get_row(**args)

        if name == "update_cell":
            results = []
            for upd in args.get("updates", []):
                col = resolve_column(upd["field"]) or upd["field"]
                results.append(executor.update_cell(args["ricefw_id"], col, upd["value"]))
            return {"updates": results}

        if name == "format_row":
            return executor.format_row(**args)

        if name == "add_row":
            next_id = executor.next_ricefw_id(args["module"])
            return executor.add_row(next_id, **args)

        return {"ok": False, "error": f"Unknown tool: {name}"}

    except Exception as ex:
        return {"ok": False, "error": str(ex)}

async def _handle(messages: list, executor: SheetsExecutor) -> str:
    client = get_deepseek_client()

    # First LLM call — may return a tool_call or a plain clarification
    response = await client.chat.completions.create(
        model="deepseek-reasoner",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=1024,
    )
    msg = response.choices[0].message

    if not msg.tool_calls:
        # DeepSeek is asking for clarification or flagging an issue
        return msg.content

    # Execute every tool call DeepSeek requested
    tool_results = []
    for tc in msg.tool_calls:
        args   = json.loads(tc.function.arguments)
        result = _dispatch_tool(tc.function.name, args, executor)
        tool_results.append({
            "tool_call_id": tc.id,
            "role":         "tool",
            "content":      json.dumps(result)
        })

    # Second LLM call — compose a human-readable reply from the tool results
    messages_with_results = [*messages, msg.model_dump(), *tool_results]
    final = await client.chat.completions.create(
        model="deepseek-reasoner",
        messages=messages_with_results,
        max_tokens=256,
    )
    return final.choices[0].message.content



# ── Page config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MigrationBot",
    page_icon="🤖",
    layout="centered"
)

# ── Step 1: Google OAuth — connect the user's Sheets account ─────────────────

st.title("🤖 MigrationBot")
st.caption("S/4HANA WRICEF Migration Tracker · powered by DeepSeek")

# st.login() / st.user is available in Streamlit ≥ 1.35
if not st.user.is_logged_in:
    st.info("Connect your Google account to read and update the migration tracker.")
    if st.button("🔑 Connect Google Account"):
        st.login()
    st.stop()   # Don't render anything else until logged in

# Show who's connected, with a disconnect option in the sidebar
with st.sidebar:
    st.markdown(f"**Connected as:**  \n{st.user.email}")
    if st.button("Disconnect"):
        st.logout()

# Retrieve the access token Streamlit obtained during the OAuth flow.
# expose_tokens = ["access"] in secrets.toml makes this available.
# 1. First, check if the user is actually logged in to prevent crashes
if st.user.is_logged_in:
    # 2. Access the token through the 'tokens' dictionary
    access_token = st.user.tokens["access"]
else:
    st.warning("Please log in to continue.")
    st.stop() # Halts the script until the user logs in

# ── Step 2: Initialise session state ────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []   # list of {"role": ..., "content": ...}

if "executor" not in st.session_state:
    st.session_state.executor = SheetsExecutor(access_token)

executor: SheetsExecutor = st.session_state.executor

# ── Step 3: Render chat history ──────────────────────────────────────────────

for msg in st.session_state.messages:
    if msg["role"] in ("user", "assistant"):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ── Step 4: Handle new user input ────────────────────────────────────────────

if user_input := st.chat_input("Ask about any WRICEF object…"):
    # Show the user's message immediately
    with st.chat_message("user"):
        st.markdown(user_input)

    # Build the message list for DeepSeek (system + history + new message)
    system_msg = {
        "role": "system",
        "content": SYSTEM_PROMPT.format(
            valid_modules=VALID_MODULES,
            column_map_json=get_column_map_json()
        )
    }
    # Keep last 12 turns (6 back-and-forths) to avoid ballooning token costs
    history = st.session_state.messages[-12:]
    messages = [system_msg, *history, {"role": "user", "content": user_input}]

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            reply = asyncio.run(_handle(messages, executor))
        st.markdown(reply)

    # Persist the turn in session history
    st.session_state.messages.append({"role": "user",      "content": user_input})
    st.session_state.messages.append({"role": "assistant", "content": reply})

