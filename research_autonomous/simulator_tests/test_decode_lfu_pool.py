"""LFU comparator keeps a previously reused prefix under normal capacity."""

import unittest

from serving.core.block_pool import BlockPool, Device


class DecodeLfuPoolTest(unittest.TestCase):
    def test_reused_hash_survives_before_single_use_hash(self):
        pool = BlockPool(Device.NPU, 3, 16, 4096, enable_caching=True)
        pool.eviction_policy = "LFU"
        blocks = pool.get_new_blocks(3)
        pool.cache_full_blocks([11, 22, 33], blocks, 0, 3)
        pool.free_blocks(reversed(blocks))
        reused = pool.get_cached_block(11)
        pool.touch([reused])
        pool.free_blocks([reused])
        self.assertEqual(reused.access_count, 2)
        pool.get_new_blocks(1)
        self.assertIs(pool.get_cached_block(11), reused)
        self.assertEqual(pool.get_num_free_blocks(), 2)

    def test_empty_blocks_are_used_before_cached_blocks(self):
        pool = BlockPool(Device.NPU, 3, 16, 4096, enable_caching=True)
        pool.eviction_policy = "LFU"
        block = pool.get_new_blocks(1)[0]
        pool.cache_full_blocks([44], [block], 0, 1)
        pool.free_blocks([block])
        chosen = pool.get_new_blocks(1)[0]
        self.assertIsNot(chosen, block)
        self.assertIs(pool.get_cached_block(44), block)


if __name__ == "__main__":
    unittest.main()
