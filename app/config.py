"""Central configuration for dataset locations and loader defaults."""

from __future__ import annotations

from pathlib import Path

# Base directory for the repository.
BASE_DIR = Path(__file__).resolve().parent.parent

# Directory that stores JSON datasets used by the support agent.
DATA_DIR = BASE_DIR / "data"

# Canonical dataset filenames. Keep all dataset path decisions here so that
# loader and future tools do not hardcode file names in multiple places.
CUSTOMERS_FILENAME = "customers.json"
ORDERS_FILENAME = "orders.json"
PRODUCTS_FILENAME = "products.json"
TICKETS_FILENAME = "tickets.json"

# Individual dataset paths are exposed as named constants so tests and future
# code can monkeypatch them without rebuilding the full mapping.
CUSTOMERS_FILE = DATA_DIR / CUSTOMERS_FILENAME
ORDERS_FILE = DATA_DIR / ORDERS_FILENAME
PRODUCTS_FILE = DATA_DIR / PRODUCTS_FILENAME
TICKETS_FILE = DATA_DIR / TICKETS_FILENAME

# Mapping from logical dataset name to its on-disk location.
DATASET_PATHS: dict[str, Path] = {
    "customers": CUSTOMERS_FILE,
    "orders": ORDERS_FILE,
    "products": PRODUCTS_FILE,
    "tickets": TICKETS_FILE,
}
