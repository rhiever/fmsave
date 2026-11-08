"""The shared rules updater preserves repository-specific instructions."""

import unittest

from scripts.sync_dev_standards import render


class TestSyncDevStandards(unittest.TestCase):
    def test_adds_rules_without_changing_existing_text(self):
        original = "# Repo\n\nLocal instructions.\n"
        self.assertEqual(
            render(original, "## Shared development\n"),
            original + "\n<!-- shared-dev-standards:start -->\n"
            "## Shared development\n<!-- shared-dev-standards:end -->\n",
        )

    def test_updates_only_the_managed_block(self):
        original = (
            "# Repo\n\n<!-- shared-dev-standards:start -->\n"
            "Old text.\n<!-- shared-dev-standards:end -->\n\nLocal instructions.\n"
        )
        expected = original.replace("Old text.", "New text.")
        self.assertEqual(render(original, "New text.\n"), expected)
        self.assertEqual(render(expected, "New text.\n"), expected)

    def test_preserves_crlf(self):
        original = "# Repo\r\n\r\nLocal instructions.\r\n"
        result = render(original, "New text.\n")
        self.assertTrue(result.startswith(original))
        self.assertNotIn("\n", result.replace("\r\n", ""))
        self.assertEqual(render(result, "New text.\n"), result)

    def test_rejects_broken_markers(self):
        with self.assertRaises(ValueError):
            render("# Repo\n<!-- shared-dev-standards:start -->\n", "New text.\n")

    def test_preserves_mixed_endings_outside_the_block(self):
        original = (
            "# Repo\r\n\r\n<!-- shared-dev-standards:start -->\n"
            "Old text.\n<!-- shared-dev-standards:end -->\n\r\nLocal instructions.\r\n"
        )
        self.assertEqual(render(original, "New text.\n"), original.replace("Old", "New"))

    def test_preserves_the_end_marker_at_eof(self):
        original = (
            "<!-- shared-dev-standards:start -->\nOld text.\n<!-- shared-dev-standards:end -->"
        )
        self.assertEqual(render(original, "New text.\n"), original.replace("Old", "New"))
