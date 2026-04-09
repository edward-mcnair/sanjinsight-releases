"""
tests/test_version.py

Tests for semver parsing, comparison, and update-check helpers.
"""

import unittest

from version import SemVer, parse_version, is_newer, INSTALLER_PATTERN


class TestSemVerParse(unittest.TestCase):
    """Test SemVer.parse() with various formats."""

    def test_ga_version(self):
        v = SemVer.parse("0.43.0")
        self.assertEqual(v.numeric_tuple, (0, 43, 0))
        self.assertFalse(v.is_prerelease)
        self.assertEqual(v.pre_type, "")

    def test_beta_dotted(self):
        v = SemVer.parse("0.43.0-beta.1")
        self.assertEqual(v.numeric_tuple, (0, 43, 0))
        self.assertTrue(v.is_prerelease)
        self.assertEqual(v.pre_type, "beta")
        self.assertEqual(v.pre_num, 1)

    def test_rc_dotted(self):
        v = SemVer.parse("0.43.0-rc.2")
        self.assertEqual(v.pre_type, "rc")
        self.assertEqual(v.pre_num, 2)

    def test_bare_beta(self):
        """Old-style 'beta' without number → pre_num=0."""
        v = SemVer.parse("1.50.47-beta")
        self.assertEqual(v.numeric_tuple, (1, 50, 47))
        self.assertEqual(v.pre_type, "beta")
        self.assertEqual(v.pre_num, 0)

    def test_v_prefix(self):
        v = SemVer.parse("v0.43.0-beta.1")
        self.assertEqual(v.numeric_tuple, (0, 43, 0))
        self.assertEqual(v.pre_type, "beta")

    def test_malformed(self):
        v = SemVer.parse("garbage")
        self.assertEqual(v.numeric_tuple, (0, 0, 0))

    def test_empty(self):
        v = SemVer.parse("")
        self.assertEqual(v.numeric_tuple, (0, 0, 0))


class TestSemVerComparison(unittest.TestCase):
    """Test the full ordering of SemVer instances."""

    def _v(self, s):
        return SemVer.parse(s)

    def test_beta1_lt_beta2(self):
        self.assertLess(self._v("0.43.0-beta.1"), self._v("0.43.0-beta.2"))

    def test_beta_lt_rc(self):
        self.assertLess(self._v("0.43.0-beta.3"), self._v("0.43.0-rc.1"))

    def test_rc_lt_ga(self):
        self.assertLess(self._v("0.43.0-rc.1"), self._v("0.43.0"))

    def test_ga_lt_next_beta(self):
        self.assertLess(self._v("0.43.0"), self._v("0.44.0-beta.1"))

    def test_numeric_progression(self):
        self.assertLess(self._v("0.43.0"), self._v("0.44.0"))
        self.assertLess(self._v("0.44.0"), self._v("1.0.0"))

    def test_equality(self):
        self.assertEqual(self._v("0.43.0-beta.1"), self._v("0.43.0-beta.1"))
        self.assertEqual(self._v("1.0.0"), self._v("1.0.0"))

    def test_bare_beta_lt_beta1(self):
        """Old-style bare 'beta' (pre_num=0) < beta.1."""
        self.assertLess(self._v("0.43.0-beta"), self._v("0.43.0-beta.1"))

    def test_full_ordering(self):
        """Verify a complete release progression sorts correctly."""
        versions = [
            "0.43.0-beta.1",
            "0.43.0-beta.2",
            "0.43.0-rc.1",
            "0.43.0-rc.2",
            "0.43.0",
            "0.44.0-beta.1",
            "0.44.0",
            "1.0.0-beta.1",
            "1.0.0",
        ]
        parsed = [self._v(v) for v in versions]
        # Verify each is strictly less than the next
        for i in range(len(parsed) - 1):
            self.assertLess(parsed[i], parsed[i + 1],
                            f"{versions[i]} should be < {versions[i + 1]}")

    def test_old_1x_lt_new_43(self):
        """Old 1.50.x versions sort above 0.43.x numerically."""
        # This is expected — the old numbering was higher.  The reset means
        # the old track is abandoned, not that 0.43 > 1.50.
        self.assertGreater(self._v("1.50.47-beta"), self._v("0.43.0-beta.1"))


class TestIsNewer(unittest.TestCase):
    """Test the is_newer() helper against CURRENT_VERSION."""

    def test_newer_beta(self):
        self.assertTrue(is_newer("0.43.0-beta.2"))

    def test_newer_rc(self):
        self.assertTrue(is_newer("0.43.0-rc.1"))

    def test_newer_ga(self):
        self.assertTrue(is_newer("0.43.0"))

    def test_same_version(self):
        self.assertFalse(is_newer("0.43.0-beta.1"))

    def test_older_version(self):
        self.assertFalse(is_newer("0.42.0"))


class TestParseVersion(unittest.TestCase):
    """Test the legacy parse_version() helper."""

    def test_simple(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_with_prerelease(self):
        self.assertEqual(parse_version("0.43.0-beta.1"), (0, 43, 0))

    def test_v_prefix(self):
        self.assertEqual(parse_version("v0.43.0"), (0, 43, 0))

    def test_garbage(self):
        self.assertEqual(parse_version("nope"), (0, 0, 0))


class TestInstallerPattern(unittest.TestCase):
    """Test the INSTALLER_PATTERN regex."""

    def test_beta(self):
        self.assertTrue(INSTALLER_PATTERN.match("SanjINSIGHT-Setup-0.43.0-beta.1.exe"))

    def test_rc(self):
        self.assertTrue(INSTALLER_PATTERN.match("SanjINSIGHT-Setup-0.43.0-rc.1.exe"))

    def test_ga(self):
        self.assertTrue(INSTALLER_PATTERN.match("SanjINSIGHT-Setup-0.43.0.exe"))

    def test_old_format(self):
        self.assertTrue(INSTALLER_PATTERN.match("SanjINSIGHT-Setup-1.50.47-beta.exe"))

    def test_non_matching(self):
        self.assertFalse(INSTALLER_PATTERN.match("random-file.exe"))
        self.assertFalse(INSTALLER_PATTERN.match("SanjINSIGHT-Setup.exe"))

    def test_case_insensitive(self):
        self.assertTrue(INSTALLER_PATTERN.match("sanjinsight-setup-0.43.0.exe"))


if __name__ == "__main__":
    unittest.main()
