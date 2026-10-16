# Runner images (synthetic test fixture)

## Available Images

| Image | Architecture | YAML Label | Included Software |
| --- | --- | --- | --- |
| Ubuntu 26.04 | x64 | `ubuntu-26.04` | [ubuntu26] |
| Ubuntu 26.04 Arm | arm64 | `ubuntu-26.04-arm` | [ubuntu26] |
| Ubuntu 24.04 Arm | arm64 | `ubuntu-24.04-arm` | [ubuntu24] |
| Ubuntu 24.04 | x64 | `ubuntu-latest` or `ubuntu-24.04` | [ubuntu24] |
| Ubuntu 28.04 ![preview](badge) | x64 | `ubuntu-28.04` | [ubuntu28] |
| Ubuntu Slim | x64 | `ubuntu-slim` | [slim] |
| macOS 14 [![deprecated](badge)](https://github.com/actions/runner-images/issues/13518) | arm64 | `macos-14` or `macos-14-xlarge` | [mac14] |
| macOS 14 ![deprecated](badge) | x64 | `macos-14-large` | [mac14intel] |
| macOS 26 | arm64 | `macos-latest`, `macos-26` or `macos-26-xlarge` | [mac26] |
| macOS 26 | x64 | `macos-latest-large`, `macos-26-intel`, `macos-26-large` | [mac26intel] |
| Windows 2022 | x64 | `windows-2022` | [win22] |
| Windows 2025 | x64 | `windows-latest`, `windows-2025` or `windows-2025-vs2026` | [win25] |
| Windows 11 | arm64 | `windows-11-arm` | [winarm] |
| Windows 11 VS2026 | arm64 | `windows-11-vs2026-arm` | [winarmvs] |

### Label scheme

[ubuntu26]: https://github.com/actions/runner-images/blob/main/images/ubuntu26.md
[ubuntu24]: https://github.com/actions/runner-images/blob/main/images/ubuntu24.md
[ubuntu28]: https://github.com/actions/runner-images/blob/main/images/ubuntu28.md
[slim]: https://github.com/actions/runner-images/blob/main/images/slim.md
[mac14]: https://github.com/actions/runner-images/blob/main/images/mac14.md
[mac14intel]: https://github.com/actions/runner-images/blob/main/images/mac14intel.md
[mac26]: https://github.com/actions/runner-images/blob/main/images/mac26.md
[mac26intel]: https://github.com/actions/runner-images/blob/main/images/mac26intel.md
[win22]: https://github.com/actions/runner-images/blob/main/images/win22.md
[win25]: https://github.com/actions/runner-images/blob/main/images/win25.md
[winarm]: https://github.com/actions/runner-images/blob/main/images/winarm.md
[winarmvs]: https://github.com/actions/runner-images/blob/main/images/winarmvs.md

## Other table (must not be parsed)

| Fake | x64 | `ubuntu-99.04` | [ubuntu26] |
