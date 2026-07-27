"use client";

/** التقاط صوت الميكروفون للتفريغ الحي (P1) — تعديل مالك 2026-07-26.
 *
 *  المخرج PCM16 أحادي بمعدل 16 kHz مُرمَّز base64 — الصيغة التي يبنيها الخادم WAV
 *  ويرسلها إلى محرك التفريغ (Gemini). الصوت لا يغادر المتصفح إلا عبر قناة الزيارة WSS.
 */

export const CAPTURE_SAMPLE_RATE = 16000;

/** معالج AudioWorklet — يُحمَّل من Blob فلا ملف عام ولا طلب شبكة إضافي. */
const WORKLET_SOURCE = `
class MedifyCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length > 0) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor("medify-capture", MedifyCaptureProcessor);
`;

export interface MicCapture {
  /** يسحب ما تجمّع من صوت منذ آخر سحب — base64 لـPCM16، أو "" إن لم يتجمّع شيء. */
  drain: () => string;
  /** الإيقاف المؤقت: يوقف التجميع دون إغلاق الميكروفون. */
  setPaused: (paused: boolean) => void;
  /** إغلاق الميكروفون وتحرير الجهاز (مؤشر التسجيل في المتصفح ينطفئ). */
  stop: () => void;
}

function floatToPcm16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index] ?? 0));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

/** إعادة تشكيل خطية إلى 16 kHz حين لا يمنح المتصفح AudioContext بالمعدل المطلوب. */
function downsample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const output = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, input.length - 1);
    const weight = position - left;
    output[index] = (input[left] ?? 0) * (1 - weight) + (input[right] ?? 0) * weight;
  }
  return output;
}

function base64FromBytes(bytes: Uint8Array): string {
  let binary = "";
  const step = 0x8000; // تفادي تجاوز حد وسائط String.fromCharCode
  for (let offset = 0; offset < bytes.length; offset += step) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + step));
  }
  return btoa(binary);
}

/** يفتح الميكروفون ويبدأ التجميع. يرمي عند رفض الإذن أو غياب الجهاز — لا تسجيل صامت. */
export async function startMicCapture(): Promise<MicCapture> {
  if (typeof navigator === "undefined" || navigator.mediaDevices?.getUserMedia === undefined) {
    throw new Error("mic_unsupported");
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });

  const AudioContextCtor: typeof AudioContext =
    typeof AudioContext !== "undefined"
      ? AudioContext
      : (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const context = new AudioContextCtor({ sampleRate: CAPTURE_SAMPLE_RATE });
  if (context.state === "suspended") await context.resume();
  const source = context.createMediaStreamSource(stream);

  const pending: Int16Array[] = [];
  let paused = false;
  let stopped = false;

  const collect = (frame: Float32Array): void => {
    if (paused || stopped) return;
    pending.push(floatToPcm16(downsample(frame, context.sampleRate, CAPTURE_SAMPLE_RATE)));
  };

  // مسار AudioWorklet (المعتمد)، مع ScriptProcessor احتياطاً للمتصفحات القديمة
  let worklet: AudioWorkletNode | null = null;
  let processor: ScriptProcessorNode | null = null;
  let workletUrl: string | null = null;
  const sink = context.createGain();
  sink.gain.value = 0; // العقدة في الرسم البياني لتُسحب العينات — بلا صوت مسموع
  sink.connect(context.destination);

  try {
    if (typeof context.audioWorklet?.addModule !== "function") throw new Error("no_worklet");
    workletUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "application/javascript" }));
    await context.audioWorklet.addModule(workletUrl);
    worklet = new AudioWorkletNode(context, "medify-capture");
    worklet.port.onmessage = (event: MessageEvent<Float32Array>) => collect(event.data);
    source.connect(worklet);
    worklet.connect(sink);
  } catch {
    processor = context.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (event) => collect(new Float32Array(event.inputBuffer.getChannelData(0)));
    source.connect(processor);
    processor.connect(sink);
  }

  return {
    drain(): string {
      if (pending.length === 0) return "";
      const total = pending.reduce((sum, part) => sum + part.length, 0);
      const merged = new Int16Array(total);
      let offset = 0;
      for (const part of pending) {
        merged.set(part, offset);
        offset += part.length;
      }
      pending.length = 0;
      return base64FromBytes(new Uint8Array(merged.buffer, merged.byteOffset, merged.byteLength));
    },
    setPaused(value: boolean): void {
      paused = value;
      if (value) pending.length = 0; // ما التُقط أثناء الإيقاف لا يُرسل
    },
    stop(): void {
      if (stopped) return;
      stopped = true;
      pending.length = 0;
      if (worklet !== null) {
        worklet.port.onmessage = null;
        worklet.disconnect();
      }
      if (processor !== null) {
        processor.onaudioprocess = null;
        processor.disconnect();
      }
      source.disconnect();
      sink.disconnect();
      for (const track of stream.getTracks()) track.stop();
      if (workletUrl !== null) URL.revokeObjectURL(workletUrl);
      void context.close().catch(() => undefined);
    },
  };
}
