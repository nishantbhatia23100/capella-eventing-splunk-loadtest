#!/bin/bash
# wrapper: load env (mock tests never see the real Splunk token), then run one scenario.  Usage: TAG=.. PROFILE=.. SHIPPERS=.. MOCKS=.. ./fv_run.sh
cd "$(dirname "$0")"
. ~/.loadtest-env; . ./ids.env; . tunnels/urls_fv.env; unset HEC_TOKEN
exec bash run_scenario.sh
