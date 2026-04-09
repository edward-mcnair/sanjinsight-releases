# Device Identity Pipeline — QA Test Checklist

Version: v1.50.46+
Date: 2026-04-08

## Setup

- PC with at least 2 FTDI serial devices (e.g. Meerstetter TEC-1089 + Arduino Nano)
- Ideally also an ESP32 or Arduino UNO Q for broader coverage
- SanjINSIGHT installed from latest beta build

## Pre-test

1. Open Device Manager dialog, click **Log** to show the log panel
2. After each test, click **Export** in the log toolbar to save the identity log
3. Attach exported logs to any bug report

---

## Test 1: Repeated Reboot (cold start stability)

**Goal:** Devices connect to the correct ports across 5 consecutive reboots.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Launch app, wait for auto-reconnect | All devices connect |
| 2 | Note COM port assignments in identity report | Documented |
| 3 | Close app completely | — |
| 4 | Relaunch app | Same devices connect to same physical devices |
| 5 | Repeat steps 3-4 five times | Assignments stable every time |
| 6 | Export identity log on final boot | Fingerprint scores = 100 if serial numbers present |

**Pass criteria:** No device swaps identity across reboots.

---

## Test 2: Plug-Order Permutations

**Goal:** Resolver matches by fingerprint, not by COM port number.

| Step | Action | Expected |
|------|--------|----------|
| 1 | With app closed, unplug all USB serial devices | — |
| 2 | Plug in Device A first, then Device B | — |
| 3 | Launch app, wait for auto-reconnect | Both connect correctly |
| 4 | Export identity log, note COM ports | e.g. A=COM3, B=COM4 |
| 5 | Close app | — |
| 6 | Reverse plug order: Device B first, then Device A | COM ports may swap |
| 7 | Launch app, wait for auto-reconnect | Both connect correctly (same logical mapping) |
| 8 | Export identity log | Resolution method = "fingerprint" |

**Pass criteria:** Logical device identity is stable regardless of plug order.
Resolver log shows fingerprint match, not COM hint fallback.

---

## Test 3: Missing Device

**Goal:** App handles absent devices gracefully without stealing other ports.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Unplug one serial device (e.g. Arduino) | — |
| 2 | Launch app | Remaining devices connect normally |
| 3 | Check identity report | Missing device shows "NOT FOUND" |
| 4 | Check log for WARNING | "saved fingerprint matched no current port" |
| 5 | Verify remaining devices are on correct ports | No port stealing |
| 6 | Plug in the missing device | — |
| 7 | Run hardware scan | Device discovered |
| 8 | Connect it manually | Connects, fingerprint saved |

**Pass criteria:** Missing device does not cause other devices to misbind.

---

## Test 4: Stale Fingerprint

**Goal:** Replacing a device (same type, different serial) is handled safely.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Connect Device A, confirm fingerprint saved | Export log shows sn=XXX |
| 2 | Close app | — |
| 3 | Swap Device A for Device A' (same model, different serial) | — |
| 4 | Launch app | Device NOT auto-connected (serial mismatch = hard reject) |
| 5 | Check log | "saved fingerprint matched no current port" WARNING |
| 6 | Run hardware scan | Device A' discovered on the port |
| 7 | Connect manually | Connects, NEW fingerprint saved |
| 8 | Restart app | Device A' auto-connects with new fingerprint |

**Pass criteria:** Stale serial number causes clean failure, not misidentification.

---

## Test 5: Scan During Active Connection

**Goal:** Running a scan while devices are connected doesn't disrupt them.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Connect all devices | All connected |
| 2 | Click "Scan Hardware" in Device Manager | Scan runs |
| 3 | Verify connected devices remain connected | No disconnections |
| 4 | Verify scan doesn't overwrite entry.address | Address unchanged |
| 5 | Check log for port ownership | Probes skip owned ports |
| 6 | Check identity report after scan | Same as before scan |

**Pass criteria:** Active connections are undisturbed by scan.
Log shows "port claimed by <uid> — skipping" for owned ports.

---

## Test 6: Interrupted Startup Recovery

**Goal:** App recovers cleanly if startup is interrupted mid-connection.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Launch app | Auto-reconnect begins |
| 2 | While "Connecting..." is shown, force-quit the app | — |
| 3 | Relaunch app immediately | — |
| 4 | Wait for auto-reconnect to complete | All devices connect |
| 5 | Export identity log | No stale port claims from previous session |

**Pass criteria:** port_ownership singleton is in-memory only, so a restart
clears all claims automatically. No leaked claims from crashed sessions.

---

## Test 7: TEC/LDD Port Swap (FTDI collision)

**Goal:** MeCom address verification prevents TEC/LDD misbinding.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Connect TEC and LDD (both FTDI 0403:6001) | Both connect |
| 2 | Export identity log | TEC shows addr=2, LDD shows addr=1 |
| 3 | Close app | — |
| 4 | Swap USB ports of TEC and LDD | COM numbers swap |
| 5 | Launch app | Both connect to correct logical devices |
| 6 | Export identity log | Fingerprint match, correct MeCom addresses |

**Pass criteria:** Fingerprint serial numbers resolve correctly despite COM swap.
If serial numbers are identical (rare), MeCom address verification catches misbinding.

---

## Collecting Results

After each test:
1. Click **Export** in the Device Manager log panel
2. Logs are saved to `~/.microsanj/identity_logs/`
3. Include the exported file with any bug report
4. Note the test number and pass/fail in the filename or a companion note
