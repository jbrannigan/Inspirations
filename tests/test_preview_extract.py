import unittest
from unittest import mock

from inspirations.storage import _extract_preview_image, _youtube_thumb_url, resolve_image_url


class _FakeResponse:
    def __init__(self, content_type: str, body: str | bytes):
        self.headers = {"Content-Type": content_type}
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self._cursor = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self._body) - self._cursor
        out = self._body[self._cursor : self._cursor + n]
        self._cursor += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestPreviewExtract(unittest.TestCase):
    def test_extract_og_image(self):
        html = """
        <html><head>
        <meta property="og:image" content="https://example.com/a.jpg" />
        </head></html>
        """
        self.assertEqual(_extract_preview_image(html), "https://example.com/a.jpg")

    def test_extract_twitter_image(self):
        html = """
        <html><head>
        <meta name="twitter:image" content="https://example.com/b.png" />
        </head></html>
        """
        self.assertEqual(_extract_preview_image(html), "https://example.com/b.png")

    def test_extract_meta_image_with_reversed_attribute_order(self):
        html = """
        <html><head>
        <meta content="https://example.com/c.webp" property="og:image" />
        </head></html>
        """
        self.assertEqual(_extract_preview_image(html), "https://example.com/c.webp")

    def test_extract_falls_back_to_first_img_src(self):
        html = """
        <html><body>
        <img src="/assets/hero.png" />
        <img src="/assets/secondary.png" />
        </body></html>
        """
        self.assertEqual(_extract_preview_image(html), "/assets/hero.png")

    def test_youtube_thumb(self):
        url = "https://www.youtube.com/watch?v=Ipm3nwuABmQ"
        self.assertEqual(_youtube_thumb_url(url), "https://img.youtube.com/vi/Ipm3nwuABmQ/hqdefault.jpg")

    @mock.patch("inspirations.storage.is_safe_public_url")
    @mock.patch("inspirations.storage.urllib.request.urlopen")
    def test_resolve_image_url_upgrades_http_preview_to_https(self, mock_urlopen, mock_is_safe):
        html = '<meta property="og:image" content="http://cdn.example.com/hero.jpg" />'
        mock_urlopen.return_value = _FakeResponse("text/html; charset=utf-8", html)
        mock_is_safe.side_effect = lambda u, allow_http=False: u in (
            "https://site.example/page",
            "https://cdn.example.com/hero.jpg",
        )
        self.assertEqual(resolve_image_url("https://site.example/page"), "https://cdn.example.com/hero.jpg")

    @mock.patch("inspirations.storage.is_safe_public_url", return_value=True)
    @mock.patch("inspirations.storage.urllib.request.urlopen")
    def test_resolve_image_url_skips_tracking_pixel_candidates(self, mock_urlopen, _mock_is_safe):
        html = '<meta property="og:image" content="https://ct.pinterest.com/v3/?event=init&tid=1" />'
        mock_urlopen.return_value = _FakeResponse("text/html; charset=utf-8", html)
        self.assertIsNone(resolve_image_url("https://site.example/page"))

    @mock.patch("inspirations.storage.is_safe_public_url", return_value=True)
    @mock.patch("inspirations.storage.urllib.request.urlopen")
    def test_resolve_image_url_uses_img_fallback(self, mock_urlopen, _mock_is_safe):
        html = '<html><body><img src="/assets/hero.png" /></body></html>'
        mock_urlopen.return_value = _FakeResponse("text/html; charset=utf-8", html)
        self.assertEqual(resolve_image_url("https://site.example/page"), "https://site.example/assets/hero.png")


if __name__ == "__main__":
    unittest.main()
