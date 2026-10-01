class AegisError(Exception):
    """An actionable domain error suitable for CLI/API presentation."""


class ConfigurationError(AegisError):
    pass


class DataIntegrityError(AegisError):
    pass


class NotFoundError(AegisError):
    pass


class GovernanceError(AegisError):
    pass
