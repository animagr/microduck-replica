# HD1910M Servo Test Tool (feetech-HD1910M-tester)

**English** · [简体中文](README.md)

A Rust-based test tool for the Feetech HD1910M serial bus servo (FT-SCS protocol),
covering every readable/writable register in the official memory table: ID/baud rate settings, position/speed/current three-loop PID,
torque and force control, operating mode, protection parameters, angle limits and zero calibration (0x0B), EPROM locking, real-time monitoring, and more.

## Quick start

```bash
cargo build
./target/debug/hd1910-tester scan      # Scan for servos (with progress bar)
./target/debug/hd1910-tester dump      # Read the whole memory table
./target/debug/hd1910-tester monitor   # Monitor feedback in real time
./target/debug/hd1910-tester --help    # All commands
```

## Documentation

For the complete tutorial manual (protocol explanation + Rust concepts + hands-on experiments), see **[TUTORIAL.md](TUTORIAL.md)**.

## The two bundled Feetech datasheets

| File | What it is | Relation to the duck |
|---|---|---|
| [`HD-1910-C001串型规格书20260907.pdf`](HD-1910-C001串型规格书20260907.pdf) | **The servo used in this project**. 4–8.4 V, gear ratio 1:320, stall torque 15 kg·cm @7.4 V. Overvoltage protection threshold 10 V, undervoltage 4 V, so a fully charged 2S battery at 8.4 V is within range | ✅ All 15 servos in the duck are this model |
| [`HL-2915-C002串型规格书20260227.pdf`](HL-2915-C002串型规格书20260227.pdf) | Another Feetech servo. **9–14 V (3S battery)**, 22.5 g, gear ratio 1:320 | ⚠️ **Not used in this project, for reference only**. Its voltage is incompatible with the duck's 2S battery; compare against it if you want to switch to a 3S setup |

Both are the original datasheets issued by Feetech, with the specification content unchanged. **The contact person's name and mobile/WeChat number have been redacted**
(the originals printed a salesperson's personal contact details, which are not appropriate for a public repo); the HD-1910 one is the official version whose contact is the company landline.
To contact Feetech, use the official website [www.feetech.cn](https://www.feetech.cn) or the company phone number 0755-89335266.

Feetech's protocol manual, memory table, and other public materials from their website are in the repo's [`docs/飞特资料/`](../../docs/飞特资料/).

## Testing

```bash
cargo test    # Protocol-layer / memory-table-layer unit tests (no hardware required)
```
