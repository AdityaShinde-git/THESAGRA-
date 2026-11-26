import os
import threading

from thesagra.query.engine import QueryError, RelationalEngine
from thesagra.query.parser import parse
from thesagra.server.protocol import bind_parameters
from thesagra.storage.database import DatabaseFile


class InventoryError(Exception):
    pass


class DuplicateSKU(InventoryError):
    pass


class ProductNotFound(InventoryError):
    pass


class InsufficientStock(InventoryError):
    pass


class InventoryStore:
    def __init__(self, database_path):
        self.database_path = os.fspath(database_path)
        os.makedirs(os.path.dirname(os.path.abspath(self.database_path)), exist_ok=True)
        if os.path.isfile(self.database_path):
            database = DatabaseFile.open(self.database_path)
        else:
            database = DatabaseFile.create(self.database_path)
        self.engine = RelationalEngine(database)
        self.lock = threading.RLock()
        self._initialize_schema()

    def _execute(self, sql, parameters=None):
        if parameters:
            sql = bind_parameters(sql, parameters)
        return self.engine.execute(parse(sql))

    def _initialize_schema(self):
        schemas = (
            (
                "products",
                "CREATE TABLE products ("
                "id INTEGER PRIMARY KEY AUTO_INCREMENT, "
                "sku TEXT NOT NULL UNIQUE, "
                "name TEXT NOT NULL, "
                "unit_price REAL NOT NULL, "
                "stock_quantity INTEGER NOT NULL);",
            ),
            (
                "orders",
                "CREATE TABLE orders ("
                "id INTEGER PRIMARY KEY AUTO_INCREMENT, "
                "customer_name TEXT NOT NULL, "
                "total REAL NOT NULL, "
                "status TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);",
            ),
            (
                "order_items",
                "CREATE TABLE order_items ("
                "id INTEGER PRIMARY KEY AUTO_INCREMENT, "
                "order_id INTEGER NOT NULL, "
                "product_id INTEGER NOT NULL, "
                "quantity INTEGER NOT NULL, "
                "unit_price REAL NOT NULL, "
                "FOREIGN KEY (order_id) REFERENCES orders(id), "
                "FOREIGN KEY (product_id) REFERENCES products(id));",
            ),
        )
        with self.lock:
            for table, statement in schemas:
                if table not in self.engine.catalog.tables:
                    self._execute(statement)

    def list_products(self):
        with self.lock:
            result = self._execute(
                "SELECT id, sku, name, unit_price, stock_quantity "
                "FROM products ORDER BY name;"
            )
        return [
            {
                "id": row[0],
                "sku": row[1],
                "name": row[2],
                "unit_price": row[3],
                "stock_quantity": row[4],
            }
            for row in result.rows
        ]

    def create_product(self, sku, name, unit_price, stock_quantity):
        try:
            with self.lock:
                self._execute(
                    "INSERT INTO products (sku, name, unit_price, stock_quantity) "
                    "VALUES (?, ?, ?, ?);",
                    [sku, name, unit_price, stock_quantity],
                )
                result = self._execute(
                    "SELECT id FROM products WHERE sku=?;",
                    [sku],
                )
        except QueryError as exc:
            if "Duplicate primary key or unique value" in str(exc):
                raise DuplicateSKU("A product with this SKU already exists") from exc
            raise
        return {
            "id": result.rows[0][0],
            "sku": sku,
            "name": name,
            "unit_price": unit_price,
            "stock_quantity": stock_quantity,
        }

    def list_orders(self):
        with self.lock:
            orders = self._execute(
                "SELECT id, customer_name, total, status, created_at "
                "FROM orders ORDER BY id DESC;"
            ).rows
            result = []
            for order in orders:
                items = self._execute(
                    "SELECT p.name, oi.quantity, oi.unit_price "
                    "FROM order_items oi "
                    "JOIN products p ON oi.product_id=p.id "
                    "WHERE oi.order_id=?;",
                    [order[0]],
                ).rows
                result.append(
                    {
                        "id": order[0],
                        "customer_name": order[1],
                        "total": order[2],
                        "status": order[3],
                        "created_at": order[4],
                        "items": [
                            {
                                "product_name": item[0],
                                "quantity": item[1],
                                "unit_price": item[2],
                            }
                            for item in items
                        ],
                    }
                )
        return result

    def create_order(self, customer_name, requested_items):
        with self.lock:
            self._execute("BEGIN;")
            try:
                items = {}
                for item in requested_items:
                    product_id = item["product_id"]
                    items[product_id] = items.get(product_id, 0) + item["quantity"]

                selected = {}
                total = 0.0
                for product_id, quantity in items.items():
                    rows = self._execute(
                        "SELECT id, name, unit_price, stock_quantity "
                        "FROM products WHERE id=?;",
                        [product_id],
                    ).rows
                    if not rows:
                        raise ProductNotFound(
                            f"Product {product_id} does not exist"
                        )
                    product = rows[0]
                    if product[3] < quantity:
                        raise InsufficientStock(
                            f"Not enough stock for {product[1]}"
                        )
                    selected[product_id] = product
                    total += product[2] * quantity

                self._execute(
                    "INSERT INTO orders (customer_name, total, status) "
                    "VALUES (?, ?, ?);",
                    [customer_name, round(total, 2), "placed"],
                )
                order_id = self._execute(
                    "SELECT id FROM orders ORDER BY id DESC LIMIT 1;"
                ).rows[0][0]

                for product_id, quantity in items.items():
                    product = selected[product_id]
                    self._execute(
                        "INSERT INTO order_items "
                        "(order_id, product_id, quantity, unit_price) "
                        "VALUES (?, ?, ?, ?);",
                        [order_id, product_id, quantity, product[2]],
                    )
                    self._execute(
                        "UPDATE products SET stock_quantity = "
                        "stock_quantity - ? WHERE id=?;",
                        [quantity, product_id],
                    )
                self._execute("COMMIT;")
            except Exception:
                if self.engine.active_transaction is not None:
                    self._execute("ROLLBACK;")
                raise

        return next(order for order in self.list_orders() if order["id"] == order_id)

    def summary(self):
        with self.lock:
            products = self._execute(
                "SELECT COUNT(*), SUM(stock_quantity) FROM products;"
            ).rows[0]
            orders = self._execute(
                "SELECT COUNT(*), SUM(total) FROM orders;"
            ).rows[0]
        return {
            "product_count": products[0] or 0,
            "units_in_stock": products[1] or 0,
            "order_count": orders[0] or 0,
            "sales_total": orders[1] or 0,
        }
