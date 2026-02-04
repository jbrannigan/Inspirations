import tempfile
import unittest
from pathlib import Path

from inspirations.ai import run_ai_labeler
from inspirations.db import Db, ensure_schema


class TestAIMock(unittest.TestCase):
    def test_mock_labels_inserted(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("a1", "pinterest", "pin://1", "White oak cabinets with brass hardware"),
                )
                run_ai_labeler(db, provider="mock")
                n = db.query_value("select count(*) from asset_labels where asset_id='a1'")
            self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()

