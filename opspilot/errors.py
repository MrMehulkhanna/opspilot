"""Domain errors, mapped to HTTP status codes by the API layer."""


class OpsPilotError(Exception):
    status_code = 400


class NotFound(OpsPilotError):
    status_code = 404


class Conflict(OpsPilotError):
    status_code = 409


class ValidationError(OpsPilotError):
    status_code = 422
