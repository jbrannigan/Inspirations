import unittest
from unittest import mock

from inspirations import security


class TestSecurity(unittest.TestCase):
    def test_blocks_non_http(self):
        self.assertFalse(security.is_safe_public_url("file:///etc/passwd"))
        self.assertFalse(security.is_safe_public_url("ftp://example.com/x"))

    def test_blocks_http_by_default(self):
        with mock.patch.object(security, "resolve_host", return_value=["93.184.216.34"]):
            self.assertFalse(security.is_safe_public_url("http://example.com/x"))

    def test_blocks_private_ips(self):
        self.assertFalse(security.is_safe_public_url("https://127.0.0.1/x"))
        self.assertFalse(security.is_safe_public_url("https://10.0.0.1/x"))

    def test_allows_public_https_with_mocked_dns(self):
        with mock.patch.object(security, "resolve_host", return_value=["93.184.216.34"]):
            self.assertTrue(security.is_safe_public_url("https://example.com/x"))


if __name__ == "__main__":
    unittest.main()

