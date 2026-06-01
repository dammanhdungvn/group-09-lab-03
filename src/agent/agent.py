import re
import ast
import json
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

    def get_system_prompt(self) -> str:
        """
        TODO: Implement the system prompt that instructs the agent to follow ReAct.
        Should include:
        1.  Available tools and their descriptions.
        2.  Format instructions: Thought, Action, Observation.
        """
        tool_descriptions = "\n".join([f"- {t['name']}: {t['description']}" for t in self.tools])
        return f"""
        You are an intelligent assistant. You have access to the following tools:
        {tool_descriptions}

        Use the following format:
        Thought: your line of reasoning.
        Action: tool_name(arguments)
        Observation: result of the tool call.
        ... (repeat Thought/Action/Observation if needed)
        Final Answer: your final response.
        """

    def run(self, user_input: str) -> str:
        """
        TODO: Implement the ReAct loop logic.
        1. Generate Thought + Action.
        2. Parse Action and execute Tool.
        3. Append Observation to prompt and repeat until Final Answer.
        """
        logger.log_event("AGENT_START", {"input": user_input, "model": self.llm.model_name})
        
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

            final_answer = self._parse_final_answer(content)
            if final_answer:
                logger.log_event("AGENT_END", {"steps": steps + 1, "status": "final_answer"})
                return final_answer

            try:
                action = self._parse_action(content)
            except (ValueError, SyntaxError, json.JSONDecodeError) as exc:
                logger.log_event("PARSER_ERROR", {"step": steps + 1, "error": str(exc), "content": content})
                return f"Parser error: {exc}"
            if action is None:
                logger.log_event("AGENT_END", {"steps": steps + 1, "status": "no_action"})
                return content.strip()

            tool_name, args = action
            observation = self._execute_tool(tool_name, args)
            self.history.append(
                {
                    "step": steps + 1,
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
            
        logger.log_event("AGENT_END", {"steps": steps, "status": "max_steps"})
        return "Unable to complete within max_steps."

    def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Helper method to execute tools by name.
        """
        for tool in self.tools:
            if tool['name'] == tool_name:
                func = tool.get("func")
                if not callable(func):
                    return f"Tool {tool_name} has no callable implementation."
                try:
                    result = func(**args)
                    return json.dumps(result, ensure_ascii=False)
                except Exception as exc:
                    logger.log_event("TOOL_ERROR", {"tool": tool_name, "args": args, "error": str(exc)})
                    return f"Tool {tool_name} failed: {exc}"
        logger.log_event("TOOL_NOT_FOUND", {"tool": tool_name, "args": args})
        return f"Tool {tool_name} not found."

    def _parse_action(self, content: str) -> Optional[tuple[str, Dict[str, Any]]]:
        match = re.search(r"Action:\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\((.*?)\)", content, re.DOTALL)
        if not match:
            return None

        tool_name = match.group(1)
        raw_args = match.group(2).strip()
        return tool_name, self._parse_args(raw_args)

    @staticmethod
    def _parse_final_answer(content: str) -> Optional[str]:
        match = re.search(r"Final Answer:\s*(.*)", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _parse_args(raw_args: str) -> Dict[str, Any]:
        if not raw_args:
            return {}

        if raw_args.startswith("{") and raw_args.endswith("}"):
            return json.loads(raw_args)

        parsed: Dict[str, Any] = {}
        for item in raw_args.split(","):
            if not item.strip():
                continue
            key, _, value = item.partition("=")
            if not key or not value:
                raise ValueError(f"Invalid tool argument: {item}")
            parsed[key.strip()] = ast.literal_eval(value.strip())
        return parsed

    def _format_history(self) -> str:
        rows = []
        for item in self.history:
            rows.append(
                "Step {step}\n{thought_action}\nObservation: {observation}".format(
                    step=item["step"],
                    thought_action=item["thought_action"],
                    observation=item["observation"],
                )
            )
        return "\n\n".join(rows)
