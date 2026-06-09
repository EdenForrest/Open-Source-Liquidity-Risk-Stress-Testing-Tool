"""Pydantic request/response schemas for the FastAPI backend.

Schemas live here (rather than inline in routers) so the HTTP layer stays a thin
shell over the service layer. See ``backend.schemas.analysis`` for the request
models consumed by ``backend.routers.analysis``.
"""
