"""
config.py — ShopWave Centralised Configuration
===============================================

Purpose:
    Single source of truth for all environment-driven settings and filesystem
    paths.  Importing this module is the *only* place where os.getenv() calls
    for credentials should appear — all other modules read from these constants.

Role in system:
    Imported by data_loader.py (dataset paths), llm.py (OpenAI key), and
    email_service.py (SMTP settings) so that individual modules never contain
    raw os.getenv() calls or hardcoded file names.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from the project root so os.getenv() picks up credentials
# defined there (EMAIL_USER, EMAIL_PASSWORD, OPENAI_API_KEY, etc.)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Filesystem paths ──────────────────────────────────────────────────────────

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

# ── LLM credentials ───────────────────────────────────────────────────────────

# Optional OpenAI key; when absent the agent falls back to heuristic logic.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ── Email / SMTP configuration ────────────────────────────────────────────────
# Set these in a .env file or your shell before running the application.
# For Gmail, use an App Password (not your account password) and make sure
# "Less secure app access" or OAuth is configured appropriately.

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")        # sender address
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "") # app password / SMTP secret
