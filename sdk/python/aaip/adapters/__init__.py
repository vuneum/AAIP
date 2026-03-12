"""
AAIP Framework Adapters
Plug your existing agents into the AAIP network without rebuilding them.

Supported frameworks:
    - LangChain (AAIPLangChainAgent)
    - CrewAI (AAIPCrewAdapter)
    - OpenAI Agents SDK (AAIPOpenAIAgent)
    - AutoGPT (AAIPAutoGPTAdapter)

Usage:
    from aaip.adapters.langchain import AAIPLangChainAgent
    from aaip.adapters.crewai import AAIPCrewAdapter
    from aaip.adapters.openai_agents import AAIPOpenAIAgent
    from aaip.adapters.autogpt import AAIPAutoGPTAdapter
"""

# Lazy imports to avoid requiring all frameworks to be installed
def __getattr__(name):
    if name in ("AAIPLangChainAgent", "register_langchain_agent"):
        from .langchain import AAIPLangChainAgent, register_langchain_agent  # noqa: F401
        return locals()[name]
    if name in ("AAIPCrewAdapter", "register_crew"):
        from .crewai import AAIPCrewAdapter, register_crew  # noqa: F401
        return locals()[name]
    if name in ("AAIPOpenAIAgent", "register_openai_agent"):
        from .openai_agents import AAIPOpenAIAgent, register_openai_agent  # noqa: F401
        return locals()[name]
    if name in ("AAIPAutoGPTAdapter", "register_autogpt_agent"):
        from .autogpt import AAIPAutoGPTAdapter, register_autogpt_agent  # noqa: F401
        return locals()[name]
    raise AttributeError(f"module 'aaip.adapters' has no attribute {name!r}")
