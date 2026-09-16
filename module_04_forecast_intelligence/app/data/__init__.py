"""
Frost OS Module 04 — Data Ingestion & Adapters Package.
"""

from app.data.nwp_adapter import NWPAdapterBase, MockNWPProvider, get_nwp_adapter
from app.data.weather_client import WeatherClient
from app.data.historical_loader import HistoricalDataLoader

__all__ = [
    "NWPAdapterBase",
    "MockNWPProvider",
    "get_nwp_adapter",
    "WeatherClient",
    "HistoricalDataLoader",
]
