# Public-release audit

Audit date: **2026-10-07**. Repository visibility remains **private**.

## Result

No credential leaks were detected in the scanned repository history, enclosure
package, or downloaded release contents. Publication would nevertheless expose
personal information already present in the project. Choose whether to retain
that information before changing visibility; the repository is not anonymous.
Licensing update after this audit: the project-owned software now has an MIT
license. Upstream components and the third-party board CAD reference remain
under their own terms; see [license scope and notices](../THIRD_PARTY_NOTICES.md).

## Scope and checks

- Fetched the repository's remote tags and inspected all reachable Git history:
  12 commits before the enclosure/audit addition, through `e53d79d`.
- Ran checksum-verified **Gitleaks 8.30.1**, with redacted JSON reporting, on all
  history. It reported zero findings.
- Downloaded and inspected the assets of all five releases: `v0.3.0`, `v0.4.0`,
  `android-v1.0.0`, `android-v1.0.1`, and their source/validation/DFU ZIPs and APKs.
  Expanded archive contents were scanned separately; zero Gitleaks findings.
- Retrieved the supplied enclosure ZIP from authenticated Drive and verified its
  SHA-256 against the existing local package before importing it. Scanned its
  extracted source, documentation, geometry and references; zero findings.
- Checked reachable historical filenames and extracted artifacts for credential
  files, Android signing keystores/password files, and private-key markers. None
  were found in the inspected material.
- Inspected EXIF/XMP location fields in eight user images and four validation
  screenshots. No GPS metadata was found. The visible personal content remains.

The Android signing key and password reside outside the repository, and no copies
were found in source archives, APK contents or other inspected releases. The
public certificate carried by an APK is expected and is not the private signing
key. Build scripts reference signing environment variables; those variable names
and local signing-file locations are not secret values.

## Information that would become public

| Finding | Where | Assessment |
| --- | --- | --- |
| Real name and personal email | Existing Git author and committer metadata | Identity/contact exposure. Changing future Git configuration does not alter old commits. |
| Pod BLE address | `recordings/*/session.json`, validation JSON/JSONL, and older release archives | A device identifier, not an authentication credential. Consider anonymizing it if you want the hardware less identifiable. |
| Computer username and absolute paths | Build instructions and several validation reports, including older release source/report archives | Reveals local account name and directory structure. No private file contents are exposed by the path alone. |
| Workout timestamps and metrics | Recordings, reference annotations, and Strava / Zwift screenshots | Personal activity data: cadence, pace, heart rate, time and distance. Keep only if you intend to share them. |
| Personal photographs | `docs/images/` | Shows legs/shoes and the desk/workspace. No GPS metadata was detected; visible content can still be identifying. |
| Drive file IDs and links | READMEs, Android validation reports, and some release metadata | Links to the APK/design files you intentionally supplied. They are not OAuth tokens; access follows Drive sharing settings. |

The author identity is not copied into this report as a new email listing; it is
already visible in `git log`. Raw scan reports contain no secret findings and were
kept outside the repository.

## Before publication

If those personal details are acceptable to you, this audit found no credential
issue that requires rotating a token or signing key. If any should remain private,
remove them from **history/tags and downloadable releases**, not only the latest
working files. Old source/validation ZIPs still contain device IDs and paths.
No history rewriting, image editing, release replacement or data deletion was
performed during this audit.

The original software is now MIT-licensed, as requested by the owner. The
imported CAD package has no licensing notice and includes an unchanged Seeed
board-reference STEP file. That reference and STL/STEP assets are outside the
software MIT grant. Its separate terms still apply to redistribution; the
software license does not change the contents or terms of the original ZIP.
The Gradle wrapper's existing upstream notices must also be retained.

Making a repository public is separate from granting an open-source license:
[GitHub's licensing guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
explains the distinction. For cleanup, use
[GitHub's guidance on removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

## Limits

Secret scanners can miss custom/encoded secrets, and this is not a guarantee that
every possible sensitive value is absent. Checks covered available repository
refs, uploaded release assets, supplied design files and visible images; they did
not review other private Drive files, unrelated repositories, or firmware/app
security vulnerabilities. This report records evidence at the audit date.
