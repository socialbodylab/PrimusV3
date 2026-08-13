# Windows Azure Signing Setup — Quick Reference

Use this guide when setting up PrimusCentral Windows release signing on a **new PC**. The repo contains the build scripts and docs, but signing credentials and metadata stay **local** (not in git).

## What you need from Azure

Create this file on the build machine:

```text
V3_6\build\windows\signing\metadata.json
```

That folder is gitignored. Copy it manually between machines if you have an old build PC.

### metadata.json template

```json
{
  "Endpoint": "https://<region>.codesigning.azure.net",
  "CodeSigningAccountName": "<trusted-signing-account-name>",
  "CertificateProfileName": "<certificate-profile-name>",
  "CorrelationId": "PrimusCentral-<version>"
}
```

| Field | Required | What it is |
|-------|----------|------------|
| `Endpoint` | Yes | Regional signing URL — must match the account region |
| `CodeSigningAccountName` | Yes | Trusted Signing account name |
| `CertificateProfileName` | Yes | Certificate profile inside that account |
| `CorrelationId` | Optional | Build label for logs (e.g. `PrimusCentral-0.76`) |

---

## Portal checklist — copy these 4 fields

Work through this on [https://portal.azure.com](https://portal.azure.com):

- [ ] **Subscription name or ID** — needed for `az account set`
- [ ] **CodeSigningAccountName** — Trusted signing account name
- [ ] **CertificateProfileName** — profile under that account
- [ ] **Endpoint** — from the account’s Azure region (table below)

### Where to find each value

#### 1. Subscription

1. Search **Trusted signing accounts** (may appear as **Code signing accounts**).
2. Open your PrimusCentral signing account.
3. On **Overview**, note **Subscription** (name and/or ID).

#### 2. CodeSigningAccountName

1. Same account **Overview** page.
2. Copy **Account name** (the resource name you created).

#### 3. CertificateProfileName

1. Open the same Trusted signing account.
2. Left menu → **Certificate profiles**.
3. Open the profile used for release builds.
4. Copy **Profile name**.

#### 4. Endpoint (region URL)

1. On the account **Overview**, note **Region**.
2. Use the matching endpoint:

| Azure region | Endpoint |
|--------------|----------|
| East US | `https://eus.codesigning.azure.net` |
| West US | `https://wus.codesigning.azure.net` |
| West US 2 | `https://wus2.codesigning.azure.net` |
| Central US | `https://cus.codesigning.azure.net` |
| North Europe | `https://neu.codesigning.azure.net` |
| West Europe | `https://weu.codesigning.azure.net` |
| UK South | `https://uks.codesigning.azure.net` |

Wrong region → signing usually fails with **403**.

---

## IAM checklist

The account used for `az login` needs signing permission.

1. Open the Trusted signing account or certificate profile.
2. **Access control (IAM)** → **Role assignments**.
3. Confirm your user or service principal has:
   - **Trusted Signing Certificate Profile Signer**  
     (docs may also say **Artifact Signing Certificate Profile Signer**)

Without this role, signing fails even with a correct `metadata.json`.

---

## Fastest path: copy from old build PC

If the previous Windows build machine is available:

```text
V3_6\build\windows\signing\metadata.json
```

Copy that file to the same path on the new machine. Then you only need `az login` and installed tools.

---

## New PC setup (full)

### 1. Clone and install build tools

```powershell
git clone https://github.com/socialbodylab/PrimusV3.git
cd PrimusV3
py -m pip install -r V3_6\requirements-build.txt
```

### 2. Install signing tools

```powershell
winget install -e --id Microsoft.AzureCLI
winget install -e --id Microsoft.Azure.ArtifactSigningClientTools
winget install -e --id JRSoftware.InnoSetup
```

Also ensure **Windows SDK** (for `signtool.exe`) and **.NET 8** are installed. SignTool is typically at:

```text
C:\Program Files (x86)\Windows Kits\10\bin\<sdk-version>\x64\signtool.exe
```

After installing Artifact Signing Client Tools, locate:

```text
Azure.CodeSigning.Dlib.dll
```

Common install locations vary; search the machine if needed.

### 3. Create metadata.json

```powershell
mkdir V3_6\build\windows\signing -Force
notepad V3_6\build\windows\signing\metadata.json
```

Paste the template above with your real Azure values.

### 4. Sign in to Azure

```powershell
az login
az account set --subscription "<subscription name or id>"
az account show
```

Confirm the subscription matches where the Trusted signing account lives.

### 5. Build and sign

**Executable only:**

```powershell
py V3_6\build_sender_app.py --target windows `
  --windows-sign-metadata V3_6\build\windows\signing\metadata.json `
  --windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

**Executable + installer (recommended for GitHub release):**

```powershell
py V3_6\build_sender_app.py --target windows --windows-installer `
  --windows-sign-metadata V3_6\build\windows\signing\metadata.json `
  --windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

**Environment variable alternative:**

```powershell
$env:PRIMUSV3_WINDOWS_SIGN_METADATA = "V3_6\build\windows\signing\metadata.json"
$env:PRIMUSV3_ARTIFACT_SIGNING_DLIB = "C:\Path\To\Azure.CodeSigning.Dlib.dll"
$env:PRIMUSV3_SIGNTOOL = "C:\Path\To\signtool.exe"
py V3_6\build_sender_app.py --target windows --windows-installer
```

### 6. Verify signature

```powershell
& "C:\Path\To\signtool.exe" verify /pa /v V3_6\dist\windows\PrimusCentral.exe
Get-AuthenticodeSignature V3_6\dist\windows\PrimusCentral.exe | Format-List
```

If you built the installer:

```powershell
& "C:\Path\To\signtool.exe" verify /pa /v V3_6\dist\windows\PrimusCentral-<version>-Windows-x64-Setup.exe
```

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| **403** on sign | Wrong `Endpoint` region, wrong subscription, or missing Signer role |
| Account not found | Wrong `CodeSigningAccountName` |
| Profile not found | Wrong `CertificateProfileName` |
| Dlib not found | Reinstall Artifact Signing Client Tools; fix `--windows-sign-dlib` path |
| SignTool not found | Install Windows SDK; set `--windows-signtool` or `PRIMUSV3_SIGNTOOL` |
| Not logged in | Run `az login` and `az account set` |

---

## What stays in Azure vs on the PC

| In Azure (already provisioned) | On each build PC (you set up) |
|--------------------------------|-------------------------------|
| Trusted Signing account | `metadata.json` |
| Certificate profile | `az login` |
| IAM / Signer role | Artifact Signing Client Tools |
| | SignTool, Python, PyInstaller, Inno Setup |

No `.pfx` or private key is stored in the repo. Authentication uses Azure at build time.

---

## Related docs in this repo

- [PACKAGING.md](PACKAGING.md) — full macOS and Windows packaging
- [WINDOWS_BUILD.md](WINDOWS_BUILD.md) — Windows build handoff and release assets

## My values (fill in locally — do not commit)

Keep a copy of this section on the build machine only. **Do not commit real names to git.**

```text
Subscription: 
CodeSigningAccountName: 
CertificateProfileName: 
Endpoint: 
Azure.CodeSigning.Dlib.dll path: 
SignTool.exe path: 
Last successful build version: 
Last successful build date: 
```
