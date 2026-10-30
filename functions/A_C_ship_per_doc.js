// SHIPPER for variants A and C: one HEC call per log document.
// Variant A: each doc is a single log line.  Variant C: each doc holds an "events" array,
// but is still sent as one HEC event (so call volume falls with fewer docs, not with batching).
//
// Capella settings:
//   Source collection : eventing-logs.eventing.logs
//   Eventing storage  : data.eventing.metadata
//   URL binding       : alias "splunkHEC" -> https://<mock or Splunk>/services/collector/event
//        Auth: No Auth (the Splunk header is set in code)   Validate SSL: ON
//   Workers           : set per test (1, 8, 16, 32 ...)
//   Feed boundary     : From now

function OnUpdate(doc, meta) {
  var request = {
    path: "",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Splunk <hec-token>"
    },
    body: {
      "time": Math.floor(Date.now() / 1000),
      "sourcetype": "couchbase:eventing",
      "index": "couchbase",
      "event": doc
    }
  };

  try {
    var response = curl("POST", splunkHEC, request);
    if (response.status !== 200) {
      log("HEC rejected", meta.id, response.status);
    }
  } catch (e) {
    log("HEC POST failed", meta.id, e);
  }
}

function OnDelete(meta, options) {}
