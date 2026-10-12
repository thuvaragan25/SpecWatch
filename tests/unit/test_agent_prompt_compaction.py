from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from specwatch.agent.graph import (
    KEEP_RECENT_TOOL_RESULTS,
    OLD_TOOL_RESULT_CHARS,
    _compact_history,
    _truncate,
)


def test_truncate_leaves_short_text_alone_and_marks_cut_text() -> None:
    assert _truncate("abc", 10) == "abc"
    cut = _truncate("x" * 50, 10)
    assert cut.startswith("x" * 10)
    assert "truncated 40 chars" in cut


def test_compact_history_shortens_only_older_tool_results_without_mutating() -> None:
    big = "[ev-1]\n" + "y" * 5000
    messages = [HumanMessage(content="seed")]
    for i in range(KEEP_RECENT_TOOL_RESULTS + 2):
        messages.append(AIMessage(content=""))
        messages.append(ToolMessage(content=big, tool_call_id=str(i)))

    compacted = _compact_history(messages)

    tool_results = [m for m in compacted if isinstance(m, ToolMessage)]
    older, recent = tool_results[:-KEEP_RECENT_TOOL_RESULTS], tool_results[-KEEP_RECENT_TOOL_RESULTS:]
    assert all(len(m.content) < OLD_TOOL_RESULT_CHARS + 100 and m.content.startswith("[ev-1]") for m in older)
    assert all(m.content == big for m in recent)
    assert all(m.content == big for m in messages if isinstance(m, ToolMessage))
