import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

# ─── MCP state (singleton, lives for app lifetime) ───────────────────────────

mcp_session: ClientSession | None = None
function_declarations: list = []
cached_tools: list[dict] = []

MAIN_PY = str(Path(__file__).parent / "main.py")


def _json_schema_to_proto(schema: dict) -> genai.protos.Schema:
    type_map = {
        "string": genai.protos.Type.STRING,
        "number": genai.protos.Type.NUMBER,
        "integer": genai.protos.Type.INTEGER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array": genai.protos.Type.ARRAY,
        "object": genai.protos.Type.OBJECT,
    }
    t = type_map.get(schema.get("type", "string"), genai.protos.Type.STRING)
    kwargs: dict = {"type": t}
    if "description" in schema:
        kwargs["description"] = schema["description"]
    if t == genai.protos.Type.ARRAY and "items" in schema:
        kwargs["items"] = _json_schema_to_proto(schema["items"])
    if t == genai.protos.Type.OBJECT and "properties" in schema:
        kwargs["properties"] = {k: _json_schema_to_proto(v) for k, v in schema["properties"].items()}
        kwargs["required"] = schema.get("required", [])
    return genai.protos.Schema(**kwargs)


def _build_function_declarations(tools) -> list:
    return [
        genai.protos.FunctionDeclaration(
            name=t.name,
            description=t.description or "",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    k: _json_schema_to_proto(v)
                    for k, v in (t.inputSchema.get("properties") or {}).items()
                },
                required=t.inputSchema.get("required") or [],
            ),
        )
        for t in tools
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_session, function_declarations, cached_tools
    params = StdioServerParameters(command=sys.executable, args=[MAIN_PY])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_session = session
            result = await session.list_tools()
            function_declarations = _build_function_declarations(result.tools)
            cached_tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema.get("properties") or {},
                    "required": t.inputSchema.get("required") or [],
                }
                for t in result.tools
            ]
            yield
    mcp_session = None


# ─── app ─────────────────────────────────────────────────────────────────────

app = FastAPI(lifespan=lifespan, title="Weather MCP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse((STATIC / "index.html").read_text())


@app.get("/api/tools")
async def get_tools():
    return cached_tools


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set on server.")
    if not mcp_session:
        raise HTTPException(status_code=503, detail="MCP server not ready.")

    async def generate() -> AsyncGenerator[str, None]:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name="gemini-3.1-flash-lite",
                tools=[genai.protos.Tool(function_declarations=function_declarations)],
            )
            chat_session = model.start_chat()
            response = await asyncio.to_thread(chat_session.send_message, req.message)

            while True:
                fn_calls = [p.function_call for p in response.parts if p.function_call.name]

                if not fn_calls:
                    yield f"data: {json.dumps({'type': 'text', 'content': response.text})}\n\n"
                    break

                response_parts = []
                for fn in fn_calls:
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': fn.name, 'args': dict(fn.args)})}\n\n"

                    mcp_result = await mcp_session.call_tool(fn.name, dict(fn.args))
                    result_text = "\n".join(
                        c.text for c in mcp_result.content if hasattr(c, "text")
                    )

                    yield f"data: {json.dumps({'type': 'tool_result', 'name': fn.name, 'content': result_text})}\n\n"

                    response_parts.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=fn.name,
                                response={"output": result_text},
                            )
                        )
                    )

                response = await asyncio.to_thread(chat_session.send_message, response_parts)

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
