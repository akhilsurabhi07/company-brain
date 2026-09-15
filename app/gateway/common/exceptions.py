"""
Common Gateway Exceptions — Module 5 EKAP
=========================================
"""
class GatewayException(Exception):
    def __init__(self, message: str, code: str = "GATEWAY_ERROR", status_code: int = 500, details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

class AuthenticationException(GatewayException):
    def __init__(self, message: str = "Invalid authentication credentials"):
        super().__init__(message, code="UNAUTHORIZED", status_code=401)

class AuthorizationException(GatewayException):
    def __init__(self, message: str = "Access denied due to policy restriction"):
        super().__init__(message, code="FORBIDDEN", status_code=403)

class RateLimitException(GatewayException):
    def __init__(self, message: str = "Tenant quota rate limit exceeded"):
        super().__init__(message, code="TOO_MANY_REQUESTS", status_code=429)

class ValidationException(GatewayException):
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, code="BAD_REQUEST", status_code=400, details=details)

class NotFoundException(GatewayException):
    def __init__(self, message: str = "The requested resource was not found."):
        super().__init__(message, code="NOT_FOUND", status_code=404)

class TimeoutException(GatewayException):
    def __init__(self, message: str = "Gateway execution request timed out"):
        super().__init__(message, code="GATEWAY_TIMEOUT", status_code=540)
