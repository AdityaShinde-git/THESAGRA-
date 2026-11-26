# Stockroom

Stockroom is a local inventory and order-management portfolio application.
It uses FastAPI for the Python API, a small browser UI, and the THESAGRA
database for persistent products, orders, and order items.

## Run locally

From the repository root, install the project and run the app:

```powershell
python -m pip install -e .
python -m inventory_app
```

Open `http://127.0.0.1:8000`. By default, the app creates `stockroom.db` in
the current directory on first run. Set `THESAGRA_DB_PATH` to use another
local database file. Interactive API documentation is available at `/docs`.

## Connect to a THESAGRA server

Set `THESAGRA_URL` on the server-side Stockroom API deployment to use a
remote THESAGRA database instead of a local file:

```text
thesagra://stockroom_app:<url-encoded-password>@<private-host>:5439/stockroom
```

The database, user, and `CONNECT`, `READ`, and `WRITE` grants must already
exist. Stockroom creates its three tables on first connection; the database
user therefore needs permission to create tables. Set `THESAGRA_TLS=true`
when the server connection uses TLS, and optionally set `THESAGRA_TLS_CA` to
the CA certificate path. Keep the URL in the API host's secret environment
variables, never in browser code or source control. When `THESAGRA_URL` is
unset, the app uses local-file mode.

## First-release features

- Add and browse products with SKU, unit price, and available stock.
- Place a customer order against in-stock products.
- Update stock and write the order plus its line items in one transaction.
- View inventory totals and sales summary.
- Use the same-origin browser UI or the documented JSON API.

## API

- `GET /api/products`, `POST /api/products`
- `GET /api/orders`, `POST /api/orders`
- `GET /api/summary`

## Architecture and limitations

The UI is static HTML, CSS, and JavaScript. FastAPI validates requests and
serves JSON endpoints. `InventoryStore` keeps all THESAGRA access behind one
thread lock and uses bound SQL values; order placement uses a THESAGRA
transaction so failed orders do not reduce stock.

THESAGRA is an experimental database prototype, so this application is for
local development and portfolio demonstration, not production or untrusted
public networks. For deployment, use a persistent host and protect the API
with authentication and HTTPS before exposing it.
