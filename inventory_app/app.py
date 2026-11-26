import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .store import (
    DuplicateSKU,
    InsufficientStock,
    InventoryStore,
    ProductNotFound,
)


STATIC_DIR = Path(__file__).parent / "static"


class ProductInput(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    unit_price: float = Field(gt=0, allow_inf_nan=False)
    stock_quantity: int = Field(ge=0)


class OrderItemInput(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderInput(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    items: list[OrderItemInput] = Field(min_length=1, max_length=100)


def create_app(database_path=None):
    app = FastAPI(
        title="Stockroom",
        description="Inventory and order management powered by THESAGRA.",
        version="0.1.0",
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.on_event("startup")
    def initialize_store():
        connection_url = (
            os.environ.get("THESAGRA_URL")
            if database_path is None
            else None
        )
        if connection_url:
            tls_value = os.environ.get("THESAGRA_TLS", "false").strip().lower()
            if tls_value not in ("true", "false", "1", "0", "yes", "no"):
                raise ValueError(
                    "THESAGRA_TLS must be true, false, 1, 0, yes, or no"
                )
            app.state.store = InventoryStore(
                connection_url=connection_url,
                tls=tls_value in ("true", "1", "yes"),
                tls_ca=os.environ.get("THESAGRA_TLS_CA") or None,
            )
        else:
            resolved_database_path = database_path or os.environ.get(
                "THESAGRA_DB_PATH",
                "stockroom.db",
            )
            app.state.store = InventoryStore(resolved_database_path)

    @app.on_event("shutdown")
    def close_store():
        store = getattr(app.state, "store", None)
        if store is not None:
            store.close()

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/products")
    def list_products():
        return app.state.store.list_products()

    @app.post("/api/products", status_code=201)
    def create_product(product: ProductInput):
        try:
            return app.state.store.create_product(**product.model_dump())
        except DuplicateSKU as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/orders")
    def list_orders():
        return app.state.store.list_orders()

    @app.post("/api/orders", status_code=201)
    def create_order(order: OrderInput):
        try:
            return app.state.store.create_order(
                order.customer_name,
                [item.model_dump() for item in order.items],
            )
        except ProductNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InsufficientStock as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/summary")
    def summary():
        return app.state.store.summary()

    return app


app = create_app()
