"use client";

/**
 * W-223 Enhancement: Upload status indicator during live streaming
 * Shows connection state, buffer size, and retry indicators
 */

import { ConnectionState } from "@/lib/use_audio_ws";
import { useLang } from "@/lib/i18n";

interface UploadStatusProps {
  state: ConnectionState;
  pendingChunks: number;
  bufferSizeKb: number;
  onlineChunks: number;
  showDetails?: boolean;
}

export function UploadStatus({
  state,
  pendingChunks,
  bufferSizeKb,
  onlineChunks,
  showDetails = false,
}: UploadStatusProps) {
  const { L } = useLang();

  const statusConfig = {
    connected: {
      icon: "●",
      color: "#00c2b8",
      label: L("متصل — الصوت يُرفع", "Connected — uploading"),
      details: onlineChunks > 0 ? L(`${onlineChunks} جزء مرسل`, `${onlineChunks} chunks sent`) : L("جاهز", "Ready"),
    },
    connecting: {
      icon: "◐",
      color: "#f5a623",
      label: L("جارٍ الاتصال…", "Connecting…"),
      details: L("انتظر", "Waiting"),
    },
    resuming: {
      icon: "◑",
      color: "#f5a623",
      label: L("جارٍ استئناف الاتصال…", "Resuming…"),
      details: pendingChunks > 0 ? L(`${pendingChunks} جزء محفوظ`, `${pendingChunks} chunks buffered`) : L("", ""),
    },
    disconnected: {
      icon: "○",
      color: "#d94b4b",
      label: L("منقطع — الصوت محفوظ محلياً", "Disconnected — buffering locally"),
      details: pendingChunks > 0 ? L(`${pendingChunks} جزء محفوظ (${bufferSizeKb}KB)`, `${pendingChunks} chunks (${bufferSizeKb}KB)`) : L("لا بيانات", "No data"),
    },
    error: {
      icon: "✕",
      color: "#d94b4b",
      label: L("خطأ في الاتصال", "Connection error"),
      details: L("يجري إعادة الاتصال…", "Reconnecting…"),
    },
  };

  const config = statusConfig[state as keyof typeof statusConfig] || statusConfig.disconnected;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        background: "#f0f8f7",
        border: `1px solid ${config.color}`,
        borderRadius: 8,
        fontSize: 13,
        color: "#2c3e50",
      }}
    >
      <span
        style={{
          fontSize: 16,
          color: config.color,
          fontWeight: "bold",
          animation: state === "connecting" || state === "resuming" ? "spin 1s linear infinite" : "none",
        }}
      >
        {config.icon}
      </span>

      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, color: config.color }}>
          {config.label}
        </div>
        {showDetails && config.details && (
          <div style={{ fontSize: 12, color: "#5c7096", marginTop: 4 }}>
            {config.details}
          </div>
        )}
      </div>

      {state === "disconnected" && pendingChunks > 0 && (
        <div
          style={{
            background: "#fff",
            border: `1px solid ${config.color}`,
            borderRadius: 4,
            padding: "6px 10px",
            fontSize: 11,
            fontWeight: 600,
            color: config.color,
          }}
        >
          {L(`${pendingChunks} قيد الانتظار`, `${pendingChunks} pending`)}
        </div>
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
