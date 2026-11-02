// FUNCTION 2: enrich_orders
// The "business logic" function. Fires on each order, does light processing,
// and writes structured log documents into a dedicated logs collection.
// This is the pattern from Couchbase's official eventing-observability guide:
// turn log lines into documents so they can be shipped downstream.
//
// Capella settings:
//   Source collection : data.sales.orders
//   Eventing storage   : data.eventing.metadata
//   Bucket binding     : alias "logCollection" -> eventing-logs.eventing.logs  (read + write)
//   Feed boundary      : From now
//
// NOTE: this function deliberately does NOT write back into data.sales.orders,
//       to avoid re-triggering itself / populate_orders (infinite loop).

function OnUpdate(doc, meta) {
  if (meta.id === "start" || doc.type !== "order") return;

  logIt("debug", "start evaluating " + meta.id, meta.id, doc);

  var tier = doc.amount > 300 ? "GOLD" : (doc.amount > 100 ? "SILVER" : "BRONZE");
  logIt("info", "assigned tier " + tier + " to " + meta.id, meta.id, doc);

  if (doc.category === "electronics" && doc.amount > 400) {
    logIt("warning", "high-value electronics order " + meta.id + " flagged for review", meta.id, doc);
  }

  // simulate an occasional downstream failure so Splunk has errors to show
  if (Math.random() < 0.03) {
    logIt("error", "enrichment API timeout for " + meta.id, meta.id, doc);
  }

  logIt("debug", "end evaluating " + meta.id, meta.id, doc);
}

function OnDelete(meta, options) {}

function logIt(level, message, id, doc) {
  var now = new Date();
  var logId = "log::" + now.getTime() + "::" + Math.floor(Math.random() * 1e7);
  logCollection[logId] = {
    "@timestamp": now.toISOString(),
    "level": level,
    "function": "enrich_orders",
    "message": message,
    "meta_id": id,
    "bucket": "data",
    "scope": "sales",
    "collection": "orders",
    "category": (doc && doc.category) || null,
    "amount": (doc && doc.amount) || null,
    "cluster_id": "my-cluster",
    "log": { "level": level, "logger": "eventing", "origin": { "function": "enrich_orders" } }
  };
}
