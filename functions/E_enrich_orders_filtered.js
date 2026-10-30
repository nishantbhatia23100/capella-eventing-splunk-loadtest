// VARIANT E: as C/D (one log doc per invocation) but filtered: debug dropped, info sampled at 10%,
// warning and error always kept. Only invocations that produce at least one line write a doc.
// VARIANT C and D: business function that writes ONE log document per invocation.
// Log lines are collected in a local array and written once in finally{}, turning N mutations
// per order into 1. Produces the same log lines as variant A so the comparison is fair.
// (Eventing has no global state, so the buffer lives only for the duration of this invocation.)
//
// Capella settings: same as variant A (source data.sales.orders, binding "logCollection").
//

// NOTE: Eventing does not allow global variables, so the volume controls live inside OnUpdate.

function OnUpdate(doc, meta) {
  if (meta.id === "start" || doc.type !== "order") return;

  // Volume controls (defaults keep every line, for an apples-to-apples test):
  //   MIN_LEVEL   : lowest level written ("debug" = all, "warning" = only warning/error)
  //   INFO_SAMPLE : fraction of info lines kept (1 = all, 0.1 = one in ten)
  var MIN_LEVEL = "info";
  var INFO_SAMPLE = 0.1;
  var RANK = { debug: 0, info: 1, warning: 2, error: 3 };

  var logs = [];
  function L(level, message) {
    if (RANK[level] < RANK[MIN_LEVEL]) return;
    if (level === "info" && Math.random() >= INFO_SAMPLE) return;
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
        "events": logs
      };
    }
  }
}

function OnDelete(meta, options) {}
