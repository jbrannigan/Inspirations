import unittest
from pathlib import Path
from unittest import mock

from inspirations.cli import main


class TestCliServe(unittest.TestCase):
    def test_serve_dev_alias_uses_reload_server(self):
        with mock.patch("inspirations.devserver.run_with_reload") as run_with_reload, \
             mock.patch("inspirations.cli.run_server") as run_server:
            rc = main(
                [
                    "--db",
                    "/tmp/inspirations.sqlite",
                    "serve",
                    "--app",
                    "/tmp/app",
                    "--store",
                    "/tmp/store",
                    "--dev",
                ]
            )
        self.assertEqual(rc, 0)
        run_server.assert_not_called()
        run_with_reload.assert_called_once_with(
            host="127.0.0.1",
            port=8001,
            db_path=Path("/tmp/inspirations.sqlite").resolve(),
            app_dir=Path("/tmp/app").resolve(),
            store_dir=Path("/tmp/store").resolve(),
        )

    def test_serve_without_reload_uses_regular_server(self):
        with mock.patch("inspirations.devserver.run_with_reload") as run_with_reload, \
             mock.patch("inspirations.cli.run_server") as run_server:
            rc = main(
                [
                    "--db",
                    "/tmp/inspirations.sqlite",
                    "serve",
                    "--app",
                    "/tmp/app",
                    "--store",
                    "/tmp/store",
                ]
            )
        self.assertEqual(rc, 0)
        run_with_reload.assert_not_called()
        run_server.assert_called_once_with(
            host="127.0.0.1",
            port=8001,
            db_path=Path("/tmp/inspirations.sqlite").resolve(),
            app_dir=Path("/tmp/app").resolve(),
            store_dir=Path("/tmp/store").resolve(),
        )


if __name__ == "__main__":
    unittest.main()
