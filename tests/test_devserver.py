import unittest
from pathlib import Path
from unittest import mock

from inspirations import devserver


class TestDevServer(unittest.TestCase):
    def test_start_child_execs_fresh_python_process(self):
        with mock.patch("inspirations.devserver.os.fork", return_value=0), \
             mock.patch("inspirations.devserver.os.execvpe", side_effect=RuntimeError("exec called")) as execvpe:
            with self.assertRaisesRegex(RuntimeError, "exec called"):
                devserver._start_child(
                    host="0.0.0.0",
                    port=8001,
                    db_path=Path("/tmp/inspirations.sqlite"),
                    app_dir=Path("/tmp/app"),
                    store_dir=Path("/tmp/store"),
                )

        args = execvpe.call_args.args
        self.assertEqual(args[0], devserver.sys.executable)
        self.assertEqual(
            args[1],
            [
                devserver.sys.executable,
                "-m",
                "inspirations",
                "--db",
                "/tmp/inspirations.sqlite",
                "--store",
                "/tmp/store",
                "serve",
                "--host",
                "0.0.0.0",
                "--port",
                "8001",
                "--app",
                "/tmp/app",
            ],
        )

    def test_child_exited_false_when_still_running(self):
        with mock.patch("inspirations.devserver.os.waitpid", return_value=(0, 0)):
            self.assertFalse(devserver._child_exited(123))

    def test_child_exited_true_when_reaped(self):
        with mock.patch("inspirations.devserver.os.waitpid", return_value=(123, 0)):
            self.assertTrue(devserver._child_exited(123))

    def test_run_with_reload_restarts_when_child_exits(self):
        with mock.patch("inspirations.devserver.Path.cwd", return_value=Path("/tmp")), \
             mock.patch("inspirations.devserver._scan", side_effect=[{"a": 1.0}, {"a": 1.0}]), \
             mock.patch("inspirations.devserver._child_exited", side_effect=[True]), \
             mock.patch("inspirations.devserver._changed", return_value=False), \
             mock.patch("inspirations.devserver._start_child", side_effect=[111, 222]) as start_child, \
             mock.patch("inspirations.devserver._stop_child") as stop_child, \
             mock.patch("inspirations.devserver.time.sleep", side_effect=[None, None, KeyboardInterrupt]):
            devserver.run_with_reload(
                host="127.0.0.1",
                port=8001,
                db_path=Path("/tmp/inspirations.sqlite"),
                app_dir=Path("/tmp/app"),
                store_dir=Path("/tmp/store"),
            )

        self.assertEqual(start_child.call_count, 2)
        stop_child.assert_called_once_with(222)

    def test_run_with_reload_still_restarts_on_file_change(self):
        with mock.patch("inspirations.devserver.Path.cwd", return_value=Path("/tmp")), \
             mock.patch("inspirations.devserver._scan", side_effect=[{"a": 1.0}, {"a": 2.0}]), \
             mock.patch("inspirations.devserver._child_exited", side_effect=[False]), \
             mock.patch("inspirations.devserver._changed", side_effect=[True]), \
             mock.patch("inspirations.devserver._start_child", side_effect=[111, 222]) as start_child, \
             mock.patch("inspirations.devserver._stop_child") as stop_child, \
             mock.patch("inspirations.devserver.time.sleep", side_effect=[None, None, KeyboardInterrupt]):
            devserver.run_with_reload(
                host="127.0.0.1",
                port=8001,
                db_path=Path("/tmp/inspirations.sqlite"),
                app_dir=Path("/tmp/app"),
                store_dir=Path("/tmp/store"),
            )

        self.assertEqual(start_child.call_count, 2)
        self.assertEqual(stop_child.call_args_list[0].args, (111,))
        self.assertEqual(stop_child.call_args_list[1].args, (222,))


if __name__ == "__main__":
    unittest.main()
