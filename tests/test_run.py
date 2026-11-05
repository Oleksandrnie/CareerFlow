from __future__ import annotations

import unittest

from run import _browser_host


class BrowserHostTest(unittest.TestCase):
    def test_wildcard_addresses_open_browser_on_loopback(self) -> None:
        self.assertEqual(_browser_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(_browser_host("::"), "127.0.0.1")
        self.assertEqual(_browser_host("[::]"), "127.0.0.1")

    def test_specific_addresses_and_hostnames_are_preserved(self) -> None:
        self.assertEqual(_browser_host("127.0.0.2"), "127.0.0.2")
        self.assertEqual(_browser_host("[::1]"), "[::1]")
        self.assertEqual(_browser_host("localhost"), "localhost")


if __name__ == "__main__":
    unittest.main()
