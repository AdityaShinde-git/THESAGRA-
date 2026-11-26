import os
import tempfile
import unittest

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
