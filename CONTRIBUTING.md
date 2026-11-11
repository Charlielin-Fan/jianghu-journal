# Contributing

Thank you for helping make 江湖行记 more useful.

## Before opening an issue or pull request

- Describe the Windows version, what you expected, and what happened.
- Reproduce the problem with made-up entries. **Never attach <code>数据/行记.json</code>, backups, or screenshots containing personal plans.**
- Keep changes focused and update the Chinese and English README sections when user-facing behavior changes.

## Build and verify

Use Windows, Git LFS, and Go 1.24 or newer. Run <code>git lfs install</code> before cloning so the embedded fonts are available.

~~~powershell
go test ./...
go build -trimpath -ldflags="-H windowsgui -s -w" -o .\江湖行记.exe .
~~~

For the browser workflow and dense-month checks, install the test dependency and Chromium:

~~~powershell
py -m pip install -r requirements-test.txt
py -m playwright install chromium
py .\qa.py .\江湖行记.exe --usb $env:TEMP
~~~

For native-window checks, run <code>py .\qa_desktop.py .\江湖行记.exe</code> on a Windows desktop with Microsoft Edge WebView2 Runtime installed. The QA scripts create synthetic data in temporary folders.

By submitting a contribution, you agree that it may be distributed under this repository's MIT license. Bundled fonts and third-party components keep their own licenses.
