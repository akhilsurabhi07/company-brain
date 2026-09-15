import logging
import asyncio
from typing import Dict, Any, List
from app.agents.interfaces.agent_interfaces import BaseSubagent, AgentTaskContext, AgentResult
from app.agents.tools.tool_registry import tool_registry
import json

logger = logging.getLogger("company_brain.agents.background_researcher")

class BackgroundResearcherAgent(BaseSubagent):
    """
    Background Researcher Agent.
    Capable of calling Python tools from the tool registry autonomously.
    """

    @property
    def agent_name(self) -> str:
        return "BackgroundResearcher"

    async def execute(self, context: AgentTaskContext) -> AgentResult:
        query_text = context.subtask_query or context.user_query
        logger.info(f"[{self.agent_name}] Starting autonomous background research for: {query_text}")

        # Execute all tools that match the query (In a real system, the LLM would pick the tool)
        # For now, we will just provide the tool registry's available tools as metadata
        available_tools = tool_registry.get_all_tools()
        
        # Mock execution of a time tool if the user asks about time
        executed_tools = []
        tool_results = []
        if "time" in query_text.lower():
            time_res = await tool_registry.execute_tool("get_current_time")
            executed_tools.append("get_current_time")
            tool_results.append(f"Current UTC Time: {time_res}")
            
        summary = f"Background research complete. Tools available: {len(available_tools)}. Tools executed: {len(executed_tools)}."

        return AgentResult(
            agent_name=self.agent_name,
            success=True,
            retrieved_chunks=[{"content": r, "document_title": "Tool Output", "score": 1.0} for r in tool_results],
            citations=["Tool Execution Logs"],
            summary_text=summary,
            metadata={"tools_executed": executed_tools}
        )

background_researcher = BackgroundResearcherAgent()
