# A7Z web console frontend integration

**English** · [简体中文](README.md)

Connects the approved v18 page structure to the original Studio's Preact, WebSocket, authentication and business interfaces. The install package only updates changed files in `web/`; it does not install the backend, models, the development simulator or local state.

Installed on `cubie-XXXX` on Nov 9, 2026: <http://BOARD_IP:8000/>, release `20261109-console1`. Only the frontend was updated; the Studio/robotd PIDs, backend, binaries and calibration digests were all unchanged. The user confirmed that only the main controller was powered and no servos were connected; this installation used `--static-startup`, and real-world torque-off, standing and walking were not verified.

Old web page backup: `/opt/microduck-studio/console-backups/20261109T024849766301Z-c5f27ff2b853/`. The installation result is in the local `artifacts/deployment-20261109.json`; for the verification scope, see [VERIFICATION.md](VERIFICATION.en.md). Board capabilities that are not installed or are turned off are still shown as unavailable.

## Directories and baseline

- `web/`: versionable frontend changed files, not the complete Studio.
- `baseline-web.json`: SHA256 of the complete original frontend, pinned at export time. Paths start with `web/`; the original model digests are also kept for comparison, but models do not go into the payload.
- `deleted-web.json`: generated only when original files were actually deleted; its content is a list of paths relative to web. A file missing from the sparse `web/` does not mean it was deleted.
- `prepare_console.py`: rebuilds a complete local workspace from the specified upstream commit and the two A7Z patches, then overlays `web/`.
- `workspace/`: the ignored workspace, original digests and local evidence; not packaged.
- `package_console.py`: exports, generates the manifest, verifies the payload and generates a reproducible archive.
- `install_console.py`: previews by default; installs or rolls back only with an explicit `--apply`.
- `run_dev.py`: fixed entry point for local simulated-hardware integration testing; not packaged.
- `artifacts/`: ignored packages, simulated runtime state and logs; not committed to Git.

The source commit is `f682b7bd30d1ef4e6f931db16406b340d4d54fec`, followed by applying `a7z-readonly-studio.patch` and `a7z-disabled-configd-pad.patch` from the parent directory, in that order. The existing patches already include `configd none`, the 500 ms readback validity period and the 10 Hz cached query fix, and no longer overwrite the old install archive or the uninstalled tracking backend.

Both rebuilds and real installations check the following A7Z backend digests; they are not part of the frontend payload, and the installer does not rewrite them:

```text
studio/pad.py     27bbe0ae137b6e827f5b1d1b8a40a62ae57e670b19d9c36cc498ca884eaf2b5f
studio/robotd.py  8f3f4412901756fdd29fb6305b89421cbf1a9fa45e33df73e413faaef69c2750
studio/state.py   fba77fae1068faed81267bd86687e81bf6851a62e93d1ce860d4ede61fc38c77
```

## Rebuild and local integration testing

Use Python 3.13. The commands below start from the repo root; `source_repo` is the root of the repo containing the upstream commit, not its `software/studio` subdirectory.

```sh
cd radxa-cubie-a7z/studio/console-integration
python3.13 prepare_console.py /path/to/studio-replica
python3.13 -I run_dev.py --check
python3.13 -I run_dev.py
```

`prepare_console.py` refuses to overwrite existing output. If a workspace already exists, keep any unexported changes first; for an independent check, you can use `--output artifacts/rebuild/studio` to specify a directory that does not exist. Normal integration testing always uses `workspace/studio`.

Open <http://127.0.0.1:18880/> in a browser. This is the original Studio backend with simulated robotd/configd, on the fixed ports `127.0.0.1:18701`, `18702` and `18880`. The simulator refuses device Unix sockets, real serial ports, external addresses and the real helper; credentials, logs and test state are only written to a newly created `artifacts/dev-*`. `--check` does not start the listening services. Ctrl+C stops the two child processes; it does not stop existing processes or connect to the main controller.

## Verification

First run the contract and installer tests, which do not use hardware:

```sh
python3.13 -m py_compile package_console.py prepare_console.py install_console.py run_dev.py
python3.13 -m unittest discover -s tests -p 'test_*.py'
node --test tests/startup-contracts.mjs
```

The original Studio frontend regression tests run in the rebuilt workspace:

```sh
cd workspace/studio
node --test tests/models_ui_unit.mjs tests/ai_ui.test.mjs tests/ai_settings_lifecycle.test.mjs tests/updates_ui.test.mjs tests/wifi_find.mjs tests/stepper.test.mjs tests/motion_heartbeat.test.mjs tests/motion_studio_lifecycle.test.mjs
```

The installer tests use temporary directories and an injected state guard to verify hash mismatches, path/link rejection, atomic replacement, failure recovery and rollback; they do not query the main controller. The first-boot tests verify real readback evidence, unloaded models, stale servo caches, disconnection and torque-off confirmation, and cannot replace on-site action checks. Tests involving the simulated backend need local test ports to be allowed.

## Export and reproducible packaging

When changes are made only in `workspace/studio/web/`, export the changes and build:

```sh
python3.13 package_console.py --export --release 20261109-console1
```

`--export` compares `workspace/baseline-web.json` with the workspace, writes only the changed files into the versionable `web/`, and also writes `baseline-web.json` in this directory. It replaces the previously exported sparse `web/`; it does not modify the workspace. Changes to models, links, hidden files, unsupported types or the workspace backend digests make the export fail. Explicit deletions of ordinary frontend files are recorded in `deleted-web.json`.

Later, in a fresh checkout, you can build directly from the versioned frontend and digests, without depending on the workspace or a neighboring upstream repo:

```sh
python3.13 package_console.py --release 20261109-console1
```

Output:

```text
artifacts/bundle/manifest.json
artifacts/bundle/payload/web/<changed files>
artifacts/console-web-20261109-console1.tar.gz
artifacts/console-web-20261109-console1.tar.gz.sha256
artifacts/install_console.py
artifacts/install_console.py.sha256
```

The manifest format shares its verification code with the installer. For new files `before_sha256` is `null`; for deleted files `after_sha256` is `null` and there is no payload. The set of payload files must match the manifest exactly, and every SHA256 is recomputed and checked. The package contains only `bundle/manifest.json` and `bundle/payload/web/*`, without the installer, backend, `model/**`, `workspace/baseline-app.js`, `board-before`, keys, logs or Python caches.

The same release with the same inputs produces identical compressed bytes under the same Python/zlib toolchain: files are sorted by path, tar times, owners and permissions are fixed, and the gzip time and file name fields are fixed. A change in the compression toolchain may affect the gzip bytes, so recheck with the Python/zlib versions recorded at release time; the manifest and file digests are not affected by the compression method.

## Install preview, apply and rollback

The commands below are for later installation or recovery. First transfer the archive, the installer and their respective `.sha256` files from `artifacts/` using your existing authentication method; SSH passwords or private keys are not recorded in the repo. The installer and the payload are verified separately and do not go into the web directory. On the board, use the existing Studio standalone Python to avoid system Python version differences.

```sh
cd /tmp
sha256sum -c console-web-20261109-console1.tar.gz.sha256
sha256sum -c install_console.py.sha256
mkdir console-web-20261109-console1
tar -xzf console-web-20261109-console1.tar.gz -C console-web-20261109-console1
/opt/microduck-studio/python/bin/python3 install_console.py /tmp/console-web-20261109-console1/bundle --base /opt/microduck-studio/app
```

The default command only verifies the package and the current frontend digests and lists the changes, outputting `preview: true` and `readiness_checked: false`; it does not query or control the robot. If the digests do not match, check the actual version on the board first; do not edit the manifest to get around it.

Before a real apply, hand maintenance control back on the page, and have an on-site operator confirm torque is off. The installer then independently performs read-only checks: the main controller is in the expected motion mode, the policy is off, torque is confirmed off, and there are no maintenance/recovery/IMU verification tasks; it also checks the running PID, binary, calibration file and the three backend digests above. If these are not met, it refuses to publish and does not send torque-off or motion commands.

```sh
sudo /opt/microduck-studio/python/bin/python3 install_console.py /tmp/console-web-20261109-console1/bundle --base /opt/microduck-studio/app --apply
```

The installer backs up the complete web directory and then publishes by atomic directory swap; it does not restart Studio or robotd and does not change the main controller binary, configuration or calibration. It only deletes old `.gz`/`.br` caches with the same names as changed files; models and their compressed files are kept. Fingerprints and the complete web directory are checked before and after publishing, and on failure it attempts an atomic rollback. Systems that do not support atomic directory swaps are rejected outright.

The `backup` field of the successful JSON points to `/opt/microduck-studio/console-backups/<time and unique ID>/`, and `rollback_command` gives the exact rollback arguments. The backup must stay at its original path inside `base.parent/console-backups/` and remain a private directory owned by the installer. After refreshing the page, check desktop and phone, login, real status, the calibration entry, models and settings, and then have an on-site operator verify the actual functions.

Rollback also previews first; replace `BACKUP` with the real backup path from the successful output:

```sh
/opt/microduck-studio/python/bin/python3 install_console.py --rollback BACKUP --base /opt/microduck-studio/app
sudo /opt/microduck-studio/python/bin/python3 install_console.py --rollback BACKUP --base /opt/microduck-studio/app --apply
```

Rollback checks that the current complete frontend is still that installed version and that the backup digests are unchanged, then runs the same state guard and atomic swap; if the frontend has been modified separately, it refuses to roll back to avoid overwriting later work. No service restart is needed.

### Non-intrusive publishing while the main controller waits for the bus

The default `--apply` still requires motion/control, policy off and a full torque-off readback. If the main controller on site only returns `mode: motion, phase: waiting_for_bus`, the torque and policy fields may not have been read back, and it cannot be described as torque-off or hardware OK. Only an explicit `--static-startup` allows a static UI publish in this exact phase; other phases or modes never take this exception.

```sh
sudo /opt/microduck-studio/python/bin/python3.13 /tmp/install_console.py /tmp/console-web-20261109-console1/bundle --base /opt/microduck-studio/app --apply --static-startup
```

This mode only swaps the static web directory; it does not stop or start services, does not send motion, torque-on, torque-off or repair commands, and does not refresh browsers that are already open. It still refuses when maintenance is held, a home recovery/IMU verification is active or the policy is explicitly enabled, and fully checks the PID, binary, the three backend files, calibration and web fingerprints. The phase must be the same before and after publishing; if it changes, the publish is cancelled or the original web is restored.

The result explicitly outputs `static_startup: true`, `readiness_checked: false` and `torque_off_verified: false`, and the static publish is not described as the device fault having been resolved. The new page loads only after the user refreshes; a waiting main controller or unresponsive servos should be shown as they are and handled separately. Static rollback uses the same explicit argument:

```sh
sudo /opt/microduck-studio/python/bin/python3.13 /tmp/install_console.py --rollback BACKUP --base /opt/microduck-studio/app --apply --static-startup
```

If the main controller has already left `waiting_for_bus`, this command refuses; first recheck the state read-only, then choose the corresponding normal flow.
