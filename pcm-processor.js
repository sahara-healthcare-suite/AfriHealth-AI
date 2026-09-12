class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0]) {
      const inputData = input[0];
      const ratio = sampleRate / 16000;
      const newLength = Math.floor(inputData.length / ratio);
      const pcm16 = new Int16Array(newLength);
      for (let i = 0; i < newLength; i++) {
        const s = Math.max(-1, Math.min(1, inputData[Math.floor(i * ratio)]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
