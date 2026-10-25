# Privacy policy

Kohya-LoRA Tool is a local Windows application. This policy describes the project's application code; downloaded training engines and third-party services also have their own policies.

## Local data

Projects, captions, training images, model files, generated samples, settings and diagnostic logs are stored locally in the selected data directory. Exporting a feedback archive creates a local file; exporting alone does not send it to the project maintainers. Review exported files before sharing them.

## Network access

- **Update checks:** the application can check public update metadata at startup and when requested. Current sources include ModelScope, GitHub and jsDelivr. Those services receive normal network request information, such as the connecting IP address and HTTP headers. Update checks do not require uploading training images or project files.
- **Downloads and environment setup:** installing engines, Python packages or models contacts the selected upstream repositories, package indexes or mirrors. Their own access logs and privacy policies apply. Local training engines may make additional network requests according to their implementation.
- **Optional AI services:** when an operator configures and uses a remote assistant or image description service, the messages, image inputs and task context used for that request are sent to that configured provider. Use local captioning when images must remain on the computer. Review the configured provider's privacy policy before use.
- **External agents and MCP:** enabling agent access allows configured clients to access the capabilities and data exposed by the local interface. See [MCP documentation](MCP.md) before connecting an external client.

The application does not sell project data or automatically upload feedback archives to the maintainers. These statements do not extend to separate services chosen by the operator.

## User control and system changes

Model and dependency downloads are initiated through setup, captioning or training operations. They use disk space and may install packages in application-managed environments. Review the environment location before setup. Optional cloud services should be left unconfigured when not needed. Operating system or network controls can block update checks when offline operation is required.

The installer provides Windows uninstall support. Uninstalling the application does not erase separately stored training data or model environments; remove those only after making any needed backups.

## Third parties and contact

See [third-party notices](../THIRD_PARTY_NOTICES.md). Update and download services include [GitHub](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement), [ModelScope](https://modelscope.cn) and [jsDelivr](https://www.jsdelivr.com/terms/privacy-policy). Optional provider terms depend on the endpoint selected by the operator.

For project questions, use [GitHub Issues](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/issues) without posting private files or credentials.

Last reviewed: 2026-10-26.
