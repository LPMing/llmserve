#!/usr/bin/env python3
"""Regression for adopting destination prefix blocks at a P/D handoff."""

from serving.core.block_pool import BlockPool, Device
from serving.core.kv_cache_manager import TieredKVCacheManager
from serving.core.request import Request


BLOCK_SIZE = 16
PREFIX_TOKENS = 4096


def make_request(request_id, prompt_ids, output_ids=(), reached=None,
                 computed=0):
    prompt_ids = list(prompt_ids)
    output_ids = list(output_ids)
    req = Request(
        request_id,
        "Qwen/Qwen3-30B-A3B-Instruct-2507",
        len(prompt_ids),
        len(prompt_ids) + len(output_ids),
        0,
        0,
        prompt_ids,
        output_ids,
    )
    if reached is not None:
        req.num_tokens_reached = reached
    req.num_computed_tokens = computed
    return req


def main():
    pool = BlockPool(
        Device.NPU,
        num_blocks=2048,
        block_size=BLOCK_SIZE,
        bytes_per_block=1,
        enable_caching=True,
    )
    manager = TieredKVCacheManager(BLOCK_SIZE, pool, enable_caching=True)

    prefix = list(range(1000, 1000 + PREFIX_TOKENS))
    warmup = make_request(0, prefix, [130000])
    assert manager.allocate_slots(warmup, PREFIX_TOKENS) is not None
    manager.cache_blocks(warmup, PREFIX_TOKENS)
    manager.free(warmup)

    suffix = [140000 + i for i in range(9)]
    target_prompt = prefix + suffix
    output = [145000, 145001, 145002]
    target = make_request(
        1,
        target_prompt,
        output,
        reached=len(target_prompt) + 1,  # Prefill has emitted token one.
        computed=len(target_prompt),
    )

    hit_blocks, npu_hit, lower_hit = manager.get_computed_blocks(target)
    assert npu_hit == PREFIX_TOKENS, npu_hit
    assert lower_hit == 0, lower_hit
    free_before = pool.get_num_free_blocks()

    # The P2D receiver adopts the matching cached prefix and allocates just the
    # one block needed for the suffix/first decode output. The Prefill-computed
    # prompt count is already on the Request and must not be added to the hit.
    assert manager.allocate_slots(target, 1, hit_blocks, 0, 0) is not None
    assert len(manager.req_to_blocks[target.id]) == 257
    assert free_before - pool.get_num_free_blocks() == 257

    second = make_request(
        2,
        target_prompt,
        output,
        reached=len(target_prompt) + 1,
        computed=len(target_prompt),
    )
    hit_blocks2, npu_hit2, lower_hit2 = manager.get_computed_blocks(second)
    assert npu_hit2 == PREFIX_TOKENS
    assert lower_hit2 == 0
    free_before_second = pool.get_num_free_blocks()
    assert manager.allocate_slots(second, 1, hit_blocks2, 0, 0) is not None
    assert len(manager.req_to_blocks[second.id]) == 257
    # All 256 prefix blocks are already pinned by the first request; only the
    # distinct suffix/output tail block consumes additional free capacity.
    assert free_before_second - pool.get_num_free_blocks() == 1
    assert all(block.ref_cnt == 2 for block in hit_blocks2)

    manager.free(target)
    manager.free(second)
    print("PASS: Decode handoff adopts resident prefix without double allocation")


if __name__ == "__main__":
    main()
