import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../api/client';

interface AppNotification {
  id: string;
  type: 'error' | 'warning' | 'info';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
}

const POLL_INTERVAL_MS = 30_000;

function requestDesktopPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    void Notification.requestPermission();
  }
}

function fireDesktopNotification(title: string, body: string) {
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(title, { body, icon: '/favicon.ico' });
  }
}

export default function NotificationPanel() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const panelRef = useRef<HTMLDivElement>(null);
  const prevStatusRef = useRef<string | null>(null);
  const prevOfflineRef = useRef(false);

  const addNotification = useCallback((n: Omit<AppNotification, 'id' | 'timestamp' | 'read'>) => {
    const entry: AppNotification = {
      ...n,
      id: `${Date.now()}-${Math.random()}`,
      timestamp: new Date(),
      read: false,
    };
    setNotifications((prev) => [entry, ...prev].slice(0, 50));
    fireDesktopNotification(n.title, n.message);
  }, []);

  // Poll health endpoint
  useEffect(() => {
    requestDesktopPermission();

    const poll = async () => {
      try {
        const res = await apiClient.get<{ status: string }>('/health');
        const status = res.data.status;

        if (prevOfflineRef.current) {
          prevOfflineRef.current = false;
          addNotification({
            type: 'info',
            title: t('notifications.serverBack'),
            message: t('notifications.serverBackMsg'),
          });
        }

        if (prevStatusRef.current !== null && prevStatusRef.current !== status && status !== 'ok') {
          addNotification({
            type: 'error',
            title: t('notifications.serverStatus'),
            message: t('notifications.serverStatusMsg', { status }),
          });
        }

        prevStatusRef.current = status;
      } catch {
        if (!prevOfflineRef.current) {
          prevOfflineRef.current = true;
          addNotification({
            type: 'error',
            title: t('notifications.serverOffline'),
            message: t('notifications.serverOfflineMsg'),
          });
        }
      }
    };

    void poll();
    const id = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [addNotification, t]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const unread = notifications.filter((n) => !n.read).length;

  const markAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  const typeIcon = (type: AppNotification['type']) => {
    if (type === 'error') return '✕';
    if (type === 'warning') return '!';
    return 'i';
  };

  const typeBg = (type: AppNotification['type']) => {
    if (type === 'error') return 'text-[color:var(--color-danger)]';
    if (type === 'warning') return 'text-[color:var(--color-accent)]';
    return 'text-[color:var(--color-primary)]';
  };

  return (
    <div ref={panelRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          if (!open) markAllRead();
        }}
        className="relative px-2.5 py-1 text-xs border border-[color:var(--color-border-dark)] rounded hover:bg-[color:var(--color-surface)] transition-colors cursor-pointer bg-transparent text-ink"
        aria-label={t('notifications.label')}
      >
        <span>🔔</span>
        {unread > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 flex items-center justify-center text-[10px] font-bold bg-[color:var(--color-danger)] text-white rounded-full px-0.5 leading-none">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 z-50 bg-[color:var(--color-surface)] border-2 border-[color:var(--color-ink)] shadow-lg rounded-[var(--radius)] overflow-hidden">
          <div className="px-4 py-3 border-b border-[color:var(--color-border)] flex items-center justify-between">
            <span className="font-bold text-sm">{t('notifications.title')}</span>
            {notifications.length > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="text-xs text-muted hover:text-ink transition-colors cursor-pointer bg-transparent border-0 p-0"
              >
                {t('notifications.markAllRead')}
              </button>
            )}
          </div>

          <div className="max-h-72 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="p-4 text-sm text-muted text-center">{t('notifications.empty')}</div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className={`px-4 py-3 border-b border-[color:var(--color-border)] text-sm ${n.read ? 'opacity-60' : ''}`}
                >
                  <div className="flex items-start gap-2">
                    <span className={`font-bold shrink-0 mt-0.5 ${typeBg(n.type)}`}>[{typeIcon(n.type)}]</span>
                    <div className="min-w-0 flex-1">
                      <div className="font-bold truncate">{n.title}</div>
                      <div className="text-muted text-xs mt-0.5">{n.message}</div>
                      <div className="text-muted text-xs mt-1">{n.timestamp.toLocaleTimeString()}</div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
