"""Reusable JSON loading and dataset validation utilities.

This module loads the support datasets exactly once per application startup,
validates them, and returns a structured in-memory container that future tools
and agent components can share.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from app.config import CUSTOMERS_FILE, ORDERS_FILE, PRODUCTS_FILE, TICKETS_FILE
from app.schemas import Customer, LoadedData, Order, Product, Ticket


class DataLoaderError(Exception):
    """Base exception for data loading and validation failures."""


class MissingDataFileError(DataLoaderError, FileNotFoundError):
    """Raised when an expected dataset file does not exist."""


class InvalidJSONError(DataLoaderError, ValueError):
    """Raised when a dataset file contains malformed JSON."""


class InvalidDatasetTypeError(DataLoaderError, TypeError):
    """Raised when a dataset JSON file does not contain a top-level list."""


class EmptyDatasetError(DataLoaderError, ValueError):
    """Raised when a dataset file contains an empty list."""


class DatasetValidationError(DataLoaderError, ValueError):
    """Raised when an item fails schema validation."""


def load_json(file_path: str | Path) -> Any:
    """Load and parse JSON from disk with explicit, helpful errors."""
    path = Path(file_path)

    if not path.exists():
        raise MissingDataFileError(f"Dataset file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise InvalidJSONError(
            f"Invalid JSON in file '{path.name}': {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc


def validate_list_of_objects(
    data: Any,
    schema: Type[BaseModel],
    dataset_name: str,
) -> list[BaseModel]:
    """Validate a top-level list of dataset items against a Pydantic schema."""
    if not isinstance(data, list):
        raise InvalidDatasetTypeError(
            f"Dataset '{dataset_name}' must be a top-level JSON list, got {type(data).__name__}."
        )

    if not data:
        raise EmptyDatasetError(f"Dataset '{dataset_name}' is empty.")

    validated_items: list[BaseModel] = []

    for index, item in enumerate(data):
        try:
            validated_items.append(schema.model_validate(item))
        except ValidationError as exc:
            raise DatasetValidationError(
                f"Validation failed for dataset '{dataset_name}' at item index {index}: {exc}"
            ) from exc

    return validated_items


def load_all_data() -> LoadedData:
    """Load and validate all supported datasets into a single container."""
    customers_data = load_json(CUSTOMERS_FILE)
    orders_data = load_json(ORDERS_FILE)
    products_data = load_json(PRODUCTS_FILE)
    tickets_data = load_json(TICKETS_FILE)

    customers = validate_list_of_objects(customers_data, Customer, "customers")
    orders = validate_list_of_objects(orders_data, Order, "orders")
    products = validate_list_of_objects(products_data, Product, "products")
    tickets = validate_list_of_objects(tickets_data, Ticket, "tickets")

    return LoadedData(
        customers=customers,
        orders=orders,
        products=products,
        tickets=tickets,
    )


def load_and_validate_data() -> LoadedData:
    """Alias kept for readability and future extension points."""
    return load_all_data()
