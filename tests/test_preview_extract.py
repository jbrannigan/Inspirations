import unittest

from inspirations.storage import _extract_preview_image, _youtube_thumb_url


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

    def test_youtube_thumb(self):
        url = "https://www.youtube.com/watch?v=Ipm3nwuABmQ"
        self.assertEqual(_youtube_thumb_url(url), "https://img.youtube.com/vi/Ipm3nwuABmQ/hqdefault.jpg")


if __name__ == "__main__":
    unittest.main()
