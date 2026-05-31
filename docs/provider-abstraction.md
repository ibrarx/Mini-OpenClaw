# LLM Provider Abstraction

## Why

Before the refactor, `core/planner.py` imported `AsyncAnthropic` and made
Anthropic-specific calls directly. Adding a second model meant rewriting the
planner. After the refactor, the planner depends only on the abstract
`LLMProvider` interface in `apps/api/providers/base.py`; concrete providers
translate that interface to the vendor's SDK.

The agent doesn't know — or care — which model is on the other end.

## Layout

```
apps/api/providers/
├── __init__.py           # public re-exports
├── base.py               # LLMProvider ABC + LLMMessage/LLMResponse/LLMToolSchema/LLMToolCall
├── errors.py             # provider-agnostic exception hierarchy
├── factory.py            # build_provider(settings) + ProviderType enum
├── anthropic_provider.py # AnthropicProvider — wraps AsyncAnthropic
└── gemini_provider.py    # GeminiProvider — wraps google-genai
```

## The four key types

| Type             | Role                                              |
|------------------|---------------------------------------------------|
| `LLMMessage`     | Normalized chat message: `role` + `content`       |
| `LLMToolSchema`  | Normalized tool/function definition (JSON Schema) |
| `LLMToolCall`    | Normalized tool invocation from the model         |
| `LLMResponse`    | Normalized response: `text`, `tool_calls`, `finish_reason`, `raw` |

Every provider takes the normalized inputs, translates them to the vendor's
native shape, calls the SDK, and translates the response back. **Anything
above the providers/ boundary deals only in these four types.**

## Switching providers

Set `LLM_PROVIDER` in `.env`:

```dotenv
# Use Claude
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-sonnet-4-6   # optional override

# OR use Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=AI...
# GEMINI_MODEL=gemini-2.5-flash               # optional override
```

Restart the backend. `GET /api/health` reports the active provider and
model:

```json
{
  "llm_provider": "gemini",
  "llm_model": "gemini-2.5-flash",
  "api_key_configured": true,
  ...
}
```

## Adding a new provider

Suppose you want to add OpenAI. The recipe is **five small steps**, none of
which touch the planner, orchestrator, executor, or any tool:

1. **Implement** `apps/api/providers/openai_provider.py`:
   ```python
   class OpenAIProvider(LLMProvider):
       name = "openai"
       def __init__(self, api_key: str, model: str) -> None: ...
       async def generate(self, messages, *, system=None, tools=None,
                          max_tokens=2048, temperature=None, timeout=60.0): ...
   ```
2. **Add an enum member** in `providers/factory.py`:
   ```python
   class ProviderType(str, Enum):
       ANTHROPIC = "anthropic"
       GEMINI    = "gemini"
       OPENAI    = "openai"          # ← new
   ```
3. **Add a branch** in `build_provider()`:
   ```python
   if ptype is ProviderType.OPENAI:
       from apps.api.providers.openai_provider import OpenAIProvider
       return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
   ```
4. **Add settings fields** in `apps/api/config.py`:
   ```python
   openai_api_key: str = ""
   openai_model: str = "gpt-4o-mini"
   ```
5. **Document** the new value in `.env.example` and the README.

Same recipe applies to Ollama, Groq, DeepSeek, or any local model — the
interface doesn't change.

## Exception mapping

Every provider catches its SDK's exceptions and re-raises one of:

| Provider error              | Cause                              | When the planner sees this... |
|-----------------------------|------------------------------------|--------------------------------|
| `ProviderConfigError`       | Missing API key, unknown provider  | Surfaces as "LLM provider not configured" run-failure |
| `ProviderAuthError`         | 401/403 from vendor                | Becomes `PlannerError` → run fails with message |
| `ProviderRateLimitError`    | 429 from vendor                    | Becomes `PlannerError`; caller may retry |
| `ProviderTimeoutError`      | `asyncio.TimeoutError` past timeout| Becomes `PlannerError` |
| `LLMProviderError` (base)   | Anything else                      | Becomes `PlannerError` |

Upstream code never imports anything from `anthropic.*` or `google.genai.*`.

## JSON-mode contract

Mini-OpenClaw's planner uses **JSON-mode prompting**: the system prompt
instructs the model to emit a JSON plan as its text response. Every provider
exposes a `generate_json(...)` method that:

1. Calls the SDK with whatever steering yields the cleanest JSON
   (Anthropic: prompt-only; Gemini: `response_mime_type="application/json"`).
2. Strips any stray ```json …``` fences as a defence-in-depth measure.
3. Parses the result and returns a `dict`.

This contract works identically across vendors and across local models like
Ollama, where native tool-calling APIs differ widely.

Native tool calling is also supported on the `LLMResponse.tool_calls` field —
both providers populate it correctly — but the V1 planner doesn't rely on it.
Future agents can opt in without re-engineering the interface.

## Streaming

`LLMProvider.stream_text(...)` exists as an extension point. The V1 planner
does not stream. When a future caller needs streaming, override `stream_text`
in each provider (Anthropic SDK: `client.messages.stream`; Gemini SDK:
`client.aio.models.generate_content_stream`).

---

# Diagrams

## 1. Provider abstraction

```mermaid
classDiagram
    class LLMProvider {
        <<abstract>>
        +str name
        +str model
        +generate(messages, system, tools, max_tokens, temperature, timeout) LLMResponse
        +generate_json(messages, system, max_tokens, timeout) dict
        +stream_text(messages, ...) AsyncIterator~str~
    }

    class AnthropicProvider {
        +name = "anthropic"
        -AsyncAnthropic _client
        -str _model
        -_to_anthropic_messages(...)
        -_to_anthropic_tools(...)
    }

    class GeminiProvider {
        +name = "gemini"
        -genai.Client _client
        -str _model
        -_to_gemini_contents(...)
        -_to_gemini_tools(...)
    }

    class LLMMessage {
        +role: "system" | "user" | "assistant"
        +content: str
    }

    class LLMToolSchema {
        +name: str
        +description: str
        +input_schema: dict
    }

    class LLMToolCall {
        +id: str
        +name: str
        +arguments: dict
    }

    class LLMResponse {
        +text: str
        +tool_calls: list~LLMToolCall~
        +finish_reason: str?
        +raw: dict?
    }

    class build_provider {
        <<factory>>
        +build_provider(settings) LLMProvider
    }

    LLMProvider <|-- AnthropicProvider
    LLMProvider <|-- GeminiProvider
    LLMProvider ..> LLMMessage : consumes
    LLMProvider ..> LLMToolSchema : consumes
    LLMProvider ..> LLMResponse : produces
    LLMResponse "1" *-- "*" LLMToolCall
    build_provider ..> LLMProvider : creates
```

## 2. Request flow (planner-driven)

```mermaid
sequenceDiagram
    autonumber
    participant U as User (React UI)
    participant API as FastAPI /api/chat
    participant O as Orchestrator
    participant PL as Planner
    participant FP as LLMProvider (Anthropic|Gemini)
    participant SDK as Vendor SDK
    participant PE as PolicyEngine
    participant EX as Executor

    U->>API: POST {message, session_id}
    API->>O: handle_message()
    O->>O: load memory context
    O->>PL: create_plan(message, context)
    PL->>FP: generate_json(messages, system)
    FP->>SDK: messages.create / generate_content
    SDK-->>FP: vendor-specific response
    FP-->>PL: dict (normalized plan JSON)
    PL-->>O: Plan{task_type, steps[], ...}

    alt task_type == direct_answer
        O-->>API: completed run + final_response
    else tool_needed / multi_step
        loop for each step
            O->>PE: classify_tool / validate_path / validate_shell
            alt forbidden
                PE-->>O: deny → step fails
            else approval_required
                O-->>U: approval_requested event
                U->>O: approve_step()
            end
            O->>EX: execute_tool(name, args, context)
            EX-->>O: ToolResult
        end
        O->>PL: generate_summary(message, results)
        PL->>FP: generate(messages, system)
        FP->>SDK: messages.create / generate_content
        SDK-->>FP: vendor response
        FP-->>PL: LLMResponse{text}
        PL-->>O: summary text
        O-->>API: completed run + final_response
    end
    API-->>U: run status updates (polling)
```

## 3. Tool-calling normalization

```mermaid
flowchart TB
    subgraph Agent ["Agent layer (vendor-agnostic)"]
        Reg[SkillRegistry] --> Manifests
        Manifests["[ToolManifest...]"] --> Norm
        Norm["LLMToolSchema<br/>name, description, input_schema"]
        Resp["LLMResponse<br/>tool_calls: [LLMToolCall...]"]
    end

    subgraph Anth ["AnthropicProvider"]
        AT["Anthropic tool format<br/>{name, description, input_schema}"]
        AR["Anthropic content blocks<br/>type=tool_use → tool_calls"]
    end

    subgraph Gem ["GeminiProvider"]
        GT["Gemini tool format<br/>Tool(function_declarations=[...])"]
        GR["response.function_calls<br/>[FunctionCall(name, args)]"]
    end

    subgraph SDK ["Vendor SDKs"]
        AS[("Anthropic API")]
        GS[("Gemini API")]
    end

    Norm -->|_to_anthropic_tools| AT
    AT --> AS
    AS --> AR
    AR -->|extracted in generate| Resp

    Norm -->|_to_gemini_tools| GT
    GT --> GS
    GS --> GR
    GR -->|extracted in generate| Resp

    Resp --> Planner["Planner<br/>(only sees normalized types)"]
```

Whichever provider is active, the agent sees the same `LLMToolSchema` going
in and the same `LLMToolCall` list coming out. Adding OpenAI / Ollama / etc.
adds a new column to the middle — nothing else moves.
