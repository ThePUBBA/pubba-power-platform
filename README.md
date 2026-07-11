# Only1 LMP API

FastAPI service for retrieving CAISO locational marginal price (LMP) data for Only1 Power workflows.

## Overview

This API exposes a simple HTTP interface for LMP lookups. It is intended to support market research, dispatch analysis, reporting, and downstream automation for energy storage and trading workflows.

## Endpoints

### `GET /`

Health check endpoint.

Example response:

```json
{"message":"Only1 LMP API is running"}
```

### `GET /lmp`

Fetch LMP records for a market, location, and optional date.

Query parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `market` | `LMP` | CAISO market/product identifier. |
| `location` | `TH_NP15_GEN-APND` | CAISO pricing node or location code. |
| `date` | `null` | Optional date passed through to the CAISO fetch layer. |

Example:

```bash
curl "http://localhost:8000/lmp?market=LMP&location=TH_NP15_GEN-APND"
```

## Local Development

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the API:

```bash
uvicorn main:app --reload
```

Open the interactive API docs at:

```text
http://localhost:8000/docs
```

## Project Structure

```text
.
├── main.py              # FastAPI routes
├── caiso.py             # CAISO data retrieval logic
├── requirements.txt     # Python dependencies
└── .gitignore           # Local files and generated artifacts to exclude
```

## Notes

`main.py` expects `caiso.py` to provide `fetch_lmp_data(location, market, date)`, returning a pandas DataFrame. Keep fetch-layer assumptions documented as the CAISO integration evolves.

## License

MIT License. See `LICENSE` for details.
