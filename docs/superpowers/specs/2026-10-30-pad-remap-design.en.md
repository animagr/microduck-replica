# Gamepad remapping / calibration

**English** · [简体中文](2026-10-30-pad-remap-design.md)

The user has confirmed the emulator-style button learning approach and asked for a complete implementation: click the target button in the web page, then press the button on the physical gamepad; dual stick / trigger calibration, test and save, load on reconnect. Together with the earlier AI SSH guide, it stays on the local software branch, and for now is not released or deployed to the physical board.

## UI and responsibilities

Add "重新映射／校准" (Remap / Calibrate) next to the gamepad title, opening a standalone learning panel. Button targets include south/east/west/north (the standard positions of A/B/X/Y), LB/RB, Select/Start, the four directions, L3/R3, and optional Home; supports selecting item by item, re-recording, skipping optional items, cancel and restore defaults. The four stick axes and LT/RT can be chosen as an axis source or a digital trigger source; a stick starts in the specified positive direction, is pushed to both ends and recentered to confirm, and a trigger is pressed fully and released to confirm. Before saving, live testing is available while motion output remains forbidden. The relationship between the standard button positions in the diagram and the labels printed on the user's physical gamepad must be made explicit.

Normal mapping is applied in padd by a single binding of the raw input and read back to the web page. The default device keeps the existing gilrs path; custom devices are saved keyed by a combination of the kernel bus type, vendor / product and capabilities, with Bluetooth / USB modes kept separate. When the old driver lacks the new capability, it explicitly prompts to upgrade the matching padd, and the web page is not allowed to fake a save or only change icons.

## Driver boundary and wire protocol v1

Keep `/run/padd/pad.sock` as the read-only raw input stream. Add `/run/padd/mapping.sock`, owned by padd, robot group 0660; it only accepts one length-limited line of JSON and returns one line of JSON, with bounded timeouts / concurrency. The new interface has its own `version:1` and does not fabricate support for older versions. The default persistence directory is `/var/lib/padd`, systemd `StateDirectory=padd`, saved atomically to `mappings.json`; a new command-line parameter allows an isolated test directory.

Request format `{op, ...}`; response `{ok:true,version:1,status:{...},token?:string}` or `{ok:false,version:1,error:string,code:string}`.

- `status`: read-only.
- `begin {device_id}`: the main program must be able to prove the policy is stopped and it is not in a transition state; an unpredictable session token is returned only after the main loop confirms output is paused.
- `renew {token}`: the session lease is 5 seconds. The page renews every second; it does not renew indefinitely in the background.
- `preview {token,bindings}`: validates and saves an in-memory draft, reads back the preview state, and does not write to disk / resume motion.
- `save {token,name,bindings}`: validates the complete configuration and saves it atomically, switches into the waiting-for-recenter state, clears old button edges, and counts as saved only when the readback succeeds.
- `cancel {token}`: discards the draft, keeps the old configuration, and waits for all buttons to be released / sticks recentered.
- `reset {token}`: deletes the current device's custom configuration and returns to the default mapping, likewise waiting for recentering.

Exact `status` fields:

```
device: null | {id,name,node,unique?,bus,vendor,product,axes:[{code,name,min,max,flat,fuzz,value}],buttons:[{code,name,pressed}]}
raw: {seq:u64,buttons:{decimal_code:bool},axes:{decimal_code:i32},events:[{seq:u64,kind:u16,code:u16,value:i32}]} | null
mapped: {buttons:{role:bool},axes:{lx,ly,rx,ry,lt,rt}} | null
preview: same shape as mapped, or null
profile: null | {schema:1,name,bindings:{role:binding}}
session: null | {phase:"learning"|"waiting_neutral",remaining_ms:u64}
output_blocked: bool
```

The session token is only returned by begin and is not exposed in ordinary status. raw.events is a bounded recent event history, each with a monotonic seq; the client learns by cursor and must not mistake a button already pressed before learning started. Device replacement / dropout and SYN_DROPPED invalidate the capture and pause it, waiting for a fresh re-read and recentering.

Binding shapes:

```
key: {kind:"key",code:u16}
axis_button: {kind:"axis_button",code:u16,value:-1|1}  # digital D-pad hat
axis: {kind:"axis",code:u16,min:i32,max:i32,center:i32,invert:bool,deadzone:f64}
```

buttons use key or the digital D-pad hat; LT/RT can use key or axis; lx/ly/rx/ry must be axis. Coordinates are uniformly positive to the right / downward, triggers 0..1; the Y-axis difference between padd and gilrs is converted only at the boundary. Ranges and source capabilities are strictly validated, and the same button / same hat direction / same axis cannot be bound twice (hat positive and negative can be used separately). Saving requires Select, Start, lx/ly/rx/ry; others may be skipped, and unset ones trigger no action. Data, files, roles and the number of devices are all bounded.

## Safety and sessions

Learning only reads raw data and sends no actions. On pause, continuous velocity, posture latches and mouth targets are cleared once, and skills, mode switching, long-press shutdown and R3 voice are forbidden; web torque off is kept. The pause does not pretend the gamepad is lost and does not trigger the auto sit-down on loss. After ending, timeout, disconnection or device replacement, output resumes only after neutral input is stable; old edges and long-press timers cannot carry across sessions.

Studio holds the token exclusively per page connection conn; other tabs can see the status but cannot change this session. Closing, going to the background or navigating away cancels or stops lease renewal. Before starting, web action sessions, motion, calibration / servo sessions and updates are rejected, and during learning other web action entries are rejected. The original program on the board must still independently enforce the pause / recenter gating; it cannot rely only on the web page blocking.

## Verification

Rust synthesizes raw frames to verify A/B swapping, stick axis swapping / inversion / recentering / deadzone, digital and analog triggers, hat axes, save and re-read, identity mode isolation, abnormal files and lease / edge gating. Python unit tests verify learning, the normalization contract and session ownership, with serial / input all using isolated fixtures. A real browser uses a same-shape driver fixture to verify from clicking a button to learn through save and readback, reconnection, restore defaults and the phone layout; confirming there are no robot motion requests. Linux verifies the actual padd control loop, and ARM64 builds padd. Acceptance with real gamepads of different models is listed separately, and software simulation is not presented as a substitute for physical hardware.
