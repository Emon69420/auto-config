"""Exceptions raised by the generator pipeline.

The routes map these to HTTP responses, so the rest of the codebase can raise
domain errors without knowing about the web layer.
"""


class ConfigError(RuntimeError):
    """The site could not be turned into a config for a reason worth saying."""


class LLMError(RuntimeError):
    """The LLM backend could not be reached or refused to answer."""


class ValidationFailed(Exception):
    """A generated config failed automated validation.

    Carries the validation report so the route can return it alongside the
    error (spec section 3.1).
    """

    def __init__(self, report: dict):
        super().__init__("Config validation failed")
        self.report = report


class RenderingError(RuntimeError):
    """A page could not be rendered in a browser."""