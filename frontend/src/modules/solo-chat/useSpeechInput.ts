"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { transcribeAudio } from "@/matrix/client";

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onerror: ((ev: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
  }>;
};

function getSpeechRecognitionCtor():
  | (new () => SpeechRecognitionLike)
  | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export type SpeechMode = "idle" | "listening" | "recording" | "transcribing";

/**
 * 语音输入：优先 Web Speech；不支持或失败时 MediaRecorder → /api/v1/stt。
 */
export function useSpeechInput(opts: {
  sessionId?: string;
  onTranscript: (text: string, opts?: { replaceInterim?: boolean }) => void;
  onError?: (message: string) => void;
}) {
  const { sessionId, onTranscript, onError } = opts;
  const [mode, setMode] = useState<SpeechMode>("idle");
  const [webSpeechSupported, setWebSpeechSupported] = useState(false);
  const recogRef = useRef<SpeechRecognitionLike | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const preferServerRef = useRef(false);
  const onTranscriptRef = useRef(onTranscript);
  const onErrorRef = useRef(onError);
  onTranscriptRef.current = onTranscript;
  onErrorRef.current = onError;

  useEffect(() => {
    setWebSpeechSupported(Boolean(getSpeechRecognitionCtor()));
  }, []);

  const stopMediaTracks = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };

  const stopAll = useCallback(() => {
    try {
      recogRef.current?.abort();
    } catch {
      // ignore
    }
    recogRef.current = null;
    const rec = mediaRef.current;
    if (rec && rec.state !== "inactive") {
      try {
        rec.stop();
      } catch {
        // ignore
      }
    }
    mediaRef.current = null;
    stopMediaTracks();
    setMode("idle");
  }, []);

  useEffect(() => () => stopAll(), [stopAll]);

  const startServerRecording = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      onErrorRef.current?.("当前环境无法访问麦克风。");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";
      const recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);
      mediaRef.current = recorder;
      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data);
      };
      recorder.onstop = async () => {
        stopMediaTracks();
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        chunksRef.current = [];
        mediaRef.current = null;
        if (blob.size < 200) {
          setMode("idle");
          onErrorRef.current?.("录音太短，请再说长一点。");
          return;
        }
        setMode("transcribing");
        try {
          const { text } = await transcribeAudio(blob, sessionId);
          if (text.trim()) {
            onTranscriptRef.current(text.trim());
          } else {
            onErrorRef.current?.("没有听清内容。");
          }
        } catch (e) {
          onErrorRef.current?.(e instanceof Error ? e.message : String(e));
        } finally {
          setMode("idle");
        }
      };
      recorder.start();
      setMode("recording");
    } catch (e) {
      setMode("idle");
      onErrorRef.current?.(
        e instanceof Error ? e.message : "无法打开麦克风，请检查权限。",
      );
    }
  }, [sessionId]);

  const startWebSpeech = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      void startServerRecording();
      return;
    }
    try {
      const recog = new Ctor();
      recog.lang = "zh-CN";
      recog.continuous = true;
      recog.interimResults = true;
      recog.onresult = (ev) => {
        let interim = "";
        let finalChunk = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const piece = ev.results[i][0]?.transcript || "";
          if (ev.results[i].isFinal) finalChunk += piece;
          else interim += piece;
        }
        if (finalChunk) {
          onTranscriptRef.current(finalChunk, { replaceInterim: false });
        } else if (interim) {
          onTranscriptRef.current(interim, { replaceInterim: true });
        }
      };
      recog.onerror = (ev) => {
        const code = ev.error || "error";
        if (code === "aborted" || code === "no-speech") return;
        // 不支持 / 网络错误 → 回退服务端
        if (code === "not-allowed") {
          onErrorRef.current?.("麦克风权限被拒绝。");
          setMode("idle");
          return;
        }
        preferServerRef.current = true;
        try {
          recog.abort();
        } catch {
          // ignore
        }
        void startServerRecording();
      };
      recog.onend = () => {
        if (recogRef.current === recog) {
          recogRef.current = null;
          setMode((m) => (m === "listening" ? "idle" : m));
        }
      };
      recogRef.current = recog;
      recog.start();
      setMode("listening");
    } catch {
      void startServerRecording();
    }
  }, [startServerRecording]);

  const toggle = useCallback(() => {
    if (mode === "listening" || mode === "recording") {
      if (mode === "listening") {
        try {
          recogRef.current?.stop();
        } catch {
          // ignore
        }
        recogRef.current = null;
        setMode("idle");
        return;
      }
      if (mode === "recording") {
        try {
          mediaRef.current?.stop();
        } catch {
          // ignore
        }
        return;
      }
    }
    if (mode === "transcribing") return;
    if (preferServerRef.current || !getSpeechRecognitionCtor()) {
      void startServerRecording();
    } else {
      startWebSpeech();
    }
  }, [mode, startServerRecording, startWebSpeech]);

  /** 强制走服务端 STT（录音 → 转写） */
  const toggleServer = useCallback(() => {
    if (mode === "recording") {
      try {
        mediaRef.current?.stop();
      } catch {
        // ignore
      }
      return;
    }
    if (mode === "listening") {
      try {
        recogRef.current?.abort();
      } catch {
        // ignore
      }
      recogRef.current = null;
    }
    if (mode === "transcribing") return;
    preferServerRef.current = true;
    void startServerRecording();
  }, [mode, startServerRecording]);

  return {
    mode,
    webSpeechSupported,
    toggle,
    toggleServer,
    stop: stopAll,
    busy: mode === "transcribing",
    active: mode === "listening" || mode === "recording",
  };
}
