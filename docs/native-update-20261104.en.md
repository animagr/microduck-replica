# 2026-11-04 native driver bundle update and recovery of old transactions

**English** · [简体中文](native-update-20261104.md)

This release's software package is bound to robotd `replica-imu-verify-control.48` (IPC API 43) and the published padd mapping build.
After updating the web software, you still need to explicitly confirm installation of the native driver bundle on the software update page; a change in the web version does not prove the drivers have been updated.
This release's new image comes with the pinned driver bundle preinstalled; it reports "installed" only when the full set of on-disk components matches the actual runtime health check, and it does not claim to have a recovery backup of old drivers.

Cards that already have a `2026.10.31-r1` driver bundle transaction should proceed in this order:

1. Support the duck by hand or on a stand, turn off the policy and torque, and close voice, music and activity sessions.
2. In the driver bundle section of the software update page, reconfirm and click **恢复旧配套驱动** (Restore previous driver bundle). This step restores the complete old components and service configuration saved by the original `.47`
   driver bundle transaction; your own parameters, calibration and persistent gamepad mapping configuration are kept.
3. After confirming the restore succeeded, explicitly confirm and install this release's driver bundle. The updater first saves the old transaction's original record, then creates the new transaction.
4. Only after this release's complete component vector and the actual running processes pass verification will the page report this release's driver bundle as installed.

If a restore in step 2 that was explicitly started by this release's updater is interrupted, keep the duck supported with torque off, reconfirm on the same page and click **恢复未完成的配套驱动更新** (Resume unfinished driver bundle update).
Before starting the restore, this release saves the original completed record; it only allows itself to continue the restore when that fixed restore starting point exactly matches the original component record.
An explicit restore after this release's target components have been installed uses the same check, so that the recovery entry isn't lost if the interruption happens between committing the record and writing the runtime baseline.

When the old `.47` transaction has completed, the new updater only allows the explicit restore steps above; it will not treat the old target as this release being installed,
nor directly overwrite the service configuration that transaction owns. If the old `.47` transaction is still in progress, pending recovery or pending cleanup, or has left guard files behind,
a maintainer must first recover it using the updater in the original `2026.10.31-r1` signed software package; keep the records and guard files, and do not manually delete them or start the control services.

Completed or rolled-back `.45`, `.46` and `.47` transactions created by standalone robotd updates are only accepted for explicitly registered predecessor SHA256 combinations.
Once their final-state identity is verified against the current on-disk bytes, the history can be saved and upgraded; unfinished transactions are still recovered by the original signed version.
Unknown binaries, modified backups, user files or service configuration, a wrong IPC API, and missing or tampered software packages continue to be rejected.

This description of the mechanism and the automated tests do not replace acceptance checks with real hardware running.
