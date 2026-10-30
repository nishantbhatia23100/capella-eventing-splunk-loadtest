#!/usr/bin/env python3
"""Set up the load-test keyspaces and Eventing functions through the Capella Management API (v4).

Env vars: CAPELLA_API_KEY, ORG_ID, PROJECT_ID, CLUSTER_ID

  python3 setup_capella.py --buckets                       # data + eventing-logs, scopes, collections
  python3 setup_capella.py --list-functions
  python3 setup_capella.py --export-function enrich_orders --out template_biz.json
  python3 setup_capella.py --create-function template_biz.json --name enrich_orders --code functions/A_enrich_orders.js
  python3 setup_capella.py --deploy enrich_orders          # also --undeploy / --pause / --resume
  python3 setup_capella.py --update-function template_biz.json --name enrich_orders --code functions/C_D_enrich_orders_batched.js

UNVERIFIED: the bucket/scope/collection request bodies below are best guesses from the v4 docs,
and Eventing function bodies are never hand-written: create ONE function in the Capella UI, export it
with --export-function (documented: export=true strips read-only fields), then reuse that JSON as the
template. Fill in any redacted URL-binding secrets (they come back as *****) before creating.
Every error response is printed in full so the bodies can be corrected quickly.
"""
import argparse, base64, json, os, sys
import requests

API = os.environ.get("CAPELLA_API", "https://cloudapi.cloud.couchbase.com")
_missing = [v for v in ("CAPELLA_API_KEY", "ORG_ID", "PROJECT_ID", "CLUSTER_ID") if not os.environ.get(v)]
if _missing:
    sys.exit("missing env vars: " + ", ".join(_missing) +
             "\n(set them in this terminal; find the IDs with: python3 ../audit-to-splunk/capella_audit_to_splunk.py --whoami)")
BASE =(f"{API}/v4/organizations/{os.environ['ORG_ID']}"
        f"/projects/{os.environ['PROJECT_ID']}/clusters/{os.environ['CLUSTER_ID']}")
H = {"Authorization": f"Bearer {os.environ['CAPELLA_API_KEY']}", "Content-Type": "application/json"}

LAYOUT = {  # bucket -> scope -> [collections]
    "data": {"sales": ["orders"], "eventing": ["metadata"]},
    "eventing-logs": {"eventing": ["logs", "shipper_errors"]},
}
BUCKET_BODY = {"type": "couchbase", "storageBackend": "couchstore", "memoryAllocationInMb": 200,
               "bucketConflictResolution": "seqno", "durabilityLevel": "none",
               "replicas": 1, "flush": True, "timeToLiveInSeconds": 0}


def show(r, label=""):
    print(f"{label} HTTP {r.status_code}")
    if r.text:
        try:
            print(json.dumps(r.json(), indent=2)[:3000])
        except ValueError:
            print(r.text[:1000])


def bucket_id(name, padded=True):
    s = base64.urlsafe_b64encode(name.encode()).decode()
    return s if padded else s.rstrip("=")


def post_ok(url, body, what):
    r = requests.post(url, headers=H, json=body, timeout=60)
    if r.status_code == 409 or (r.status_code == 422 and "already exists" in r.text):
        print(f"= {what}: already exists")
        return True
    if r.ok:
        print(f"+ {what}: created")
        return True
    print(f"! {what}")
    show(r)
    return False


def create_layout():
    for b, scopes in LAYOUT.items():
        if not post_ok(f"{BASE}/buckets", dict(BUCKET_BODY, name=b), f"bucket {b}"):
            sys.exit("bucket creation failed; fix BUCKET_BODY from the API reference and retry")
        bid = bucket_id(b)
        for s, cols in scopes.items():
            if s != "_default":
                post_ok(f"{BASE}/buckets/{bid}/scopes", {"name": s}, f"scope {b}.{s}")
            for c in cols:
                post_ok(f"{BASE}/buckets/{bid}/scopes/{s}/collections", {"name": c}, f"collection {b}.{s}.{c}")
    print("\nbuckets can take a minute to become ready before functions can use them")


def fn_url(name=""):
    return f"{BASE}/eventingFunctions" + (f"/{name}" if name else "")


def find_code_key(node, path=()):
    """Locate the string field that holds the handler source (key name contains 'code')."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and "code" in k.lower() and len(v) > 20:
                return path + (k,)
            f = find_code_key(v, path + (k,))
            if f:
                return f
    return None


def load_template(path, name, code_file, hec_url="", workers=0):
    raw = open(path).read()
    if hec_url:
        raw = raw.replace("REPLACE_HEC_URL", hec_url)
    body = json.loads(raw)
    if workers:
        body.setdefault("settings", {})["workerCount"] = workers
    if "REPLACE_HEC_URL" in raw:
        print("WARNING: template still contains REPLACE_HEC_URL (pass --hec-url)")
    if name:
        for k in ("name", "functionName"):
            if k in body:
                body[k] = name
    if code_file and "code" in body:
        body["code"] = open(code_file).read()
        print("replaced code at: code")
    elif code_file:
        key = find_code_key(body)
        if not key:
            sys.exit("could not find the code field in the template; edit it by hand")
        node = body
        for k in key[:-1]:
            node = node[k]
        node[key[-1]] = open(code_file).read()
        print(f"replaced code at: {'.'.join(key)}")
    if "*****" in json.dumps(body):
        print("WARNING: template still has redacted ***** values (URL binding secrets). Fill them in.")
    return body


def verify_bindings(name, sent):
    """Bindings in a guessed format may be silently dropped: re-read the function and compare."""
    if not sent.get("bindings"):
        return
    r = requests.get(fn_url(name), headers=H, params={"export": "true"}, timeout=30)
    got = r.json().get("bindings") if r.ok else None
    if not got:
        print("\nWARNING: bindings are EMPTY on the server; the binding format in the template is wrong.")
    else:
        print("\nbindings stored on the server:", json.dumps(got))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--buckets", action="store_true")
    ap.add_argument("--list-functions", action="store_true")
    ap.add_argument("--delete-function", metavar="NAME", help="delete an (undeployed) function; path unverified")
    ap.add_argument("--probe-create", action="store_true", help="send a trial body to create-function to learn required fields")
    ap.add_argument("--probe-json", default="", help="JSON body for --probe-create (default {})")
    ap.add_argument("--export-function")
    ap.add_argument("--out", default="")
    ap.add_argument("--create-function", metavar="TEMPLATE.json")
    ap.add_argument("--update-function", metavar="TEMPLATE.json")
    ap.add_argument("--name")
    ap.add_argument("--hec-url", default="", help="replaces REPLACE_HEC_URL in the template")
    ap.add_argument("--workers", type=int, default=0, help="override settings.workerCount")
    ap.add_argument("--code")
    for st in ("deploy", "undeploy", "pause", "resume"):
        ap.add_argument(f"--{st}", metavar="FUNCTION")
    a = ap.parse_args()

    c = requests.get(BASE, headers=H, timeout=30)
    print("cluster:", c.json().get("name") if c.ok else f"<lookup failed HTTP {c.status_code}>", "\n")

    if a.buckets:
        create_layout()
    elif a.delete_function:
        show(requests.delete(fn_url(a.delete_function), headers=H, timeout=60), "delete")
    elif a.probe_create:
        body = json.loads(a.probe_json) if a.probe_json else {}
        print("posting a trial body to create-function:", json.dumps(body))
        print("(an incomplete body returns a 4xx naming the next missing field; a COMPLETE one creates an undeployed function)")
        show(requests.post(fn_url(), headers=H, json=body, timeout=60), "probe")
    elif a.list_functions:
        show(requests.get(fn_url(), headers=H, timeout=30))
    elif a.export_function:
        r = requests.get(fn_url(a.export_function), headers=H, params={"export": "true"}, timeout=30)
        if not r.ok:
            return show(r)
        out = a.out or f"{a.export_function}.json"
        json.dump(r.json(), open(out, "w"), indent=2)
        print(f"saved {out}")
    elif a.create_function or a.update_function:
        path = a.create_function or a.update_function
        body = load_template(path, a.name, a.code, a.hec_url, a.workers)
        name = a.name or body.get("name") or body.get("functionName")
        if a.create_function:
            show(requests.post(fn_url(), headers=H, json=body, timeout=60), "create")
            verify_bindings(name, body)
        else:
            show(requests.put(fn_url(name), headers=H, json=body, timeout=60), "update")
            verify_bindings(name, body)
    else:
        for st in ("deploy", "undeploy", "pause", "resume"):
            fn = getattr(a, st)
            if fn:
                r = requests.put(f"{fn_url(fn)}/activationState", headers=H, json={"state": st}, timeout=60)
                return show(r, st)
        ap.print_help()


if __name__ == "__main__":
    main()
