#!/usr/bin/env python3
"""Regression tests for model-derived P2D bytes after prefix-cache hits."""

from serving.core.request import Request
from serving.core.scheduler import Scheduler


class _KVStub:
    def take_traffic(self):
        return 0, 0

    def npu_used_bytes(self):
        return 0


class _LoggerStub:
    def info(self, *_args, **_kwargs):
        pass


def build_batch(*, hit_tokens, computed_before, new_tokens):
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.pd_type = "prefill"
    scheduler.batch_ids = -1
    scheduler.model = "Qwen/Qwen3-30B-A3B-Instruct-2507"
    scheduler.kv = _KVStub()
    scheduler.inflight = []
    scheduler.running = []
    scheduler.max_num_seqs = 128
    scheduler.max_num_batched_tokens = 2048
    scheduler.node_id = 0
    scheduler.instance_id = 0
    scheduler.research_event_path = None
    scheduler.logger = _LoggerStub()
    scheduler._record_research_event = lambda *_args, **_kwargs: None

    request = Request(
        1, scheduler.model, 4105, 4108, 0, 0,
        input_hash_ids=list(range(4105)), output_hash_ids=[],
    )
    request.prefix_cache_hit = hit_tokens
    batch = scheduler._build_batch(
        0, 0, [(request, new_tokens, computed_before)])
    return batch


def main():
    # A 4096-token cache hit plus nine newly computed prompt tokens must ship
    # the complete 4105-token KV to Decode on the first Prefill batch.
    hit = build_batch(hit_tokens=4096, computed_before=4096, new_tokens=9)
    assert hit.pd_kv_send_tokens == 4105, hit.pd_kv_send_tokens

    # A later chunk must not resend the already-accounted cached prefix.
    later = build_batch(hit_tokens=4096, computed_before=4105, new_tokens=3)
    assert later.pd_kv_send_tokens == 3, later.pd_kv_send_tokens

    # A miss sends only the tokens actually computed in its first chunk.
    miss = build_batch(hit_tokens=0, computed_before=0, new_tokens=2048)
    assert miss.pd_kv_send_tokens == 2048, miss.pd_kv_send_tokens

    # Qwen3 BF16, TP2: total KV bytes/token over all 48 layers is 98,304;
    # each Prefill rank sends half. The cache-hit request still sends its full
    # 4105-token KV exactly once.
    bytes_per_token_per_rank = 98_304 // 2
    assert hit.pd_kv_send_tokens * bytes_per_token_per_rank == 201_768_960

    print("PASS: cache-hit P2D token/byte accounting is conserved")


if __name__ == "__main__":
    main()
