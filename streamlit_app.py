import asyncio
import os
import sys
import threading
from pathlib import Path

import google.genai as genai
from google.genai import types
import streamlit as st
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ─── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Weather MCP",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Async bridge (one background event loop for the whole app) ───────────────

@st.cache_resource
def _bg_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def arun(coro, timeout: int = 60):
    return asyncio.run_coroutine_threadsafe(coro, _bg_loop()).result(timeout=timeout)

# ─── Schema conversion (JSON Schema → google.genai types.Schema) ─────────────

def _schema_to_genai(s: dict) -> types.Schema:
    TYPE = {
        "string": types.Type.STRING,
        "number": types.Type.NUMBER,
        "integer": types.Type.INTEGER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
        "object": types.Type.OBJECT,
    }
    t = TYPE.get(s.get("type", "string"), types.Type.STRING)
    kw: dict = {"type": t}
    if d := s.get("description"):
        kw["description"] = d
    if t == types.Type.ARRAY and "items" in s:
        kw["items"] = _schema_to_genai(s["items"])
    if t == types.Type.OBJECT and "properties" in s:
        kw["properties"] = {k: _schema_to_genai(v) for k, v in s["properties"].items()}
        kw["required"] = s.get("required", [])
    return types.Schema(**kw)

# ─── MCP connection (shared singleton) ───────────────────────────────────────

class _MCP:
    session: ClientSession
    tools: list
    fn_decls: list
    _cm1: object
    _cm2: object


@st.cache_resource
def get_mcp() -> _MCP:
    mcp = _MCP()

    async def _init():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).parent / "main.py")],
        )
        mcp._cm1 = stdio_client(params)
        r, w = await mcp._cm1.__aenter__()
        mcp._cm2 = ClientSession(r, w)
        mcp.session = await mcp._cm2.__aenter__()
        await mcp.session.initialize()

        res = await mcp.session.list_tools()
        mcp.tools = res.tools
        mcp.fn_decls = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description or "",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        k: _schema_to_genai(v)
                        for k, v in (t.inputSchema.get("properties") or {}).items()
                    },
                    required=t.inputSchema.get("required") or [],
                ),
            )
            for t in res.tools
        ]

    arun(_init())
    return mcp

# ─── Agentic loop ─────────────────────────────────────────────────────────────

def query(message: str, mcp: _MCP, api_key: str) -> dict:
    """
    Runs the full Gemini + MCP tool-use loop.
    Returns {"response": str, "tool_calls": [{"name", "args", "result"}]}
    """
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=mcp.fn_decls)],
    )
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=message)])
    ]

    async def _loop() -> dict:
        tool_calls: list[dict] = []

        while True:
            response = await client.aio.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=contents,
                config=config,
            )

            # Check for function calls in response
            fn_calls = response.function_calls
            if not fn_calls:
                return {"response": response.text or "", "tool_calls": tool_calls}

            # Append the model's response (with function calls) to history
            contents.append(response.candidates[0].content)

            # Execute each tool and collect function response parts
            fn_response_parts: list[types.Part] = []
            for fn in fn_calls:
                res = await mcp.session.call_tool(fn.name, dict(fn.args or {}))
                result_text = "\n".join(
                    c.text for c in res.content if hasattr(c, "text")
                )
                tool_calls.append(
                    {"name": fn.name, "args": dict(fn.args or {}), "result": result_text}
                )
                fn_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fn.name,
                            response={"output": result_text},
                        )
                    )
                )

            # Append function results as a user turn
            contents.append(
                types.Content(role="user", parts=fn_response_parts)
            )

    return arun(_loop())

# ─── Data ─────────────────────────────────────────────────────────────────────

TOOL_EXAMPLES = {
    "get_weather":            "What is the current weather in Tokyo?",
    "get_forecast":           "Give me a 5-day forecast for Paris.",
    "get_hourly_forecast":    "Show me hourly weather for Singapore today.",
    "compare_cities_weather": "Compare weather in New York, London, and Dubai.",
    "should_i_bring_umbrella":"Should I bring an umbrella in Mumbai today?",
    "get_air_quality":        "What is the air quality in Beijing?",
    "get_weather_alerts":     "Are there any weather warnings for Florida this week?",
    "get_uv_index":           "What is the UV index in Sydney for the next 3 days?",
    "get_sunrise_sunset":     "What time does the sun rise in Oslo this week?",
    "get_historical_weather": "What was the weather in London on 2024-07-04?",
    "get_pollen_forecast":    "What are the pollen levels in Berlin today?",
    "get_marine_weather":     "What are the wave conditions in Lisbon?",
}

# ─── Init ─────────────────────────────────────────────────────────────────────

api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    st.error("GEMINI_API_KEY environment variable is not set.")
    st.stop()

mcp = get_mcp()

if "messages" not in st.session_state:
    st.session_state.messages = []

# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Weather MCP")
    st.caption("Powered by Gemini 3.1 Flash Lite")
    st.divider()

    st.markdown("**Available Tools**")
    st.caption(f"{len(mcp.tools)} tools connected to Open-Meteo APIs")

    for t in mcp.tools:
        label = t.name.replace("_", " ").title()
        with st.expander(label):
            st.caption(t.description or "")
            if t.name in TOOL_EXAMPLES:
                if st.button(
                    "Try example",
                    key=f"ex_{t.name}",
                    use_container_width=True,
                ):
                    st.session_state.pending = TOOL_EXAMPLES[t.name]

    st.divider()
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ─── Chat ─────────────────────────────────────────────────────────────────────

# Render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            n = len(msg["tool_calls"])
            label = f"{n} tool{'s' if n > 1 else ''} used"
            with st.expander(label, expanded=False):
                for tc in msg["tool_calls"]:
                    name = tc["name"].replace("_", " ").title()
                    st.markdown(f"**{name}**")
                    if tc["args"]:
                        cols = st.columns(max(len(tc["args"]), 1))
                        for i, (k, v) in enumerate(tc["args"].items()):
                            cols[i].metric(label=k, value=str(v))
                    st.code(tc["result"], language=None)
                    st.divider()
        st.write(msg["content"])

# Pick up input from sidebar button or chat field
effective_input = st.session_state.pop("pending", None)
typed = st.chat_input("Ask about weather, forecasts, air quality, UV index, marine conditions...")
if typed:
    effective_input = typed

# Process message
if effective_input:
    st.session_state.messages.append({"role": "user", "content": effective_input})

    with st.chat_message("user"):
        st.write(effective_input)

    with st.chat_message("assistant"):
        with st.spinner("Calling tools and generating response..."):
            try:
                result = query(effective_input, mcp, api_key)
            except Exception as e:
                st.error(f"Error: {e}")
                st.stop()

        if result["tool_calls"]:
            n = len(result["tool_calls"])
            label = f"{n} tool{'s' if n > 1 else ''} used"
            with st.expander(label, expanded=True):
                for tc in result["tool_calls"]:
                    name = tc["name"].replace("_", " ").title()
                    st.markdown(f"**{name}**")
                    if tc["args"]:
                        cols = st.columns(max(len(tc["args"]), 1))
                        for i, (k, v) in enumerate(tc["args"].items()):
                            cols[i].metric(label=k, value=str(v))
                    st.code(tc["result"], language=None)
                    st.divider()

        st.write(result["response"])

    st.session_state.messages.append({
        "role": "assistant",
        "content": result["response"],
        "tool_calls": result["tool_calls"],
    })
