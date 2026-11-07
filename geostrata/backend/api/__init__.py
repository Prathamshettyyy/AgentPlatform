"""GeoStrata Application API.

Canonical FastAPI application factory for GeoStrata domain services.
"""
from geostrata.backend.api.app import create_geostrata_app

__all__ = ["create_geostrata_app"]
