-- ZaowuGrowthManager SQLite schema v1; generated from Store.migrate(). No business data.
PRAGMA foreign_keys=ON;

CREATE TABLE products (id INTEGER PRIMARY KEY, "business" TEXT, "name" TEXT, "price" INTEGER, "material" INTEGER, "active" INTEGER, "features" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE customers (id INTEGER PRIMARY KEY, "code" TEXT, "business" TEXT, "category" TEXT, "source" TEXT, "preferences" TEXT, "consent" INTEGER, "notes" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE orders (id INTEGER PRIMARY KEY, "date" TEXT, "business" TEXT, "product_id" INTEGER REFERENCES products(id) ON DELETE RESTRICT, "customer_id" INTEGER REFERENCES customers(id) ON DELETE RESTRICT, "quantity" INTEGER, "people" INTEGER, "customer_kind" TEXT, "source" TEXT, "channel" TEXT, "status" TEXT, "expected" INTEGER, "revenue" INTEGER, "material" INTEGER, "labor" INTEGER, "other" INTEGER, "delivery" TEXT, "fulfillment" TEXT, "festival" TEXT, "location" TEXT, "activity" TEXT, "notes" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE inventory (id INTEGER PRIMARY KEY, "date" TEXT, "item" TEXT, "movement" TEXT, "quantity" INTEGER, "unit" TEXT, "amount" INTEGER, "notes" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE expenses (id INTEGER PRIMARY KEY, "date" TEXT, "category" TEXT, "amount" INTEGER, "notes" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE goals (id INTEGER PRIMARY KEY, "date" TEXT, "business" TEXT, "title" TEXT, "metric" TEXT, "target" REAL, "actual" REAL, "deadline" TEXT, "notes" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE campaigns (id INTEGER PRIMARY KEY, "date" TEXT, "business" TEXT, "title" TEXT, "platform" TEXT, "hypothesis" TEXT, "audience" TEXT, "budget" INTEGER, "spent" INTEGER, "criterion" TEXT, "exposures" INTEGER, "visits" INTEGER, "inquiries" INTEGER, "conversions" INTEGER, "result" TEXT, "status" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE tasks (id INTEGER PRIMARY KEY, "date" TEXT, "business" TEXT, "title" TEXT, "deadline" TEXT, "status" TEXT, "result" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE contents (id INTEGER PRIMARY KEY, "date" TEXT, "business" TEXT, "platform" TEXT, "title" TEXT, "format" TEXT, "body" TEXT, "status" TEXT, "url" TEXT, "views" INTEGER, "inquiries" INTEGER, "orders" INTEGER, updated_at TEXT NOT NULL);

CREATE TABLE assets (id INTEGER PRIMARY KEY, "date" TEXT, "business" TEXT, "title" TEXT, "path" TEXT, "description" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE competitors (id INTEGER PRIMARY KEY, "date" TEXT, "name" TEXT, "product" TEXT, "price" INTEGER, "features" TEXT, "marketing" TEXT, "url" TEXT, "learnings" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE reviews (id INTEGER PRIMARY KEY, "date" TEXT, "period" TEXT, "title" TEXT, "facts" TEXT, "findings" TEXT, "actions" TEXT, updated_at TEXT NOT NULL);

CREATE TABLE memories (id INTEGER PRIMARY KEY, "date" TEXT, "category" TEXT, "title" TEXT, "body" TEXT, "share_ai" INTEGER, updated_at TEXT NOT NULL);

CREATE TABLE followups (id INTEGER PRIMARY KEY, "date" TEXT, "customer_id" INTEGER REFERENCES customers(id) ON DELETE RESTRICT, "stage" TEXT, "body" TEXT, "next_date" TEXT, updated_at TEXT NOT NULL);

CREATE UNIQUE INDEX customer_code ON customers(code);

CREATE INDEX order_date ON orders(date, business);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE sessions (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, table_name TEXT NOT NULL, row_id INTEGER);

CREATE TABLE reports (id INTEGER PRIMARY KEY, period TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(period,start,end));
PRAGMA user_version=1;
