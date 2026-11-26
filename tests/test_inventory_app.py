import os
import tempfile
import threading
import unittest

from thesagra import THESAGRAServer
from thesagra.drivers.python.client import THESAGRAConnection
from inventory_app.store import (
    DuplicateSKU,
    InsufficientStock,
    InventoryStore,
    ProductNotFound,
)


class InventoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.directory.name, "stockroom.db")
        self.store = InventoryStore(self.database_path)

    def tearDown(self):
        self.directory.cleanup()

    def test_duplicate_sku_is_rejected(self):
        self.store.create_product("MUG-01", "Travel mug", 18.5, 6)

        with self.assertRaises(DuplicateSKU):
            self.store.create_product("MUG-01", "Another mug", 20, 2)

    def test_order_reduces_stock_and_updates_summary(self):
        product = self.store.create_product("BEAN-01", "Coffee beans", 12.5, 8)

        order = self.store.create_order(
            "Ada Lovelace",
            [{"product_id": product["id"], "quantity": 3}],
        )

        self.assertEqual(order["total"], 37.5)
        self.assertEqual(order["items"][0]["product_name"], "Coffee beans")
        self.assertEqual(self.store.list_products()[0]["stock_quantity"], 5)
        self.assertEqual(self.store.summary()["order_count"], 1)

    def test_invalid_order_rolls_back_without_changing_stock(self):
        product = self.store.create_product("TEA-01", "Green tea", 7, 2)

        with self.assertRaises(InsufficientStock):
            self.store.create_order(
                "Grace Hopper",
                [{"product_id": product["id"], "quantity": 3}],
            )

        self.assertEqual(self.store.list_orders(), [])
        self.assertEqual(self.store.list_products()[0]["stock_quantity"], 2)

    def test_unknown_product_is_rejected(self):
        with self.assertRaises(ProductNotFound):
            self.store.create_order(
                "Grace Hopper",
                [{"product_id": 999, "quantity": 1}],
            )

    def test_inventory_persists_when_store_reopens(self):
        self.store.create_product("PEN-01", "Fountain pen", 32, 4)

        reopened = InventoryStore(self.database_path)

        self.assertEqual(reopened.list_products()[0]["sku"], "PEN-01")

    def test_inventory_store_uses_remote_database_connection(self):
        data_directory = os.path.join(self.directory.name, "hosted")
        server = THESAGRAServer(
            os.path.join(self.directory.name, "unused.db"),
            host="127.0.0.1",
            port=0,
            username="root",
            password="strong-admin-secret",
            database_directory=data_directory,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        store = None
        reopened = None
        try:
            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="strong-admin-secret",
            ) as admin:
                admin.create_database("stockroom")
                admin.create_role("stockroom_rw")
                admin.create_user("stockroom_app", "stockroom-app-secret")
                admin.grant_role("stockroom_rw", "stockroom_app")
                for privilege in ("CONNECT", "READ", "WRITE"):
                    admin.grant_database(
                        "stockroom_rw",
                        "stockroom",
                        privilege,
                    )

            uri = (
                f"thesagra://stockroom_app:stockroom-app-secret@"
                f"{host}:{port}/stockroom"
            )
            store = InventoryStore(connection_url=uri)
            product = store.create_product(
                "REMOTE-01",
                "Remote inventory item",
                14.5,
                5,
            )
            order = store.create_order(
                "Ada Lovelace",
                [{"product_id": product["id"], "quantity": 2}],
            )
            self.assertEqual(order["total"], 29.0)
            store.close()

            reopened = InventoryStore(connection_url=uri)
            self.assertEqual(
                reopened.list_products()[0]["stock_quantity"],
                3,
            )
            self.assertEqual(reopened.summary()["order_count"], 1)
        finally:
            if store is not None:
                store.close()
            if reopened is not None:
                reopened.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
