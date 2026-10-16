import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


SOURCE = os.environ.get('ALX_SOURCE')
COMPILER = shutil.which('cc')
HARNESS = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint16_t u16;
#define ALX_DEFAULT_TX_WORK 128
#define unlikely(value) (value)
#define netdev_err(...) ((void)0)
struct sk_buff { unsigned int len; };
struct alx_buffer { struct sk_buff *skb; };
struct netdev_queue { int unused; };
struct alx_priv { int hw; void *dev; };
struct alx_tx_queue {
    void *netdev;
    u16 read_idx, write_idx, count;
    unsigned int c_reg;
    struct alx_buffer bufs[256];
};
static struct alx_priv adapter;
static struct netdev_queue queue;
static u16 hardware_index;
static unsigned int resets, freed, packets, bytes;
static struct alx_priv *netdev_priv(void *dev) { return &adapter; }
static struct netdev_queue *alx_get_tx_queue(struct alx_tx_queue *q) { return &queue; }
static u16 alx_read_mem16(int *hw, unsigned int reg) { return hardware_index; }
static int net_ratelimit(void) { return 1; }
static void alx_schedule_reset(struct alx_priv *alx) { resets++; }
static void alx_free_txbuf(struct alx_tx_queue *q, int i) { freed++; q->bufs[i].skb = NULL; }
static void netdev_tx_completed_queue(struct netdev_queue *q, unsigned int p, unsigned int b) { packets += p; bytes += b; }
static bool netif_tx_queue_stopped(struct netdev_queue *q) { return false; }
static bool netif_carrier_ok(void *dev) { return true; }
static int alx_tpd_avail(struct alx_tx_queue *q) { return 255; }
static void netif_tx_wake_queue(struct netdev_queue *q) { }
'''
MAIN = r'''
int main(int argc, char **argv) {
    struct alx_tx_queue q = { .count = 256 };
    struct sk_buff skb = { .len = 100 };
    hardware_index = (u16)strtoul(argv[1], NULL, 10);
    q.read_idx = (u16)strtoul(argv[2], NULL, 10);
    unsigned int occupied = strtoul(argv[3], NULL, 10);
    for (unsigned int i = 0; i < occupied; i++)
        q.bufs[(q.read_idx + i) % q.count].skb = &skb;
    bool complete = alx_clean_tx_irq(&q);
    printf("%u %u %u %u %u %u\n", complete, resets, freed, q.read_idx, packets, bytes);
    return 0;
}
'''


@unittest.skipUnless(SOURCE and COMPILER, 'ALX_SOURCE and a C compiler are required')
class AlxTxGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(SOURCE).read_text()
        match = re.search(r'static bool alx_clean_tx_irq\(struct alx_tx_queue \*txq\)\s*\{', source)
        if match is None:
            raise AssertionError('alx_clean_tx_irq definition not found')
        depth = 1
        end = match.end()
        while depth and end < len(source):
            depth += (source[end] == '{') - (source[end] == '}')
            end += 1
        if depth:
            raise AssertionError('unterminated alx_clean_tx_irq definition')
        function = source[match.start():end]
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        c_file = directory / 'guard.c'
        c_file.write_text(HARNESS + function + MAIN)
        cls.binary = directory / 'guard'
        subprocess.run([COMPILER, '-O0', '-std=c11', str(c_file), '-o', str(cls.binary)],
                       check=True, capture_output=True, text=True, timeout=30)

    def run_cleanup(self, hardware_index, software_index, occupied):
        result = subprocess.run([str(self.binary), str(hardware_index), str(software_index), str(occupied)],
                                check=True, capture_output=True, text=True, timeout=1)
        return tuple(map(int, result.stdout.split()))

    def test_invalid_indices_schedule_reset_without_consuming_descriptors(self):
        for hardware_index in [256, 65535]:
            with self.subTest(hardware_index=hardware_index):
                self.assertEqual(self.run_cleanup(hardware_index, 0, 3), (1, 1, 0, 0, 0, 0))

    def test_last_valid_index_completes(self):
        self.assertEqual(self.run_cleanup(255, 250, 5), (1, 0, 5, 255, 5, 500))

    def test_ring_wrap_preserves_completion_accounting(self):
        self.assertEqual(self.run_cleanup(2, 254, 4), (1, 0, 4, 2, 4, 400))

    def test_empty_ring_does_no_work(self):
        self.assertEqual(self.run_cleanup(0, 0, 0), (1, 0, 0, 0, 0, 0))

    def test_budget_preserves_pending_work(self):
        self.assertEqual(self.run_cleanup(200, 0, 200), (0, 0, 128, 128, 128, 12800))


if __name__ == '__main__':
    unittest.main()
