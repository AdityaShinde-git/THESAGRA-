const currency = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });
const byId = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "Request failed");
  return payload;
}

function showMessage(id, message, isError = false) {
  const element = byId(id);
  element.textContent = message;
  element.classList.toggle("error", isError);
}

function renderProducts(products) {
  byId("catalog-count").textContent = `${products.length} ${products.length === 1 ? "item" : "items"}`;
  byId("products-body").innerHTML = products.length
    ? products.map((product) => `<tr>
        <td>${escapeHTML(product.name)}</td>
        <td>${escapeHTML(product.sku)}</td>
        <td>${currency.format(product.unit_price)}</td>
        <td>${product.stock_quantity}</td>
      </tr>`).join("")
    : '<tr><td class="empty" colspan="4">No products yet. Add your first product above.</td></tr>';

  const select = byId("order-product");
  select.innerHTML = products
    .filter((product) => product.stock_quantity > 0)
    .map((product) => `<option value="${product.id}">${escapeHTML(product.name)} · ${product.stock_quantity} available</option>`)
    .join("");
  if (!select.options.length) {
    select.innerHTML = '<option value="">Add an in-stock product first</option>';
  }
}

function renderOrders(orders) {
  byId("orders-body").innerHTML = orders.length
    ? orders.map((order) => `<tr>
        <td>#${order.id}</td>
        <td>${escapeHTML(order.customer_name)}</td>
        <td>${currency.format(order.total)}</td>
        <td><span class="badge">${escapeHTML(order.status)}</span></td>
      </tr>`).join("")
    : '<tr><td class="empty" colspan="4">No orders yet.</td></tr>';
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function refresh() {
  const [products, orders, summary] = await Promise.all([
    request("/api/products"),
    request("/api/orders"),
    request("/api/summary"),
  ]);
  renderProducts(products);
  renderOrders(orders);
  byId("product-count").textContent = summary.product_count;
  byId("units-in-stock").textContent = summary.units_in_stock;
  byId("order-count").textContent = summary.order_count;
  byId("sales-total").textContent = currency.format(summary.sales_total);
}

byId("product-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const data = Object.fromEntries(new FormData(form));
  data.unit_price = Number(data.unit_price);
  data.stock_quantity = Number(data.stock_quantity);
  button.disabled = true;
  showMessage("product-message", "");
  try {
    await request("/api/products", { method: "POST", body: JSON.stringify(data) });
    form.reset();
    showMessage("product-message", "Product added to the catalog.");
    await refresh();
  } catch (error) {
    showMessage("product-message", error.message, true);
  } finally {
    button.disabled = false;
  }
});

byId("order-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const data = Object.fromEntries(new FormData(form));
  data.items = [{ product_id: Number(data.product_id), quantity: Number(data.quantity) }];
  delete data.product_id;
  delete data.quantity;
  button.disabled = true;
  showMessage("order-message", "");
  try {
    const order = await request("/api/orders", { method: "POST", body: JSON.stringify(data) });
    form.reset();
    showMessage("order-message", `Order #${order.id} placed successfully.`);
    await refresh();
  } catch (error) {
    showMessage("order-message", error.message, true);
  } finally {
    button.disabled = false;
  }
});

refresh().catch((error) => {
  showMessage("product-message", `Could not load inventory: ${error.message}`, true);
});
