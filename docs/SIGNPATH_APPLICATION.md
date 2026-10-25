# SignPath Foundation application preparation

Updated 2026-10-26. The application has **not been submitted** and no certificate or signing token has been issued.

## Official requirements

- [Application](https://signpath.org/apply)
- [Foundation conditions](https://signpath.org/terms)

The current application form requires a project name, repository and homepage URLs, tagline, category, description, reputation evidence, a GitHub Actions or GitLab build system, separate first and last name fields, a contact email, a discovery channel, terms/privacy consent and reCAPTCHA. Optional marketing communications are not required.

## Prepared in this change

- [Code signing policy](CODE_SIGNING.md), explicitly identifying preparation status.
- [Privacy policy](PRIVACY.md), including startup update checks and optional remote services.
- A public Windows unsigned build workflow, action commits pinned, no signing secrets or release permissions.
- Successful public EXE and installer build: [run 40244756941](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/actions/runs/40244756941), source `59ce51d194`. Artifacts are unsigned; this is build evidence, not signing approval.
- Windows PE product/version metadata and package component inventory checks.
- Upstream MIT dictionary license and corrected third-party notices. Verified upstream license blob: `87f04113fd83a6e3027c4c056561cf8c48aa36c2`; introducing commit: `8fb4eb79225828bd7d401a5c0a2ad03d79c8a4e1`.

## Remaining before submission and signing

1. Publish these policies and the build workflow on the project's main branch; keep current releases clearly labeled unsigned.
2. Retain the successful public build run and source commit as origin evidence.
3. Obtain the contact's separate first/last name values and have the contact complete the browser CAPTCHA and consent.
4. Submit the form once and retain the confirmation; preparation is not submission.
5. After acceptance, confirm MFA, approver access and Foundation artifact restrictions. Request credentials only through the official service; never commit them.
6. Enable signatures only for the project's own executable and installer, with manual approval per request. Do not re-sign third-party DLLs under the project's certificate.
7. Compile the installer after receiving the signed application EXE; sign the installer afterward. Calculate release hashes only after both signing steps and signature verification.

The public unsigned workflow is a build provenance foundation, not a completed signing integration. It does not publish application updates. Installer privacy presentation, dependency-license review and the signed two-stage packaging path must be reviewed before the first signed release.
