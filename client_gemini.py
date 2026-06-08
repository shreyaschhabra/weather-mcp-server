import asyncio
import os
import sys
from pathlib import Path
import google.generativeai as genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(
    command=sys.executable,
    args=[str(Path(__file__).parent / "main.py")],
)

async def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY before running.")
        sys.exit(1)

    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Fetch MCP tools — inputSchema is already JSON Schema, Gemini accepts it directly
            tools_result = await session.list_tools()
            function_declarations = [
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
                for t in tools_result.tools
            ]

            tool_names = [t.name for t in tools_result.tools]
            print(f"Connected. {len(tool_names)} tools: {', '.join(tool_names)}")
            print("Type your question or 'exit' to quit.\n")

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name="gemini-3.1-flash-lite",
                tools=[genai.protos.Tool(function_declarations=function_declarations)],
            )

            while True:
                try:
                    user_input = input("You: ").strip()
                except EOFError:
                    break
                if not user_input:
                    continue
                if user_input.lower() == "exit":
                    break

                chat = model.start_chat()
                response = await asyncio.to_thread(chat.send_message, user_input)

                # Agentic loop
                while True:
                    fn_calls = [p.function_call for p in response.parts if p.function_call.name]

                    if not fn_calls:
                        print(f"\nGemini: {response.text}\n")
                        break

                    response_parts = []
                    for fn in fn_calls:
                        print(f"  [{fn.name}] ", end="", flush=True)
                        result = await session.call_tool(fn.name, dict(fn.args))
                        result_text = "\n".join(
                            c.text for c in result.content if hasattr(c, "text")
                        )
                        print("done")
                        response_parts.append(
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=fn.name,
                                    response={"output": result_text},
                                )
                            )
                        )

                    response = await asyncio.to_thread(chat.send_message, response_parts)


def _json_schema_to_proto(schema: dict) -> genai.protos.Schema:
    """Convert a JSON Schema property to a Gemini proto Schema."""
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


if __name__ == "__main__":
    asyncio.run(main())
