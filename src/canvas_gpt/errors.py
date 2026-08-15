class CanvasGPTError(Exception):
    """Base exception for errors that should be shown cleanly in the CLI."""


class NotInitializedError(CanvasGPTError):
    pass


class NodeNotFoundError(CanvasGPTError):
    pass


class ProviderError(CanvasGPTError):
    pass

