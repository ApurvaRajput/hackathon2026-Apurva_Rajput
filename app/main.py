"""Entry point for verifying dataset loading during Step 1."""

from __future__ import annotations

from app.data_loader import DataLoaderError, load_all_data


def main() -> None:
    """Load datasets and print simple readiness information."""
    try:
        data = load_all_data()
    except DataLoaderError as exc:
        print(f"Failed to load datasets: {exc}")
        raise SystemExit(1) from exc

    print("ShopWave datasets loaded successfully.")
    print(f"Customers: {len(data.customers)}")
    print(f"Orders: {len(data.orders)}")
    print(f"Products: {len(data.products)}")
    print(f"Tickets: {len(data.tickets)}")


if __name__ == "__main__":
    main()