# Security Policy

---

## Supported Versions

| Version | Supported |
|---|---|
| `main` (latest) | ✅ Active support |
| Tagged releases | ✅ Critical security fixes backported where feasible |
| Older branches | ❌ Not supported |

Security fixes are applied to the `main` branch first. Tagged release patches are issued for critical vulnerabilities at maintainer discretion.

---

## PHI Handling

RT Viewer is designed for deployment on a **local workstation or trusted clinical network**. The `dicom_data/` directory is the application's data root and **may contain Protected Health Information (PHI)** when used with real patient datasets.

### Critical network exposure warnings

> [!CAUTION]
> **Do not expose port 8000 (FastAPI backend) or port 5000 (frontend dev server / built app) to the public internet.**
>
> The API server has **no authentication layer**. Any process that can reach port 8000 can read, list, and stream all patient data in `dicom_data/`. This is an intentional design decision for frictionless local deployment, but it must be secured at the network level when used with real patient data.

- Run RT Viewer only on a machine connected to a **firewalled, trusted clinical network**.
- If multi-user or multi-workstation access is required, place a reverse proxy with TLS and authentication in front of both ports. See [Deployment Hardening](#deployment-hardening-recommendations).
- The `dicom_data/` directory should be treated with the same access controls as any other PHI data store at the deploying institution.

---

## Reporting a Vulnerability

> [!IMPORTANT]
> **Do not file a public GitHub issue for security vulnerabilities.**
>
> Public disclosure before a fix is available may expose users and their patient data to unnecessary risk.

To report a vulnerability, send an email to:

**`[security contact placeholder — maintainer: replace this with your security contact email before publishing]`**

### What to include in the report

- A clear description of the vulnerability
- Step-by-step reproduction instructions, including the environment (OS, Python version, network configuration)
- The potential impact — specifically, whether PHI exposure is possible or likely
- Whether the vulnerability has been publicly disclosed or shared with any third parties
- Any proof-of-concept code or screenshots (do not include real patient data in the report)

### Response commitments

| Milestone | Target |
|---|---|
| Acknowledgement of receipt | Within **48 hours** of receiving the report |
| Initial assessment and severity classification | Within **5 business days** |
| Fix timeline communicated to reporter | Within **7 days** of receipt |
| Public disclosure (coordinated with reporter) | After a fix is available and deployed |

Reporters who follow responsible disclosure practices are thanked in release notes unless they prefer to remain anonymous.

---

## Known Limitations

The following are known security limitations of RT Viewer by design. They are documented here for transparency and to inform deployment decisions.

| Limitation | Detail |
|---|---|
| **No authentication on API endpoints** | The FastAPI backend on port 8000 has no login, token, or session mechanism. Access control is enforced entirely at the network layer. This is intentional for local single-workstation deployments. |
| **No TLS / HTTPS** | Neither service uses TLS by default. Data — including CT images, dose matrices, and patient identifiers — is transmitted unencrypted over the local network. Use within a trusted network segment only, or add a TLS-terminating reverse proxy. |
| **No audit logging of data access** | RT Viewer does not log which users accessed which patient records, when, or from which IP address. Institutions with audit trail requirements must implement this at the network or infrastructure level. |
| **No access controls on `dicom_data/`** | The application does not enforce per-user or per-patient access restrictions within `dicom_data/`. Any user who can reach the API can access all data in the directory. Access controls must be enforced via filesystem permissions. |
| **No input validation on patient ID path parameters** | While basic path traversal protections are in place, the API has not undergone a formal penetration test. Do not expose it to untrusted users or networks. |

---

## Deployment Hardening Recommendations

These measures should be implemented when RT Viewer is used with real patient data.

### Network

- **Restrict ports 8000 and 5000 to the local host or local network segment** using host-based firewall rules (Windows Firewall, `ufw`, `firewalld`). Do not expose these ports to the broader hospital network or internet without additional controls.
- If access from multiple workstations is required, use a **reverse proxy (e.g., nginx)** with TLS termination and, ideally, an authentication layer (e.g., HTTP Basic Auth, OAuth2 proxy, or mTLS). Example nginx snippet:
  ```nginx
  server {
      listen 443 ssl;
      ssl_certificate     /etc/ssl/certs/rt-viewer.crt;
      ssl_certificate_key /etc/ssl/private/rt-viewer.key;

      location /api/ {
          proxy_pass http://127.0.0.1:8000/;
      }
      location / {
          proxy_pass http://127.0.0.1:5000/;
      }
  }
  ```

### File System

- **Run RT Viewer as a non-privileged service account**, not as a local administrator or root. Create a dedicated service account with access limited to the `rt-viewer` directory and `dicom_data/`.
- **Keep `dicom_data/` on an encrypted volume.** On Windows, use BitLocker. On Linux, use LUKS or an encrypted filesystem mount.
- **Apply filesystem permissions to `dicom_data/`:**
  - **Windows (NTFS):** Grant read/write access only to the RT Viewer service account and authorized clinical staff. Remove inherited permissions if the directory is on a shared drive.
  - **Linux:** `chmod 700 dicom_data/` and `chown rt-viewer-svc:rt-viewer-svc dicom_data/`. Do not place `dicom_data/` in a world-readable location.
- **Do not commit `dicom_data/` contents to version control.** The directory is listed in `.gitignore`. Verify this has not been altered before running `git add`.

### Operational

- Keep Python, Node.js, and all dependencies up to date. Run `pip list --outdated` and `npm outdated` regularly.
- Rotate or remove the `dicom_data/` contents for patients whose cases are no longer under active review, consistent with institutional data retention policies.
- Review the `logs/` directory periodically. Backend logs may contain patient identifiers in file paths. Treat log files as PHI if RT Viewer is used with real patient data.

---

## HIPAA Considerations

RT Viewer does not provide built-in HIPAA technical safeguard controls. When deployed with real patient data, the **deploying organization** is solely responsible for ensuring that the deployment meets applicable requirements under the HIPAA Security Rule (45 CFR Part 164), including:

- **Access controls** (§ 164.312(a)(1)): Restrict access to ePHI to authorized users only.
- **Audit controls** (§ 164.312(b)): Implement hardware, software, or procedural mechanisms to record and examine access to systems containing ePHI.
- **Transmission security** (§ 164.312(e)(1)): Implement technical security measures to guard against unauthorized access to ePHI transmitted over a network.
- **Encryption and decryption** (§ 164.312(a)(2)(iv), addressable): Encrypt and decrypt ePHI at rest.

The hardening measures described above are starting points, not a compliance checklist. Consult institutional compliance and information security staff before deploying RT Viewer in any environment where real patient data is processed.

> [!NOTE]
> RT Viewer is a **research tool**, not a certified medical records system. Deploying organizations assume full responsibility for HIPAA compliance when using RT Viewer with real patient data.
