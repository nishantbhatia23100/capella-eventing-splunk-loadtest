// SHIPPER for variant D: one HEC call per log document, carrying ALL events in that document
// as stacked JSON objects (HEC batch format). With variant C/D's business function this means
// 1 call per business invocation instead of 1 call per log line. Also accepts variant-A style
// docs (single line, no "events" array) so you can compare on the same shipper.
//
// Capella settings: same as A_C_ship_per_doc.js (binding "splunkHEC", No Auth).
// Verify in your Eventing version that a string "body" is sent as-is (not re-encoded as JSON).

function OnUpdate(doc, meta) {
  var events = Array.isArray(doc.events) ? doc.events : [doc];
  var base = { "function": doc["function"], "order_ts": doc.order_ts, "category": doc.category, "amount": doc.amount };

  var body = "";
  for (var i = 0; i < events.length; i++) {
    var e = events[i];
    var ev = Object.assign({}, base, e);   // keeps the line's own "t" for lag measurement
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
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Splunk <hec-token>"
    },
    body: body
  };

  try {
    var response = curl("POST", splunkHEC, request);
    if (response.status !== 200) {
      log("HEC rejected", meta.id, response.status);
    }
  } catch (err) {
    log("HEC POST failed", meta.id, err);
  }
}

function OnDelete(meta, options) {}
