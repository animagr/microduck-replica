# AI assistant SSH connection guide verification

**English** · [简体中文](2026-10-30-ai-ssh-guide.md)

Date: 2026-10-30 (Asia/Tokyo). Workspace: `feat/ai-ssh-guide-20261030`, based on `bfeb2e0`; local software implementation only, not released and not installed on the physical board.

## Results

- The new real Edge end-to-end test was red first: the old page has no `.overview .ai-ssh-entry` and failed as expected; the evidence is outside the workspace in `artifacts/ai-ssh-guide-20261030/red/`.
- After the implementation was finished, the new browser test passed. Final evidence: `artifacts/ai-ssh-guide-20261030/final/browser.json` and `shots/`; the page exception list is empty.
- Verified: the entry point and the settings sub-route, scrolling into position and navigation highlighting; after the web password is saved for the first time in normal mode (not dev-autologin), the new cookie/CSRF can continue to set up SSH; a mismatched confirmation password has no effect; the password input is cleared after saving; with an existing web password, existing SSH or public-key login, nothing needs to be reset; unknown status and a service that is not running do not show a copyable connection; failed operations can be retried; public-key registration and public-key-only login are kept; the connection text contains no password; when the clipboard is denied the text can be selected manually; the PowerShell public-key path keeps its backslashes.
- Widths of 1440, 390 and 320 pixels were each checked for no horizontal overflow, and screenshots of the desktop initial setup, the configured state on a phone, and the step 3 connection info/copy fallback were inspected visually.
- The command log of the fake robotd shows no `robot.init/enable/do/head/mouth/move`. The fixture only simulates the system SSH status/password calls, and the public-key directory is a dedicated temporary directory; the local system accounts, SSH service and personal keys were not modified.

## Commands run and scope

Under `software/studio`, Python 3.13, using the repo's vendored deps:

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['tests','-v','tests.test_ssh_guide_e2e'])"
```

Finally 1 test passed, 4.900 s; `SSH_GUIDE_E2E_DIR` points to the `final` directory above. An independent read-only reviewer also ran the same browser test and it passed.

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['tests','-v','tests.test_auth_log','tests.test_sshkeys','tests.test_helper_ssh','tests.test_http'])"
```

144 tests, 117.274 s, exit code 0; 2 Linux permission/symlink checks skipped on Windows. The output retains the unclosed file/socket ResourceWarnings from old tests and the audio background thread exception caused by Windows lacking `socket.AF_UNIX`; this is not a zero-warning claim. Audio and these existing tests were not modified this time, and we do not claim the full Studio test suite passes.

Old SSH card browser regression:

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['tests','-v','tests.test_commit_e2e.CommitE2E.test_01d_ssh_card_on_the_more_page'])"
node --check web/settings-access.js
node --check web/app.js
node --check tests/ssh_guide_e2e.mjs
git diff --check
```

The old browser test case passed (1 test, 3.216 s); the original assertions did not need to be changed. The JS syntax and whitespace checks both passed.

## Review and delivery limitations

The independent read-only code review is complete and found no Critical/Important/Minor issues; it re-checked the authentication session handoff, old public-key operations, keeping the password out of the connection instructions, the copy fallback, unknown status, routing and layout.

The existing 2026.10.30 software package and image keep their original release state; this work has no new version number, signed software package, GitHub push or deployment to the physical duck. The end-to-end SSH acceptance check on a real board has not been done yet.
