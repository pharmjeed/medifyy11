"use client";

/**
 * Enhanced WebSocket manager for audio streaming with automatic recovery
 * - Exponential backoff on reconnection failures
 * - Persistent state tracking
 * - Callback-based event handling
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getPendingChunks, markSynced } from "./audio_storage";

export type ConnectionState = "disconnected" | "connecting" | "connected" | "resuming" | "error";

export interface UseAudioWsOptions {
  visitId: string;
  token: string;
  wsUrl: string;
  onStateChange?: (state: ConnectionState) => void;
  onChunkAcked?: (seq: number) => void;
  onResumeFrom?: (seq: number, pendingCount: number) => void;
  onError?: (error: string) => void;
}

export interface UseAudioWsReturn {
  state: ConnectionState;
  isConnected: boolean;
  send: (message: Record<string, unknown>) => boolean;
  pause: () => void;
  resume: () => void;
  queryResume: () => void;
  retransmitPending: () => Promise<void>;
  close: () => void;
}

export function useAudioWs(options: UseAudioWsOptions): UseAudioWsReturn {
  const [state, setState] = useState<ConnectionState>("disconnected");
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastAckedSeqRef = useRef(-1);
  const pausedRef = useRef(false);

  const setConnectionState = useCallback(
    (newState: ConnectionState) => {
      setState(newState);
      options.onStateChange?.(newState);
    },
    [options]
  );

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) return;
    if (socketRef.current?.readyState === WebSocket.CONNECTING) return;

    setConnectionState("connecting");
    const socket = new WebSocket(options.wsUrl);
    socketRef.current = socket;

    socket.onopen = () => {
      setConnectionState("resuming");
      reconnectAttemptsRef.current = 0;
      // Query server for where we should resume from
      socket.send(JSON.stringify({ type: "resume_query" }));
    };

    socket.onmessage = async (event) => {
      const message = JSON.parse(String(event.data)) as {
        type: string;
        seq?: number;
        state?: string;
        code?: string;
      };

      if (message.type === "resume_from" && message.seq !== undefined) {
        // Server says "start from this seq" — retransmit pending chunks
        const resumeSeq = message.seq;
        lastAckedSeqRef.current = resumeSeq - 1;
        const pendingChunks = await getPendingChunks(options.visitId);
        const toResend = pendingChunks.filter((c) => c.seq >= resumeSeq);

        options.onResumeFrom?.(message.seq, toResend.length);

        for (const chunk of toResend) {
          socket.send(
            JSON.stringify({
              type: "audio_chunk",
              seq: chunk.seq,
              payload: chunk.payload,
            })
          );
        }

        setConnectionState("connected");
      } else if (message.type === "ack" && message.seq !== undefined) {
        // Server confirmed receipt of this chunk
        lastAckedSeqRef.current = Math.max(lastAckedSeqRef.current, message.seq);
        await markSynced(options.visitId, [message.seq]);
        options.onChunkAcked?.(message.seq);
      } else if (message.type === "status") {
        // Connection status update
        if (message.state === "recording") {
          setConnectionState("connected");
        } else if (message.state === "paused") {
          // Status acknowledged but still connected
        }
      }
    };

    socket.onerror = () => {
      setConnectionState("error");
      options.onError?.("WebSocket connection error");
    };

    socket.onclose = () => {
      if (socketRef.current === socket) socketRef.current = null;

      // Attempt to reconnect with exponential backoff
      const delay = Math.min(1000 * Math.pow(1.5, reconnectAttemptsRef.current), 30000);
      setConnectionState("disconnected");

      reconnectTimeoutRef.current = setTimeout(() => {
        if (socketRef.current === null) {
          // Only reconnect if we haven't been explicitly closed
          reconnectAttemptsRef.current += 1;
          connect();
        }
      }, delay);
    };
  }, [options, setConnectionState]);

  const send = useCallback(
    (message: Record<string, unknown>): boolean => {
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        try {
          socket.send(JSON.stringify(message));
          return true;
        } catch (err) {
          options.onError?.(`Send failed: ${err}`);
          return false;
        }
      }
      return false;
    },
    [options]
  );

  const pause = useCallback(() => {
    pausedRef.current = true;
    send({ type: "pause" });
  }, [send]);

  const resume = useCallback(() => {
    pausedRef.current = false;
    send({ type: "resume" });
  }, [send]);

  const queryResume = useCallback(() => {
    send({ type: "resume_query" });
  }, [send]);

  const retransmitPending = useCallback(async () => {
    const pending = await getPendingChunks(options.visitId);
    for (const chunk of pending) {
      send({
        type: "audio_chunk",
        seq: chunk.seq,
        payload: chunk.payload,
      });
    }
  }, [options.visitId, send]);

  const close = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setConnectionState("disconnected");
  }, [setConnectionState]);

  // Auto-connect on mount
  useEffect(() => {
    connect();
    return () => close();
  }, [connect, close]);

  return {
    state,
    isConnected: state === "connected",
    send,
    pause,
    resume,
    queryResume,
    retransmitPending,
    close,
  };
}
