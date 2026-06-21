"""Shared interface and metrics for every forecaster."""

from .protocol import Forecaster, BaseForecaster

__all__ = ["Forecaster", "BaseForecaster"]
