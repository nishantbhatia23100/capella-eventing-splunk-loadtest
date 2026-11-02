// FUNCTION 3: ship_logs_to_splunk
// The "log shipper". Fires on each new log document and cURL-POSTs it to the
// Splunk HTTP Event Collector. Keeping this in its own function means the
// external HTTP call never sits in the business function's hot path.
//
// Capella settings:
//   Source collection : eventing-logs.eventing.logs
//   Eventing storage   : data.eventing.metadata
//   URL binding        : alias "splunkHEC"
//        Value : https://<your-ngrok-subdomain>.ngrok-free.app/services/collector/event
//        Auth  : No Auth   <-- IMPORTANT: not Bearer. We send the header ourselves.
//        Validate SSL certificate: ON  (ngrok presents a valid cert)
//   Feed boundary      : Everything (to ship existing log docs) or From now
//
// Splunk HEC requires the "Splunk <token>" auth scheme. It does NOT accept
// "Bearer <token>" (that scheme is only for Splunk JWT platform tokens), so we
// set the binding to No Auth and add the correct Authorization header in code.

function OnUpdate(doc, meta) {
  var payload = {
    "time": Math.floor(Date.now() / 1000),
    "host": "cb.<cluster-id>.cloud.couchbase.com",
    "source": "capella-eventing",
    "sourcetype": "couchbase:eventing",
    "index": "couchbase",
    "event": doc                        // the full structured log document
  };

  var request = {
    path: "",                           // binding URL already targets /services/collector/event
    headers: {
      "Content-Type": "application/json",
      // HEC requires the "Splunk" scheme (NOT Bearer). Binding auth must be "No Auth".
      "Authorization": "Splunk <hec-token>"
    },
    body: payload
  };

  try {
    var response = curl("POST", splunkHEC, request);
    if (response.status !== 200) {
      log("Splunk HEC rejected event", meta.id, response.status, response.body);
    }
  } catch (e) {
    log("Splunk HEC POST failed", meta.id, e);
    // For production: write meta.id to a dead-letter collection for retry.
  }
}

function OnDelete(meta, options) {}
