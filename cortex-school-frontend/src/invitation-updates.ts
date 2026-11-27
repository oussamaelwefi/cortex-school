import { useEffect, useState } from "react";

export function useInvitationUpdates(
  getAccessToken: (() => Promise<string | undefined>) | undefined,
  onRefresh: () => void,
) {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setConnected(false);
    if (!getAccessToken || !window.WebSocket) return;
    const readAccessToken = getAccessToken;

    const url = new URL("/api/invitations/ws", window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    let active = true;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;
    let handshakeTimer: number | undefined;
    let retryDelay = 1000;

    function reconnect() {
      if (!active) return;
      setConnected(false);
      reconnectTimer = window.setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 30000);
    }

    function connect() {
      const connection = new window.WebSocket(url);
      socket = connection;
      let ready = false;
      handshakeTimer = window.setTimeout(() => connection.close(), 12000);

      connection.onopen = async () => {
        try {
          const token = await readAccessToken();
          if (!active || connection.readyState !== window.WebSocket.OPEN)
            return;
          if (token) connection.send(token);
          else connection.close();
        } catch {
          connection.close();
        }
      };
      connection.onmessage = ({ data }) => {
        if (!active || typeof data !== "string") return;
        let message: { type?: string } | null;
        try {
          message = JSON.parse(data);
        } catch {
          return;
        }
        if (message?.type === "invitations.ready") {
          ready = true;
          window.clearTimeout(handshakeTimer);
          retryDelay = 1000;
          setConnected(true);
          onRefresh();
        } else if (ready && message?.type === "invitations.changed") {
          onRefresh();
        }
      };
      connection.onclose = () => {
        window.clearTimeout(handshakeTimer);
        reconnect();
      };
    }

    connect();
    return () => {
      active = false;
      window.clearTimeout(reconnectTimer);
      window.clearTimeout(handshakeTimer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [getAccessToken, onRefresh]);

  return connected;
}
