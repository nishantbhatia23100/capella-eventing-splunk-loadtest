// VARIANT G: business function whose log level is controlled by a config document, with no redeploy.
// Reads "loglevel::enrich_orders" (falling back to "loglevel::default") from the config collection through
// the bucket binding "cfg" (read-only) on every execution, then applies the same one-doc-per-execution
// logging as variant C/D.
//
// Config document (all fields optional; missing doc => minLevel "info", infoSample 0.1):
//   { "minLevel": "debug|info|warning|error",   // lowest level written
//     "infoSample": 0.1,                         // fraction of info lines kept (0..1)
//     "debugUntil": 1793400000000 }              // epoch ms; until then everything is written (temporary debug)
//
// Capella settings: source data.sales.orders; bindings: "logCollection" -> eventing-logs.eventing.logs (read+write),
//                   "cfg" -> eventing-logs.eventing.config (read).
// Eventing has no global variables, so every setting lives inside OnUpdate or in the config document.

function OnUpdate(doc, meta) {
  if (meta.id === "start" || doc.type !== "order") return;

  var RANK = { debug: 0, info: 1, warning: 2, error: 3 };

  var c = {};
  try {
    c = cfg["loglevel::enrich_orders"] || cfg["loglevel::default"] || {};
  } catch (e) {
    c = {};                                   // never let a config problem break the business logic
  }
  var min = (RANK[c.minLevel] !== undefined) ? c.minLevel : "info";
  var infoSample = (typeof c.infoSample === "number") ? c.infoSample : 0.1;
  if (typeof c.debugUntil === "number" && Date.now() < c.debugUntil) {
    min = "debug";
    infoSample = 1;
  }

  var logs = [];
  function L(level, message) {
    if (RANK[level] < RANK[min]) return;
    if (level === "info" && Math.random() >= infoSample) return;
    logs.push({ t: Date.now(), level: level, message: message, meta_id: meta.id });
  }

  try {
    L("debug", "start evaluating " + meta.id);

    var tier = doc.amount > 300 ? "GOLD" : (doc.amount > 100 ? "SILVER" : "BRONZE");
    L("info", "assigned tier " + tier + " to " + meta.id);

    if (doc.category === "electronics" && doc.amount > 400) {
      L("warning", "high-value electronics order " + meta.id + " flagged for review");
    }
    if (Math.random() < 0.03) {
      L("error", "enrichment API timeout for " + meta.id);
    }

    L("debug", "end evaluating " + meta.id);
  } catch (e) {
    L("error", "unhandled exception for " + meta.id + ": " + String(e));
  } finally {
    if (logs.length) {
      var logId = "log::" + meta.id + "::" + Date.now() + "::" + Math.floor(Math.random() * 1e7);
      logCollection[logId] = {
        "function": "enrich_orders",
        "order_ts": doc.ts || null,
        "category": doc.category || null,
        "amount": doc.amount || null,
        "cfg_level": min,
        "events": logs
      };
    }
  }
}

function OnDelete(meta, options) {}
