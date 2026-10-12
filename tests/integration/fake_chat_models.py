"""Shared scripted fake chat models for deterministic agent-pipeline
tests (no live API key). Not a test module itself -- doesn't match
test_*.py, so pytest never collects it.
"""

from typing import Any, Iterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr


class ScriptedInvestigatorFake(BaseChatModel):
    """Routes to a different scripted AIMessage sequence per investigated
    symbol (parsed from the seed HumanMessage's "Changed symbols" list),
    falling back to `default_script` for any symbol without one.

    Needed because a container class's body_hash changes whenever any of
    its methods does (see git/diff.py), so a single PR edit routinely
    triggers multiple simultaneous investigations -- a fixed linear
    script would silently desync across them.
    """

    scripts: dict[str, list[AIMessage]]
    default_script: list[AIMessage]
    _iterators: dict[str, Iterator[AIMessage]] = PrivateAttr(default_factory=dict)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedInvestigatorFake":
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        symbol = self._infer_symbol(messages)
        if symbol not in self._iterators:
            script = self.scripts.get(symbol, self.default_script)
            self._iterators[symbol] = iter(script)
        message = next(self._iterators[symbol])
        return ChatResult(generations=[ChatGeneration(message=message)])

    @staticmethod
    def _infer_symbol(messages: list[BaseMessage]) -> str:
        for message in messages:
            if isinstance(message, HumanMessage) and "Changed symbols" in str(message.content):
                for line in str(message.content).splitlines():
                    if line.startswith("- "):
                        return line[2:].strip()
        return ""

    @property
    def _llm_type(self) -> str:
        return "scripted-investigator-fake"


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def submit_finding_call(call_id: str, **overrides: Any) -> AIMessage:
    args = {
        "verdict": "no_issue",
        "requirement_ids": [],
        "changed_symbol_ids": [],
        "summary": "s",
        "reasoning": "r",
        "citations": [],
        "unresolved_questions": [],
        "model_confidence": 0.9,
        **overrides,
    }
    return AIMessage(content="", tool_calls=[{"name": "submit_finding", "args": args, "id": call_id}])


def default_abstain_script() -> list[AIMessage]:
    return [submit_finding_call("default-1", verdict="insufficient_evidence", model_confidence=0.1)]
