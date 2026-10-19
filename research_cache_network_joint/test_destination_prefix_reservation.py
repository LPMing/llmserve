#!/usr/bin/env python3
"""Correctness checks for destination-prefix pin/reserve/commit semantics."""

from serving.core.block_pool import BlockPool, Device
from serving.core.kv_cache_manager import TieredKVCacheManager
from serving.core.request import Request


BLOCK_SIZE = 16
PREFIX_TOKENS = 4096
PREFIX = list(range(10000, 10000 + PREFIX_TOKENS))
LAYOUT = ("qwen3-test", "same-model-layout", 2, 1, 2, "auto",
          BLOCK_SIZE, 48, 4, 128)


def make_request(request_id, prompt, output=(), reached=None, computed=0):
    req = Request(
        request_id, "Qwen/Qwen3-30B-A3B-Instruct-2507", len(prompt),
        len(prompt) + len(output), 0, 0, list(prompt), list(output))
    if reached is not None:
        req.num_tokens_reached = reached
    req.num_computed_tokens = computed
    return req


def make_manager(num_blocks=300):
    pool = BlockPool(Device.NPU, num_blocks, BLOCK_SIZE, 1,
                     enable_caching=True)
    return TieredKVCacheManager(BLOCK_SIZE, pool, enable_caching=True)


def warm_prefix(manager):
    warmup = make_request(0, PREFIX, [900001])
    assert manager.allocate_slots(warmup, len(PREFIX)) is not None
    manager.cache_blocks(warmup, len(PREFIX))
    manager.free(warmup)


def test_reserve_and_commit():
    manager = make_manager()
    warm_prefix(manager)
    suffix = [50000 + i for i in range(9)]
    req = make_request(1, PREFIX + suffix, [70001, 70002, 70003],
                       reached=4105, computed=4105)

    reserved = manager.reserve_handoff_prefix(req, LAYOUT)
    assert reserved is not None
    assert reserved["hit_tokens"] == PREFIX_TOKENS
    assert reserved["required_blocks"] == 257
    assert len(manager.req_to_blocks[req.id]) == 257
    assert manager.has_handoff_reservation(req.id)
    prefix_blocks = manager.req_to_blocks[req.id][:256]
    assert all(block.ref_cnt == 1 for block in prefix_blocks)
    assert manager.req_to_blocks[req.id][-1].block_hash is None

    committed = manager.commit_handoff_reservation(req, LAYOUT)
    assert committed == reserved
    assert not manager.has_handoff_reservation(req.id)
    assert all(manager.npu_pool.get_cached_block(block.block_hash) is block
               for block in prefix_blocks)
    manager.free(req)
    assert manager.is_free()


def test_concurrent_hits_pin_shared_prefix():
    manager = make_manager()
    warm_prefix(manager)
    reqs = [
        make_request(i, PREFIX + [60000 + i], [80000 + i],
                     reached=4097, computed=4097)
        for i in (1, 2)
    ]
    for req in reqs:
        assert manager.reserve_handoff_prefix(req, LAYOUT) is not None
    shared = manager.req_to_blocks[1][:256]
    assert all(block.ref_cnt == 2 for block in shared)
    for req in reqs:
        manager.commit_handoff_reservation(req, LAYOUT)
    for req in reqs:
        manager.free(req)
    assert manager.is_free()


def test_partial_hit_indexes_only_received_full_blocks():
    manager = make_manager()
    warm_prefix(manager)
    # Use a second distinct prefix chain of 2,048 tokens so its cache hit is
    # partial with respect to the target's 4,105-token prompt.
    partial = [700000 + i for i in range(2048)]
    warm = make_request(10, partial, [910001])
    assert manager.allocate_slots(warm, len(partial)) is not None
    manager.cache_blocks(warm, len(partial))
    manager.free(warm)

    tail = [800000 + i for i in range(2057)]
    req = make_request(11, partial + tail, [920001, 920002, 920003],
                       reached=4105, computed=4105)
    reservation = manager.reserve_handoff_prefix(req, LAYOUT)
    assert reservation is not None
    assert reservation["hit_tokens"] == 2048
    assert len(manager.req_to_blocks[req.id]) == 257
    assert all(block.block_hash is None
               for block in manager.req_to_blocks[req.id][128:])

    manager.commit_handoff_reservation(req, LAYOUT)
    assert manager.num_cached_block[req.id] == 256
    hashes = req.block_hashes
    assert all(manager.npu_pool.get_cached_block(h) is not None
               for h in hashes[:256])
    manager.free(req)


def test_miss_and_capacity_failure_are_non_mutating():
    manager = make_manager(num_blocks=256)
    warm_prefix(manager)
    free_before = manager.npu_pool.get_num_free_blocks()
    miss = make_request(1, [x + 1_000_000 for x in PREFIX] + [42],
                        [43], reached=4097, computed=4097)
    assert manager.reserve_handoff_prefix(miss, LAYOUT) is None
    assert miss.id not in manager.req_to_blocks
    assert manager.npu_pool.get_num_free_blocks() == free_before

    hit = make_request(2, PREFIX + [44], [45], reached=4097, computed=4097)
    # The cached prefix occupies the whole undersized pool; a tail block is
    # required for the Decode slot, so the request must use full-transfer
    # fallback and leave the cache unpinned.
    assert manager.reserve_handoff_prefix(hit, LAYOUT) is None
    assert hit.id not in manager.req_to_blocks
    assert manager.npu_pool.get_num_free_blocks() == free_before
    assert all(block.ref_cnt == 0 for block in
               manager.npu_pool.cached_block_hash_to_block.values())


def test_query_hit_evicted_before_reserve_falls_back():
    manager = make_manager()
    warm_prefix(manager)
    req = make_request(3, PREFIX + [55], [56], reached=4097, computed=4097)

    blocks, hit_tokens, _ = manager.get_computed_blocks(req)
    assert hit_tokens == PREFIX_TOKENS
    # Simulate eviction in the QUERY -> RESERVE interval. Removing the head
    # invalidates the cumulative hash chain, so reservation must fall back to
    # an ordinary full handoff without pinning or allocating anything.
    assert manager.npu_pool._maybe_evict_cached_block(blocks[0])
    free_before = manager.npu_pool.get_num_free_blocks()
    assert manager.reserve_handoff_prefix(req, LAYOUT) is None
    assert req.id not in manager.req_to_blocks
    assert not manager.has_handoff_reservation(req.id)
    assert manager.npu_pool.get_num_free_blocks() == free_before


def main():
    test_reserve_and_commit()
    test_concurrent_hits_pin_shared_prefix()
    test_partial_hit_indexes_only_received_full_blocks()
    test_miss_and_capacity_failure_are_non_mutating()
    test_query_hit_evicted_before_reserve_falls_back()
    print("PASS: destination prefix reservation, commit, sharing, fallback, eviction")


if __name__ == "__main__":
    main()
