# Group Report: Lab 3 - Production-Grade Agentic System

- **Team Name**: Nhóm 09
- **Team Members**: [Đàm Mạnh Dũng, Nguyễn Hoàng Thanh Tùng, Lê Bá Chiến]
- **Deployment Date**: [2026-06-01]

---

## 1. Executive Summary

*Brief overview of the agent's goal and success rate compared to the baseline chatbot.*

- **Success Rate**: 20 assert-based automated behavior cases are covered in the repository for provider configuration, retail tools, deterministic advisor, ReAct loop, and hybrid fallback paths. The project also includes 1 local model smoke test that runs only when a GGUF model file is available.
- **Key Outcome**: Our Retail Stock Advisor converts a normal chatbot into a grounded ReAct-style inventory assistant. Instead of guessing stock decisions, the agent calls deterministic retail tools over `data/retail`, returns traceable observations, and can fall back to base rules when the LLM provider, parser, tool call, or timeout path fails.

---

## 2. System Architecture & Tooling

### 2.1 ReAct Loop Implementation
*Diagram or description of the Thought-Action-Observation loop.*

The application flow starts in `src/ui/server.py`. The web UI sends `question`, `category`, `period_id`, and `analysis_mode` to `POST /api/ask`. `HybridRetailStockAdvisor` chooses one of three modes:

1. `base`: use deterministic retail rules without LLM.
2. `llm`: use strict ReAct Agent and report errors without fallback.
3. `hybrid`: try ReAct Agent first, then fall back to deterministic rules if the AI path is unsafe.

The ReAct loop in `src/agent/agent.py` follows this protocol:

```text
User question
-> System prompt lists available tools and JSON argument schemas
-> Thought: explain why a tool is needed
-> Action: call one retail tool with JSON arguments
-> Observation: tool result from controlled retail dataset
-> Repeat until enough evidence exists
-> Final Answer: Vietnamese recommendation grounded in observations
```

The agent is not allowed to invent product, inventory, sales, or supplier facts. It must complete at least one valid tool call before a final answer.

### 2.2 Tool Definitions (Inventory)
| Tool Name | Input Format | Use Case |
| :--- | :--- | :--- |
| `get_inventory` | `json` | Get stock, reorder point, safety stock, unit, price by `product_id` or `category`. |
| `get_sales_history` | `json` | Read 7/30-day sales history for one product. |
| `calculate_sell_through_rate` | `json` | Calculate sell-through from sold units and current stock. |
| `detect_stockout_risk` | `json` | Classify low, medium, or high stockout risk using stock, sales velocity, and supplier lead time. |
| `detect_slow_moving_items` | `json` | Find overstocked products with weak 30-day sell-through for promotion/discount actions. |
| `recommend_reorder_quantity` | `json` | Recommend reorder quantity using lead time, safety stock, minimum order quantity, and pack size. |
| `get_seasonal_trends` | `json` | Load seasonal demand multipliers and promotion categories for a period such as `tet_holiday`. |
| `recommend_seasonal_stock_plan` | `json` | Recommend pre-season reorder and promotion plans using seasonal multipliers. |

### 2.3 LLM Providers Used
- **Primary**: DashScope/Qwen compatible API with `qwen3-coder-flash` for the demo configuration.
- **Secondary (Backup)**: OpenAI `gpt-4o`, Gemini `gemini-1.5-flash`, and local GGUF model through `llama-cpp-python`. The non-LLM fallback is the deterministic `RetailStockAdvisor`.

---

## 3. Telemetry & Performance Dashboard

*Analyze the industry metrics collected during the final test run.*

- **Average Latency (P50)**: Scripted automated LLM tests use `latency_ms=1`; live provider latency is collected per request by `src/telemetry/metrics.py`.
- **Max Latency (P99)**: Controlled timeout behavior is verified with a slow provider; hybrid mode falls back when `AI_TIMEOUT_SECONDS` is exceeded.
- **Average Tokens per Task**: Scripted ReAct tests use 15 total tokens per LLM step. Real token counts are stored as `prompt_tokens`, `completion_tokens`, and `total_tokens`.
- **Total Cost of Test Suite**: Mock cost is calculated as `(total_tokens / 1000) * 0.01` in `PerformanceTracker`. Base mode has no LLM token cost.

Telemetry is logged as structured JSON events in `logs/YYYY-MM-DD.log`:

- `AGENT_START`, `AGENT_STEP`, `AGENT_END` for ReAct execution.
- `LLM_METRIC` for provider, model, tokens, latency, and cost estimate.
- `PARSER_ERROR`, `TOOL_ERROR`, `TOOL_NOT_FOUND` for unsafe agent behavior.
- `RETAIL_AI_SUCCESS`, `RETAIL_AI_FALLBACK`, `RETAIL_AI_STRICT_ERROR` for retail advisor outcomes.

---

## 4. Root Cause Analysis (RCA) - Failure Traces

*Deep dive into why the agent failed.*

### Case Study: Hallucinated Tool Call
- **Input**: "Tôi nên nhập thêm P001 không?"
- **Observation**: A scripted LLM called `check_supplier_magic({"product_id": "P001"})`, but this tool is not in the approved retail tool inventory.
- **Root Cause**: The LLM generated an action outside the tool schema. This is a typical ReAct failure when the model tries to invent a helper function instead of using the listed tools.

Resolution:

- `ReActAgent._execute_tool()` marks the run as `tool_not_found`.
- `HybridRetailStockAdvisor._validate_ai_run()` rejects the unsafe AI result.
- In `hybrid` mode, the system logs `RETAIL_AI_FALLBACK` and returns deterministic recommendations from `RetailStockAdvisor`.
- This behavior is covered by `tests/test_hybrid_advisor.py::test_hybrid_advisor_falls_back_on_hallucinated_tool`.

Additional failure cases covered:

- Provider missing configuration: fallback with a clear `fallback_reason`.
- Parser error: invalid action such as `get_inventory(product_id=P001)` is rejected.
- Early final answer: agent retries because it must call a tool before answering.
- Timeout: slow LLM path falls back before blocking the UI.

---

## 5. Ablation Studies & Experiments

### Experiment 1: Prompt v1 vs Prompt v2
- **Diff**: Prompt v2 lists exact tool names, JSON argument schemas, the required Thought/Action/Observation format, and the rule that a Final Answer must come only after at least one valid tool observation.
- **Result**: The agent now retries when the model answers too early, records parser errors explicitly, and prevents ungrounded final answers. This is verified in `tests/test_react_agent.py::test_react_agent_retries_when_llm_answers_before_tool_use`.

### Experiment 2 (Bonus): Chatbot vs Agent
| Case | Chatbot Result | Agent Result | Winner |
| :--- | :--- | :--- | :--- |
| Simple product question | Can answer generally but may guess stock values. | Calls `get_inventory` and answers with current stock data. | **Agent** |
| Weekly reorder and promotion plan | Likely gives generic advice without product-level evidence. | Uses inventory, sales history, stockout risk, reorder quantity, and slow-moving detection. | **Agent** |
| Seasonal Tet preparation | May recommend popular Tet products from general knowledge. | Uses `get_seasonal_trends` and `recommend_seasonal_stock_plan` from local dataset. | **Agent** |
| Missing API key | Cannot answer if it depends on LLM. | Hybrid mode falls back to deterministic rules. | **Agent** |
| Strict LLM mode failure | May still hallucinate a confident answer. | Reports an explicit AI error without fallback. | **Agent** |

### Experiment 3: Base vs LLM vs Hybrid
| Mode | Behavior | Best Use |
| :--- | :--- | :--- |
| `base` | Deterministic rules, no API key, fastest path. | Reliable demo and offline execution. |
| `llm` | Strict ReAct, no fallback, exposes AI failures clearly. | Debugging prompts, tools, and provider behavior. |
| `hybrid` | ReAct first, deterministic fallback on unsafe AI path. | Best user-facing mode for the web app. |

---

## 6. Production Readiness Review

*Considerations for taking this system to a real-world environment.*

- **Security**: API keys are read from `.env`, request body size is limited to 16KB, server only serves `index.html`, and the agent can access only approved retail tools instead of arbitrary files or commands.
- **Guardrails**: `AI_MAX_STEPS` limits ReAct loops, `AI_TIMEOUT_SECONDS` prevents long LLM calls, `_validate_ai_run()` requires a final answer with at least one successful tool observation, and hybrid mode falls back on provider, parser, tool, or timeout errors.
- **Scaling**: Move long AI calls to an async queue, add real provider cost tables, cache retail repository data, persist telemetry to a dashboard, and replace the mock JSON dataset with a database or inventory API.

---

> [!NOTE]
> Submit this report as `GROUP_REPORT_GROUP_9.md` and place it in this folder.
