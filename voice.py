import whisper
import pyaudio
import wave
import os
import shutil
import tempfile
import time
import re
import json
from difflib import SequenceMatcher
import numpy as np

try:
    from vosk import Model as VoskModel, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
except Exception:
    VoskModel = None
    KaldiRecognizer = None

class VoiceListener:
    def __init__(self, model_size="tiny", device_index=None, voice_config=None):
        if not shutil.which("ffmpeg"):
            raise RuntimeError(
                "ffmpeg was not found on PATH. Whisper needs ffmpeg to transcribe audio. "
                "Install ffmpeg and restart Jarvis."
            )

        self.voice_config = voice_config or {}
        self.wake_engine = self.voice_config.get("wake_engine", "vosk")
        self.command_engine = self.voice_config.get("command_engine", "whisper")
        self.require_wake_phrase = self.voice_config.get("require_wake_phrase", True)
        self.vosk_model_path = self.voice_config.get(
            "vosk_model_path",
            os.path.join(os.path.dirname(__file__), "models", "vosk-model-small-en-us-0.15")
        )

        print("[Jarvis] Loading Whisper voice model...")
        self.model = whisper.load_model(model_size)
        self.sample_rate = 16000
        self.chunk = 1024
        self.channels = 1
        self.format = pyaudio.paInt16
        self.silence_threshold = self.voice_config.get("silence_threshold", 180)
        self.peak_threshold = self.voice_config.get("peak_threshold", 1200)
        self.wake_mean_threshold = self.voice_config.get("wake_mean_threshold", 180)
        self.wake_peak_threshold = self.voice_config.get("wake_peak_threshold", 2000)
        self.silence_duration = self.voice_config.get("silence_duration_seconds", 1.2)
        self.min_record_seconds = self.voice_config.get("min_record_seconds", 0.8)
        self.command_start_grace_seconds = self.voice_config.get("command_start_grace_seconds", 2.5)
        self.max_command_seconds = self.voice_config.get("max_command_seconds", 8)
        configured_device = self.voice_config.get("microphone_device_index")
        self.device_index = device_index if device_index is not None else configured_device
        self.device_index = self.device_index if self.device_index is not None else self.find_microphone()
        self.device_name = self.get_device_name(self.device_index)
        self.vosk_model = self.load_vosk_model()
        self.calibrate_noise()
        print("[Jarvis] Voice model ready.")

    def get_device_name(self, device_index):
        p = pyaudio.PyAudio()
        try:
            info = p.get_device_info_by_index(device_index)
            return info.get("name", f"device {device_index}")
        except Exception:
            return f"device {device_index}"
        finally:
            p.terminate()

    def load_vosk_model(self):
        if self.wake_engine != "vosk":
            print(f"[Jarvis] Wake engine: {self.wake_engine}")
            return None

        if VoskModel is None or KaldiRecognizer is None:
            print("[Jarvis] Vosk is not installed; falling back to Whisper wake checks.")
            self.wake_engine = "whisper"
            return None

        if not os.path.isdir(self.vosk_model_path):
            print(f"[Jarvis] Vosk model not found: {self.vosk_model_path}")
            print("[Jarvis] Falling back to Whisper wake checks until the Vosk model is installed.")
            self.wake_engine = "whisper"
            return None

        print(f"[Jarvis] Loading Vosk wake model: {self.vosk_model_path}")
        return VoskModel(self.vosk_model_path)

    def find_microphone(self):
        """Auto find the strongest working microphone."""
        p = pyaudio.PyAudio()
        best_device = None
        best_name = ""
        best_score = -1

        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            name = info['name'].lower()
            max_input = info['maxInputChannels']

            if max_input <= 0:
                continue

            if any(blocked in name for blocked in ["stereo mix", "speaker", "output", "hands-free"]):
                continue

            try:
                host_api = p.get_host_api_info_by_index(info.get("hostApi", 0)).get("name", "").lower()
                stream = p.open(
                    format=self.format,
                    channels=self.channels,
                    rate=self.sample_rate,
                    input=True,
                    input_device_index=i,
                    frames_per_buffer=self.chunk
                )

                started = time.time()
                levels = []
                peak = 0
                sample_chunks = 20
                for _ in range(sample_chunks):
                    data = stream.read(self.chunk, exception_on_overflow=False)
                    audio_array = np.frombuffer(data, dtype=np.int16)
                    levels.append(float(np.abs(audio_array).mean()))
                    peak = max(peak, int(np.abs(audio_array).max()))
                elapsed = time.time() - started

                stream.stop_stream()
                stream.close()

                expected = (self.chunk * sample_chunks) / self.sample_rate
                if elapsed < expected * 0.5:
                    continue

                mean_level = sum(levels) / len(levels)
                default_rate = float(info.get("defaultSampleRate", 0))
                preferred_keywords = self.voice_config.get("preferred_mic_keywords", ["microphone array", "realtek"])

                name_bonus = 0
                if "sound mapper" in name:
                    name_bonus -= 250
                if "primary sound" in name:
                    name_bonus -= 200
                if host_api == "mme":
                    name_bonus -= 120
                if "directsound" in host_api:
                    name_bonus += 120
                if any(word in name for word in ["microphone", "mic", "array"]):
                    name_bonus += 150
                if "realtek" in name:
                    name_bonus += 150
                if all(keyword.lower() in name for keyword in preferred_keywords):
                    name_bonus += 250
                if abs(default_rate - self.sample_rate) < 1:
                    name_bonus += 300

                score = mean_level + (peak * 0.02) + name_bonus

                if score > best_score:
                    best_score = score
                    best_device = i
                    best_name = info['name']
            except Exception:
                continue

        p.terminate()

        if best_device is None:
            best_device = 1  # fallback to device 1
            print(f"[Jarvis] Using default mic device 1")
        else:
            print(f"[Jarvis] Mic found: {best_name} (device {best_device})")
        
        return best_device

    def calibrate_noise(self, seconds=1.5):
        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk
        )

        print(f"[Jarvis] Calibrating room noise from: {self.device_name} (device {self.device_index})")
        means = []
        peaks = []
        chunks = max(1, int(self.sample_rate / self.chunk * seconds))
        for _ in range(chunks):
            data = stream.read(self.chunk, exception_on_overflow=False)
            audio_array = np.frombuffer(data, dtype=np.int16)
            means.append(float(np.abs(audio_array).mean()))
            peaks.append(int(np.abs(audio_array).max()))

        stream.stop_stream()
        stream.close()
        p.terminate()

        noise_mean = float(np.median(means)) if means else 0
        noise_peak = int(np.median(peaks)) if peaks else 0
        self.noise_mean = noise_mean
        self.noise_peak = noise_peak

        # Wake detection stays strict, but post-wake command capture must be permissive.
        self.silence_threshold = max(90, min(int(noise_mean * 1.15 + 50), 220))
        self.peak_threshold = max(500, min(int(noise_peak * 1.15 + 180), 900))
        self.wake_mean_threshold = max(self.wake_mean_threshold, int(noise_mean * 3.0 + 120))
        self.wake_peak_threshold = max(self.wake_peak_threshold, int(noise_peak * 2.0 + 700))

        print(
            "[Jarvis] Noise calibrated: "
            f"mean {noise_mean:.0f}, peak {noise_peak}, "
            f"silence threshold {self.silence_threshold}, wake peak {self.wake_peak_threshold}"
        )

    def is_silent(self, data):
        audio_array = np.frombuffer(data, dtype=np.int16)
        mean_level = np.abs(audio_array).mean()
        peak_level = np.abs(audio_array).max()
        return mean_level < self.silence_threshold and peak_level < self.peak_threshold

    def audio_stats(self, frames):
        if not frames:
            return 0, 0
        audio_array = np.frombuffer(b''.join(frames), dtype=np.int16)
        if audio_array.size == 0:
            return 0, 0
        return float(np.abs(audio_array).mean()), int(np.abs(audio_array).max())

    def normalized_audio(self, frames):
        audio_array = np.frombuffer(b''.join(frames), dtype=np.int16)
        if audio_array.size == 0:
            return b''

        peak = np.abs(audio_array).max()
        if peak == 0:
            return audio_array.tobytes()

        gain = min(20.0, 28000.0 / peak)
        normalized = np.clip(audio_array.astype(np.float32) * gain, -32768, 32767).astype(np.int16)
        return normalized.tobytes()

    def has_enough_speech(self, frames):
        mean_level, peak_level = self.audio_stats(frames)
        duration = (len(frames) * self.chunk) / self.sample_rate
        mean_floor = 45
        peak_floor = 350
        enough_energy = mean_level >= mean_floor or peak_level >= peak_floor
        enough_time = duration >= self.min_record_seconds
        if not enough_energy or not enough_time:
            print(
                "[Jarvis] Command audio rejected as too quiet/short "
                f"(duration {duration:.1f}s, mean {mean_level:.0f}, peak {peak_level})."
            )
            return False
        return True

    def wake_phrases(self, wake_word="jarvis"):
        if isinstance(wake_word, (list, tuple)):
            phrases = [str(phrase).strip().lower() for phrase in wake_word if str(phrase).strip()]
        else:
            phrases = [str(wake_word).strip().lower()]
        return phrases or ["jarvis"]

    def wake_phrase_variants(self, wake_word="jarvis"):
        variants = set()
        for phrase in self.wake_phrases(wake_word):
            pending = {phrase}
            for _ in range(3):
                next_pending = set(pending)
                for item in pending:
                    next_pending.add(item.replace("wakeup", "wake up"))
                    next_pending.add(item.replace("wake up", "wakeup"))
                    next_pending.add(item.replace("daddy's", "daddys"))
                    next_pending.add(item.replace("daddy's", "daddies"))
                    next_pending.add(item.replace("daddy's", "daddy is"))
                    next_pending.add(item.replace("daddys", "daddy is"))
                    next_pending.add(item.replace("daddies", "daddy is"))
                pending = next_pending
            variants.update(pending)

        # Keep common Jarvis mishearings only as part of the chosen phrase. This
        # avoids waking on every random "darius/garlic" style transcript.
        expanded = []
        for phrase in variants:
            expanded.append(phrase)
            if "jarvis" in phrase:
                for bad in ["jervis", "jarves", "jarvish", "jalvis"]:
                    expanded.append(phrase.replace("jarvis", bad))

        seen = set()
        unique = []
        for phrase in expanded:
            normalized = " ".join(self.normalized_words(phrase))
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(normalized)
        return unique

    def normalized_words(self, text):
        return re.findall(r"[a-z0-9]+", text.lower())

    def contains_word_sequence(self, words, sequence):
        if not sequence or len(sequence) > len(words):
            return -1
        for index in range(len(words) - len(sequence) + 1):
            if words[index:index + len(sequence)] == sequence:
                return index
        return -1

    def is_wake_text(self, text, wake_word="jarvis"):
        words = self.normalized_words(text)
        if not words:
            return False

        for phrase in self.wake_phrase_variants(wake_word):
            sequence = self.normalized_words(phrase)
            if self.contains_word_sequence(words, sequence) >= 0:
                return True

        return False

    def command_from_wake_text(self, text, wake_word="jarvis"):
        words = self.normalized_words(text)
        matches = []
        for phrase in self.wake_phrase_variants(wake_word):
            sequence = self.normalized_words(phrase)
            index = self.contains_word_sequence(words, sequence)
            if index >= 0:
                matches.append((index, len(sequence)))

        if not matches:
            return ""

        index, length = max(matches, key=lambda item: item[1])
        command_words = words[index + length:]
        if not command_words:
            return ""

        one_word_shortcuts = {
            "time",
            "date",
            "screenshot",
            "telegram",
            "workspace",
            "lock",
            "sleep",
            "shutdown",
            "restart",
            "cancel",
            "unlock",
            "wake",
            "status",
        }
        if len(command_words) == 1 and command_words[0] not in one_word_shortcuts:
            return ""

        return " ".join(command_words).strip()

        return ""

    def record_command(self):
        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk
        )

        print("[Jarvis] Listening for command...")
        frames = []
        silent_chunks = 0
        max_silent_chunks = int(self.sample_rate / self.chunk * self.silence_duration)
        min_chunks = int(self.sample_rate / self.chunk * self.min_record_seconds)
        grace_chunks = int(self.sample_rate / self.chunk * self.command_start_grace_seconds)
        max_chunks = int(self.sample_rate / self.chunk * self.max_command_seconds)

        while True:
            data = stream.read(self.chunk, exception_on_overflow=False)
            frames.append(data)
            if len(frames) >= max_chunks:
                print("[Jarvis] Command recording reached max duration.")
                break
            if len(frames) > min_chunks:
                if self.is_silent(data):
                    if len(frames) > grace_chunks:
                        silent_chunks += 1
                else:
                    silent_chunks = 0
                if silent_chunks >= max_silent_chunks:
                    break

        stream.stop_stream()
        stream.close()
        p.terminate()
        return frames

    def transcribe(self, frames):
        if not self.has_enough_speech(frames):
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        p = pyaudio.PyAudio()
        wf = wave.open(tmp_path, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(p.get_sample_size(self.format))
        wf.setframerate(self.sample_rate)
        wf.writeframes(self.normalized_audio(frames))
        wf.close()
        p.terminate()

        result = self.model.transcribe(
            tmp_path,
            language="en",
            fp16=False,
            initial_prompt="The user is speaking English commands to an assistant named Jarvis.",
        )
        os.unlink(tmp_path)
        text = result["text"].strip().lower()
        no_speech_prob = result.get("segments", [{}])[0].get("no_speech_prob", 0) if result.get("segments") else 0
        if no_speech_prob and no_speech_prob > 0.75:
            print(f"[Jarvis] Whisper rejected likely silence/noise (no_speech_prob={no_speech_prob:.2f}).")
            return ""
        if self.is_bad_transcript(text):
            print(f"[Jarvis] Whisper rejected likely hallucination: {text}")
            return ""
        print(f"[Jarvis] You said: {text}")
        return text

    def is_bad_transcript(self, text):
        text = (text or "").strip().lower()
        if not text:
            return True
        words = self.normalized_words(text)
        if len(words) == 1 and words[0] in {"you", "i", "a", "the", "ok", "okay", "uh", "um"}:
            return True
        if len(text) > 80 and len(set(words)) <= 4:
            return True
        return False

    def listen_for_wake_word(self, wake_word="jarvis"):
        if self.wake_engine == "vosk" and self.vosk_model is not None:
            return self.listen_for_wake_word_vosk(wake_word)

        return self.listen_for_wake_word_whisper(wake_word)

    def listen_for_wake_word_vosk(self, wake_word="jarvis"):
        wake_phrases = self.wake_phrases(wake_word)
        print(f"[Jarvis] Waiting for wake phrase with Vosk: {', '.join(wake_phrases)}")
        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk
        )

        grammar_phrases = self.wake_phrase_variants(wake_word)
        grammar = json.dumps(grammar_phrases + ["[unk]"])
        recognizer = KaldiRecognizer(self.vosk_model, self.sample_rate, grammar)

        while True:
            data = stream.read(self.chunk, exception_on_overflow=False)
            mean_level, peak_level = self.audio_stats([data])
            if mean_level < self.wake_mean_threshold * 0.35 and peak_level < self.wake_peak_threshold * 0.45:
                continue

            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result() or "{}")
                text = (result.get("text") or "").strip().lower()
                if text:
                    print(f"[Jarvis] Vosk wake heard: {text}")
                if self.is_wake_text(text, wake_word):
                    print("[Jarvis] Wake word detected by Vosk!")
                    stream.stop_stream()
                    stream.close()
                    p.terminate()
                    return text
            else:
                partial = json.loads(recognizer.PartialResult() or "{}").get("partial", "").strip().lower()
                if partial and self.is_wake_text(partial, wake_word):
                    print(f"[Jarvis] Vosk partial wake heard: {partial}")
                    print("[Jarvis] Wake word detected by Vosk!")
                    stream.stop_stream()
                    stream.close()
                    p.terminate()
                    return partial

    def listen_for_wake_word_whisper(self, wake_word="jarvis"):
        wake_phrases = self.wake_phrases(wake_word)
        print(f"[Jarvis] Waiting for wake phrase: {', '.join(wake_phrases)}")
        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk
        )

        frames = []
        chunk_count = 0
        check_every = int(self.sample_rate / self.chunk * 2)

        while True:
            data = stream.read(self.chunk, exception_on_overflow=False)
            frames.append(data)
            chunk_count += 1

            if chunk_count >= check_every:
                mean_level, peak_level = self.audio_stats(frames)
                if mean_level < self.wake_mean_threshold and peak_level < self.wake_peak_threshold:
                    keep = int(self.sample_rate / self.chunk * 1)
                    frames = frames[-keep:]
                    chunk_count = len(frames)
                    continue

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name

                p2 = pyaudio.PyAudio()
                wf = wave.open(tmp_path, 'wb')
                wf.setnchannels(self.channels)
                wf.setsampwidth(p2.get_sample_size(self.format))
                wf.setframerate(self.sample_rate)
                wf.writeframes(self.normalized_audio(frames))
                wf.close()
                p2.terminate()

                result = self.model.transcribe(
                    tmp_path,
                    language="en",
                    fp16=False,
                    initial_prompt=f"The wake phrase is one of: {', '.join(wake_phrases)}.",
                )
                os.unlink(tmp_path)
                text = result["text"].strip().lower()
                if text:
                    print(f"[Jarvis] Heard wake check: {text}")
                elif peak_level >= self.peak_threshold:
                    print(f"[Jarvis] Wake audio detected but no words yet (mean {mean_level:.0f}, peak {peak_level}).")

                if self.is_wake_text(text, wake_word):
                    print(f"[Jarvis] Wake word detected!")
                    stream.stop_stream()
                    stream.close()
                    p.terminate()
                    return text

                keep = int(self.sample_rate / self.chunk * 1)
                frames = frames[-keep:]
                chunk_count = len(frames)
