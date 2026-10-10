# P4 corrected remote-KV integrated validation

Generated from retained FlowSim event ledgers and request CSVs. All times are ns unless stated.

## Network accounting

|window|policy|P2D GiB|remote fetch GiB|replication GiB|EP CCT mean ms|EP CCT P99 ms|mixed links|max fluid queue GiB|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|highreuse|NO_REMOTE|2.2695|0.0000|0.0000|0.0037|0.0053|12|0.0235|
|highreuse|balanced_replica_oracle|2.2695|0.8438|0.5625|0.0036|0.0050|14|0.2986|
|highreuse|first_producer|2.2695|1.1250|0.0000|0.0036|0.0050|13|1.1424|
|highreuse|least_loaded_existing_holder|2.2695|1.1250|0.0000|0.0036|0.0050|13|1.1424|
|staggered|balanced_replica_oracle|2.2921|0.8438|0.5625|0.0036|0.0050|13|0.5682|
|staggered|first_producer|2.2921|1.1250|0.0000|0.0036|0.0050|13|0.5682|
|staggered|least_loaded_existing_holder|2.2921|1.1250|0.0000|0.0036|0.0050|13|0.5682|

## Serving critical path (request-relative handoff FCT)

|window|policy|TTFT P99 ms|TTFT mean ms|KV handoff FCT P99 ms|TBT max P99 ms|TPOT P99 ms|
|---|---|---:|---:|---:|---:|---:|
|highreuse|NO_REMOTE|214.1766|211.1495|203.2840|10.8926|3.6859|
|highreuse|balanced_replica_oracle|274.9388|194.6411|268.9003|6.0385|3.6857|
|highreuse|first_producer|238.6985|180.8552|232.6600|6.0385|3.6857|
|highreuse|least_loaded_existing_holder|238.6985|180.8552|232.6600|6.0385|3.6857|
|staggered|balanced_replica_oracle|130.1828|93.9071|124.7750|21.7942|9.0194|
|staggered|first_producer|129.9202|94.4528|124.5138|36.3452|13.9172|
|staggered|least_loaded_existing_holder|129.9202|94.4528|124.5138|36.3452|13.9172|

## Interpretation rules

- `kv_handoff_fct_ns = p2d_kv_ready_ns - arrival_ns`; it is the request-level last-required-KV barrier, not a sum of per-flow FCTs.
- P2D event rows may aggregate multiple requests in one scheduler batch. The request CSV is authoritative for each request’s serving barrier; ledger timestamps are retained as provenance.
- FlowSim queue values are analytical residual fluid backlog, not packet switch occupancy and not ECN/PFC/drop measurements.
- The existing-holder policy has no replica-creation traffic and therefore equals FIRST_PRODUCER on these windows; this is an expected negative control, not a failed implementation.
