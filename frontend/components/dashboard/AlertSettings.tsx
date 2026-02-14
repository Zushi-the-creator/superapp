"use client";

import { useState, useEffect } from "react";
import { Bell, BellOff, Send, Loader2, Check, X, Mail, FileText } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface AlertConfig {
  enabled: boolean;
  email: string;
  smtp_server: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  notify_sell_signals: boolean;
  notify_buy_signals: boolean;
  notify_upgrades: boolean;
  notify_critical_alerts: boolean;
}

const DEFAULT_CONFIG: AlertConfig = {
  enabled: false,
  email: "",
  smtp_server: "smtp.gmail.com",
  smtp_port: 587,
  smtp_user: "",
  smtp_password: "",
  notify_sell_signals: true,
  notify_buy_signals: true,
  notify_upgrades: true,
  notify_critical_alerts: true,
};

export function AlertSettings() {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<AlertConfig>(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);
  const [testingEmail, setTestingEmail] = useState(false);
  const [sendingReport, setSendingReport] = useState(false);
  const [status, setStatus] = useState<{ type: "ok" | "err"; msg: string } | null>(null);

  useEffect(() => {
    if (open) {
      api.getAlertConfig().then((c) => setConfig(c as unknown as AlertConfig)).catch(() => {});
    }
  }, [open]);

  const save = async () => {
    setSaving(true);
    setStatus(null);
    try {
      await api.updateAlertConfig(config as unknown as Record<string, unknown>);
      setStatus({ type: "ok", msg: "Saved" });
    } catch (e) {
      setStatus({ type: "err", msg: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  };

  const testEmail = async () => {
    setTestingEmail(true);
    setStatus(null);
    try {
      await api.updateAlertConfig(config as unknown as Record<string, unknown>);
      await api.testAlertEmail();
      setStatus({ type: "ok", msg: "Test email sent!" });
    } catch (e) {
      setStatus({ type: "err", msg: e instanceof Error ? e.message : "Email test failed" });
    } finally {
      setTestingEmail(false);
    }
  };

  const sendReport = async () => {
    setSendingReport(true);
    setStatus(null);
    try {
      const result = await api.sendReport();
      setStatus({ type: "ok", msg: `Report sent! (${result.positions} holdings, ${result.buy_signals} BUY signals)` });
    } catch (e) {
      setStatus({ type: "err", msg: e instanceof Error ? e.message : "Send report failed" });
    } finally {
      setSendingReport(false);
    }
  };

  const update = (key: keyof AlertConfig, value: unknown) =>
    setConfig((prev) => ({ ...prev, [key]: value }));

  if (!open) {
    return (
      <div className="space-y-2">
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-neutral-700 hover:border-neutral-500 text-neutral-400 hover:text-neutral-200 text-xs transition-colors"
        >
          {config.enabled ? (
            <Bell className="h-3.5 w-3.5 text-signal-buy" />
          ) : (
            <BellOff className="h-3.5 w-3.5" />
          )}
          Alerts
        </button>
        {config.enabled && (
          <button
            onClick={sendReport}
            disabled={sendingReport}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-neutral-700 hover:border-signal-buy/50 text-neutral-400 hover:text-signal-buy text-xs transition-colors disabled:opacity-50"
          >
            {sendingReport ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
            Send Report
          </button>
        )}
        {status && (
          <div className={cn("text-[10px] px-1", status.type === "ok" ? "text-signal-buy" : "text-signal-sell")}>
            {status.msg}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-signal-buy" />
          <h3 className="text-sm font-semibold text-neutral-200">Email Alerts</h3>
        </div>
        <button onClick={() => setOpen(false)}>
          <X className="h-4 w-4 text-neutral-500 hover:text-neutral-300" />
        </button>
      </div>

      <div className="space-y-3">
        {/* Enable toggle */}
        <div className="flex items-center gap-2">
          <Mail className="h-3.5 w-3.5 text-neutral-400" />
          <span className="text-xs text-neutral-300">Enable email alerts</span>
          <button
            onClick={() => update("enabled", !config.enabled)}
            className={cn(
              "ml-auto w-9 h-5 rounded-full transition-colors relative",
              config.enabled ? "bg-signal-buy" : "bg-neutral-700"
            )}
          >
            <span className={cn(
              "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
              config.enabled ? "translate-x-4" : "translate-x-0.5"
            )} />
          </button>
        </div>

        {config.enabled && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <Field label="Email" value={config.email} onChange={(v) => update("email", v)} placeholder="you@gmail.com" />
              <Field label="SMTP User" value={config.smtp_user} onChange={(v) => update("smtp_user", v)} placeholder="you@gmail.com" />
              <Field label="App Password" value={config.smtp_password} onChange={(v) => update("smtp_password", v)} placeholder="16-char app password" type="password" />
              <div className="flex items-end">
                <button
                  onClick={testEmail}
                  disabled={testingEmail || !config.email || !config.smtp_password}
                  className="flex items-center gap-1 px-3 py-1.5 bg-neutral-800 text-neutral-300 rounded text-xs hover:bg-neutral-700 disabled:opacity-50 transition-colors"
                >
                  {testingEmail ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                  Test Email
                </button>
              </div>
            </div>

            {/* Notification types */}
            <div className="text-xs text-neutral-500 mt-2">Notify me about:</div>
            <div className="grid grid-cols-2 gap-2">
              <Toggle label="Sell / Rotation" checked={config.notify_sell_signals} onChange={(v) => update("notify_sell_signals", v)} />
              <Toggle label="Buy signals" checked={config.notify_buy_signals} onChange={(v) => update("notify_buy_signals", v)} />
              <Toggle label="Upgrades" checked={config.notify_upgrades} onChange={(v) => update("notify_upgrades", v)} />
              <Toggle label="Critical alerts" checked={config.notify_critical_alerts} onChange={(v) => update("notify_critical_alerts", v)} />
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 mt-3 border-t border-neutral-800 pt-3">
              <button
                onClick={save}
                disabled={saving}
                className="px-3 py-1.5 bg-signal-buy/20 text-signal-buy rounded text-xs font-medium hover:bg-signal-buy/30 disabled:opacity-50 transition-colors"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
              </button>
              <button
                onClick={sendReport}
                disabled={sendingReport}
                className="flex items-center gap-1 px-3 py-1.5 bg-blue-500/20 text-blue-400 rounded text-xs font-medium hover:bg-blue-500/30 disabled:opacity-50 transition-colors"
              >
                {sendingReport ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileText className="h-3 w-3" />}
                Send Report Now
              </button>
            </div>

            <p className="text-[10px] text-neutral-600 mt-1">
              Gmail: use an App Password (Settings &gt; Security &gt; App Passwords). Alerts run every 15 min.
            </p>
          </>
        )}

        {/* Status */}
        {status && (
          <div className={cn(
            "flex items-center gap-1.5 text-xs",
            status.type === "ok" ? "text-signal-buy" : "text-signal-sell"
          )}>
            {status.type === "ok" ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
            {status.msg}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder: string; type?: string;
}) {
  return (
    <div>
      <div className="text-[10px] text-neutral-500 mb-1">{label}</div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-2 py-1.5 bg-neutral-900 border border-neutral-700 rounded text-xs text-neutral-100 placeholder:text-neutral-600 focus:outline-none focus:border-signal-buy/50"
      />
    </div>
  );
}

function Toggle({ label, checked, onChange }: {
  label: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3 w-3 rounded border-neutral-600 bg-neutral-900 text-signal-buy focus:ring-0"
      />
      <span className="text-xs text-neutral-400">{label}</span>
    </label>
  );
}
