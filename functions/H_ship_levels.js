// VARIANT H: as F (batched, with failure records), and ships ONLY the levels listed in WANT.
// Run two copies as two Eventing functions to split one log stream by level: each copy has its own
// workers, its own HEC URL/token/index, and its own backlog, so a slow debug path cannot delay errors.
// (The source collection is the same; each function filters the events it ships.)
// Based on F: plus a record for every call that does not return HTTP 200.
// Failures go to eventing-logs.eventing.shipper_errors (binding "errCol"), keyed per source doc, so you can
// count and replay them. A call that returns a non-200 status does NOT throw in Eventing, so without this
// it looks like a success in the function stats.

function OnUpdate(doc, meta) {
  var WANT = ["debug", "info", "warning", "error"];   // edit per function; no globals allowed in Eventing
  var all = Array.isArray(doc.events) ? doc.events : [doc];
  var events = [];
  for (var k = 0; k < all.length; k++) { if (WANT.indexOf(all[k].level) >= 0) events.push(all[k]); }
  if (!events.length) return;
  var base = { "function": doc["function"], "order_ts": doc.order_ts, "category": doc.category, "amount": doc.amount };

  var body = "";
  for (var i = 0; i < events.length; i++) {
    var e = events[i];
    var ev = Object.assign({}, base, e);
    body += JSON.stringify({
      "time": (e.t || Date.now()) / 1000,
      "sourcetype": "couchbase:eventing",
      "index": "couchbase",
      "event": ev
    });
  }
  if (!body) return;

  var request = {
    path: "",
    headers: { "Content-Type": "application/json", "Authorization": "Splunk <hec-token>" },
    body: body
  };

  try {
    var response = curl("POST", splunkHEC, request);
    if (response.status !== 200) {
      errCol["err::" + meta.id] = { "kind": "status", "status": response.status,
                                    "body": String(response.body).slice(0, 300), "events": events.length, "ts": Date.now() };
    }
  } catch (err) {
    errCol["err::" + meta.id] = { "kind": "exception", "error": String(err).slice(0, 300),
                                  "events": events.length, "ts": Date.now() };
  }
}

function OnDelete(meta, options) {}
