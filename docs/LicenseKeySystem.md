# SanjINSIGHT License Key System
## Operations Manual for Microsanj Staff

---

## How It Works (The Concept)

The license system uses **public-key cryptography** (Ed25519). Think of it like a wax seal:

- **You hold the signet ring (private key)** — only you can create a valid seal.
- **Every copy of the app has a photo of the ring (public key)** — anyone can verify the seal is genuine, but they cannot forge one.

This means:
- License keys work **completely offline** — no internet, no server, no phone-home.
- Even someone who decompiles the installer cannot generate valid keys — they only have the photo, not the ring.
- If someone shares their key with another user, you can revoke it in the next release by adding it to a blocklist (future enhancement).

---

## Key Files Overview

| File | Location | Who Has It | Purpose |
|------|----------|------------|---------|
| `microsanj_license_private.key` | **Your secure storage only** | Microsanj only | Signs new license keys |
| Public key (baked in) | `licensing/license_validator.py` | Every customer | Verifies keys are genuine |
| `tools/gen_license.py` | Source repo (private) | Microsanj only | Command-line tool to generate keys |
| `licensing/` package | Installed with software | Every customer | Validates keys in the app |

> ⚠️ **The private key file must never be committed to the repository or shared.**
> Store it in your password manager (1Password, Bitwarden, etc.) or an encrypted drive.

---

## First-Time Setup

This only needs to be done **once ever**. The keypair has already been generated for this project. Skip to [Generating a License Key](#generating-a-license-key-for-a-customer) unless you need to regenerate.

### If you ever need to regenerate the keypair:

```bash
cd /path/to/sanjinsight
python tools/gen_license.py --generate-keys
```

This outputs:
```
[OK] Private key saved to: microsanj_license_private.key

╔══════════════════════════════════════════════════════════╗
║  Paste this PUBLIC KEY into licensing/license_validator.py ║
╚══════════════════════════════════════════════════════════╝

_PUBLIC_KEY_B64 = "ge2cJaHYRA7ux6Um+W0J5yznK4Axsz6p8yzoY76S6is="
```

**Steps after regenerating:**
1. Save `microsanj_license_private.key` securely (password manager).
2. Open `licensing/license_validator.py` and replace the `_PUBLIC_KEY_B64` line.
3. Commit and ship a new version of the app.
4. Re-issue all existing customer keys with the new private key.

> ⚠️ Regenerating invalidates ALL existing customer keys. Only do this if the private key is compromised.

---

## Generating a License Key for a Customer

### Requirements
- Python 3.x with `cryptography` installed: `pip install cryptography`
- The private key file: `microsanj_license_private.key`

### Standard 1-year license (most common)

```bash
python tools/gen_license.py \
    --key-file microsanj_license_private.key \
    --customer "Stanford University" \
    --email    lab@stanford.edu \
    --tier     standard \
    --seats    1 \
    --days     365
```

### Site license (multiple seats, 2 years)

```bash
python tools/gen_license.py \
    --key-file microsanj_license_private.key \
    --customer "TSMC Research Lab" \
    --email    research@tsmc.com \
    --tier     site \
    --seats    10 \
    --days     730
```

### Developer license (plugin SDK access)

```bash
python tools/gen_license.py \
    --key-file microsanj_license_private.key \
    --customer "Microsanj R&D" \
    --email dev@microsanj.com \
    --tier     developer \
    --seats    1 \
    --days     365 \
    --serial   SJ-DEV-001
```

### Perpetual license (no expiry date)

```bash
python tools/gen_license.py \
    --key-file microsanj_license_private.key \
    --customer "Microsanj Internal" \
    --email    team@microsanj.com \
    --tier     site \
    --seats    99 \
    --perpetual
```

### Output

The tool prints a key string like:
```
[OK] License generated for: Stanford University
     Tier: standard  |  Seats: 1  |  expires in 365 days

────────────────────────────────────────────────────────────────────────
eyJjdXN0b21lciI6IlN0YW5mb3JkIFVuaXZlcnNpdHkiLCJlbWFpbCI6ImxhYkBzdGFu
Zm9yZC5lZHUiLCJ0aWVyIjoic3RhbmRhcmQiLCJzZWF0cyI6MSwiaXNzdWVkIjoiMjAy
Ni0wMy0wNyIsImV4cGlyZXMiOiIyMDI3LTAzLTA3In0.AAABBBCCC...
────────────────────────────────────────────────────────────────────────

Send the key string above to the customer.
They paste it into Help → License… in SanjINSIGHT.
```

Copy everything between the `─────` lines and email it to the customer.

---

## Sending the Key to a Customer

Send an email like this:

> **Subject:** Your SanjINSIGHT License Key
>
> Dear [Customer],
>
> Thank you for purchasing SanjINSIGHT. Your license key is below.
>
> **How to activate:**
> 1. Open SanjINSIGHT
> 2. Click **Help → License…** in the menu bar
> 3. Paste the key into the text box
> 4. Click **Activate License**
>
> ```
> [paste key here]
> ```
>
> Your license is valid for 1 year (expires [date]).
> Contact software-support@microsanj.com to renew.

---

## License Tiers

| Tier | What it enables | Typical use |
|------|----------------|-------------|
| **Unlicensed** | Demo mode only (simulated hardware), exports may be watermarked | Trial / evaluation |
| **Standard** | Full hardware access, all features, 1 seat | Individual researcher |
| **Developer** | Standard features + plugin SDK access (load custom plugins) | Microsanj add-on products, third-party plugin developers |
| **Site** | Full hardware access, N seats, plugin SDK access | Lab / institution |

> **Note:** The Developer tier was added in v1.5.0 for the plugin architecture. Plugins specify a `min_license_tier` in their manifest; most internal Microsanj plugins require Developer or higher. Site-tier licenses automatically have full plugin access.

---

## How the Customer Activates

The customer opens the app and goes to **Help → License…**

![License dialog shows current status at top, text box to paste key, and Activate button]

They:
1. Paste the key string into the text box.
2. Click **Activate License**.
3. The app validates the signature instantly (no internet needed).
4. On success, the dialog shows their name, tier, and expiry date.
5. The key is saved to `~/.microsanj/preferences.json` and reloaded on every startup.

If the key is wrong (typo, tampered, expired), the dialog shows a red error message.

---

## How the App Validates (Technical)

Every time the app starts up, it:

1. Reads `license.key` from `~/.microsanj/preferences.json`
2. Splits the key into two parts at the `.`: `<payload>.<signature>`
3. Base64-decodes both parts
4. Uses the baked-in Ed25519 public key to verify the signature
5. If valid, parses the JSON payload to read tier, customer, expiry, etc.
6. Sets `app_state.license_info` to the result
7. If no key / invalid key → `app_state.license_info.tier = UNLICENSED`

The whole process takes < 1 ms and requires no network connection.

---

## Verifying a Key (Troubleshooting)

If a customer reports their key isn't working, verify it yourself:

```bash
python tools/gen_license.py --verify "eyJjdXN0b21lciI6..."
```

Output if valid:
```
[OK] Key is VALID
  Customer : Stanford University
  Email    : lab@stanford.edu
  Tier     : Standard
  Seats    : 1
  Issued   : 2026-03-07
  Expires  : 2027-03-07
  Serial   : (any machine)
```

Output if invalid:
```
[FAIL] Key is INVALID or EXPIRED
```

**Common causes of invalid keys:**
- Key was truncated when copying (must be one unbroken string)
- Customer is running an old version of the app (before the license system was added)
- Key has expired — generate a new one with `--days 365`

---

## Renewing an Expired License

Generate a new key with a new expiry date. There is no "renewal" concept — each key is standalone. The old key stops working on its expiry date; the new key takes over immediately.

```bash
python tools/gen_license.py \
    --key-file microsanj_license_private.key \
    --customer "Stanford University" \
    --email    lab@stanford.edu \
    --tier     standard \
    --seats    1 \
    --days     365
```

Email the new key to the customer. They activate it the same way as before — activating a new key automatically replaces the old one.

---

## Keeping Records

Recommended: maintain a spreadsheet with one row per license issued.

| Date | Customer | Email | Tier | Seats | Issued | Expires | Notes |
|------|----------|-------|------|-------|--------|---------|-------|
| 2026-03-07 | Stanford University | lab@stanford.edu | Standard | 1 | 2026-03-07 | 2027-03-07 | Initial purchase |

This lets you track renewals, identify expired customers to follow up with, and re-issue keys quickly if needed.

---

## Command Reference

```
python tools/gen_license.py --help

  --generate-keys              Generate a new keypair (first-time only)
  --output FILE                Where to save the private key (default: microsanj_license_private.key)

  --key-file FILE              Path to your private key file
  --customer NAME              Customer / company name  (required)
  --email ADDRESS              Contact email
  --tier {standard,developer,site}  License tier  (default: standard)
  --seats N                    Number of seats  (default: 1)
  --days N                     Validity in days  (default: 365)
  --perpetual                  No expiry date
  --serial SERIAL              Lock to a specific hardware serial number

  --verify KEY_STRING          Verify an existing key (no private key needed)
```
