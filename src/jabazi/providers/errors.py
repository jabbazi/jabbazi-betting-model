"""Allowlisted operational diagnostics; never serialize URLs, keys or bodies."""

def error_details(exc):
    from .odds_transport import ProviderUnavailable
    if isinstance(exc, ProviderUnavailable):
        return {k: v for k, v in exc.details.items() if k in {
            "http_status", "reason", "provider_code", "retry_at", "observed_at"
        }} | {"error_type": "ProviderUnavailable"}
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        code = getattr(getattr(exc, "response", None), "status_code", None)
    details = {"error_type": type(exc).__name__}
    if isinstance(code, int) and 100 <= code <= 599:
        details["http_status"] = code
        details["reason"] = {
            401: "PROVIDER_AUTHENTICATION_OR_QUOTA",
            403: "PROVIDER_ACCESS_DENIED",
            404: "PROVIDER_RESOURCE_NOT_FOUND",
            429: "PROVIDER_RATE_LIMITED",
        }.get(code, "PROVIDER_HTTP_FAILURE")
    return details
