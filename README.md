# ShopWave Support Agent - Step 1

Step 1 focuses on **project structure, JSON data loading, and schema validation**.  
No agent logic, LLM workflow, tools, or API routes are implemented in this stage.

## Requirements

- Python 3.10+
- Recommended dependencies:
  - `pydantic`
  - `pytest`

Example install:

```bash
pip install pydantic pytest
```

## Recommended Folder Structure

```text
d:/KSolvees Hack/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── schemas.py
│   ├── data_loader.py
│   └── main.py
├── data/
│   ├── customers.json
│   ├── orders.json
│   ├── products.json
│   └── tickets.json
├── tests/
│   └── test_data_loader.py
├── docs/
├── outputs/
├── requirements.txt
└── README.md
```

## Key Files

### `app/config.py`
Centralizes dataset names, filenames, and file paths so the rest of the code avoids hardcoded paths.

### `app/schemas.py`
Defines the Pydantic models used to validate data loaded from JSON:
- `Address`
- `Customer`
- `Order`
- `Product`
- `Ticket`
- a container model for all loaded datasets

This is also the right place for lightweight normalization such as lowercasing customer email fields.

### `app/data_loader.py`
Implements reusable loading and validation helpers:
- `load_json(file_path)`
- `validate_list_of_objects(data, schema, dataset_name)`
- `load_all_data()` or `load_and_validate_data()`

Responsibilities:
- read JSON safely
- raise clear errors for missing files
- raise helpful errors for invalid JSON
- ensure each dataset is a top-level list
- reject empty datasets
- validate each item with dataset and index context
- return one in-memory structured container for reuse

### `app/main.py`
Entry point for a simple Step 1 smoke test. It should load all datasets and print counts plus a success message.

### `tests/test_data_loader.py`
Pytest coverage for loader and validation behavior using temporary files created with `tmp_path`.  
Tests should not depend on repository data files.

## Loading Flow

### Pseudocode

```text
for each dataset in configured dataset paths:
    raw_data = load_json(path)
    validated_items = validate_list_of_objects(raw_data, schema, dataset_name)
collect all validated datasets into one container
return the container
```

## Data Flow

1. JSON files in `data/` are read once.
2. Raw Python data is parsed from disk.
3. Each dataset is validated against a Pydantic schema.
4. Validated objects are grouped into a single container.
5. The rest of the application can reuse this in-memory data instead of re-reading files.

## Why This Structure Helps Later

This layout keeps the project easy to extend:

- **config is centralized** so future environments or dataset locations are easy to change
- **schemas are reusable** for tools, APIs, and agent responses
- **data loading is isolated** so validation rules stay in one place
- **tests stay focused** on correctness of file handling and input validation
- **main stays minimal** and can later be replaced or extended by API/agent entry points

That makes Step 2+ work simpler when adding lookup tools like `get_customer()`, `get_order()`, and ticket-driven agent workflows.