"""
Tool Registry for Autonomous Agents
===================================
Registers and executes Python tools for LLM tool calling.
"""
import logging
import inspect
from typing import Callable, Dict, Any, List

logger = logging.getLogger("company_brain.agents.tools")

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._descriptions: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, description: str, parameters: dict):
        """Decorator to register a tool."""
        def decorator(func: Callable):
            self._tools[name] = func
            self._descriptions[name] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters
                }
            }
            return func
        return decorator

    def get_all_tools(self) -> List[Dict[str, Any]]:
        return list(self._descriptions.values())

    async def execute_tool(self, name: str, **kwargs) -> Any:
        func = self._tools.get(name)
        if not func:
            raise ValueError(f"Tool {name} not found in registry.")
        
        try:
            if inspect.iscoroutinefunction(func):
                return await func(**kwargs)
            else:
                return func(**kwargs)
        except Exception as e:
            logger.error(f"[ToolRegistry] Error executing {name}: {e}")
            return f"Error executing tool {name}: {e}"

tool_registry = ToolRegistry()

# Register some basic built-in tools

@tool_registry.register(
    name="get_current_time",
    description="Returns the current UTC time.",
    parameters={"type": "object", "properties": {}}
)
def get_current_time():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
