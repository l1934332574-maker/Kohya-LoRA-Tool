# Code signing policy

Status: preparation for a SignPath Foundation application. No certificate has been granted and current releases are unsigned.

## Project and responsibilities

Kohya-LoRA Tool is maintained in [this repository](https://github.com/l1934332574-maker/Kohya-LoRA-Tool).

- Author, reviewer and proposed signing approver: [l1934332574-maker](https://github.com/l1934332574-maker).
- Contributions from other accounts require maintainer review before inclusion in a signed build.
- Before signing is enabled, the approver must enable MFA on GitHub and SignPath and confirm the signing configuration.

## Intended signing process

1. Build the application from a reviewed repository commit in GitHub Actions.
2. Submit only the project's own main EXE for signing. Third-party DLLs retain their original publisher and license.
3. Compile the installer with that signed EXE, then request a separate signature for the installer.
4. Require manual maintainer approval for each signing request.
5. Verify signatures, timestamps and version metadata before calculating final distribution hashes.

The public `Windows unsigned build` workflow currently produces unsigned artifacts for build review only. It does not request signatures, publish releases or upload to a mirror. Signing is not enabled for pull requests or forks.

The following attribution will apply only after acceptance and activation: “Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).” It is not a statement that existing releases have been signed.

## Privacy and reporting

See the [privacy policy](PRIVACY.md). Report signature or package integrity concerns through [GitHub Issues](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/issues). Do not post access tokens, private images or unredacted logs publicly.
