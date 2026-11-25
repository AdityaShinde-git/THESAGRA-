import csv
import json
import math
import mimetypes
import os
import tempfile
import threading
import time
import io
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .drivers.python.client import THESAGRAConnection
from .drivers.python.errors import THESAGRAError
from .query.parser import split_sql_statements

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None


def _blob_extension(name, mime_type):
    extension = os.path.splitext(name)[1]
    if extension:
        return extension
    normalized_mime = mime_type.split(";", 1)[0].strip().lower()
    return mimetypes.guess_extension(normalized_mime, strict=False) or ""


def _blob_save_dialog_options(name, mime_type):
    name = os.path.basename(name)
    extension = _blob_extension(name, mime_type)
    filetypes = [("All files", "*.*")]
    if extension:
        filetypes.insert(
            0,
            (f"{mime_type} (*{extension})", f"*{extension}"),
        )
    return {
        "initialfile": name,
        "title": "Download blob",
        "defaultextension": extension,
        "filetypes": filetypes,
    }


def _render_pdf_page(document, page_number, scale=1.5):
    if Image is None or pdfium is None:
        raise RuntimeError(
            "PDF preview requires Pillow and pypdfium2; install the "
            "THESAGRA dependencies."
        )
    page = document.get_page(page_number)
    try:
        bitmap = page.render(scale=scale)
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
    finally:
        page.close()


COLORS = {
    "bg": "#0b1220",
    "panel": "#111a2b",
    "panel2": "#172238",
    "line": "#26344d",
    "text": "#edf3ff",
    "muted": "#91a3bd",
    "accent": "#6c7cff",
    "accent2": "#45c4b0",
    "danger": "#ef6b73",
    "warning": "#e7b75b",
}


class THESAGRAGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("THESAGRA Studio")
        self.geometry("1180x760")
        self.minsize(980, 620)
        self.configure(bg=COLORS["bg"])
        self.connection = None
        self.query_history = []
        self.graph_data = {"nodes": [], "edges": []}
        self.graph_positions = {}
        self.graph_scale = 1.0
        self.graph_offset = (0.0, 0.0)
        self.graph_selected = None
        self.graph_drag = None
        self.graph_last_pointer = None
        self.graph_highlight_nodes = set()
        self._blob_original_image = None
        self._blob_preview_photo = None
        self._blob_zoom = None
        self._blob_render_after = None
        self._blob_image_origin = None
        self._blob_pdf_document = None
        self._blob_pdf_page = 0
        self._configure_styles()
        self._build_ui()

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Card.TFrame", background=COLORS["panel2"])
        style.configure(
            "TLabel",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Panel.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["bg"],
            foreground=COLORS["muted"],
        )
        style.configure(
            "Title.TLabel",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "Brand.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Segoe UI", 16, "bold"),
        )
        style.configure(
            "TEntry",
            fieldbackground=COLORS["panel2"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            padding=6,
        )
        style.configure(
            "TButton",
            background=COLORS["panel2"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            focuscolor=COLORS["accent"],
            padding=(10, 7),
        )
        style.map(
            "TButton",
            background=[
                ("active", COLORS["accent"]),
                ("pressed", "#5969df"),
            ],
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="#ffffff",
            bordercolor=COLORS["accent"],
            padding=(12, 8),
        )
        style.map("Accent.TButton", background=[("active", "#7f8cff")])
        style.configure(
            "Nav.TButton",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            bordercolor=COLORS["panel"],
            anchor="w",
            padding=(12, 10),
        )
        style.map(
            "Nav.TButton",
            background=[("active", COLORS["panel2"])],
            foreground=[("active", COLORS["text"])],
        )
        style.configure(
            "TLabelframe",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
        )
        style.configure(
            "TLabelframe.Label",
            background=COLORS["bg"],
            foreground=COLORS["muted"],
        )
        style.configure(
            "TNotebook",
            background=COLORS["bg"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            padding=(14, 8),
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", COLORS["panel2"]),
                ("active", COLORS["line"]),
            ],
            foreground=[("selected", COLORS["text"])],
        )

        style.configure(
            "Treeview",
            background=COLORS["panel"],
            fieldbackground=COLORS["panel"],
            foreground=COLORS["text"],
            borderwidth=0,
            rowheight=30,
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["panel2"],
            foreground=COLORS["text"],
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["accent"])],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=COLORS["panel2"],
            background=COLORS["accent2"],
        )

    def _build_ui(self):
        root = ttk.Panedwindow(self, orient="horizontal")
        root.pack(fill="both", expand=True)

        sidebar = ttk.Frame(root, style="Panel.TFrame", width=220)
        sidebar.pack_propagate(False)
        root.add(sidebar, weight=0)

        brand = ttk.Frame(sidebar, style="Panel.TFrame", height=72)
        brand.pack(fill="x")
        ttk.Label(
            brand,
            text="THESAGRA",
            style="Brand.TLabel",
            padding=(18, 18),
        ).pack(side="left")

        nav_items = (
            ("SQL Console", "sql"),
            ("Catalog", "catalog"),
            ("Graph", "graph"),
            ("Blobs", "blobs"),
            ("Workers", "workers"),
        )
        self.nav_buttons = {}
        for label, name in nav_items:
            button = ttk.Button(
                sidebar,
                text=f"  {label}",
                style="Nav.TButton",
                command=lambda page=name: self._show_page(page),
            )
            button.pack(fill="x", padx=8, pady=2)
            self.nav_buttons[name] = button

        sidebar_bottom = ttk.Frame(sidebar, style="Panel.TFrame")
        sidebar_bottom.pack(side="bottom", fill="x", padx=10, pady=12)
        ttk.Label(
            sidebar_bottom,
            text="CONNECTION",
            style="Muted.TLabel",
            background=COLORS["panel"],
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")
        self.connection_label = ttk.Label(
            sidebar_bottom,
            text="Disconnected",
            style="Panel.TLabel",
        )
        self.connection_label.pack(anchor="w", pady=(4, 8))

        main = ttk.Frame(root)
        main.pack(fill="both", expand=True)
        root.add(main, weight=1)

        toolbar = ttk.Frame(main, height=72)
        toolbar.pack(fill="x", padx=14, pady=(12, 8))
        toolbar.pack_propagate(False)

        self.host = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="5439")
        self.username = tk.StringVar(value="admin")
        self.password = tk.StringVar(value="change-me")
        self.database = tk.StringVar(value="")
        self.tls_enabled = tk.BooleanVar(value=False)

        fields = (
            ("Host", self.host, 14),
            ("Port", self.port, 6),
            ("User", self.username, 11),
            ("Password", self.password, 11),
        )
        for label, variable, width in fields:
            ttk.Label(toolbar, text=label).pack(side="left", padx=(0, 4))
            entry = ttk.Entry(
                toolbar,
                textvariable=variable,
                width=width,
                show="*" if label == "Password" else "",
            )
            entry.pack(side="left", padx=(0, 8))

        ttk.Label(toolbar, text="Database").pack(
            side="left",
            padx=(0, 4),
        )
        self.database_picker = ttk.Combobox(
            toolbar,
            textvariable=self.database,
            width=14,
            state="readonly",
        )
        self.database_picker.pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh_database_list,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            toolbar,
            text="Create DB",
            command=self.create_database_dialog,
        ).pack(side="left", padx=(0, 4))
        ttk.Checkbutton(
            toolbar,
            text="TLS",
            variable=self.tls_enabled,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            toolbar,
            text="Connect",
            style="Accent.TButton",
            command=self.connect,
        ).pack(side="left", padx=4)
        ttk.Button(
            toolbar,
            text="Disconnect",
            command=self.disconnect,
        ).pack(side="left")

        self.status = tk.StringVar(value="Ready")
        statusbar = ttk.Frame(main)
        statusbar.pack(side="bottom", fill="x")
        ttk.Separator(main, orient="horizontal").pack(side="bottom", fill="x")
        ttk.Label(
            statusbar,
            textvariable=self.status,
            style="Muted.TLabel",
            padding=(14, 7),
        ).pack(side="left")
        self.clock = tk.StringVar()
        ttk.Label(
            statusbar,
            textvariable=self.clock,
            style="Muted.TLabel",
            padding=(14, 7),
        ).pack(side="right")
        self._tick_clock()

        content = ttk.Frame(main)
        content.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self.pages = {}
        for name in ("sql", "catalog", "graph", "blobs", "workers"):
            frame = ttk.Frame(content)
            frame.pack(fill="both", expand=True)
            frame.pack_forget()
            self.pages[name] = frame

        self._build_sql_page()
        self._build_catalog_page()
        self._build_graph_page()
        self._build_blobs_page()
        self._build_workers_page()
        self._show_page("sql")

    def _tick_clock(self):
        self.clock.set(time.strftime("%H:%M:%S"))
        self.after(1000, self._tick_clock)

    def _show_page(self, name):
        for page_name, frame in self.pages.items():
            if page_name == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        if name == "catalog":
            self.refresh_catalog()
        elif name == "blobs":
            self.refresh_blobs()
        elif name == "graph":
            self.refresh_graph()
        elif name == "workers":
            self.refresh_workers()

    def _require_connection(self):
        if self.connection is None:
            messagebox.showwarning(
                "Not connected",
                "Connect to THESAGRA before continuing.",
            )
            return False
        if self.connection.database is None:
            messagebox.showwarning(
                "Choose a database",
                "Select a database, or create one before using the workbench.",
            )
            return False
        return True

    def connect(self):
        try:
            if self.connection is not None:
                self.disconnect()
            port = int(self.port.get())
            ca_file = os.environ.get("THESAGRA_TLS_CA")
            self.connection = THESAGRAConnection(
                host=self.host.get(),
                port=port,
                username=self.username.get(),
                password=self.password.get(),
                database=self.database.get().strip() or None,
                timeout=10,
                tls=self.tls_enabled.get(),
                tls_ca=ca_file,
            ).connect()
            self.connection_label.configure(text="Connected")
            if self.connection.multi_database:
                self.refresh_database_list()
                if self.connection.database is None:
                    self.connection_label.configure(
                        text="Connected\nChoose a database"
                    )
                    self.status.set(
                        "Connected; choose or create a database"
                    )
                    return
                self.database.set(self.connection.database)
            elif self.connection.database is not None:
                self.database.set(self.connection.database)
                self.database_picker.configure(
                    values=(self.connection.database,)
                )
            database = self.database.get().strip()
            target = f"{self.host.get()}:{port}"
            if database:
                target += f"/{database}"
            self.connection_label.configure(text=f"Connected\n{target}")
            self.status.set("Connected")
            self.refresh_catalog()
            self.refresh_graph()
            self.refresh_blobs()
            self.refresh_workers()
        except (THESAGRAError, OSError, ValueError) as exc:
            messagebox.showerror("Connection failed", str(exc))
            self.status.set("Connection failed")

    def refresh_database_list(self):
        if self.connection is None:
            self.connect()
            return
        if not self.connection.multi_database:
            if self.connection.database is not None:
                self.database_picker.configure(
                    values=(self.connection.database,)
                )
            return
        try:
            databases = self.connection.list_databases()["databases"]
            self.database_picker.configure(values=databases)
            if (
                self.database.get()
                and self.database.get() not in databases
            ):
                self.database.set("")
            self.status.set(
                f"{len(databases)} accessible database(s)"
            )
        except THESAGRAError as exc:
            messagebox.showerror("Database list failed", str(exc))

    def create_database_dialog(self):
        try:
            if self.connection is None:
                port = int(self.port.get())
                ca_file = os.environ.get("THESAGRA_TLS_CA")
                self.connection = THESAGRAConnection(
                    host=self.host.get(),
                    port=port,
                    username=self.username.get(),
                    password=self.password.get(),
                    timeout=10,
                    tls=self.tls_enabled.get(),
                    tls_ca=ca_file,
                ).connect()
                if self.connection.multi_database:
                    self.refresh_database_list()
            if not self.connection.multi_database:
                messagebox.showinfo(
                    "Named databases unavailable",
                    "Start the server with --data-dir to create named "
                    "project databases.",
                )
                return
            if not self.connection.is_admin:
                messagebox.showerror(
                    "Administrator required",
                    "Connect using the system administrator account to "
                    "create a database.",
                )
                return
            name = simpledialog.askstring(
                "Create project database",
                "New database name:",
                parent=self,
            )
            if not name:
                return
            self.connection.create_database(name.strip())
            self.database.set(name.strip())
            self.refresh_database_list()
            self.connect()
        except (THESAGRAError, OSError, ValueError) as exc:
            messagebox.showerror("Database creation failed", str(exc))

    def disconnect(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.connection_label.configure(text="Disconnected")
        self.status.set("Ready")

    def _build_sql_page(self):
        page = self.pages["sql"]
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="SQL Workbench", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Button(
            toolbar,
            text="Execute",
            style="Accent.TButton",
            command=self.execute_sql,
        ).pack(side="right")
        ttk.Button(
            toolbar,
            text="Export CSV",
            command=self.export_csv,
        ).pack(side="right", padx=6)
        ttk.Button(
            toolbar,
            text="Format",
            command=self.format_sql,
        ).pack(side="right")

        self.transaction_label = tk.StringVar(value="Transaction: idle")
        ttk.Label(
            toolbar,
            textvariable=self.transaction_label,
            style="Muted.TLabel",
        ).pack(side="right", padx=12)

        editor = tk.Text(
            page,
            height=11,
            wrap="none",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            borderwidth=0,
            padx=12,
            pady=10,
            font=("Cascadia Code", 11),
        )
        editor.pack(fill="x")
        editor.insert(
            "1.0",
            "-- THESAGRA SQL\n"
            "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);\n"
            "INSERT INTO people VALUES (1, 'Ada');\n"
            "SELECT * FROM people;",
        )
        self.sql_editor = editor
        self.bind("<Control-Return>", lambda event: self.execute_sql())
        self.bind("<F5>", lambda event: self.execute_sql())

        transaction = ttk.Frame(page)
        transaction.pack(fill="x", pady=8)
        ttk.Button(
            transaction,
            text="BEGIN",
            command=lambda: self.execute_control("begin"),
        ).pack(side="left")
        ttk.Button(
            transaction,
            text="COMMIT",
            command=lambda: self.execute_control("commit"),
        ).pack(side="left", padx=4)
        ttk.Button(
            transaction,
            text="ROLLBACK",
            command=lambda: self.execute_control("rollback"),
        ).pack(side="left")

        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)
        result_page = ttk.Frame(notebook)
        history_page = ttk.Frame(notebook)
        notebook.add(result_page, text="Results")
        notebook.add(history_page, text="History")

        self.result_tree = ttk.Treeview(result_page, show="headings")
        self.result_tree.pack(fill="both", expand=True)
        result_scroll_y = ttk.Scrollbar(
            result_page,
            orient="vertical",
            command=self.result_tree.yview,
        )
        result_scroll_y.pack(side="right", fill="y")
        self.result_tree.configure(yscrollcommand=result_scroll_y.set)

        result_scroll_x = ttk.Scrollbar(
            result_page,
            orient="horizontal",
            command=self.result_tree.xview,
        )
        result_scroll_x.pack(side="bottom", fill="x")
        self.result_tree.configure(xscrollcommand=result_scroll_x.set)

        self.history_tree = ttk.Treeview(
            history_page,
            columns=("time", "sql"),
            show="headings",
        )
        self.history_tree.heading("time", text="Time")
        self.history_tree.heading("sql", text="Statement")
        self.history_tree.column("time", width=140)
        self.history_tree.column("sql", width=800)
        self.history_tree.pack(fill="both", expand=True)

    def format_sql(self):
        sql = self.sql_editor.get("1.0", "end").strip()
        sql = "\n".join(
            " ".join(line.strip().split())
            for line in sql.splitlines()
            if line.strip()
        )
        self.sql_editor.delete("1.0", "end")
        self.sql_editor.insert("1.0", sql)

    def execute_control(self, operation):
        if not self._require_connection():
            return
        try:
            if operation == "begin":
                cursor = self.connection.begin()
            elif operation == "commit":
                cursor = self.connection.commit()
            else:
                cursor = self.connection.rollback()
            active = operation if operation != "rollback" else "idle"
            if operation == "commit":
                active = "idle"
            self.transaction_label.set(f"Transaction: {active}")
            self.status.set(f"{operation.upper()} completed")
        except Exception as exc:
            messagebox.showerror("Transaction failed", str(exc))

    def execute_sql(self):
        if not self._require_connection():
            return
        sql = self.sql_editor.get("1.0", "end").strip()
        if not sql:
            return
        threading.Thread(
            target=self._execute_sql,
            args=(sql,),
            daemon=True,
        ).start()

    def _execute_sql(self, sql):
        try:
            statements = split_sql_statements(sql)
            cursors = []
            for statement in statements:
                cursors.append(self.connection.execute(statement))
                self.after(
                    0,
                    lambda statement=statement: self._add_history(statement),
                )
            cursor = cursors[-1] if cursors else None
            self.after(0, self._sync_database_after_query)
            self.after(0, lambda: self._show_result(cursor))
        except Exception as exc:
            self.after(
                0,
                lambda error=str(exc): messagebox.showerror(
                    "Query failed",
                    error,
                ),
            )

    def _sync_database_after_query(self):
        if self.connection is None:
            return
        if self.connection.multi_database:
            self.database.set(self.connection.database or "")
            self.refresh_database_list()
        database = self.connection.database
        target = f"{self.host.get()}:{self.port.get()}"
        if database:
            target += f"/{database}"
        self.connection_label.configure(text=f"Connected\n{target}")

    def _add_history(self, sql):
        stamp = time.strftime("%H:%M:%S")
        self.history_tree.insert("", 0, values=(stamp, sql))

    def _show_result(self, cursor):
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        if cursor is None:
            self.status.set("No result")
            return
        columns = cursor.columns or (
            [f"column_{index + 1}" for index in range(
                len(cursor.rows[0]) if cursor.rows else 0
            )]
        )
        self.result_tree["columns"] = columns
        for column in columns:
            self.result_tree.heading(column, text=column)
            self.result_tree.column(column, width=150, stretch=True)
        for row in cursor.rows:
            self.result_tree.insert("", "end", values=row)
        self.status.set(f"{cursor.rowcount} row(s) returned")

    def export_csv(self):
        if not self.result_tree["columns"]:
            messagebox.showinfo("Export", "Execute a result before exporting.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        columns = list(self.result_tree["columns"])
        with open(path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(columns)
            for item in self.result_tree.get_children():
                writer.writerow(self.result_tree.item(item, "values"))
        self.status.set(f"Exported {path}")

    def _build_catalog_page(self):
        page = self.pages["catalog"]
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Database Catalog", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh_catalog,
        ).pack(side="right")
        ttk.Button(
            toolbar,
            text="Open in SQL",
            command=self._catalog_open_in_sql,
        ).pack(side="right", padx=6)
        ttk.Button(
            toolbar,
            text="View Data",
            style="Accent.TButton",
            command=self._load_catalog_data,
        ).pack(side="right", padx=6)

        split = ttk.Panedwindow(page, orient="horizontal")
        split.pack(fill="both", expand=True)
        explorer = ttk.Frame(split, style="Panel.TFrame", width=250)
        explorer.pack_propagate(False)
        split.add(explorer, weight=1)
        ttk.Label(
            explorer,
            text="DATABASE OBJECTS",
            style="Panel.TLabel",
            padding=(10, 9),
        ).pack(anchor="w", fill="x")
        self.catalog_tree = ttk.Treeview(
            explorer,
            columns=("kind",),
            show="tree",
        )
        catalog_scroll = ttk.Scrollbar(
            explorer,
            orient="vertical",
            command=self.catalog_tree.yview,
        )
        self.catalog_tree.configure(yscrollcommand=catalog_scroll.set)
        catalog_scroll.pack(side="right", fill="y")
        self.catalog_tree.pack(fill="both", expand=True)
        self.catalog_tree.bind("<<TreeviewSelect>>", self._select_catalog_object)
        self.catalog_tree.bind("<Double-1>", self._catalog_double_click)

        detail = ttk.Frame(split)
        split.add(detail, weight=4)
        self.catalog_detail_title = tk.StringVar(value="Select a table")
        ttk.Label(
            detail,
            textvariable=self.catalog_detail_title,
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        notebook = ttk.Notebook(detail)
        notebook.pack(fill="both", expand=True)
        columns_page = ttk.Frame(notebook)
        data_page = ttk.Frame(notebook)
        notebook.add(columns_page, text="Columns")
        notebook.add(data_page, text="Data Preview")
        self.catalog_notebook = notebook
        self.catalog_columns_tree = ttk.Treeview(
            columns_page,
            columns=("name", "type", "nullable", "key", "default"),
            show="headings",
        )
        for key, title, width in (
            ("name", "Column", 200),
            ("type", "Type", 150),
            ("nullable", "Nullable", 100),
            ("key", "Key", 110),
            ("default", "Default", 220),
        ):
            self.catalog_columns_tree.heading(key, text=title)
            self.catalog_columns_tree.column(key, width=width)
        self.catalog_columns_tree.pack(fill="both", expand=True)
        self.catalog_data_tree = ttk.Treeview(data_page, show="headings")
        data_scroll_y = ttk.Scrollbar(
            data_page,
            orient="vertical",
            command=self.catalog_data_tree.yview,
        )
        data_scroll_x = ttk.Scrollbar(
            data_page,
            orient="horizontal",
            command=self.catalog_data_tree.xview,
        )
        self.catalog_data_tree.configure(
            yscrollcommand=data_scroll_y.set,
            xscrollcommand=data_scroll_x.set,
        )
        data_scroll_y.pack(side="right", fill="y")
        data_scroll_x.pack(side="bottom", fill="x")
        self.catalog_data_tree.pack(fill="both", expand=True)
        self.catalog_tables_by_id = {}
        self.catalog_selected_table = None

    def refresh_catalog(self):
        if not self._require_connection_quiet():
            return
        try:
            catalog = self.connection.list_catalog()
            for item in self.catalog_tree.get_children():
                self.catalog_tree.delete(item)
            self.catalog_tables_by_id = {}
            root_id = "catalog:database"
            self.catalog_tree.insert(
                "",
                "end",
                iid=root_id,
                text=(
                    f"Database  {self.database.get().strip() or 'unselected'}"
                    f"  ·  {self.host.get()}:{self.port.get()}"
                ),
                open=True,
            )
            tables_id = "catalog:tables"
            self.catalog_tree.insert(
                root_id,
                "end",
                iid=tables_id,
                text=f"Tables ({len(catalog['tables'])})",
                open=True,
            )
            for table in catalog["tables"]:
                table_id = f"table:{table['name']}"
                self.catalog_tables_by_id[table_id] = table
                self.catalog_tree.insert(
                    tables_id,
                    "end",
                    iid=table_id,
                    text=f"{table['name']}  ({len(table['columns'])})",
                )
                for index, column in enumerate(table["columns"]):
                    column_type = column["type"]
                    if column.get("max_length") is not None:
                        column_type = (
                            f"{column_type}({column['max_length']})"
                        )
                    self.catalog_tree.insert(
                        table_id,
                        "end",
                        iid=f"{table_id}:column:{index}",
                        text=f"{column['name']}  ·  {column_type}",
                    )
            if not catalog["tables"]:
                self.catalog_tree.insert(
                    tables_id,
                    "end",
                    text="No user tables",
                )
            self.status.set(f"Catalog: {len(catalog['tables'])} table(s)")
        except Exception as exc:
            messagebox.showerror("Catalog refresh failed", str(exc))

    def _selected_catalog_table(self):
        selection = self.catalog_tree.selection()
        if not selection:
            return None
        item_id = selection[0]
        if item_id in self.catalog_tables_by_id:
            return self.catalog_tables_by_id[item_id]
        parent_id = self.catalog_tree.parent(item_id)
        return self.catalog_tables_by_id.get(parent_id)

    def _select_catalog_object(self, event=None):
        table = self._selected_catalog_table()
        if table is None:
            self.catalog_selected_table = None
            self.catalog_detail_title.set("Select a table")
            return
        self.catalog_selected_table = table
        self.catalog_detail_title.set(
            f"{table['name']}  ·  {len(table['columns'])} columns"
        )
        for item in self.catalog_columns_tree.get_children():
            self.catalog_columns_tree.delete(item)
        for column in table["columns"]:
            key = "PRIMARY KEY" if column["primary_key"] else (
                "UNIQUE" if column.get("unique") else ""
            )
            default = column.get("default")
            column_type = column["type"]
            if column.get("max_length") is not None:
                column_type = f"{column_type}({column['max_length']})"
            self.catalog_columns_tree.insert(
                "",
                "end",
                values=(
                    column["name"],
                    column_type,
                    "Yes" if column["nullable"] else "No",
                    key,
                    "" if default is None else default,
                ),
            )
        for item in self.catalog_data_tree.get_children():
            self.catalog_data_tree.delete(item)
        self.catalog_data_tree["columns"] = ()
        self.catalog_notebook.select(0)

    def _catalog_double_click(self, event=None):
        if self._selected_catalog_table() is not None:
            self._load_catalog_data()

    def _load_catalog_data(self):
        if not self._require_connection():
            return
        table = self.catalog_selected_table or self._selected_catalog_table()
        if table is None:
            messagebox.showinfo("Select a table", "Choose a table first.")
            return
        try:
            cursor = self.connection.execute(
                f"SELECT * FROM {table['name']} LIMIT 100;"
            )
            columns = cursor.columns or [
                f"column_{index + 1}"
                for index in range(
                    len(cursor.rows[0]) if cursor.rows else 0
                )
            ]
            self.catalog_data_tree.delete(
                *self.catalog_data_tree.get_children()
            )
            self.catalog_data_tree["columns"] = columns
            for column in columns:
                self.catalog_data_tree.heading(column, text=column)
                self.catalog_data_tree.column(
                    column,
                    width=160,
                    stretch=True,
                )
            for row in cursor.rows:
                self.catalog_data_tree.insert("", "end", values=row)
            self.catalog_notebook.select(1)
            self.status.set(
                f"{table['name']}: showing {len(cursor.rows)} row(s), "
                "limited to 100"
            )
        except Exception as exc:
            messagebox.showerror("Table preview failed", str(exc))

    def _catalog_open_in_sql(self):
        table = self.catalog_selected_table or self._selected_catalog_table()
        if table is None:
            messagebox.showinfo("Select a table", "Choose a table first.")
            return
        self.sql_editor.delete("1.0", "end")
        self.sql_editor.insert(
            "1.0",
            f"SELECT * FROM {table['name']} LIMIT 100;",
        )
        self._show_page("sql")
        if self._require_connection_quiet():
            self.execute_sql()

    def _require_connection_quiet(self):
        return (
            self.connection is not None
            and self.connection.database is not None
        )

    def _build_graph_page(self):
        page = self.pages["graph"]
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Graph Explorer", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Button(
            toolbar,
            text="Fit Graph",
            command=self.fit_graph,
        ).pack(side="right", padx=(6, 0))
        ttk.Button(
            toolbar,
            text="Refresh Graph",
            command=self.refresh_graph,
        ).pack(side="right")

        controls = ttk.Notebook(page)
        controls.pack(fill="x", pady=(0, 8))
        cypher_page = ttk.Frame(controls)
        actions_page = ttk.Frame(controls)
        controls.add(cypher_page, text="Cypher")
        controls.add(actions_page, text="Quick Actions")

        cypher_toolbar = ttk.Frame(cypher_page)
        cypher_toolbar.pack(fill="x")
        ttk.Label(
            cypher_toolbar,
            text="Supported MATCH pattern · Ctrl+Enter to run",
            style="Muted.TLabel",
        ).pack(side="left", padx=8, pady=5)
        ttk.Button(
            cypher_toolbar,
            text="Run Cypher",
            style="Accent.TButton",
            command=self.execute_cypher,
        ).pack(side="right", padx=8, pady=4)
        self.cypher_editor = tk.Text(
            cypher_page,
            height=3,
            wrap="none",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            borderwidth=0,
            padx=10,
            pady=8,
            font=("Cascadia Code", 10),
        )
        self.cypher_editor.pack(fill="x", padx=8, pady=(0, 6))
        self.cypher_editor.insert(
            "1.0",
            "MATCH (p:Person)-[:KNOWS]->(q:Person);",
        )
        self.cypher_editor.bind(
            "<Control-Return>",
            self._execute_cypher_shortcut,
        )
        results_frame = ttk.Frame(cypher_page)
        results_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.cypher_results = ttk.Treeview(
            results_frame,
            height=3,
            show="headings",
        )
        results_scroll_y = ttk.Scrollbar(
            results_frame,
            orient="vertical",
            command=self.cypher_results.yview,
        )
        results_scroll_x = ttk.Scrollbar(
            results_frame,
            orient="horizontal",
            command=self.cypher_results.xview,
        )
        self.cypher_results.configure(
            yscrollcommand=results_scroll_y.set,
            xscrollcommand=results_scroll_x.set,
        )
        results_scroll_y.pack(side="right", fill="y")
        results_scroll_x.pack(side="bottom", fill="x")
        self.cypher_results.pack(side="left", fill="x", expand=True)

        form = ttk.Frame(actions_page)
        form.pack(fill="x", padx=8, pady=(8, 4))
        self.node_id = tk.StringVar(value="")
        self.node_label = tk.StringVar(value="Person")
        self.node_properties = tk.StringVar(value='{"name":"Ada"}')
        for label, variable, width in (
            ("ID (auto)", self.node_id, 9),
            ("Label", self.node_label, 14),
            ("Properties JSON", self.node_properties, 42),
        ):
            ttk.Label(form, text=label).pack(side="left", padx=(0, 4))
            ttk.Entry(form, textvariable=variable, width=width).pack(
                side="left",
                padx=(0, 10),
            )
        ttk.Button(
            form,
            text="Create Node",
            command=self.create_node,
        ).pack(side="left")

        self.edge_source = tk.StringVar(value="1")
        self.edge_target = tk.StringVar(value="2")
        self.edge_type = tk.StringVar(value="KNOWS")
        self.edge_properties = tk.StringVar(value="{}")
        edge_form = ttk.Frame(actions_page)
        edge_form.pack(fill="x", padx=8, pady=4)
        for label, variable, width in (
            ("From ID", self.edge_source, 8),
            ("To ID", self.edge_target, 8),
            ("Relationship", self.edge_type, 14),
            ("Properties JSON", self.edge_properties, 32),
        ):
            ttk.Label(edge_form, text=label).pack(side="left", padx=(0, 4))
            ttk.Entry(edge_form, textvariable=variable, width=width).pack(
                side="left",
                padx=(0, 8),
            )
        ttk.Button(
            edge_form,
            text="Create Relationship",
            command=self.create_edge,
        ).pack(side="left")

        traversal = ttk.Frame(actions_page)
        traversal.pack(fill="x", padx=8, pady=(4, 8))
        self.traversal_start = tk.StringVar(value="1")
        self.traversal_depth = tk.StringVar(value="2")
        self.traversal_limit = tk.StringVar(value="100")
        for label, variable, width in (
            ("Start ID", self.traversal_start, 8),
            ("Depth", self.traversal_depth, 6),
            ("Max Nodes", self.traversal_limit, 8),
        ):
            ttk.Label(traversal, text=label).pack(side="left", padx=(0, 4))
            ttk.Entry(traversal, textvariable=variable, width=width).pack(
                side="left",
                padx=(0, 8),
            )
        ttk.Button(
            traversal,
            text="Traverse",
            style="Accent.TButton",
            command=self.traverse_graph,
        ).pack(side="left")

        graph_split = ttk.Panedwindow(page, orient="horizontal")
        graph_split.pack(fill="both", expand=True)
        canvas_frame = ttk.Frame(graph_split, style="Panel.TFrame")
        graph_split.add(canvas_frame, weight=4)
        self.graph_canvas = tk.Canvas(
            canvas_frame,
            bg=COLORS["panel"],
            highlightthickness=0,
            cursor="hand2",
        )
        self.graph_canvas.pack(fill="both", expand=True)
        inspector = ttk.Frame(graph_split, style="Panel.TFrame", width=280)
        inspector.pack_propagate(False)
        graph_split.add(inspector, weight=1)
        ttk.Label(
            inspector,
            text="SELECTION DETAILS",
            style="Panel.TLabel",
            padding=(10, 9),
        ).pack(anchor="w", fill="x")
        self.graph_inspector = ttk.Treeview(
            inspector,
            columns=("value",),
            show="tree headings",
        )
        self.graph_inspector.heading("#0", text="Property")
        self.graph_inspector.heading("value", text="Value")
        self.graph_inspector.column("#0", width=140)
        self.graph_inspector.column("value", width=180)
        self.graph_inspector.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.graph_canvas.bind("<Configure>", self._on_graph_canvas_configure)
        self.graph_canvas.bind("<ButtonPress-1>", self._on_graph_mouse_down)
        self.graph_canvas.bind("<B1-Motion>", self._on_graph_mouse_drag)
        self.graph_canvas.bind("<ButtonRelease-1>", self._on_graph_mouse_up)
        self.graph_canvas.bind("<MouseWheel>", self._on_graph_mouse_wheel)

    def create_node(self):
        if not self._require_connection():
            return
        try:
            properties = json.loads(self.node_properties.get())
            node_id = self.node_id.get().strip()
            node = self.connection.create_node(
                self.node_label.get(),
                properties,
                int(node_id) if node_id else None,
            )
            self.status.set(f"Created node {node['node_id']}")
            self.refresh_catalog()
            self.refresh_graph()
            self._select_graph_item("node", node["node_id"])
        except Exception as exc:
            messagebox.showerror("Create node failed", str(exc))

    def create_edge(self):
        if not self._require_connection():
            return
        try:
            properties = json.loads(self.edge_properties.get())
            edge = self.connection.create_edge(
                int(self.edge_source.get()),
                int(self.edge_target.get()),
                self.edge_type.get(),
                properties,
            )
            self.status.set(f"Created edge {edge['edge_id']}")
            self.refresh_catalog()
            self.refresh_graph()
            self._select_graph_item("edge", edge["edge_id"])
        except Exception as exc:
            messagebox.showerror("Create edge failed", str(exc))

    def execute_cypher(self):
        if not self._require_connection():
            return
        query = self.cypher_editor.get("1.0", "end").strip()
        if not query:
            return
        try:
            cursor = self.connection.execute(query)
            for item in self.cypher_results.get_children():
                self.cypher_results.delete(item)
            columns = cursor.columns or [
                f"column_{index + 1}"
                for index in range(
                    len(cursor.rows[0]) if cursor.rows else 0
                )
            ]
            self.cypher_results["columns"] = columns
            for column in columns:
                self.cypher_results.heading(column, text=column)
                self.cypher_results.column(column, width=140, stretch=True)
            for row in cursor.rows:
                self.cypher_results.insert("", "end", values=row)
            self.status.set(f"Cypher returned {cursor.rowcount} record(s)")
        except Exception as exc:
            messagebox.showerror("Cypher query failed", str(exc))

    def _execute_cypher_shortcut(self, event=None):
        self.execute_cypher()
        return "break"

    def traverse_graph(self):
        if not self._require_connection():
            return
        try:
            paths = self.connection.traverse(
                int(self.traversal_start.get()),
                int(self.traversal_depth.get()),
                max_nodes=int(self.traversal_limit.get()),
            )
            self.graph_highlight_nodes = {
                node["node_id"] for path in paths for node in path
            }
            self._draw_graph()
            self.status.set(f"{len(paths)} path(s) found")
        except Exception as exc:
            messagebox.showerror("Traversal failed", str(exc))

    def _draw_graph(self):
        self.graph_canvas.delete("all")
        self.graph_canvas.create_text(
            12,
            10,
            anchor="nw",
            text="Drag nodes to arrange · drag background to pan · scroll to zoom",
            fill=COLORS["muted"],
        )
        nodes = self.graph_data["nodes"]
        edges = self.graph_data["edges"]
        if not nodes:
            self.graph_canvas.create_text(
                max(self.graph_canvas.winfo_width(), 360) // 2,
                max(self.graph_canvas.winfo_height(), 300) // 2,
                text="No graph nodes yet",
                fill=COLORS["muted"],
                font=("Segoe UI", 11),
            )
            return
        self._ensure_graph_positions()
        positions = {}
        for node in nodes:
            world_x, world_y = self.graph_positions[node["node_id"]]
            cx = world_x * self.graph_scale + self.graph_offset[0]
            cy = world_y * self.graph_scale + self.graph_offset[1]
            positions[node["node_id"]] = (cx, cy)

        for edge in edges:
            start = positions.get(edge["source_node_id"])
            end = positions.get(edge["target_node_id"])
            if start and end:
                self.graph_canvas.create_line(
                    start[0],
                    start[1],
                    end[0],
                    end[1],
                    fill=COLORS["line"],
                    width=2,
                    arrow="last",
                    tags=("edge", f"edge:{edge['edge_id']}"),
                )
                self.graph_canvas.create_text(
                    (start[0] + end[0]) / 2,
                    (start[1] + end[1]) / 2,
                    text=edge["relationship_type"],
                    fill=COLORS["muted"],
                    font=("Segoe UI", 8),
                    tags=("edge", f"edge:{edge['edge_id']}"),
                )
        for node in nodes:
            cx, cy = positions[node["node_id"]]
            radius = max(15, 24 * self.graph_scale)
            selected = self.graph_selected == ("node", node["node_id"])
            fill = (
                COLORS["accent2"]
                if node["node_id"] in self.graph_highlight_nodes
                else COLORS["accent"]
            )
            self.graph_canvas.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                fill=fill,
                outline=COLORS["warning"] if selected else COLORS["text"],
                width=3 if selected else 2,
                tags=("node", f"node:{node['node_id']}"),
            )
            self.graph_canvas.create_text(
                cx,
                cy,
                text=str(node["node_id"]),
                fill="#ffffff",
                font=("Segoe UI", 9, "bold"),
                tags=("node", f"node:{node['node_id']}"),
            )
            self.graph_canvas.create_text(
                cx,
                cy + radius + 10,
                text=node["label"],
                fill=COLORS["text"],
                font=("Segoe UI", 9),
                tags=("node", f"node:{node['node_id']}"),
            )

    def _ensure_graph_positions(self):
        missing = [
            node for node in self.graph_data["nodes"]
            if node["node_id"] not in self.graph_positions
        ]
        if not missing:
            return
        count = len(self.graph_positions) + len(missing)
        radius = max(150, count * 30)
        for index, node in enumerate(missing):
            angle = (index * 2.399963) % (2 * math.pi)
            self.graph_positions[node["node_id"]] = (
                radius * math.cos(angle),
                radius * math.sin(angle),
            )
        if len(missing) == len(self.graph_data["nodes"]):
            self.fit_graph()

    def fit_graph(self):
        if not self.graph_data["nodes"]:
            self._draw_graph()
            return
        self._ensure_graph_positions()
        width = max(self.graph_canvas.winfo_width(), 320)
        height = max(self.graph_canvas.winfo_height(), 280)
        points = [
            self.graph_positions[node["node_id"]]
            for node in self.graph_data["nodes"]
        ]
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        span_x = max(max_x - min_x, 1)
        span_y = max(max_y - min_y, 1)
        self.graph_scale = max(
            0.25,
            min((width - 100) / span_x, (height - 100) / span_y, 1.8),
        )
        self.graph_offset = (
            (width - (min_x + max_x) * self.graph_scale) / 2,
            (height - (min_y + max_y) * self.graph_scale) / 2,
        )
        self._draw_graph()

    def _on_graph_canvas_configure(self, event=None):
        if self.graph_data["nodes"] and not self.graph_positions:
            self._ensure_graph_positions()
        if self.graph_data["nodes"] and self.graph_offset == (0.0, 0.0):
            self.fit_graph()
        else:
            self._draw_graph()

    def _graph_item_at_pointer(self):
        current = self.graph_canvas.find_withtag("current")
        if not current:
            return None
        for tag in self.graph_canvas.gettags(current[-1]):
            if tag.startswith("node:"):
                return "node", int(tag.split(":", 1)[1])
            if tag.startswith("edge:"):
                return "edge", int(tag.split(":", 1)[1])
        return None

    def _on_graph_mouse_down(self, event):
        item = self._graph_item_at_pointer()
        self.graph_drag = item if item and item[0] == "node" else "pan"
        self.graph_last_pointer = (event.x, event.y)
        if item:
            self._select_graph_item(*item)
        return "break"

    def _on_graph_mouse_drag(self, event):
        if self.graph_drag is None or self.graph_last_pointer is None:
            return
        dx = event.x - self.graph_last_pointer[0]
        dy = event.y - self.graph_last_pointer[1]
        self.graph_last_pointer = (event.x, event.y)
        if self.graph_drag == "pan":
            self.graph_offset = (
                self.graph_offset[0] + dx,
                self.graph_offset[1] + dy,
            )
        else:
            _, node_id = self.graph_drag
            world_x, world_y = self.graph_positions[node_id]
            self.graph_positions[node_id] = (
                world_x + dx / self.graph_scale,
                world_y + dy / self.graph_scale,
            )
        self._draw_graph()
        return "break"

    def _on_graph_mouse_up(self, event=None):
        self.graph_drag = None
        self.graph_last_pointer = None

    def _on_graph_mouse_wheel(self, event):
        factor = 1.12 if event.delta > 0 else 0.89
        old_scale = self.graph_scale
        self.graph_scale = min(max(old_scale * factor, 0.2), 3.0)
        self.graph_offset = (
            event.x - (event.x - self.graph_offset[0]) *
            self.graph_scale / old_scale,
            event.y - (event.y - self.graph_offset[1]) *
            self.graph_scale / old_scale,
        )
        self._draw_graph()
        return "break"

    def _select_graph_item(self, item_type, item_id):
        self.graph_selected = (item_type, item_id)
        for child in self.graph_inspector.get_children():
            self.graph_inspector.delete(child)
        if item_type == "node":
            item = next(
                (node for node in self.graph_data["nodes"]
                 if node["node_id"] == item_id),
                None,
            )
            if item is None:
                return
            root_id = "selected-node"
            title = f"Node {item_id}"
            heading_value = item["label"]
            details = [("Label", item["label"])]
            properties = item["properties"]
        else:
            item = next(
                (edge for edge in self.graph_data["edges"]
                 if edge["edge_id"] == item_id),
                None,
            )
            if item is None:
                return
            root_id = "selected-edge"
            title = f"Relationship {item_id}"
            heading_value = item["relationship_type"]
            details = [
                ("Type", item["relationship_type"]),
                ("Source node", item["source_node_id"]),
                ("Target node", item["target_node_id"]),
            ]
            properties = item["properties"]
        self.graph_inspector.insert(
            "",
            "end",
            iid=root_id,
            text=title,
            values=(heading_value,),
            open=True,
        )
        for label, value in details:
            self.graph_inspector.insert(
                root_id,
                "end",
                text=label,
                values=(value,),
            )
        properties_id = f"{root_id}:properties"
        self.graph_inspector.insert(
            root_id,
            "end",
            iid=properties_id,
            text=f"Properties ({len(properties)})",
            values=("",),
            open=True,
        )
        for index, (key, value) in enumerate(sorted(properties.items())):
            self.graph_inspector.insert(
                properties_id,
                "end",
                iid=f"{properties_id}:{index}",
                text=str(key),
                values=(json.dumps(value, ensure_ascii=False),),
            )
        self.status.set(f"Selected {title} · {heading_value}")
        self._draw_graph()

    def refresh_graph(self):
        if not self._require_connection_quiet():
            return
        try:
            self.graph_data = self.connection.list_graph()
            existing_ids = {
                node["node_id"] for node in self.graph_data["nodes"]
            }
            self.graph_positions = {
                node_id: position
                for node_id, position in self.graph_positions.items()
                if node_id in existing_ids
            }
            self._ensure_graph_positions()
            self._draw_graph()
            if self.graph_selected:
                self._select_graph_item(*self.graph_selected)
            self.status.set(
                f"Graph: {len(self.graph_data['nodes'])} node(s), "
                f"{len(self.graph_data['edges'])} edge(s)"
            )
        except Exception as exc:
            messagebox.showerror("Graph refresh failed", str(exc))

    def _build_blobs_page(self):
        page = self.pages["blobs"]
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Blob Browser", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Button(
            toolbar,
            text="Upload",
            style="Accent.TButton",
            command=self.upload_blob,
        ).pack(side="right")
        ttk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh_blobs,
        ).pack(side="right", padx=6)
        ttk.Button(
            toolbar,
            text="Download",
            command=self.download_blob,
        ).pack(side="right")

        self.blob_tree = ttk.Treeview(
            page,
            height=5,
            columns=("id", "name", "mime", "bytes", "state"),
            show="headings",
        )
        for name, title in (
            ("id", "Object ID"),
            ("name", "Name"),
            ("mime", "MIME"),
            ("bytes", "Bytes"),
            ("state", "State"),
        ):
            self.blob_tree.heading(name, text=title)
        self.blob_tree.column("id", width=80, stretch=False)
        self.blob_tree.column("name", width=250)
        self.blob_tree.column("mime", width=180)
        self.blob_tree.column("bytes", width=110, stretch=False)
        self.blob_tree.column("state", width=100, stretch=False)
        blob_area = ttk.Frame(page)
        blob_area.pack(fill="both", expand=True)

        table_container = ttk.Frame(blob_area)
        table_container.pack(side="top", fill="x", pady=(0, 8))
        blob_scroll_y = ttk.Scrollbar(
            table_container,
            orient="vertical",
            command=self.blob_tree.yview,
        )
        blob_scroll_y.pack(side="right", fill="y")
        blob_scroll_x = ttk.Scrollbar(
            table_container,
            orient="horizontal",
            command=self.blob_tree.xview,
        )
        blob_scroll_x.pack(side="bottom", fill="x")
        self.blob_tree.configure(
            yscrollcommand=blob_scroll_y.set,
            xscrollcommand=blob_scroll_x.set,
        )
        self.blob_tree.pack(side="left", fill="both", expand=True)

        preview = ttk.Frame(blob_area, style="Panel.TFrame")
        preview.pack(side="top", fill="both", expand=True)
        preview_header = ttk.Frame(preview, style="Panel.TFrame")
        preview_header.pack(fill="x", padx=10, pady=8)
        ttk.Label(
            preview_header,
            text="Preview",
            style="Panel.TLabel",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        self.blob_details = tk.StringVar(value="Select an object to preview it.")
        ttk.Label(
            preview_header,
            textvariable=self.blob_details,
            style="Panel.TLabel",
        ).pack(side="left", padx=12, fill="x", expand=True)
        self.blob_pdf_page_label = tk.StringVar(value="")
        self.blob_pdf_previous = ttk.Button(
            preview_header,
            text="‹",
            width=3,
            command=lambda: self._change_blob_pdf_page(-1),
            state="disabled",
        )
        self.blob_pdf_previous.pack(side="right", padx=(0, 2))
        ttk.Label(
            preview_header,
            textvariable=self.blob_pdf_page_label,
            style="Panel.TLabel",
        ).pack(side="right", padx=4)
        self.blob_pdf_next = ttk.Button(
            preview_header,
            text="›",
            width=3,
            command=lambda: self._change_blob_pdf_page(1),
            state="disabled",
        )
        self.blob_pdf_next.pack(side="right", padx=(2, 6))
        ttk.Button(
            preview_header,
            text="Fit",
            command=self._fit_blob_image,
        ).pack(side="right", padx=(0, 4))
        ttk.Button(
            preview_header,
            text="100%",
            command=self._actual_size_blob_image,
        ).pack(side="right", padx=(0, 4))
        ttk.Button(
            preview_header,
            text="Zoom +",
            command=lambda: self._zoom_blob_image(1.25),
        ).pack(side="right", padx=(0, 4))
        ttk.Button(
            preview_header,
            text="Zoom −",
            command=lambda: self._zoom_blob_image(0.8),
        ).pack(side="right", padx=(0, 4))
        ttk.Button(
            preview_header,
            text="Open",
            command=self.open_selected_blob,
        ).pack(side="right", padx=(0, 6))
        ttk.Button(
            preview_header,
            text="Delete",
            command=self.delete_selected_blob,
        ).pack(side="right")

        preview_body = ttk.Frame(preview)
        preview_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.blob_canvas_area = ttk.Frame(preview_body)
        self.blob_canvas_area.pack(fill="both", expand=True)
        self.blob_preview = tk.Canvas(
            self.blob_canvas_area,
            bg=COLORS["bg"],
            highlightthickness=0,
            xscrollincrement=24,
            yscrollincrement=24,
        )
        preview_scroll_y = ttk.Scrollbar(
            self.blob_canvas_area,
            orient="vertical",
            command=self.blob_preview.yview,
        )
        preview_scroll_x = ttk.Scrollbar(
            self.blob_canvas_area,
            orient="horizontal",
            command=self.blob_preview.xview,
        )
        self.blob_preview.configure(
            yscrollcommand=preview_scroll_y.set,
            xscrollcommand=preview_scroll_x.set,
        )
        self.blob_preview.bind("<MouseWheel>", self._on_blob_mouse_wheel)
        self.blob_preview.bind("<ButtonPress-1>", self._on_blob_mouse_down)
        self.blob_preview.bind("<B1-Motion>", self._on_blob_mouse_drag)
        preview_scroll_y.pack(side="right", fill="y")
        preview_scroll_x.pack(side="bottom", fill="x")
        self.blob_preview.pack(side="left", fill="both", expand=True)
        self.blob_text_area = ttk.Frame(preview_body)
        self.blob_preview_text = tk.Text(
            self.blob_text_area,
            wrap="none",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            borderwidth=0,
            padx=12,
            pady=12,
            font=("Cascadia Code", 10),
        )
        text_scroll_y = ttk.Scrollbar(
            self.blob_text_area,
            orient="vertical",
            command=self.blob_preview_text.yview,
        )
        text_scroll_x = ttk.Scrollbar(
            self.blob_text_area,
            orient="horizontal",
            command=self.blob_preview_text.xview,
        )
        self.blob_preview_text.configure(
            yscrollcommand=text_scroll_y.set,
            xscrollcommand=text_scroll_x.set,
        )
        text_scroll_y.pack(side="right", fill="y")
        text_scroll_x.pack(side="bottom", fill="x")
        self.blob_preview_text.pack(side="left", fill="both", expand=True)
        self.blob_text_area.pack_forget()
        self.blob_tree.bind("<<TreeviewSelect>>", self.preview_selected_blob)
        self.blob_preview.bind("<Configure>", self._schedule_blob_image_render)
        self.blob_preview.create_text(
            20,
            20,
            anchor="nw",
            text="Select a blob to preview it",
            fill=COLORS["muted"],
        )

    def refresh_blobs(self):
        if not self._require_connection_quiet():
            return
        try:
            response = self.connection.list_blobs()
            self.blob_metadata_by_id = {
                blob["object_id"]: blob for blob in response["blobs"]
            }
            for item in self.blob_tree.get_children():
                self.blob_tree.delete(item)
            for blob in response["blobs"]:
                self.blob_tree.insert(
                    "",
                    "end",
                    values=(
                        blob["object_id"],
                        blob["name"],
                        blob["mime_type"],
                        blob["byte_length"],
                        blob["state"],
                    ),
                )
            self._set_blob_text_preview("Select a blob to preview it.")
            self.blob_details.set(
                f"{len(response['blobs'])} object(s) · select one to inspect"
            )
            self.status.set(f"{len(response['blobs'])} blob(s)")
        except Exception as exc:
            messagebox.showerror("Blob refresh failed", str(exc))

    def preview_selected_blob(self, event=None):
        selection = self.blob_tree.selection()
        if not selection:
            return
        self._close_blob_pdf()
        values = self.blob_tree.item(selection[0], "values")
        object_id = int(values[0])
        mime_type = str(values[2])
        state = str(values[4])
        name = str(values[1]).lower()
        metadata = self.blob_metadata_by_id.get(object_id, {})
        self.blob_details.set(
            f"#{object_id} · {metadata.get('name', values[1])} · "
            f"{mime_type} · {values[3]} bytes · "
            f"SHA-256 {metadata.get('checksum', 'unavailable')}"
        )
        image_extension = os.path.splitext(name)[1] in (
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
        )
        is_pdf = (
            mime_type.lower() == "application/pdf"
            or os.path.splitext(name)[1] == ".pdf"
        )
        if state != "ready":
            self._set_blob_text_preview(
                f"Object {object_id}\nState: {state}\n"
                "Preview is available after finalization."
            )
            return
        try:
            size = int(values[3])
            preview_size = min(size, 256 * 1024)
            if image_extension:
                data = self.connection.read_blob(object_id)
            else:
                data = self.connection.read_blob(
                    object_id,
                    start=0,
                    length=preview_size,
                )
        except Exception as exc:
            self._set_blob_text_preview(f"Preview failed:\n{exc}")
            return

        if is_pdf or data.startswith(b"%PDF-"):
            max_preview_size = 32 * 1024 * 1024
            if size > max_preview_size:
                self._set_blob_text_preview(
                    "PDF is larger than the 32 MiB in-app preview limit.\n"
                    "Download it to open it in your PDF viewer."
                )
                return
            try:
                pdf_data = bytearray()
                for chunk in self.connection.stream_blob(object_id):
                    if len(pdf_data) + len(chunk) > max_preview_size:
                        raise ValueError(
                            "PDF exceeds the 32 MiB in-app preview limit"
                        )
                    pdf_data.extend(chunk)
                self._show_blob_pdf(bytes(pdf_data))
                self.status.set(f"Previewing PDF blob {object_id}")
                return
            except Exception as exc:
                self._set_blob_text_preview(
                    f"PDF preview failed:\n{exc}"
                )
                return

        if (
            mime_type.startswith("image/")
            or image_extension
        ):
            try:
                self._show_blob_image(data)
                self.status.set(
                    f"Previewing image blob {object_id}"
                )
                return
            except Exception as exc:
                self._set_blob_text_preview(
                    f"Image preview failed:\n{exc}"
                )
                return

        if mime_type.startswith("text/") or mime_type in (
            "application/json",
            "application/xml",
        ):
            text = data.decode("utf-8", errors="replace")
            if size > preview_size:
                text += "\n\nPreview truncated to the first 256 KiB."
            self._set_blob_text_preview(text)
            return

        hex_preview = data[:4096].hex(" ")
        self._set_blob_text_preview(
            f"Binary preview · {size} bytes\n"
            f"MIME: {mime_type}\n\n"
            f"{hex_preview}"
        )

    def _set_blob_text_preview(self, text):
        self._close_blob_pdf()
        self._blob_original_image = None
        self._blob_preview_photo = None
        self.blob_canvas_area.pack_forget()
        self.blob_text_area.pack(fill="both", expand=True)
        self.blob_preview.delete("all")
        self.blob_preview_text.configure(state="normal")
        self.blob_preview_text.delete("1.0", "end")
        self.blob_preview_text.insert("1.0", text)
        self.blob_preview_text.configure(state="disabled")

    def _close_blob_pdf(self):
        if self._blob_pdf_document is not None:
            self._blob_pdf_document.close()
            self._blob_pdf_document = None
        self._blob_pdf_page = 0
        self.blob_pdf_page_label.set("")
        self.blob_pdf_previous.configure(state="disabled")
        self.blob_pdf_next.configure(state="disabled")

    def _show_blob_pdf(self, data):
        if pdfium is None or Image is None:
            raise RuntimeError(
                "Install pypdfium2 and Pillow to preview PDF files."
            )
        document = pdfium.PdfDocument(data)
        if len(document) == 0:
            document.close()
            raise RuntimeError("The PDF contains no pages.")
        self._blob_pdf_document = document
        self._blob_pdf_page = 0
        self._render_blob_pdf_page()

    def _render_blob_pdf_page(self):
        if self._blob_pdf_document is None:
            return
        self._blob_original_image = _render_pdf_page(
            self._blob_pdf_document,
            self._blob_pdf_page,
        )
        self._blob_zoom = None
        self._blob_image_origin = None
        page_count = len(self._blob_pdf_document)
        self.blob_pdf_page_label.set(
            f"{self._blob_pdf_page + 1} / {page_count}"
        )
        self.blob_pdf_previous.configure(
            state="normal" if self._blob_pdf_page > 0 else "disabled"
        )
        self.blob_pdf_next.configure(
            state=(
                "normal"
                if self._blob_pdf_page + 1 < page_count
                else "disabled"
            )
        )
        self.blob_text_area.pack_forget()
        self.blob_canvas_area.pack(fill="both", expand=True)
        self._schedule_blob_image_render()

    def _change_blob_pdf_page(self, offset):
        if self._blob_pdf_document is None:
            return
        page = self._blob_pdf_page + offset
        if 0 <= page < len(self._blob_pdf_document):
            self._blob_pdf_page = page
            self._render_blob_pdf_page()

    def _show_blob_image(self, data):
        if Image is None:
            raise RuntimeError("Pillow is required for image preview")
        image = Image.open(io.BytesIO(data))
        image.load()
        self._blob_original_image = image.convert("RGBA")
        self._blob_zoom = None
        self._blob_image_origin = None
        self.blob_text_area.pack_forget()
        self.blob_canvas_area.pack(fill="both", expand=True)
        self._schedule_blob_image_render()

    def _schedule_blob_image_render(self, event=None):
        if self._blob_original_image is None:
            return
        if self._blob_render_after is not None:
            self.after_cancel(self._blob_render_after)
        self._blob_render_after = self.after(80, self._render_blob_image)

    def _fit_blob_scale(self):
        if self._blob_original_image is None:
            return 1.0
        width = max(self.blob_preview.winfo_width() - 32, 1)
        height = max(self.blob_preview.winfo_height() - 32, 1)
        return min(
            width / self._blob_original_image.width,
            height / self._blob_original_image.height,
            1.0,
        )

    def _render_blob_image(self):
        self._blob_render_after = None
        if self._blob_original_image is None or ImageTk is None:
            return
        scale = self._blob_zoom or self._fit_blob_scale()
        width = max(1, round(self._blob_original_image.width * scale))
        height = max(1, round(self._blob_original_image.height * scale))
        image = self._blob_original_image.resize(
            (width, height),
            Image.Resampling.LANCZOS,
        )
        self._blob_preview_photo = ImageTk.PhotoImage(image)
        canvas_width = max(self.blob_preview.winfo_width(), 1)
        canvas_height = max(self.blob_preview.winfo_height(), 1)
        if self._blob_image_origin is None:
            x = max((canvas_width - width) // 2, 0)
            y = max((canvas_height - height) // 2, 0)
        else:
            x, y = self._blob_image_origin
        self.blob_preview.delete("all")
        self.blob_preview.create_image(
            x,
            y,
            image=self._blob_preview_photo,
            anchor="nw",
        )
        self.blob_preview.configure(
            scrollregion=(
                min(0, x),
                min(0, y),
                max(canvas_width, x + width),
                max(canvas_height, y + height),
            )
        )

    def _fit_blob_image(self):
        self._blob_zoom = None
        self._blob_image_origin = None
        self._schedule_blob_image_render()

    def _actual_size_blob_image(self):
        self._blob_zoom = 1.0
        self._blob_image_origin = None
        self._schedule_blob_image_render()

    def _zoom_blob_image(self, factor):
        if self._blob_original_image is None:
            return
        current = self._blob_zoom or self._fit_blob_scale()
        self._blob_zoom = min(max(current * factor, 0.1), 5.0)
        self._schedule_blob_image_render()

    def _on_blob_mouse_wheel(self, event):
        if self._blob_original_image is None:
            return
        old_scale = self._blob_zoom or self._fit_blob_scale()
        new_scale = min(max(old_scale * (1.12 if event.delta > 0 else 0.89),
                            0.1), 5.0)
        canvas_x = self.blob_preview.canvasx(event.x)
        canvas_y = self.blob_preview.canvasy(event.y)
        origin_x, origin_y = self._blob_image_origin or (
            max((self.blob_preview.winfo_width() -
                 self._blob_original_image.width * old_scale) / 2, 0),
            max((self.blob_preview.winfo_height() -
                 self._blob_original_image.height * old_scale) / 2, 0),
        )
        image_x = (canvas_x - origin_x) / old_scale
        image_y = (canvas_y - origin_y) / old_scale
        self._blob_zoom = new_scale
        self._blob_image_origin = (
            canvas_x - image_x * new_scale,
            canvas_y - image_y * new_scale,
        )
        self._schedule_blob_image_render()
        return "break"

    def _on_blob_mouse_down(self, event):
        if self._blob_original_image is not None:
            self.blob_preview.scan_mark(event.x, event.y)

    def _on_blob_mouse_drag(self, event):
        if self._blob_original_image is not None:
            self.blob_preview.scan_dragto(event.x, event.y, gain=1)

    def open_selected_blob(self):
        selection = self.blob_tree.selection()
        if not selection:
            messagebox.showwarning(
                "Select a blob",
                "Choose a blob row before opening.",
            )
            return
        values = self.blob_tree.item(selection[0], "values")
        object_id = int(values[0])
        name = os.path.basename(str(values[1]))
        metadata = self.blob_metadata_by_id.get(object_id, {})
        suffix = _blob_extension(
            name,
            str(metadata.get("mime_type", "application/octet-stream")),
        )
        try:
            data = self.connection.read_blob(object_id)
            with tempfile.NamedTemporaryFile(
                suffix=suffix,
                prefix="thesagra-",
                delete=False,
            ) as temp_file:
                temp_file.write(data)
                temp_path = temp_file.name
            os.startfile(temp_path)
            self.status.set(
                f"Opened blob {object_id} in the system viewer"
            )
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))

    def delete_selected_blob(self):
        selection = self.blob_tree.selection()
        if not selection:
            messagebox.showwarning(
                "Select a blob",
                "Choose a blob row before deleting.",
            )
            return
        values = self.blob_tree.item(selection[0], "values")
        object_id = int(values[0])
        if not messagebox.askyesno(
            "Delete blob",
            f"Mark blob {object_id} ({values[1]}) as deleted?",
        ):
            return
        try:
            self.connection.delete_blob(object_id)
            self.refresh_blobs()
            self._set_blob_text_preview(
                f"Blob {object_id} marked deleted."
            )
            self.status.set(f"Deleted blob {object_id}")
        except Exception as exc:
            messagebox.showerror("Delete failed", str(exc))

    def upload_blob(self):
        if not self._require_connection():
            return
        path = filedialog.askopenfilename(title="Upload file")
        if not path:
            return
        threading.Thread(
            target=self._upload_blob,
            args=(path,),
            daemon=True,
        ).start()

    def _upload_blob(self, path):
        try:
            size = os.path.getsize(path)
            extension = os.path.splitext(path)[1].lower()
            mime_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".txt": "text/plain",
                ".json": "application/json",
                ".pdf": "application/pdf",
                ".csv": "text/csv",
            }
            mime = mime_types.get(
                extension,
                "application/octet-stream",
            )
            object_id = self.connection.begin_blob_upload(
                os.path.basename(path),
                mime,
                {},
                max_size=size,
            )
            with open(path, "rb") as blob_file:
                written = 0
                while True:
                    chunk = blob_file.read(64 * 1024)
                    if not chunk:
                        break
                    written += self.connection.append_blob(
                        object_id,
                        chunk,
                    )
                    self.after(
                        0,
                        lambda value=written, total=size:
                        self.status.set(
                            f"Uploading: {value}/{total} bytes"
                        ),
                    )
            metadata = self.connection.finalize_blob(
                object_id,
                declared_size=size,
            )
            self.after(0, self.refresh_blobs)
            self.after(
                0,
                lambda: self.status.set(
                    f"Uploaded blob {metadata['object_id']}"
                ),
            )
        except Exception as exc:
            self.after(
                0,
                lambda error=str(exc): messagebox.showerror(
                    "Upload failed",
                    error,
                ),
            )

    def download_blob(self):
        if not self._require_connection():
            return
        selection = self.blob_tree.selection()
        if not selection:
            messagebox.showwarning(
                "Select a blob",
                "Choose a blob row before downloading.",
            )
            return
        values = self.blob_tree.item(selection[0], "values")
        object_id = int(values[0])
        path = filedialog.asksaveasfilename(
            **_blob_save_dialog_options(
                str(values[1]),
                str(values[2]),
            )
        )
        if not path:
            return
        threading.Thread(
            target=self._download_blob,
            args=(object_id, path),
            daemon=True,
        ).start()

    def _download_blob(self, object_id, path):
        try:
            with open(path, "wb") as output:
                for chunk in self.connection.stream_blob(object_id):
                    output.write(chunk)
            self.after(
                0,
                lambda: self.status.set(f"Downloaded blob {object_id}"),
            )
        except Exception as exc:
            self.after(
                0,
                lambda error=str(exc): messagebox.showerror(
                    "Download failed",
                    error,
                ),
            )

    def _build_workers_page(self):
        page = self.pages["workers"]
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Worker Dashboard", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh_workers,
        ).pack(side="right")
        ttk.Button(
            toolbar,
            text="Reconcile Blobs",
            command=lambda: self.enqueue_task("blob_reconcile"),
        ).pack(side="right", padx=6)
        ttk.Button(
            toolbar,
            text="Integrity Check",
            command=lambda: self.enqueue_task("integrity_check"),
        ).pack(side="right")

        self.worker_summary = tk.StringVar(value="Worker: unknown")
        ttk.Label(
            page,
            textvariable=self.worker_summary,
            style="Title.TLabel",
        ).pack(anchor="w", pady=(4, 10))

        self.worker_tree = ttk.Treeview(
            page,
            height=2,
            columns=("running", "queued", "completed", "failed", "dead",
                     "claimed"),
            show="headings",
        )
        for name, title in (
            ("running", "Worker"),
            ("queued", "Queued"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("dead", "Dead"),
            ("claimed", "Claimed"),
        ):
            self.worker_tree.heading(name, text=title)
            self.worker_tree.column(name, width=140)
        self.worker_tree.pack(fill="x", expand=False)
        ttk.Label(
            page,
            text="Recent tasks",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(14, 6))
        task_frame = ttk.Frame(page)
        task_frame.pack(fill="both", expand=True)
        self.task_tree = ttk.Treeview(
            task_frame,
            columns=(
                "id",
                "type",
                "state",
                "attempts",
                "created",
                "completed",
                "error",
            ),
            show="headings",
        )
        for name, title, width in (
            ("id", "Task ID", 245),
            ("type", "Type", 150),
            ("state", "State", 100),
            ("attempts", "Attempts", 90),
            ("created", "Created", 180),
            ("completed", "Completed", 180),
            ("error", "Error", 300),
        ):
            self.task_tree.heading(name, text=title)
            self.task_tree.column(name, width=width, stretch=name == "error")
        task_scroll_y = ttk.Scrollbar(
            task_frame,
            orient="vertical",
            command=self.task_tree.yview,
        )
        task_scroll_x = ttk.Scrollbar(
            task_frame,
            orient="horizontal",
            command=self.task_tree.xview,
        )
        self.task_tree.configure(
            yscrollcommand=task_scroll_y.set,
            xscrollcommand=task_scroll_x.set,
        )
        task_scroll_y.pack(side="right", fill="y")
        task_scroll_x.pack(side="bottom", fill="x")
        self.task_tree.pack(side="left", fill="both", expand=True)

    def refresh_workers(self):
        if not self._require_connection_quiet():
            return
        try:
            worker_status = self.connection.get_worker_status()
            queue = worker_status["queue"]
            metrics = worker_status["metrics"]
            for item in self.worker_tree.get_children():
                self.worker_tree.delete(item)
            self.worker_tree.insert(
                "",
                "end",
                values=(
                    "Running" if worker_status["running"] else "Stopped",
                    queue.get("queued", 0),
                    queue.get("completed", 0),
                    queue.get("failed", 0),
                    queue.get("dead", 0),
                    metrics.get("tasks_claimed", 0),
                ),
            )
            for item in self.task_tree.get_children():
                self.task_tree.delete(item)
            for task in worker_status.get("tasks", []):
                self.task_tree.insert(
                    "",
                    "end",
                    values=(
                        task["task_id"],
                        task["task_type"],
                        task["state"],
                        f"{task['attempts']}/{task['max_attempts']}",
                        task["created_at"],
                        task["completed_at"] or "",
                        task["error"] or "",
                    ),
                )
            self.worker_summary.set(
                "Worker: "
                + ("running" if worker_status["running"] else "stopped")
            )
            self.status.set(
                f"Worker status refreshed · {len(worker_status.get('tasks', []))} "
                "recent task(s)"
            )
        except Exception as exc:
            self.status.set(f"Worker status unavailable: {exc}")

    def enqueue_task(self, task_type):
        if not self._require_connection():
            return
        try:
            response = self.connection.enqueue_task(
                task_type,
                payload={},
                max_attempts=3,
                idempotency_key=None,
            )
            self.status.set(f"Queued task {response['task_id']}")
            self.after(500, self.refresh_workers)
        except Exception as exc:
            messagebox.showerror("Task failed", str(exc))


def main():
    app = THESAGRAGui()
    app.mainloop()


if __name__ == "__main__":
    main()
