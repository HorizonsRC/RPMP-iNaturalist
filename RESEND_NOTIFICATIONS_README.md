# Resend Notifications — Backup Script

Manual backup for `resend_notifications.py`. Use this when the main pipeline
(`RPMP_iNat_PROD.py`) fails to send staff alerts for Eradication / Exclusion
observations.

It re-sends the same alert emails the main pipeline would have sent, using
the existing `inat_email_notifications` module and the data already in the
AGOL hosted layers.

---

## Quick start

> **Heads-up:** The Python path in the examples below uses
> `<YOUR-USERNAME>`. Replace it with the Windows user that owns the
> ArcGIS Pro Conda env. If you don't know it, run this in PowerShell:
>
> ```powershell
> dir "C:\Users\$env:USERNAME\AppData\Local\ESRI\conda\envs"
> ```
>
> Use the env name that appears (e.g. `arcpro-scripts-3-5`). On some
> installs the Python lives under `C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe`
> instead — check the env path the main pipeline runs under.

From PowerShell, in `D:\Scripts\iNaturalist`:

```powershell
# 1. Preview (dry-run) — last 7 days, filtered by observed_on
& "C:\Users\<YOUR-USERNAME>\AppData\Local\ESRI\conda\envs\arcpro-scripts-3-5\python.exe" resend_notifications.py

# 2. Once the list looks right, send
& "C:\Users\<YOUR-USERNAME>\AppData\Local\ESRI\conda\envs\arcpro-scripts-3-5\python.exe" resend_notifications.py --send
```

Dry-run is the default — no emails are sent unless you pass `--send`.

---

## Tip — set a PowerShell alias

To avoid typing the full Python path every time, run this once per session:

```powershell
Set-Alias propy "C:\Users\<YOUR-USERNAME>\AppData\Local\ESRI\conda\envs\arcpro-scripts-3-5\python.exe"
```

Then commands become:

```powershell
propy resend_notifications.py --by-upload-date --days 14
propy resend_notifications.py --by-upload-date --days 14 --send
```

Add the `Set-Alias` line to your PowerShell `$PROFILE` to make it permanent.

---

## Arguments

| Flag | Default | Meaning |
|------|---------|---------|
| `--days N` | `7` | Look back N days |
| `--by-upload-date` | off | Filter by iNat upload date (`created_at`) instead of `observed_on`. Best for catching up after a pipeline failure. |
| `--send` | off | Actually send emails. Without this, runs in dry-run mode. |

---

## Two filtering modes

### Default — by `observed_on`

Pulls features straight from the `iNat_Eradication` and `iNat_Exclusion`
AGOL layers, filters to those where `observed_on >= today − N days`. Fast
and simple, but **misses observations made long ago that were uploaded to
iNat recently** (e.g. observed Feb 27, added May 10).

```powershell
propy resend_notifications.py --days 30
```

### `--by-upload-date` — by iNat `created_at`

Queries the iNat API for observations *uploaded* to your project in the
past N days, then intersects with the AGOL priority layers to pick up the
already-processed `operatingArea` → staff assignment. This is what "should
have been notified" most accurately.

```powershell
propy resend_notifications.py --by-upload-date --days 14
```

Use this mode when catching up after a known pipeline failure — the
upload date is when staff *would* have been pinged.

---

## Typical workflow after a pipeline failure

1. **Preview** in upload-date mode with a window wide enough to cover the
   failed runs (check the logs in `D:\Scripts\iNaturalist\Logs\` for the
   earliest failure date):

   ```powershell
   propy resend_notifications.py --by-upload-date --days 14
   ```

2. **Review the output.** It will list each observation grouped by staff
   member, with email address, programme, species, operating area, and
   observation ID. Make sure the staff and obs look right.

3. **Send** by re-running with `--send`:

   ```powershell
   propy resend_notifications.py --by-upload-date --days 14 --send
   ```

4. Staff receive the same `URGENT: Eradication/Exclusion Species Detected`
   email format as a normal alert.

---

## Notes

- **Duplicates:** The script doesn't track which observations have
  already been emailed. If you re-run it twice with `--send`, staff will
  get duplicate alerts. Run carefully.
- **Operating area / staff lookup:** Comes from the AGOL layers (already
  spatially joined by the main pipeline). If an obs has no `operatingArea`
  in AGOL, it falls back to `"Unknown"` → `"Unassigned"` staff and is
  skipped at send time with a warning.
- **Email template:** Identical to the main pipeline's immediate alert.
  Staff have no way to tell whether an email came from the scheduled run
  or this backup script.
- **Auth:** Reuses your existing AGOL Pro login and the iNat OAuth token
  at `config.INAT_TOKEN_FILE`. No re-authentication required.
