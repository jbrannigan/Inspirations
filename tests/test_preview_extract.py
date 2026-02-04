import unittest

from inspirations.storage import _extract_preview_image


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


if __name__ == "__main__":
    unittest.main()

