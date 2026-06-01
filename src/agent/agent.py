import json
import re
import ast
from typing import List, Dict, Any, Optional
from src.core.llm_provider import LLMProvider
from src.telemetry.logger import logger
from src.telemetry.metrics import tracker

class ReActAgent:
    """
    SKELETON: A ReAct-style Agent that follows the Thought-Action-Observation loop.
    Students should implement the core loop logic and tool execution.
    """
    
    def __init__(self, llm: LLMProvider, tools: List[Dict[str, Any]], max_steps: int = 5):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.history = []
        self.last_status: str | None = None
        self.last_error: str | None = None
        self.had_tool_failure = False

    def get_system_prompt(self) -> str:
        tool_descriptions = self._format_tool_descriptions()
        return f"""
You are an intelligent ReAct assistant. You can only use facts returned by tools.

Available tools:
{tool_descriptions}

Follow this exact loop:
Thought: briefly explain why the next tool is needed.
Action: tool_name({{"argument_name": "value"}})
Observation: the system will append the tool result here.

After the system provides an Observation, continue with another Thought/Action or finish with:
Final Answer: your final response.

Rules:
- Use only the listed tools and exact argument names.
- Prefer JSON object arguments inside Action parentheses.
- Before any Final Answer, you must complete at least one valid tool call.
- If you do not yet have a tool Observation, do not answer. Write Thought and Action only.
- Do not invent product, inventory, sales, or supplier facts.
- Do not write Observation yourself.

Examples:
Thought: Need current stock for this product.
Action: get_inventory({{"product_id": "P001"}})

Thought: Need promotion candidates in the requested category.
Action: detect_slow_moving_items({{"category": "snack", "days": 30}})
        """

    def run(self, user_input: str) -> str:
        logger.log_event("AGENT_START", {"input": user_input, "model": self.llm.model_name})

        self.history = []
        self.last_status = None
        self.last_error = None
        self.had_tool_failure = False
        current_prompt = user_input
        steps = 0

        while steps < self.max_steps:
            result = self.llm.generate(current_prompt, system_prompt=self.get_system_prompt())
            content = result.get("content", "")
            tracker.track_request(
                provider=result.get("provider", "unknown"),
                model=self.llm.model_name,
                usage=result.get("usage", {}),
                latency_ms=result.get("latency_ms", 0),
            )
            logger.log_event("AGENT_STEP", {"step": steps + 1, "content": content})

            try:
                action = self._parse_action(content)
            except (ValueError, SyntaxError, json.JSONDecodeError) as exc:
                self.last_status = "parser_error"
                self.last_error = str(exc)
                logger.log_event("PARSER_ERROR", {"step": steps + 1, "error": str(exc), "content": content})
                return f"Parser error: {exc}"

            final_answer = self._parse_final_answer(content)
            if action is None and final_answer:
                if not self.history:
                    self.last_status = "protocol_retry"
                    self.last_error = "LLM answered before calling any tool."
                    logger.log_event(
                        "AGENT_PROTOCOL_RETRY",
                        {"step": steps + 1, "reason": self.last_error, "content": content},
                    )
                    current_prompt = self._build_protocol_retry_prompt(
                        user_input,
                        "You must call one retail tool before Final Answer. Reply with Thought and Action only.",
                    )
                    steps += 1
                    continue
                self.last_status = "final_answer"
                logger.log_event("AGENT_END", {"steps": steps + 1, "status": "final_answer"})
                return final_answer

            if action is None:
                self.last_status = "protocol_retry"
                self.last_error = "LLM did not produce a tool action or final answer."
                logger.log_event(
                    "AGENT_PROTOCOL_RETRY",
                    {"step": steps + 1, "reason": self.last_error, "content": content},
                )
                current_prompt = self._build_protocol_retry_prompt(
                    user_input,
                    "Reply using ReAct format exactly: Thought then Action with one listed tool.",
                )
                steps += 1
                continue

            tool_name, args = action
            observation = self._execute_tool(tool_name, args)
            self.history.append(
                {
                    "step": steps + 1,
                    "thought": self._extract_label(content, "Thought"),
                    "action": self._format_action(tool_name, args),
                    "tool_name": tool_name,
                    "args": args,
                    "thought_action": content,
                    "observation": observation,
                }
            )
            current_prompt = (
                f"{user_input}\n\n"
                f"Previous work:\n{self._format_history()}\n\n"
                "Continue reasoning. If enough information is available, answer with Final Answer."
            )
            steps += 1

        self.last_status = "max_steps"
        self.last_error = f"Agent exceeded max_steps={self.max_steps}."
        logger.log_event("AGENT_END", {"steps": steps, "status": "max_steps"})
        return "Unable to complete within max_steps."

    def _build_protocol_retry_prompt(self, user_input: str, instruction: str) -> str:
        history = self._format_history()
        sections = [user_input]
        if history:
            sections.append(f"Previous work:\n{history}")
        sections.append(
            "Protocol correction:\n"
            f"{instruction}\n"
            "Do not write Final Answer yet unless you already have at least one tool Observation."
        )
        return "\n\n".join(sections)

    def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        for tool in self.tools:
            if tool['name'] == tool_name:
                func = tool.get("func")
                if not callable(func):
                    self.had_tool_failure = True
                    self.last_status = "tool_error"
                    self.last_error = f"Tool {tool_name} has no callable implementation."
                    return f"Tool {tool_name} has no callable implementation."
                try:
                    result = func(**args)
                    return json.dumps(result, ensure_ascii=False)
                except Exception as exc:
                    self.had_tool_failure = True
                    self.last_status = "tool_error"
                    self.last_error = str(exc)
                    logger.log_event("TOOL_ERROR", {"tool": tool_name, "args": args, "error": str(exc)})
                    return f"Tool {tool_name} failed: {exc}"
        self.had_tool_failure = True
        self.last_status = "tool_not_found"
        self.last_error = f"Tool {tool_name} not found."
        logger.log_event("TOOL_NOT_FOUND", {"tool": tool_name, "args": args})
        return f"Tool {tool_name} not found."

    def _format_tool_descriptions(self) -> str:
        rows = []
        for tool in self.tools:
            parameters = tool.get("parameters")
            parameter_text = ""
            if parameters:
                parameter_text = f" Args JSON schema: {json.dumps(parameters, ensure_ascii=False)}"
            rows.append(f"- {tool['name']}: {tool['description']}{parameter_text}")
        return "\n".join(rows)

    def _parse_action(self, content: str) -> Optional[tuple[str, Dict[str, Any]]]:
        cleaned = self._strip_code_fences(content)
        match = re.search(
            r"Action\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\((.*?)\)|(\{.*?\}))",
            cleaned,
            re.DOTALL,
        )
        if not match:
            return None

        tool_name = match.group(1)
        raw_args = (match.group(2) or match.group(3) or "").strip()
        return tool_name, self._parse_args(raw_args)

    @staticmethod
    def _parse_final_answer(content: str) -> Optional[str]:
        cleaned = ReActAgent._strip_code_fences(content)
        match = re.search(r"(?:^|\n)\s*(?:\*\*)?Final Answer(?:\*\*)?\s*:\s*(.*)", cleaned, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_label(content: str, label: str) -> str:
        cleaned = ReActAgent._strip_code_fences(content)
        match = re.search(
            rf"{label}\s*:\s*(.*?)(?=\n\s*(?:Thought|Action|Observation|Final Answer)\s*:|\Z)",
            cleaned,
            re.DOTALL,
        )
        if not match:
            return ""
        return match.group(1).strip()

    @staticmethod
    def _format_action(tool_name: str, args: Dict[str, Any]) -> str:
        return f"{tool_name}({json.dumps(args, ensure_ascii=False)})"

    @staticmethod
    def _parse_args(raw_args: str) -> Dict[str, Any]:
        if not raw_args:
            return {}

        if raw_args.startswith("{") and raw_args.endswith("}"):
            return json.loads(raw_args)

        parsed: Dict[str, Any] = {}
        for item in ReActAgent._split_args(raw_args):
            if not item.strip():
                continue
            separator = "=" if "=" in item else ":"
            key, _, value = item.partition(separator)
            if not key or not value:
                raise ValueError(f"Invalid tool argument: {item}")
            parsed[key.strip()] = ast.literal_eval(value.strip())
        return parsed

    @staticmethod
    def _strip_code_fences(content: str) -> str:
        return re.sub(r"```(?:json|python|text)?\s*|\s*```", "", content.strip(), flags=re.IGNORECASE)

    @staticmethod
    def _split_args(raw_args: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        quote: str | None = None
        escaped = False

        for char in raw_args:
            if escaped:
                current.append(char)
                escaped = False
                continue
            if char == "\\":
                current.append(char)
                escaped = True
                continue
            if quote:
                current.append(char)
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                current.append(char)
                quote = char
                continue
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            if char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
            current.append(char)

        if current:
            parts.append("".join(current).strip())
        return parts

    def _format_history(self) -> str:
        rows = []
        for item in self.history:
            rows.append(
                "Step {step}\nThought: {thought}\nAction: {action}\nObservation: {observation}".format(
                    step=item["step"],
                    thought=item.get("thought") or ReActAgent._extract_label(item["thought_action"], "Thought"),
                    action=item.get("action") or ReActAgent._extract_label(item["thought_action"], "Action"),
                    observation=item["observation"],
                )
            )
        return "\n\n".join(rows)
