import {
  GoogleGenerativeAI,
  SchemaType,
  type FunctionDeclaration,
  type FunctionDeclarationSchema,
  type Schema,
  type Part,
} from '@google/generative-ai';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import * as readline from 'readline';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// ─── schema conversion ───────────────────────────────────────────────────────

type JsonSchema = Record<string, unknown>;

function toNestedSchema(s: JsonSchema): Schema {
  const t = (s.type as string) ?? 'string';
  const base = { description: (s.description as string | undefined) };

  switch (t) {
    case 'number':  return { ...base, type: SchemaType.NUMBER };
    case 'integer': return { ...base, type: SchemaType.INTEGER };
    case 'boolean': return { ...base, type: SchemaType.BOOLEAN };
    case 'array':   return {
      ...base,
      type: SchemaType.ARRAY,
      items: toNestedSchema((s.items ?? {}) as JsonSchema),
    };
    case 'object':  return {
      ...base,
      type: SchemaType.OBJECT,
      properties: toProperties((s.properties ?? {}) as Record<string, JsonSchema>),
      required: s.required as string[] | undefined,
    };
    default:        return { ...base, type: SchemaType.STRING };
  }
}

function toProperties(props: Record<string, JsonSchema>): Record<string, Schema> {
  return Object.fromEntries(Object.entries(props).map(([k, v]) => [k, toNestedSchema(v)]));
}

// Root schema for tool parameters is always object
function toRootSchema(inputSchema: JsonSchema): FunctionDeclarationSchema {
  return {
    type: SchemaType.OBJECT,
    description: inputSchema.description as string | undefined,
    properties: toProperties((inputSchema.properties ?? {}) as Record<string, JsonSchema>),
    required: inputSchema.required as string[] | undefined,
  };
}

// ─── main ────────────────────────────────────────────────────────────────────

async function main() {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    console.error('Set GEMINI_API_KEY before running: GEMINI_API_KEY=your-key npm run chat-gemini');
    process.exit(1);
  }

  // Spawn and connect to the MCP weather server over stdio
  const transport = new StdioClientTransport({
    command: 'npx',
    args: ['tsx', join(__dirname, 'main.ts')],
  });
  const mcp = new Client({ name: 'weather-client-gemini', version: '1.0.0' }, { capabilities: {} });
  await mcp.connect(transport);

  // Fetch MCP tools and convert to Gemini function declarations
  const { tools } = await mcp.listTools();
  const functionDeclarations: FunctionDeclaration[] = tools.map(t => ({
    name: t.name,
    description: t.description ?? '',
    parameters: toRootSchema(t.inputSchema as JsonSchema),
  }));

  console.log(`Connected. ${tools.length} tools: ${tools.map(t => t.name).join(', ')}`);
  console.log('Type your question or "exit" to quit.\n');

  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({
    model: 'gemini-3.1-flash-lite',
    tools: [{ functionDeclarations }],
  });

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  let closed = false;
  rl.on('close', () => { closed = true; });
  const ask = (prompt: string) => new Promise<string>((resolve, reject) =>
    closed ? reject(new Error('EOF')) : rl.question(prompt, resolve)
  );

  while (true) {
    let userInput: string;
    try { userInput = (await ask('You: ')).trim(); }
    catch { break; }
    if (!userInput) continue;
    if (userInput.toLowerCase() === 'exit') break;

    const chat = model.startChat();
    let result = await chat.sendMessage(userInput);

    // Agentic tool-use loop — keep going until Gemini stops calling tools
    while (true) {
      const calls = result.response.functionCalls();

      if (!calls || calls.length === 0) {
        console.log(`\nGemini: ${result.response.text()}\n`);
        break;
      }

      const responseParts: Part[] = [];
      for (const call of calls) {
        process.stdout.write(`  [${call.name}] `);

        const mcpResult = await mcp.callTool({
          name: call.name,
          arguments: call.args as Record<string, unknown>,
        });

        const text = (mcpResult.content as Array<{ type: string; text?: string }>)
          .filter(c => c.type === 'text')
          .map(c => c.text ?? '')
          .join('\n');

        process.stdout.write('done\n');

        responseParts.push({
          functionResponse: {
            name: call.name,
            response: { output: text },
          },
        });
      }

      result = await chat.sendMessage(responseParts);
    }
  }

  rl.close();
  await mcp.close();
}

main().catch(console.error);
