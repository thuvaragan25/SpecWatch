"""LLM provider factory: maps a "provider:model" config string to a
langchain-core BaseChatModel.

See plan.md's corrected Review Addendum: `init_chat_model` needs the
full `langchain` metapackage, not just `langchain-core`, so this is a
small hand-rolled equivalent instead -- swapping providers means adding
another small `langchain-<provider>` package and one more branch here,
not the whole metapackage.
"""

from langchain_core.language_models import BaseChatModel


def create_chat_model(model: str) -> BaseChatModel:
    provider, _, model_name = model.partition(":")
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name)
    if provider == "groq":
        from langchain_groq import ChatGroq

        # Free-tier token-per-minute caps are easy to hit across a multi-round
        # tool loop; the client honors retry-after, so retry generously.
        return ChatGroq(model=model_name, max_retries=8)
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model_name, max_retries=6)
    raise ValueError(f"Unsupported model provider: {provider!r} (from config value {model!r})")
