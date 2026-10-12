"""Cross-cutting domain exceptions."""


class ContainerOrchestratorException(Exception):
    """Base domain exception for the container orchestrator."""


class ContainerAlreadyExistsError(ContainerOrchestratorException):
    """Raised when scheduling a container with an existing name."""


class InsufficientCapacityError(ContainerOrchestratorException):
    """Raised when no machine in the fleet has sufficient CPU and memory."""


class ContainerNotFoundError(ContainerOrchestratorException):
    """Raised when the requested container is not found in the fleet."""


class ContainerAlreadyStoppedError(ContainerOrchestratorException):
    """Raised when attempting to stop a container that is already stopped."""
