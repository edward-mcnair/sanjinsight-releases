"""
tests/test_port_resolver.py

Unit / integration tests for the USB-fingerprint port resolver.

These tests use synthetic PortInfo and USBFingerprint objects — no
hardware needed.  They exercise:
  - Scoring logic (_score)
  - Single-device resolution (_resolve_one)
  - Batch resolution with duplicate/ambiguity detection (resolve_all)
  - Port ownership claim/release/watchdog
  - AmbiguousPortError on duplicate port claims
"""

from __future__ import annotations

import time
import unittest

# The module under test
from hardware.port_resolver import (
    _score,
    AmbiguousPortError,
    HandshakeMismatchError,
    USBFingerprint,
    PortInfo,
    ResolveResult,
    PortResolver,
    _PortOwnership,
)


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers — build synthetic data
# ──────────────────────────────────────────────────────────────────────────────

def _fp(*, sn="", vid=None, pid=None, loc="", mfr="", prod=""):
    return USBFingerprint(
        vid=vid, pid=pid, serial_number=sn,
        location=loc, manufacturer=mfr, product=prod,
    )

def _port_info(device, *, sn="", vid=None, pid=None, loc="", mfr="", prod=""):
    return PortInfo(
        device=device,
        fingerprint=_fp(sn=sn, vid=vid, pid=pid, loc=loc, mfr=mfr, prod=prod),
    )


# ──────────────────────────────────────────────────────────────────────────────
#  _score() tests
# ──────────────────────────────────────────────────────────────────────────────

class TestScore(unittest.TestCase):
    """Verify the fingerprint scoring function."""

    def test_exact_serial_match(self):
        """Serial number match → 100 + VID/PID bonus."""
        port_fp = _fp(sn="ABC123", vid=0x0403, pid=0x6001)
        saved   = _fp(sn="ABC123", vid=0x0403, pid=0x6001)
        self.assertEqual(_score(port_fp, saved), 100 + 20 + 20)

    def test_serial_mismatch_hard_reject(self):
        """Different serial numbers → hard reject (-1)."""
        port_fp = _fp(sn="ABC123", vid=0x0403, pid=0x6001)
        saved   = _fp(sn="XYZ999", vid=0x0403, pid=0x6001)
        self.assertEqual(_score(port_fp, saved), -1)

    def test_serial_missing_on_port_hard_reject(self):
        """Saved has serial but port doesn't → hard reject."""
        port_fp = _fp(sn="", vid=0x0403, pid=0x6001)
        saved   = _fp(sn="ABC123", vid=0x0403, pid=0x6001)
        self.assertEqual(_score(port_fp, saved), -1)

    def test_vid_pid_only(self):
        """VID:PID match with no serial → 40 points."""
        port_fp = _fp(vid=0x0403, pid=0x6001)
        saved   = _fp(vid=0x0403, pid=0x6001)
        self.assertEqual(_score(port_fp, saved), 40)

    def test_vid_mismatch(self):
        """Wrong VID → hard reject."""
        port_fp = _fp(vid=0x1234, pid=0x6001)
        saved   = _fp(vid=0x0403, pid=0x6001)
        self.assertEqual(_score(port_fp, saved), -1)

    def test_pid_mismatch(self):
        """Wrong PID → hard reject."""
        port_fp = _fp(vid=0x0403, pid=0x9999)
        saved   = _fp(vid=0x0403, pid=0x6001)
        self.assertEqual(_score(port_fp, saved), -1)

    def test_location_bonus(self):
        """Matching location adds 10 points."""
        port_fp = _fp(vid=0x0403, pid=0x6001, loc="1-3.2")
        saved   = _fp(vid=0x0403, pid=0x6001, loc="1-3.2")
        self.assertEqual(_score(port_fp, saved), 40 + 10)

    def test_location_different(self):
        """Different location → no bonus (not a reject)."""
        port_fp = _fp(vid=0x0403, pid=0x6001, loc="1-3.2")
        saved   = _fp(vid=0x0403, pid=0x6001, loc="1-4.1")
        self.assertEqual(_score(port_fp, saved), 40)

    def test_manufacturer_bonus(self):
        """Matching manufacturer substring adds 5 points."""
        port_fp = _fp(vid=0x0403, pid=0x6001, mfr="FTDI")
        saved   = _fp(vid=0x0403, pid=0x6001, mfr="FTDI")
        self.assertEqual(_score(port_fp, saved), 40 + 5)

    def test_product_bonus(self):
        """Matching product substring adds 5 points."""
        port_fp = _fp(vid=0x0403, pid=0x6001, prod="FT232R")
        saved   = _fp(vid=0x0403, pid=0x6001, prod="FT232R")
        self.assertEqual(_score(port_fp, saved), 40 + 5)

    def test_full_match_all_fields(self):
        """All fields matching → maximum score."""
        fp = _fp(sn="ABC", vid=0x0403, pid=0x6001, loc="1-2", mfr="FTDI", prod="FT232R")
        # 100 (sn) + 20 (vid) + 20 (pid) + 10 (loc) + 5 (mfr) + 5 (prod)
        self.assertEqual(_score(fp, fp), 160)

    def test_empty_saved_fingerprint(self):
        """Saved fingerprint with no fields → score 0 (matches anything)."""
        port_fp = _fp(sn="ABC", vid=0x0403, pid=0x6001)
        saved   = _fp()
        self.assertEqual(_score(port_fp, saved), 0)

    def test_case_insensitive_serial(self):
        """Serial number comparison is case-insensitive."""
        port_fp = _fp(sn="abc123")
        saved   = _fp(sn="ABC123")
        self.assertEqual(_score(port_fp, saved), 100)


# ──────────────────────────────────────────────────────────────────────────────
#  PortResolver tests
# ──────────────────────────────────────────────────────────────────────────────

class TestPortResolver(unittest.TestCase):
    """Test single and batch resolution with synthetic port snapshots."""

    def _make_resolver(self, ports: list[PortInfo]) -> PortResolver:
        r = PortResolver()
        r._ports = ports  # inject synthetic snapshot
        return r

    # ── Single-device resolution ──────────────────────────────────────

    def test_resolve_by_serial_number(self):
        """Device with matching serial resolves correctly."""
        ports = [
            _port_info("COM3", sn="TEC_001", vid=0x0403, pid=0x6001),
            _port_info("COM4", sn="LDD_001", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        saved_fp = _fp(sn="LDD_001", vid=0x0403, pid=0x6001)
        rr = resolver._resolve_one("ldd", saved_fp, "COM5", claimed=set())
        self.assertEqual(rr.port, "COM4")
        self.assertEqual(rr.method, "fingerprint")
        self.assertGreaterEqual(rr.score, 100)

    def test_resolve_port_moved(self):
        """Device moves to new COM port — resolved by fingerprint."""
        ports = [
            _port_info("COM7", sn="TEC_001", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        saved_fp = _fp(sn="TEC_001", vid=0x0403, pid=0x6001)
        rr = resolver._resolve_one("tec", saved_fp, "COM3", claimed=set())
        self.assertEqual(rr.port, "COM7")
        self.assertEqual(rr.method, "fingerprint")

    def test_resolve_device_missing_no_hint(self):
        """Device not present and no COM hint → port=None."""
        ports = [
            _port_info("COM3", sn="OTHER", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        saved_fp = _fp(sn="GONE", vid=0x0403, pid=0x6001)
        rr = resolver._resolve_one("tec", saved_fp, "", claimed=set())
        self.assertIsNone(rr.port)

    def test_resolve_serial_mismatch_com_hint_fallback(self):
        """Different serial but saved COM hint → falls back to com_hint."""
        ports = [
            _port_info("COM3", sn="OTHER", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        saved_fp = _fp(sn="GONE", vid=0x0403, pid=0x6001)
        rr = resolver._resolve_one("tec", saved_fp, "COM3", claimed=set())
        # Fingerprint rejects (serial mismatch) but COM hint matches
        self.assertEqual(rr.port, "COM3")
        self.assertEqual(rr.method, "com_hint")

    def test_resolve_com_hint_fallback(self):
        """No fingerprint saved → fall back to COM port hint."""
        ports = [_port_info("COM3", vid=0x0403, pid=0x6001)]
        resolver = self._make_resolver(ports)
        rr = resolver._resolve_one("tec", None, "COM3", claimed=set())
        self.assertEqual(rr.port, "COM3")
        self.assertEqual(rr.method, "com_hint")

    def test_resolve_com_hint_port_gone(self):
        """COM hint port not in enumeration → not found."""
        ports = [_port_info("COM5", vid=0x0403, pid=0x6001)]
        resolver = self._make_resolver(ports)
        rr = resolver._resolve_one("tec", None, "COM3", claimed=set())
        self.assertIsNone(rr.port)

    def test_resolve_skips_claimed_ports(self):
        """Claimed ports are not available for resolution."""
        ports = [
            _port_info("COM3", sn="TEC_001", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        saved_fp = _fp(sn="TEC_001", vid=0x0403, pid=0x6001)
        rr = resolver._resolve_one("tec", saved_fp, "", claimed={"COM3"})
        self.assertIsNone(rr.port)

    def test_resolve_ambiguous_low_confidence_skipped(self):
        """Two ports with same low-confidence score → skipped (no guess)."""
        ports = [
            _port_info("COM3", vid=0x0403, pid=0x6001, loc="1-2"),
            _port_info("COM4", vid=0x0403, pid=0x6001, loc="1-3"),
        ]
        resolver = self._make_resolver(ports)
        # Saved fingerprint matches VID:PID on both but no serial → score 40 each
        saved_fp = _fp(vid=0x0403, pid=0x6001)
        rr = resolver._resolve_one("tec", saved_fp, "", claimed=set())
        self.assertIsNone(rr.port)  # should refuse to guess

    def test_resolve_tiebreaker_by_serial(self):
        """Serial number breaks the tie between two VID:PID matches."""
        ports = [
            _port_info("COM3", sn="TEC_001", vid=0x0403, pid=0x6001),
            _port_info("COM4", sn="LDD_001", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        saved_fp = _fp(sn="TEC_001", vid=0x0403, pid=0x6001)
        rr = resolver._resolve_one("tec", saved_fp, "", claimed=set())
        self.assertEqual(rr.port, "COM3")
        self.assertGreaterEqual(rr.score, 100)

    # ── Batch resolution ─────────────────────────────────────────────

    def test_resolve_all_two_devices(self):
        """Two devices with different serials resolve correctly."""
        ports = [
            _port_info("COM3", sn="TEC_001", vid=0x0403, pid=0x6001),
            _port_info("COM4", sn="LDD_001", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        device_map = {
            "tec": (_fp(sn="TEC_001", vid=0x0403, pid=0x6001), "COM3"),
            "ldd": (_fp(sn="LDD_001", vid=0x0403, pid=0x6001), "COM4"),
        }
        results = resolver.resolve_all(device_map)
        self.assertEqual(results["tec"].port, "COM3")
        self.assertEqual(results["ldd"].port, "COM4")

    def test_resolve_all_swapped_ports(self):
        """Devices swap COM ports — resolved by fingerprint."""
        ports = [
            _port_info("COM4", sn="TEC_001", vid=0x0403, pid=0x6001),
            _port_info("COM3", sn="LDD_001", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        device_map = {
            "tec": (_fp(sn="TEC_001", vid=0x0403, pid=0x6001), "COM3"),
            "ldd": (_fp(sn="LDD_001", vid=0x0403, pid=0x6001), "COM4"),
        }
        results = resolver.resolve_all(device_map)
        self.assertEqual(results["tec"].port, "COM4")  # moved
        self.assertEqual(results["ldd"].port, "COM3")  # moved

    def test_resolve_all_one_missing(self):
        """One device unplugged → port=None, other still resolves."""
        ports = [
            _port_info("COM3", sn="TEC_001", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        device_map = {
            "tec": (_fp(sn="TEC_001", vid=0x0403, pid=0x6001), "COM3"),
            "ldd": (_fp(sn="LDD_001", vid=0x0403, pid=0x6001), "COM4"),
        }
        results = resolver.resolve_all(device_map)
        self.assertEqual(results["tec"].port, "COM3")
        self.assertIsNone(results["ldd"].port)

    def test_resolve_all_stale_fingerprint_no_hint(self):
        """Replaced device (different serial), no COM hint → not found."""
        ports = [
            _port_info("COM3", sn="NEW_SERIAL", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        device_map = {
            "tec": (_fp(sn="OLD_SERIAL", vid=0x0403, pid=0x6001), ""),
        }
        results = resolver.resolve_all(device_map)
        self.assertIsNone(results["tec"].port)

    def test_resolve_all_stale_fingerprint_com_hint(self):
        """Replaced device with COM hint → falls back to com_hint."""
        ports = [
            _port_info("COM3", sn="NEW_SERIAL", vid=0x0403, pid=0x6001),
        ]
        resolver = self._make_resolver(ports)
        device_map = {
            "tec": (_fp(sn="OLD_SERIAL", vid=0x0403, pid=0x6001), "COM3"),
        }
        results = resolver.resolve_all(device_map)
        # Serial mismatch rejects fingerprint match, but COM hint is available
        self.assertEqual(results["tec"].port, "COM3")
        self.assertEqual(results["tec"].method, "com_hint")

    def test_resolve_all_priority_serial_first(self):
        """Devices with serial numbers are resolved before hint-only ones."""
        # Arduino (no serial) and TEC (has serial) competing for COM3
        ports = [
            _port_info("COM3", sn="TEC_001", vid=0x0403, pid=0x6001),
            _port_info("COM4", vid=0x2341, pid=0x0043),
        ]
        resolver = self._make_resolver(ports)
        device_map = {
            "tec":     (_fp(sn="TEC_001", vid=0x0403, pid=0x6001), ""),
            "arduino": (None, "COM3"),  # stale COM hint pointing to TEC's port
        }
        results = resolver.resolve_all(device_map)
        # TEC should win COM3 (serial match, resolved first)
        self.assertEqual(results["tec"].port, "COM3")
        # Arduino's COM3 hint fails because COM3 is claimed by TEC
        self.assertIsNone(results["arduino"].port)


# ──────────────────────────────────────────────────────────────────────────────
#  Port ownership tests
# ──────────────────────────────────────────────────────────────────────────────

class TestPortOwnership(unittest.TestCase):
    """Test the port ownership registry and watchdog."""

    def setUp(self):
        self.po = _PortOwnership()

    def test_claim_and_release(self):
        self.po.claim("COM3", "tec")
        self.assertEqual(self.po.owner_of("COM3"), "tec")
        self.assertEqual(self.po.port_of("tec"), "COM3")
        self.po.release("tec")
        self.assertIsNone(self.po.owner_of("COM3"))
        self.assertIsNone(self.po.port_of("tec"))

    def test_double_claim_same_uid(self):
        """Same UID claiming same port again is fine."""
        self.po.claim("COM3", "tec")
        self.po.claim("COM3", "tec")  # should not raise
        self.assertEqual(self.po.owner_of("COM3"), "tec")

    def test_claim_conflict_raises(self):
        """Two UIDs claiming same port raises AmbiguousPortError."""
        self.po.claim("COM3", "tec")
        with self.assertRaises(AmbiguousPortError) as ctx:
            self.po.claim("COM3", "ldd")
        self.assertEqual(ctx.exception.port, "COM3")

    def test_uid_moves_port(self):
        """UID moving to a new port releases the old one."""
        self.po.claim("COM3", "tec")
        self.po.claim("COM4", "tec")
        self.assertIsNone(self.po.owner_of("COM3"))
        self.assertEqual(self.po.owner_of("COM4"), "tec")

    def test_claimed_ports_snapshot(self):
        self.po.claim("COM3", "tec")
        self.po.claim("COM4", "ldd")
        snapshot = self.po.claimed_ports()
        self.assertEqual(snapshot, {"COM3": "tec", "COM4": "ldd"})

    def test_clear(self):
        self.po.claim("COM3", "tec")
        self.po.clear()
        self.assertIsNone(self.po.owner_of("COM3"))
        self.assertFalse(self.po.is_claimed("COM3"))

    # ── Watchdog tests ───────────────────────────────────────────────

    def test_stale_probe_detected(self):
        """Probe claims older than threshold are flagged as stale."""
        self.po.PROBE_CLAIM_TIMEOUT = 0.1  # 100ms for testing
        self.po.claim("COM3", "__probe__COM3")
        time.sleep(0.15)
        stale = self.po.check_stale_claims()
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0][0], "__probe__COM3")
        self.assertEqual(stale[0][1], "COM3")

    def test_fresh_probe_not_stale(self):
        """Recent probe claims are NOT flagged."""
        self.po.PROBE_CLAIM_TIMEOUT = 10.0
        self.po.claim("COM3", "__probe__COM3")
        stale = self.po.check_stale_claims()
        self.assertEqual(len(stale), 0)

    def test_device_claim_never_stale(self):
        """Regular device claims are never flagged, even if old."""
        self.po.PROBE_CLAIM_TIMEOUT = 0.01
        self.po.claim("COM3", "tec")
        time.sleep(0.02)
        stale = self.po.check_stale_claims()
        self.assertEqual(len(stale), 0)  # not a probe → not flagged

    def test_release_stale_probes(self):
        """release_stale_probes() clears stale probe claims."""
        self.po.PROBE_CLAIM_TIMEOUT = 0.05
        self.po.claim("COM3", "__probe__COM3")
        self.po.claim("COM4", "tec")  # regular claim
        time.sleep(0.06)
        released = self.po.release_stale_probes()
        self.assertEqual(released, 1)
        self.assertIsNone(self.po.owner_of("COM3"))  # probe released
        self.assertEqual(self.po.owner_of("COM4"), "tec")  # kept


# ──────────────────────────────────────────────────────────────────────────────
#  USBFingerprint tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUSBFingerprint(unittest.TestCase):

    def test_stable_id_serial(self):
        fp = _fp(sn="ABC123")
        self.assertEqual(fp.stable_id, "sn:ABC123")

    def test_stable_id_location_fallback(self):
        fp = _fp(loc="1-3.2")
        self.assertEqual(fp.stable_id, "loc:1-3.2")

    def test_stable_id_vidpid_fallback(self):
        fp = _fp(vid=0x0403, pid=0x6001)
        self.assertEqual(fp.stable_id, "vid:0403:pid:6001")

    def test_stable_id_empty(self):
        fp = _fp()
        self.assertEqual(fp.stable_id, "")

    def test_is_empty(self):
        self.assertTrue(_fp().is_empty())
        self.assertFalse(_fp(sn="X").is_empty())
        self.assertFalse(_fp(vid=0x0403).is_empty())

    def test_roundtrip_dict(self):
        fp = _fp(sn="ABC", vid=0x0403, pid=0x6001, loc="1-2", mfr="FTDI", prod="FT232R")
        restored = USBFingerprint.from_dict(fp.to_dict())
        self.assertEqual(restored.serial_number, fp.serial_number)
        self.assertEqual(restored.vid, fp.vid)
        self.assertEqual(restored.pid, fp.pid)
        self.assertEqual(restored.location, fp.location)
        self.assertEqual(restored.manufacturer, fp.manufacturer)
        self.assertEqual(restored.product, fp.product)


if __name__ == "__main__":
    unittest.main()
