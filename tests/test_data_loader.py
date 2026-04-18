import json
from pathlib import Path

import pytest

from app.data_loader import (
    DatasetValidationError,
    EmptyDatasetError,
    InvalidDatasetTypeError,
    InvalidJSONError,
    MissingDataFileError,
    load_all_data,
    load_json,
    validate_list_of_objects,
)
from app.schemas import Customer, Ticket


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def customer_payload() -> dict:
    return {
        "customer_id": "C001",
        "name": "Alice Smith",
        "email": "ALICE@example.com",
        "phone": "1234567890",
        "tier": "gold",
        "member_since": "2023-01-10",
        "total_orders": 4,
        "total_spent": 499.99,
        "address": {
            "street": "1 Main St",
            "city": "Springfield",
            "state": "CA",
            "zip": "90001",
        },
        "notes": "VIP customer",
    }


def order_payload() -> dict:
    return {
        "order_id": "O001",
        "customer_id": "C001",
        "product_id": "P001",
        "quantity": 1,
        "amount": 99.99,
        "status": "shipped",
        "order_date": "2024-01-15",
        "delivery_date": "2024-01-18",
        "return_deadline": "2024-02-15",
        "refund_status": "not_requested",
        "notes": "Leave at front desk",
    }


def product_payload() -> dict:
    return {
        "product_id": "P001",
        "name": "Widget",
        "category": "Gadgets",
        "price": 99.99,
        "warranty_months": 12,
        "return_window_days": 30,
        "returnable": True,
        "notes": "Popular item",
    }


def ticket_payload() -> dict:
    return {
        "ticket_id": "T001",
        "customer_email": "ALICE@example.com",
        "subject": "Where is my order?",
        "body": "I want to know the shipment status.",
        "source": "email",
        "created_at": "2024-01-16T10:00:00Z",
        "tier": "gold",
        "expected_action": "track_order",
    }


def create_all_dataset_files(base_dir: Path) -> None:
    write_json(base_dir / "customers.json", [customer_payload()])
    write_json(base_dir / "orders.json", [order_payload()])
    write_json(base_dir / "products.json", [product_payload()])
    write_json(base_dir / "tickets.json", [ticket_payload()])


def test_load_json_reads_valid_json_file(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.json"
    payload = [{"id": 1, "name": "example"}]
    write_json(file_path, payload)

    result = load_json(file_path)

    assert result == payload


def test_load_json_raises_file_not_found_for_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(MissingDataFileError) as exc_info:
        load_json(missing_path)

    assert str(missing_path) in str(exc_info.value)


def test_load_json_raises_value_error_for_invalid_json(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.json"
    file_path.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(InvalidJSONError) as exc_info:
        load_json(file_path)

    message = str(exc_info.value)
    assert "broken.json" in message
    assert "Invalid JSON" in message


def test_validate_list_of_objects_returns_validated_models_and_normalizes_email() -> None:
    data = [customer_payload()]

    result = validate_list_of_objects(data, Customer, "customers")

    assert len(result) == 1
    assert result[0].email == "alice@example.com"


def test_validate_list_of_objects_raises_for_wrong_top_level_type() -> None:
    data = {"customer_id": "C001"}

    with pytest.raises(InvalidDatasetTypeError) as exc_info:
        validate_list_of_objects(data, Customer, "customers")

    message = str(exc_info.value)
    assert "customers" in message
    assert "list" in message


def test_validate_list_of_objects_raises_for_empty_list() -> None:
    with pytest.raises(EmptyDatasetError) as exc_info:
        validate_list_of_objects([], Customer, "customers")

    message = str(exc_info.value)
    assert "customers" in message
    assert "empty" in message.lower()


def test_validate_list_of_objects_raises_validation_error_with_dataset_context() -> None:
    invalid_customer = customer_payload()
    invalid_customer["address"].pop("city")

    with pytest.raises(DatasetValidationError) as exc_info:
        validate_list_of_objects([invalid_customer], Customer, "customers")

    message = str(exc_info.value)
    assert "customers" in message
    assert "0" in message or "index" in message.lower()


def test_load_all_data_loads_all_datasets_and_normalizes_emails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_all_dataset_files(tmp_path)

    monkeypatch.setattr("app.data_loader.CUSTOMERS_FILE", tmp_path / "customers.json")
    monkeypatch.setattr("app.data_loader.ORDERS_FILE", tmp_path / "orders.json")
    monkeypatch.setattr("app.data_loader.PRODUCTS_FILE", tmp_path / "products.json")
    monkeypatch.setattr("app.data_loader.TICKETS_FILE", tmp_path / "tickets.json")

    loaded = load_all_data()

    assert len(loaded.customers) == 1
    assert len(loaded.orders) == 1
    assert len(loaded.products) == 1
    assert len(loaded.tickets) == 1
    assert loaded.customers[0].email == "alice@example.com"
    assert loaded.tickets[0].customer_email == "alice@example.com"


def test_load_all_data_propagates_empty_dataset_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_json(tmp_path / "customers.json", [])
    write_json(tmp_path / "orders.json", [order_payload()])
    write_json(tmp_path / "products.json", [product_payload()])
    write_json(tmp_path / "tickets.json", [ticket_payload()])

    monkeypatch.setattr("app.data_loader.CUSTOMERS_FILE", tmp_path / "customers.json")
    monkeypatch.setattr("app.data_loader.ORDERS_FILE", tmp_path / "orders.json")
    monkeypatch.setattr("app.data_loader.PRODUCTS_FILE", tmp_path / "products.json")
    monkeypatch.setattr("app.data_loader.TICKETS_FILE", tmp_path / "tickets.json")

    with pytest.raises(EmptyDatasetError) as exc_info:
        load_all_data()

    assert "customers" in str(exc_info.value)


def test_load_all_data_raises_for_wrong_top_level_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_json(tmp_path / "customers.json", {"customer_id": "C001"})
    write_json(tmp_path / "orders.json", [order_payload()])
    write_json(tmp_path / "products.json", [product_payload()])
    write_json(tmp_path / "tickets.json", [ticket_payload()])

    monkeypatch.setattr("app.data_loader.CUSTOMERS_FILE", tmp_path / "customers.json")
    monkeypatch.setattr("app.data_loader.ORDERS_FILE", tmp_path / "orders.json")
    monkeypatch.setattr("app.data_loader.PRODUCTS_FILE", tmp_path / "products.json")
    monkeypatch.setattr("app.data_loader.TICKETS_FILE", tmp_path / "tickets.json")

    with pytest.raises(InvalidDatasetTypeError) as exc_info:
        load_all_data()

    assert "customers" in str(exc_info.value)


def test_validate_list_of_objects_normalizes_ticket_customer_email() -> None:
    data = [ticket_payload()]

    result = validate_list_of_objects(data, Ticket, "tickets")

    assert result[0].customer_email == "alice@example.com"
