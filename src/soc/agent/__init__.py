"""에이전트 계층. 파이프는 run_agent(AgentTask) -> AgentResult 하나로 부른다(에이전트 구조, D-024).

에이전트 프레임워크는 OpenAI Agents SDK다(D-022). 트레이싱은 진입점에서 끈다.
"""

from soc.agent.runner import first_call_size, run_agent
from soc.agent.types import FAILURES, AgentResult, AgentTask, AgentWorker, TaskPrompt

__all__ = [
    "FAILURES",
    "AgentResult",
    "AgentTask",
    "AgentWorker",
    "TaskPrompt",
    "first_call_size",
    "run_agent",
]
