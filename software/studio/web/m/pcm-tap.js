// Small PCM-capture worker: every frame AudioContext processes (128 samples), it sends that frame's float samples back to the main thread.
// It's a separate file rather than a blob: stuffed into the page because iOS Safari loading an AudioWorklet from blob:
// often just fails (which shows up as "long press does nothing").
class PcmTap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(ch.slice());
    return true; // keep alive, process keeps getting called
  }
}
registerProcessor('pcm-tap', PcmTap);
