# Studio camera and ToF

**English** · [简体中文](2026-10-23-sensors-design.md)

The user proposed adding camera and ToF, and explicitly confirmed: both go between "手柄" (Gamepad) and "舵机" (Servos) in the left navigation, each as a standalone page, providing the picture, readings and connection status. Development continues locally only, without connecting to or updating the board.

## Pages and scope

- The navigation is Overview, Gamepad, Camera, ToF, Servos, IMU, Models, Logs, Settings. Phones can also reach these two pages, and the touch entries stay usable.
- The camera page connects to the existing mediad LAN WebRTC video signaling (default 8443). It does not embed the old console with motion controls. The page can start/stop the preview and reconnect, and shows connecting/negotiating/playing/failed, the actual video dimensions and reception status. It connects automatically on first entry; leaving or hiding the page closes the video and signaling, and returning reconnects.
- The camera source distinguishes camera/test/unknown in the configuration from the runtime producer's simulated metadata; a configured source cannot pass itself off as verified real hardware. When an existing image defaults to the test picture, this is stated explicitly. Only media.video metadata is requested; no motion is sent, no settings are changed, nothing is recorded and no video is uploaded.
- The ToF page provides an 8×8 distance heatmap, the number of valid cells, the nearest/farthest valid distance, the sensor model and the update time. Each cell can show its millimeter value and raw status; only status 5/9 with distance > 0 is valid, 255 is no target, and everything else is invalid; no target/errors are not drawn as 0mm obstacles.
- ToF uses the existing tofd tof.stream read-only interface and fetches the latest frame on demand; background/leaving stops polling, and it does not continuously occupy the serial port or the motion RPC. The geometry is fixed at 8×8, and arrays, values, message size and read timeout are strictly validated; missing sensor, service offline, waiting for the first frame, bad data and disconnection are each explained separately.
- This round adds no obstacle avoidance/navigation, does not change servo or motion protections, does not start/restart system services, and does not modify image configuration. An unavailable service is shown truthfully, and demo data cannot pass itself off as hardware.

## Boundaries and architecture

Studio adds sensors.py, providing a read-only configuration summary CameraInfo and on-demand ToF snapshots. The HTTP endpoints GET /api/camera and GET /api/tof both use the existing login/Host checks and no-store. ToF reads use a separate connection, an overall timeout and merging of concurrent requests, and do not block the e-stop. ToF JSON is capped at 64KiB, and arbitrary client addresses are not accepted. The CLI provides controlled development/install address configuration; the web page does not accept a socket or URL.

CameraInfo: `{source:'camera'|'test'|'unknown', source_label, source_basis:'config', source_verified:false, signaling_port:8443, error:null}`. By default, HTTP success only means the configuration was read; the actual video status is confirmed by the browser's handshake with mediad and video playback. When the configuration cannot be found, signaling can still be attempted; a missing configuration is not treated as a missing camera.

ToFView: `{state:'ready'|'unavailable'|'waiting'|'error', connected, sensor, reason, rows:8,cols:8,hz, seq, age_ms, distance_mm:[64],status:[64],valid_count,nearest_mm,farthest_mm, zones:[{kind:'range'|'no_target'|'unusable',mm,status}], simulated:false}`. When the runtime sensor is sim/fake, simulated must be true. With no valid frame the arrays are empty/the statistics are empty, and old values cannot be shown as current. tofd does not support hello; after connecting, it requests tof.stream directly.

The WebRTC client is a standalone camera-link.js, reusing the existing GStreamer welcome/list/startSession/sessionStarted/peer/endSession protocol. It strictly matches sessionId, processes SDP/ICE serially, and the RTCDataChannel only sends media.video read requests; the control part of the old console is not imported. Media/signaling both have failure states, release on stop, release on hide, and timeouts; candidate/negotiation messages have size limits. When no recognizable local producer exists, it fails explicitly.

## Verification

Write failing cases first, then implement: ToF valid/no target/invalid/negative distance, array errors, first-frame timeout, disconnection, read merging and socket release; camera source configuration, read-only HTTP session protection; WebRTC signaling order with real readback of video status, errors/release on stop/reconnection; browser navigation between the two pages, the 8×8 map, empty/error states, stopping requests on leave/background, and the phone layout. Tests may use clearly labeled fake sensors and video streams. Real-hardware acceptance is left until the user separately confirms the connection.
