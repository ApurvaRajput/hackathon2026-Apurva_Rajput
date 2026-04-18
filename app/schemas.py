"""Pydantic schemas for ShopWave support datasets.

These models represent the validated in-memory shape of the JSON data used by
the support agent. Keeping them in one place makes the loader, tests, and
future tools easier to maintain.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class BaseDataModel(BaseModel):
    """Shared schema behavior for all validated dataset items."""

    model_config = ConfigDict(str_strip_whitespace=True)


class Address(BaseDataModel):
    """Postal address nested inside customer records."""

    street: str
    city: str
    state: str
    zip: str
    postal_code: str | None = None
    country: str = "USA"

    @field_validator("postal_code", mode="before")
    @classmethod
    def default_postal_code(cls, value: Any, info: Any) -> Any:
        """Mirror `zip` into `postal_code` when only one is provided."""
        if value is not None:
            return value
        if isinstance(info.data, dict):
            return info.data.get("zip")
        return value

    @field_validator("zip", mode="before")
    @classmethod
    def ensure_zip_present(cls, value: Any, info: Any) -> Any:
        """Accept `postal_code` as input while keeping `zip` as the canonical field."""
        if value is not None:
            return value
        if isinstance(info.data, dict):
            return info.data.get("postal_code")
        return value


class Customer(BaseDataModel):
    """Customer profile used for support lookup and policy checks."""

    customer_id: str
    name: str
    email: EmailStr
    phone: str | None = None
    tier: str | None = None
    member_since: str | None = None
    total_orders: int | None = Field(default=None, ge=0)
    total_spent: float | None = Field(default=None, ge=0)
    address: Address
    notes: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: Any) -> Any:
        """Normalize emails to lowercase for stable joins across datasets."""
        if isinstance(value, str):
            return value.strip().lower()
        return value


class Order(BaseDataModel):
    """Customer purchase record referenced during support resolution."""

    order_id: str
    customer_id: str
    product_id: str
    quantity: int = Field(gt=0)
    amount: float = Field(ge=0)
    status: str
    order_date: str
    delivery_date: str | None = None
    return_deadline: str | None = None
    refund_status: str | None = None
    notes: str | None = None


class Product(BaseDataModel):
    """Catalog item referenced by orders and support workflows."""

    product_id: str
    name: str
    category: str
    price: float = Field(ge=0)
    warranty_months: int | None = Field(default=None, ge=0)
    return_window_days: int | None = Field(default=None, ge=0)
    returnable: bool | None = None
    notes: str | None = None


class Ticket(BaseDataModel):
    """Incoming support ticket to be processed by the future agent."""

    ticket_id: str
    customer_email: EmailStr
    subject: str
    body: str
    source: str
    created_at: str
    tier: str | None = None
    expected_action: str | None = None

    @field_validator("customer_email", mode="before")
    @classmethod
    def normalize_customer_email(cls, value: Any) -> Any:
        """Normalize ticket email values for matching against customers."""
        if isinstance(value, str):
            return value.strip().lower()
        return value


class LoadedData(BaseModel):
    """Container that stores all validated datasets in memory."""

    customers: list[Customer]
    orders: list[Order]
    products: list[Product]
    tickets: list[Ticket]
