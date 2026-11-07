class AgentRuntimeError(Exception):
    """Base error for normalized agent execution failures."""


class AgentNotFoundError(AgentRuntimeError):
    pass


class AgentDisabledError(AgentRuntimeError):
    pass

