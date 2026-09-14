/**
 * Sahara Healthcare Suite - Audio Worklet PCM Processor
 * Resilient Audio Buffer & Continuous Queue
 * Converts Float32 audio stream to 16-bit PCM buffer with loss-prevention queueing.
 */

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 4096;
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
    this.isPaused = false;

    this.port.onmessage = (event) => {
      if (event.data.command === 'PAUSE') {
        this.isPaused = true;
      } else if (event.data.command === 'RESUME') {
        this.isPaused = false;
      } else if (event.data.command === 'FLUSH') {
        this.flushBuffer();
      }
    };
  }

  process(inputs, outputs, parameters) {
    if (this.isPaused) return true;

    const input = inputs[0];
    if (input && input.length > 0) {
      const channelData = input[0]; // Mono input channel

      for (let i = 0; i < channelData.length; i++) {
        this.buffer[this.bufferIndex++] = channelData[i];

        if (this.bufferIndex >= this.bufferSize) {
          this.flushBuffer();
        }
      }
    }
    return true;
  }

  flushBuffer() {
    if (this.bufferIndex === 0) return;

    // Convert Float32Array to 16-bit PCM Int16Array
    const pcm16 = new Int16Array(this.bufferIndex);
    for (let i = 0; i < this.bufferIndex; i++) {
      const s = Math.max(-1, Math.min(1, this.buffer[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }

    // Transfer raw PCM buffer to main thread for network transmission or local buffering
    this.port.postMessage(
      {
        eventType: 'pcmdata',
        pcmBuffer: pcm16.buffer
      },
      [pcm16.buffer]
    );

    // Reset buffer state
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
