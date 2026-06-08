# Weather MCP Server

A production-grade **Model Context Protocol (MCP)** server that exposes 12 real-time weather tools to large language models. Built in Python using the FastMCP framework, integrated with Google Gemini 3.1 Flash Lite, and deployable as a Streamlit web application or a FastAPI REST service.

All weather data is sourced from the [Open-Meteo](https://open-meteo.com/) family of free APIs. No API keys are required for weather data.

---

## Table of Contents

1. [What is MCP](#what-is-mcp)
2. [How MCP and LLM Work Together](#how-mcp-and-llm-work-together)
3. [Project Architecture](#project-architecture)
4. [Features](#features)
5. [Tech Stack](#tech-stack)
6. [Project Structure](#project-structure)
7. [Available Tools](#available-tools)
8. [Prerequisites](#prerequisites)
9. [Installation](#installation)
10. [Configuration](#configuration)
11. [Running the Project](#running-the-project)
    - [Streamlit Web UI](#streamlit-web-ui)
    - [FastAPI Web Server](#fastapi-web-server)
    - [Command-Line Chat (Python)](#command-line-chat-python)
    - [Command-Line Chat (TypeScript)](#command-line-chat-typescript)
12. [API Reference](#api-reference)
13. [Deployment](#deployment)
    - [Streamlit Community Cloud](#streamlit-community-cloud)
    - [Railway](#railway)
    - [Render](#render)
14. [Data Sources](#data-sources)
15. [Environment Variables](#environment-variables)
16. [Roadmap](#roadmap)

---

## What is MCP

The **Model Context Protocol (MCP)** is an open standard introduced by Anthropic in late 2024 that defines how large language models communicate with external tools and data sources. It provides a uniform interface so that any MCP-compatible LLM host (Claude Desktop, VS Code Copilot, custom agents) can discover and invoke tools without being tightly coupled to a specific implementation.

An MCP server is a process that:

- Declares a list of tools, each with a name, description, and typed parameter schema
- Listens for JSON-RPC 2.0 requests over a transport (stdio in this project)
- Executes the requested tool and returns structured results

The key benefit is **separation of concerns**: the LLM decides which tool to call and with what arguments; the MCP server handles the actual execution. This makes tools reusable across any LLM that supports the protocol.

---

## How MCP and LLM Work Together

The following sequence describes what happens when a user sends a message to the assistant:

```
User: "Should I bring an umbrella in London today?"
        |
        v
Client (streamlit_app.py / client_gemini.py)
  -- Sends the user message to Gemini API
  -- Attaches the full list of 12 tool definitions (name, description, parameter schema)
        |
        v
Gemini 3.1 Flash Lite
  -- Reads the message and the tool list
  -- Determines that "should_i_bring_umbrella" with city="London" is the correct tool
  -- Returns a tool_use response (not a text answer)
        |
        v
Client
  -- Receives the tool_use response
  -- Extracts the tool name and arguments
  -- Calls the MCP server via stdio: call_tool("should_i_bring_umbrella", {"city": "London"})
        |
        v
MCP Server (main.py)
  -- Runs the tool function
  -- Geocodes London via Open-Meteo geocoding API
  -- Fetches hourly precipitation probability from Open-Meteo forecast API
  -- Calculates max rain probability and total expected rainfall
  -- Returns: "Maybe bring one just in case. (max rain chance: 45%, 3h with >50% chance)"
        |
        v
Client
  -- Sends the tool result back to Gemini
        |
        v
Gemini 3.1 Flash Lite
  -- Reads the tool result
  -- Generates a natural language response based on the data
        |
        v
User sees: "There is a 45% chance of rain in London today. You may want
            to carry an umbrella, particularly in the afternoon."
```

The LLM is never directly fetching weather data. It only decides which tool to call and synthesises the final response. The MCP server is the data layer.

---

## Project Architecture

```
+---------------------+       stdio (JSON-RPC 2.0)      +-------------------+
|                     | <------------------------------> |                   |
|  Client Layer       |                                  |  MCP Server       |
|                     |                                  |  (main.py)        |
|  streamlit_app.py   |   1. list_tools()                |                   |
|  client_gemini.py   |   2. call_tool(name, args)       |  12 tools         |
|  app.py (FastAPI)   |   3. receive result              |  FastMCP          |
|  client-gemini.ts   |                                  |  httpx async      |
|                     |                                  |                   |
+---------------------+                                  +--------+----------+
          |                                                       |
          | Anthropic / Google API calls                         | HTTP requests
          v                                                       v
+---------------------+                                  +-------------------+
|  Gemini 3.1 Flash   |                                  |  Open-Meteo APIs  |
|  Lite               |                                  |                   |
|  (Tool-use loop)    |                                  |  Forecast         |
|                     |                                  |  Archive          |
+---------------------+                                  |  Air Quality      |
                                                         |  Marine           |
                                                         |  Geocoding        |
                                                         +-------------------+
```

---

## Features

- 12 real-time weather tools accessible to Gemini via MCP
- Agentic tool-use loop: Gemini calls one or more tools per query, processes the results, and generates a natural language response
- Streamlit web UI with sidebar tool list, example prompts, and live tool call display
- FastAPI REST server with server-sent events (SSE) streaming for the same functionality
- Python CLI client and TypeScript CLI client
- Dark, formal UI theme with no decorative icons
- All weather data from Open-Meteo — no paid API keys required
- MCP server compatible with Claude Desktop, VS Code Copilot, and any other MCP host

---

## Tech Stack

| Layer | Technology |
|---|---|
| MCP Server | Python, [FastMCP](https://github.com/jlowin/fastmcp) (`mcp` package v1.x) |
| HTTP Requests | `httpx` (async) |
| LLM | Google Gemini 3.1 Flash Lite via `google-generativeai` |
| Web UI | Streamlit |
| REST API | FastAPI + Uvicorn |
| TypeScript Client | `@modelcontextprotocol/sdk`, `@google/generative-ai` |
| Weather Data | Open-Meteo (free, no key required) |

---

## Project Structure

```
weather-mcp-server/
|
|-- main.py                  # MCP server — all 12 tool definitions
|-- streamlit_app.py         # Streamlit web UI (primary interface)
|-- app.py                   # FastAPI REST server (alternative interface)
|-- client_gemini.py         # Python CLI chat client
|-- client-gemini.ts         # TypeScript CLI chat client
|-- main.ts                  # TypeScript version of the MCP server
|
|-- requirements.txt         # Python dependencies
|-- package.json             # Node.js dependencies (TypeScript client)
|-- tsconfig.json            # TypeScript configuration
|-- .gitignore
|
|-- .streamlit/
|   `-- config.toml          # Streamlit dark theme configuration
|
`-- static/
    `-- index.html           # Standalone HTML frontend for FastAPI server
```

---

## Available Tools

The MCP server exposes the following 12 tools. All tools accept a `city` parameter (the city name as a plain string). The server geocodes the city automatically using the Open-Meteo Geocoding API.

---

### 1. get_weather

Returns the current weather conditions for a city.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

Current temperature (actual and feels-like), humidity, wind speed, precipitation, cloud cover, and a WMO weather condition description.

**Example prompt:** "What is the current weather in Tokyo?"

---

### 2. get_forecast

Returns a daily weather forecast for up to 7 days.

**Parameters**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| city | string | Yes | — | Name of the city |
| days | integer | No | 7 | Number of forecast days (1–7) |

**Returns**

Per-day summary including temperature range, precipitation total, max wind speed, and weather condition.

**Example prompt:** "Give me a 5-day forecast for Paris."

---

### 3. get_hourly_forecast

Returns an hour-by-hour weather breakdown for the current day.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

24 rows of hourly data: time, condition, temperature, precipitation probability, and wind speed.

**Example prompt:** "Show me hourly weather for Singapore today."

---

### 4. compare_cities_weather

Fetches current conditions for multiple cities in parallel and presents them side by side.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| cities | array of strings | Yes | 2 to 5 city names |

**Returns**

Per-city summary with temperature, feels-like temperature, humidity, wind speed, and weather condition.

**Example prompt:** "Compare the weather in New York, London, Dubai, and Sydney."

---

### 5. should_i_bring_umbrella

Analyses today's hourly precipitation probabilities and advises whether an umbrella is needed.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

A clear recommendation (yes / maybe / no) with the maximum rain probability, expected total rainfall, and the number of hours with greater than 50% rain chance.

**Thresholds**

- Max probability >= 70% or total rain > 5mm: Definite umbrella
- Max probability >= 30%: Possibly needed
- Below 30%: No umbrella required

**Example prompt:** "Should I bring an umbrella in Mumbai today?"

---

### 6. get_air_quality

Returns current air quality measurements including the European AQI and key pollutant concentrations.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

European AQI with label (Good / Fair / Moderate / Poor / Very Poor / Extremely Poor), PM2.5, PM10, NO2, O3, and CO values in µg/m³.

**Example prompt:** "What is the air quality in Beijing?"

---

### 7. get_weather_alerts

Scans the 7-day forecast for potentially hazardous conditions and returns structured alerts.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

A list of alerts grouped by severity (WARNING / WATCH / ADVISORY), each with a date, category, and detail message. Returns a clear all-clear message if no hazardous conditions are detected.

**Alert categories**

| Category | Trigger condition |
|---|---|
| Thunderstorm | WMO codes 95, 96, 99 |
| Heavy Rain / Storms | WMO codes 65, 67, 82 |
| Heavy Snow | WMO codes 75, 77, 85, 86 |
| High Wind | Wind speed >= 75 km/h |
| Wind | Wind speed >= 50 km/h |
| Extreme Heat | Max temperature >= 40°C |
| Heat | Max temperature >= 35°C |
| Extreme Cold | Min temperature <= -15°C |
| Cold | Min temperature <= -5°C |
| Flooding Risk | Daily precipitation >= 30mm |

**Example prompt:** "Are there any weather warnings for Florida this week?"

---

### 8. get_uv_index

Returns the maximum UV index forecast and corresponding sun protection advice for up to 3 days.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

Daily UV index maximum with a protection recommendation.

**UV scale**

| UV Index | Level | Advice |
|---|---|---|
| 0–2 | Low | No protection needed |
| 3–5 | Moderate | SPF 30+, seek shade at noon |
| 6–7 | High | SPF 50+, hat and sunglasses required |
| 8–10 | Very High | Minimise midday exposure |
| 11+ | Extreme | Avoid going outside 10am–4pm |

**Example prompt:** "What is the UV index in Sydney for the next 3 days?"

---

### 9. get_sunrise_sunset

Returns sunrise time, sunset time, and total daylight duration for the next 7 days, adjusted to the city's local timezone.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

7-day table with sunrise time (HH:MM), sunset time (HH:MM), and daylight duration in hours.

**Example prompt:** "What time does the sun rise in Oslo this week?"

---

### 10. get_historical_weather

Queries the Open-Meteo Archive API to retrieve weather data for a specific past date. Data is available from 1940 onwards for most locations.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |
| date | string | Yes | Date in YYYY-MM-DD format |

**Returns**

Daily summary for the given date: temperature high and low, precipitation total, maximum wind speed, and weather condition.

**Example prompt:** "What was the weather in London on 2024-07-04?"

---

### 11. get_pollen_forecast

Returns today's peak pollen concentrations by type. Coverage is best in Europe and parts of North America.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of the city |

**Returns**

Peak concentration (grains/m³) and level (None / Low / Moderate / High / Very High) for each of: Alder, Birch, Grass, Mugwort, Olive, and Ragweed.

**Example prompt:** "What are the pollen levels in Berlin today?"

---

### 12. get_marine_weather

Returns current wave conditions and a 3-day wave forecast. Best results for coastal cities and island locations.

**Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| city | string | Yes | Name of a coastal city |

**Returns**

Current wave height with sea state label (Glassy / Calm / Slight / Moderate / Rough / Very Rough / High), wave direction and period, wind wave height, swell height and period, and a 3-day daily maximum forecast.

**Example prompt:** "What are the wave conditions in Lisbon?"

---

## Prerequisites

- Python 3.11 or higher
- A Google Gemini API key (free tier available at [aistudio.google.com](https://aistudio.google.com))
- Node.js 18+ and npm (only required for the TypeScript client)
- Git

---

## Installation

```bash
# Clone the repository
git clone https://github.com/shreyaschhabra/weather-mcp-server.git
cd weather-mcp-server

# Install Python dependencies
pip install -r requirements.txt

# (Optional) Install Node.js dependencies for the TypeScript client
npm install
```

---

## Configuration

The only required configuration is the Gemini API key. Set it as an environment variable before running any client or server.

```bash
export GEMINI_API_KEY="your_gemini_api_key_here"
```

To get a free Gemini API key:
1. Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with a Google account
3. Click "Create API key"

The MCP server (`main.py`) does not require any API key. It only calls Open-Meteo endpoints which are free and unauthenticated.

---

## Running the Project

### Streamlit Web UI

The primary interface. Provides a full chat UI with a tool sidebar, example prompts, and live tool call display.

```bash
GEMINI_API_KEY="your_key" streamlit run streamlit_app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

**What the UI shows:**
- Left sidebar: all 12 tools with descriptions and one-click example prompts
- Chat area: user messages, a collapsible "Tools used" section showing tool name, arguments as metrics, and raw tool output, followed by Gemini's final response
- Input field at the bottom with Enter-to-send support

---

### FastAPI Web Server

An alternative REST-based interface that streams responses via server-sent events (SSE). Includes a standalone dark-themed HTML/JS frontend.

```bash
GEMINI_API_KEY="your_key" uvicorn app:app --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

The server exposes two endpoints:

- `GET /api/tools` — returns the full list of available tools
- `POST /api/chat` — accepts `{"message": "..."}` and streams SSE events

SSE event types:

| Event type | Payload | Description |
|---|---|---|
| `tool_call` | `{name, args}` | Gemini has invoked a tool |
| `tool_result` | `{name, content}` | The tool has returned data |
| `text` | `{content}` | Gemini's final text response |
| `error` | `{content}` | An error occurred |
| `done` | — | Stream complete |

---

### Command-Line Chat (Python)

A terminal-based interactive chat client. Connects to the MCP server as a subprocess and uses the same agentic loop as the web interfaces.

```bash
GEMINI_API_KEY="your_key" python3 client_gemini.py
```

Type any weather question at the `You:` prompt. Type `exit` to quit.

---

### Command-Line Chat (TypeScript)

The TypeScript equivalent of the Python CLI client. Uses `@modelcontextprotocol/sdk` for MCP and `@google/generative-ai` for Gemini.

```bash
GEMINI_API_KEY="your_key" npm run chat-gemini
```

---

### Running the MCP Server Standalone

To run the MCP server by itself for testing or integration with another MCP host (Claude Desktop, VS Code Copilot, etc.):

```bash
python3 main.py
```

The server communicates over stdio using JSON-RPC 2.0. To connect it to Claude Desktop, add the following to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "weather": {
      "command": "python3",
      "args": ["/absolute/path/to/weather-mcp-server/main.py"]
    }
  }
}
```

To connect it to VS Code Copilot, the `.vscode/mcp.json` configuration is already included in the repository.

---

## API Reference

### GET /api/tools

Returns the list of all tools registered on the MCP server.

**Response**

```json
[
  {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "parameters": {
      "city": {
        "type": "string",
        "description": "City name"
      }
    },
    "required": ["city"]
  }
]
```

---

### POST /api/chat

Initiates a streaming chat request. The server runs the full Gemini + MCP agentic loop and streams events as they occur.

**Request body**

```json
{
  "message": "What is the weather in London?"
}
```

**Response** — `text/event-stream`

```
data: {"type": "tool_call", "name": "get_weather", "args": {"city": "London"}}

data: {"type": "tool_result", "name": "get_weather", "content": "Location: London...\nTemperature: 14.1°C..."}

data: {"type": "text", "content": "The current weather in London is 14.1°C with slight rain."}

data: {"type": "done"}
```

---

## Deployment

### Streamlit Community Cloud

The recommended deployment path. Free, permanent public URL, no server management required.

1. Fork or push this repository to your GitHub account.
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **New app**.
4. Select your repository, set the branch to `main`, and set the main file path to `streamlit_app.py`.
5. Click **Advanced settings** and add the following secret:
   ```
   GEMINI_API_KEY = "your_gemini_api_key"
   ```
6. Click **Deploy**.

The app will be available at a URL of the form `https://your-app-name.streamlit.app`.

---

### Railway

1. Push the repository to GitHub.
2. Create a new project at [railway.app](https://railway.app) and select **Deploy from GitHub repo**.
3. Add the environment variable `GEMINI_API_KEY` in the Variables tab.
4. Create a `Procfile` in the project root with the following content:
   ```
   web: uvicorn app:app --host 0.0.0.0 --port $PORT
   ```
5. Railway will detect Python, install dependencies from `requirements.txt`, and deploy automatically.

---

### Render

1. Push the repository to GitHub.
2. Create a new **Web Service** at [render.com](https://render.com).
3. Connect your GitHub repository.
4. Set the following:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Add the environment variable `GEMINI_API_KEY` under the Environment tab.
6. Click **Create Web Service**.

Note: the free tier on Render spins down inactive services after 15 minutes of inactivity. The first request after a period of inactivity will take longer while the service restarts.

---

## Data Sources

All weather data is provided by the Open-Meteo project. Open-Meteo is a free, open-source weather API with no rate limits for non-commercial use.

| API | Endpoint | Used by tools |
|---|---|---|
| Geocoding | `geocoding-api.open-meteo.com/v1/search` | All tools (city name to coordinates) |
| Weather Forecast | `api.open-meteo.com/v1/forecast` | get_weather, get_forecast, get_hourly_forecast, compare_cities_weather, should_i_bring_umbrella, get_uv_index, get_sunrise_sunset, get_weather_alerts |
| Historical Archive | `archive-api.open-meteo.com/v1/archive` | get_historical_weather |
| Air Quality | `air-quality-api.open-meteo.com/v1/air-quality` | get_air_quality, get_pollen_forecast |
| Marine | `marine-api.open-meteo.com/v1/marine` | get_marine_weather |

Full Open-Meteo documentation: [https://open-meteo.com/en/docs](https://open-meteo.com/en/docs)

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key. Required by all client-side files (`streamlit_app.py`, `app.py`, `client_gemini.py`, `client-gemini.ts`). Not required by `main.py`. |

---

## Roadmap

- Add support for multi-turn conversation history in the Streamlit UI
- Add get_uv_index hourly breakdown for the current day
- Add weather widgets / data visualisation charts using Plotly or Altair
- Add a caching layer to reduce repeated API calls for the same city
- Publish the MCP server to the MCP registry so it can be installed by other MCP hosts without cloning the repository
- Add support for units switching (Fahrenheit / mph)
- Extend pollen coverage using additional data sources for Asia and South America
