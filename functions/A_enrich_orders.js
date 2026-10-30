// VARIANT A (baseline): business function, one log document per log line.
// Same behaviour as the demo repo's enrich_orders: every logIt() is a separate mutation.
//
// Capella settings:
//   Source collection : data.sales.orders
//   Eventing storage  : data.eventing.metadata
//   Bucket binding    : alias "logCollection" -> eventing-logs.eventing.logs (read + write)
//   Feed boundary     : From now

function OnUpdate(doc, meta) {
  if (meta.id === "start" || doc.type !== "order") return;

  logIt("debug", "start evaluating " + meta.id, meta.id, doc);

  var tier = doc.amount > 300 ? "GOLD" : (doc.amount > 100 ? "SILVER" : "BRONZE");
  logIt("info", "assigned tier " + tier + " to " + meta.id, meta.id, doc);

  if (doc.category === "electronics" && doc.amount > 400) {
    logIt("warning", "high-value electronics order " + meta.id + " flagged for review", meta.id, doc);
  }
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
    "order_ts": (doc && doc.ts) || null,
    "category": (doc && doc.category) || null,
    "amount": (doc && doc.amount) || null
  };
}
