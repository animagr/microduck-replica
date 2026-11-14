# AI assistant SSH connection guide

**English** · [简体中文](2026-10-30-ai-ssh-guide-design.md)

The user has confirmed the entry, navigation and step-by-step hint design, and asked for it to be implemented and the hints and layout checked.

## Behavior and layout

- After the overview dashboard band and after the settings page title, provide a compact "让 AI 连接鸭子（SSH）" (Let AI connect to the duck (SSH)) entry that jumps to `#/settings/ssh` and scrolls to the connection guide; the settings navigation stays highlighted.
- The guide reuses the existing `/api/password` and `/api/ssh`, does not enable SSH automatically, and does not change authentication, system services or motion control.
- It shows, in order, the web password, the SSH system password, and copying the connection instructions. The web password protects browser control; the SSH password is used by a computer terminal / AI assistant to log in to the radxa system account. They are saved separately and changed independently. The confirmation input is only for checking; a normal login enters it once.
- When the web password is already set, it shows as set and the change form is collapsed; when the SSH password is already enabled or a public key already exists, the existing connection information is shown without needing to reset. Public key management goes in an expandable area, keeping the old functionality.
- SSH status failure, service not running, no web login password, and operation failure are each explained separately with a retry option; registering a key or enabling a password is not treated as a successful connection.
- The connection instructions contain the verified board address, account, port 22, the login command and the password / public key method; copy is only offered when the system reports SSH running and a login method exists. The password is not involved in generating, copying or storing. When the Clipboard API is unavailable in an HTTP environment, selectable text is provided.
- Desktop width follows the settings page; on narrow screens all inputs and buttons may wrap; visible focus, form labels and step states are kept.

## Verification boundaries

Use the real Studio, an isolated fake robotd, and a helper fixture that only replaces the system SSH boundary. The browser verifies the entry navigation, the difference between the two kinds of password, password confirmation, moving to the next step after the web password is saved, SSH enable / change / failure / retry / already enabled, public key compatibility, copying without the password, the manual path when HTTP copy fails, and the 1440/390/320 pixel layouts. Run the existing authentication, SSH helper, key and related backend regressions. Tests do not connect to the physical duck, do not make system SSH changes, do not enable motion, and do not publish upgrade packages.
