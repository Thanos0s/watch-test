"use client";

/**
 * SmartwatchBridge - pairs with a BLE pulse sensor/smartwatch directly from
 * the kiosk browser (Web Bluetooth) and auto-syncs readings to the backend.
 *
 * GATT services used:
 *   - Heart Rate (0x180D) / Heart Rate Measurement (0x2A37) -- REQUIRED,
 *     requested via the chooser filter. This is the only service every
 *     paired device is guaranteed to expose.
 *   - Pulse Oximeter (0x1822) / PLX Continuous Measurement (0x2A5F) --
 *     OPTIONAL, requested as an optionalService. Most cheap fitness bands
 *     do NOT implement this; when it's absent, SpO2 is shown as
 *     unavailable rather than guessed at.
 *
 * Backend contract: POST /vitals/sync (see intake-engine/app/routes/vitals.py).
 * That endpoint's heart_rate_bpm/spo2_percent/systolic_bp/diastolic_bp are
 * all individually optional -- this component only ever sends the vitals
 * it actually read off the device. It never sends blood pressure (the
 * standard Heart Rate service has no BP data at all -- that needs a
 * different GATT service most wearables don't implement either) and never
 * sends a fabricated ppg_waveform_sample (the Heart Rate Measurement
 * characteristic exposes a computed BPM, not a raw optical waveform, so
 * there is no real sample to send).
 */

import { useCallback, useEffect, useRef, useState } from "react";

// --------------------------------------------------------------------------
// Minimal local Web Bluetooth types (kept self-contained rather than
// depending on @types/web-bluetooth, and scoped to exactly what's used
// here rather than augmenting the global Navigator/EventTarget types).
// --------------------------------------------------------------------------

interface BleCharacteristic extends EventTarget {
  readonly value: DataView | null;
  startNotifications(): Promise<BleCharacteristic>;
  stopNotifications(): Promise<BleCharacteristic>;
}

interface BleService {
  getCharacteristic(characteristic: string | number): Promise<BleCharacteristic>;
}

interface BleRemoteGATTServer {
  readonly connected: boolean;
  connect(): Promise<BleRemoteGATTServer>;
  disconnect(): void;
  getPrimaryService(service: string | number): Promise<BleService>;
}

interface BleDevice extends EventTarget {
  readonly name?: string;
  readonly gatt?: BleRemoteGATTServer;
}

interface BleRequestDeviceFilter {
  services: (string | number)[];
}

interface BleRequestDeviceOptions {
  filters?: BleRequestDeviceFilter[];
  optionalServices?: (string | number)[];
}

interface BluetoothApi {
  requestDevice(options: BleRequestDeviceOptions): Promise<BleDevice>;
}

interface NavigatorWithBluetooth extends Navigator {
  bluetooth?: BluetoothApi;
}

// --------------------------------------------------------------------------
// GATT UUIDs (standard registered names -- Chrome resolves these to
// 0x180D / 0x2A37 / 0x1822 / 0x2A5F internally).
// --------------------------------------------------------------------------

const HEART_RATE_SERVICE = "heart_rate"; // 0x180D
const HEART_RATE_MEASUREMENT_CHARACTERISTIC = "heart_rate_measurement"; // 0x2A37
const PULSE_OXIMETER_SERVICE = "pulse_oximeter"; // 0x1822 (optional)
const PLX_CONTINUOUS_MEASUREMENT_CHARACTERISTIC = "plx_continuous_measurement"; // 0x2A5F (optional)

// --------------------------------------------------------------------------
// GATT payload parsing
// --------------------------------------------------------------------------

/** Heart Rate Measurement (0x2A37), per the Bluetooth GATT spec's flags byte. */
function parseHeartRateMeasurement(value: DataView): number {
  const flags = value.getUint8(0);
  const is16Bit = (flags & 0x01) !== 0;
  return is16Bit ? value.getUint16(1, true) : value.getUint8(1);
}

/** IEEE-11073 16-bit SFLOAT decoder, used by the Pulse Oximeter service. */
function parseSFLOAT(raw: number): number {
  // Reserved special values (NaN, NRes, +INFINITY, Reserved, -INFINITY).
  if (raw === 0x07ff || raw === 0x0800 || raw === 0x07fe || raw === 0x0801 || raw === 0x0802) {
    return NaN;
  }
  const mantissaRaw = raw & 0x0fff;
  const exponentRaw = (raw >> 12) & 0x000f;
  const mantissa = mantissaRaw >= 0x0800 ? mantissaRaw - 0x1000 : mantissaRaw;
  const exponent = exponentRaw >= 0x0008 ? exponentRaw - 0x0010 : exponentRaw;
  return mantissa * Math.pow(10, exponent);
}

/** PLX Continuous Measurement (0x2A5F) -- only the mandatory SpO2PR-Normal
 * field (Flags + SpO2 SFLOAT + Pulse Rate SFLOAT) is parsed; optional
 * trailing fields (fast/slow averages, status, pulse amplitude index) are
 * flag-gated and not needed for a basic SpO2 readout. */
function parsePulseOximeterSpo2(value: DataView): number | null {
  if (value.byteLength < 3) return null;
  const spo2 = parseSFLOAT(value.getUint16(1, true));
  return Number.isFinite(spo2) ? Math.round(spo2) : null;
}

// --------------------------------------------------------------------------
// Stability detection
// --------------------------------------------------------------------------

const STABILITY_WINDOW_SIZE = 5;
const STABILITY_TOLERANCE_BPM = 4;
const RESYNC_COOLDOWN_MS = 20_000;

function isStable(readings: number[]): boolean {
  if (readings.length < STABILITY_WINDOW_SIZE) return false;
  const window = readings.slice(-STABILITY_WINDOW_SIZE);
  return Math.max(...window) - Math.min(...window) <= STABILITY_TOLERANCE_BPM;
}

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------

type ConnectionState = "unsupported" | "idle" | "requesting" | "connecting" | "connected" | "error";

export interface VitalsSyncResult {
  session_id: string;
  trigger_red_flag: boolean;
  red_flag_reason: string | null;
  nadi_trait_estimate: string | null;
  hrv_sdnn_ms: number | null;
  patient_record: Record<string, unknown>;
}

export interface SmartwatchBridgeProps {
  apiBaseUrl?: string;
  sessionId: string;
  onSynced?: (result: VitalsSyncResult) => void;
  onRedFlag?: (reason: string) => void;
}

const DEFAULT_API_BASE =
  typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_BASE_URL
    ? process.env.NEXT_PUBLIC_API_BASE_URL
    : "http://127.0.0.1:8001";

// --------------------------------------------------------------------------
// Component
// --------------------------------------------------------------------------

export default function SmartwatchBridge({
  apiBaseUrl = DEFAULT_API_BASE,
  sessionId,
  onSynced,
  onRedFlag,
}: SmartwatchBridgeProps) {
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [deviceName, setDeviceName] = useState<string | null>(null);
  const [heartRate, setHeartRate] = useState<number | null>(null);
  const [spo2, setSpo2] = useState<number | null>(null);
  const [spo2Supported, setSpo2Supported] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<"idle" | "syncing" | "synced" | "error">("idle");
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);

  const deviceRef = useRef<BleDevice | null>(null);
  const hrCharacteristicRef = useRef<BleCharacteristic | null>(null);
  const plxCharacteristicRef = useRef<BleCharacteristic | null>(null);
  const hrReadingsRef = useRef<number[]>([]);
  const lastAutoSyncAtRef = useRef<number>(0);
  const isSyncingRef = useRef(false);

  const bluetoothApi = (typeof navigator !== "undefined" ? (navigator as NavigatorWithBluetooth).bluetooth : undefined);

  useEffect(() => {
    if (!bluetoothApi) {
      setConnectionState("unsupported");
    }
  }, [bluetoothApi]);

  // ------------------------------------------------------------------
  // Auto-sync
  // ------------------------------------------------------------------

  const syncVitals = useCallback(
    async (hr: number, sp02Reading: number | null) => {
      if (isSyncingRef.current) return;
      isSyncingRef.current = true;
      setSyncStatus("syncing");

      try {
        const body: Record<string, number> = { heart_rate_bpm: hr };
        if (sp02Reading !== null) body.spo2_percent = sp02Reading;

        const resp = await fetch(`${apiBaseUrl}/vitals/sync`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, ...body }),
        });
        if (!resp.ok) throw new Error(`Vitals sync failed (${resp.status})`);

        const result: VitalsSyncResult = await resp.json();
        setSyncStatus("synced");
        setLastSyncedAt(Date.now());
        lastAutoSyncAtRef.current = Date.now();
        onSynced?.(result);
        if (result.trigger_red_flag && result.red_flag_reason) {
          onRedFlag?.(result.red_flag_reason);
        }
      } catch {
        setSyncStatus("error");
      } finally {
        isSyncingRef.current = false;
      }
    },
    [apiBaseUrl, sessionId, onSynced, onRedFlag]
  );

  const maybeAutoSync = useCallback(
    (hr: number, sp02Reading: number | null) => {
      const readings = hrReadingsRef.current;
      const stable = isStable(readings);
      const cooldownElapsed = Date.now() - lastAutoSyncAtRef.current >= RESYNC_COOLDOWN_MS;
      if (stable && cooldownElapsed) {
        void syncVitals(hr, sp02Reading);
      }
    },
    [syncVitals]
  );

  // ------------------------------------------------------------------
  // GATT notification handlers
  // ------------------------------------------------------------------

  const handleHeartRateNotification = useCallback(
    (event: Event) => {
      const target = event.currentTarget as BleCharacteristic;
      if (!target.value) return;
      const hr = parseHeartRateMeasurement(target.value);
      setHeartRate(hr);

      const readings = [...hrReadingsRef.current, hr].slice(-STABILITY_WINDOW_SIZE);
      hrReadingsRef.current = readings;

      maybeAutoSync(hr, spo2);
    },
    [maybeAutoSync, spo2]
  );

  const handlePulseOxNotification = useCallback((event: Event) => {
    const target = event.currentTarget as BleCharacteristic;
    if (!target.value) return;
    setSpo2(parsePulseOximeterSpo2(target.value));
  }, []);

  // ------------------------------------------------------------------
  // Pairing
  // ------------------------------------------------------------------

  const handleDisconnect = useCallback(() => {
    hrCharacteristicRef.current?.removeEventListener(
      "characteristicvaluechanged",
      handleHeartRateNotification as EventListener
    );
    plxCharacteristicRef.current?.removeEventListener(
      "characteristicvaluechanged",
      handlePulseOxNotification as EventListener
    );
    deviceRef.current?.gatt?.disconnect();
    deviceRef.current = null;
    hrCharacteristicRef.current = null;
    plxCharacteristicRef.current = null;
    hrReadingsRef.current = [];
    setConnectionState("idle");
    setDeviceName(null);
    setHeartRate(null);
    setSpo2(null);
    setSpo2Supported(false);
    setSyncStatus("idle");
  }, [handleHeartRateNotification, handlePulseOxNotification]);

  const handlePair = useCallback(async () => {
    if (!bluetoothApi) return;
    setErrorMessage(null);
    setConnectionState("requesting");

    try {
      const device = await bluetoothApi.requestDevice({
        filters: [{ services: [HEART_RATE_SERVICE] }],
        optionalServices: [PULSE_OXIMETER_SERVICE],
      });
      deviceRef.current = device;
      setDeviceName(device.name ?? "Paired device");

      device.addEventListener("gattserverdisconnected", handleDisconnect);

      setConnectionState("connecting");
      const server = await device.gatt?.connect();
      if (!server) throw new Error("GATT connect() returned no server");

      const heartRateService = await server.getPrimaryService(HEART_RATE_SERVICE);
      const heartRateCharacteristic = await heartRateService.getCharacteristic(
        HEART_RATE_MEASUREMENT_CHARACTERISTIC
      );
      hrCharacteristicRef.current = heartRateCharacteristic;
      heartRateCharacteristic.addEventListener(
        "characteristicvaluechanged",
        handleHeartRateNotification as EventListener
      );
      await heartRateCharacteristic.startNotifications();

      // Best-effort: most simple heart-rate wearables don't implement this.
      try {
        const pulseOxService = await server.getPrimaryService(PULSE_OXIMETER_SERVICE);
        const plxCharacteristic = await pulseOxService.getCharacteristic(
          PLX_CONTINUOUS_MEASUREMENT_CHARACTERISTIC
        );
        plxCharacteristicRef.current = plxCharacteristic;
        plxCharacteristic.addEventListener(
          "characteristicvaluechanged",
          handlePulseOxNotification as EventListener
        );
        await plxCharacteristic.startNotifications();
        setSpo2Supported(true);
      } catch {
        setSpo2Supported(false);
      }

      setConnectionState("connected");
    } catch (err) {
      // A user backing out of the device chooser throws NotFoundError --
      // that's a cancellation, not a real error, so just reset quietly.
      const isCancellation = err instanceof DOMException && err.name === "NotFoundError";
      if (!isCancellation) {
        setErrorMessage(err instanceof Error ? err.message : "Could not pair with the device.");
        setConnectionState("error");
      } else {
        setConnectionState("idle");
      }
    }
  }, [bluetoothApi, handleDisconnect, handleHeartRateNotification, handlePulseOxNotification]);

  useEffect(() => {
    return () => {
      deviceRef.current?.gatt?.disconnect();
    };
  }, []);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  if (connectionState === "unsupported") {
    return (
      <div className="rounded-2xl bg-slate-900 p-6 text-center text-slate-300">
        <p className="text-lg font-semibold text-amber-400">⚠️ Bluetooth pairing not supported</p>
        <p className="mt-2 text-sm">
          This browser doesn&apos;t support Web Bluetooth. Use Chrome or Edge on this kiosk device to pair a
          pulse sensor.
        </p>
      </div>
    );
  }

  if (connectionState === "idle" || connectionState === "requesting" || connectionState === "error") {
    return (
      <div className="flex flex-col items-center gap-4 rounded-2xl bg-slate-900 p-8 text-center">
        <div className="text-5xl">⌚</div>
        <button
          type="button"
          onClick={() => void handlePair()}
          disabled={connectionState === "requesting"}
          className="min-h-[72px] w-full max-w-md rounded-2xl bg-blue-600 px-6 py-4 text-xl font-semibold text-white
            shadow-lg transition-transform hover:bg-blue-500 active:scale-95 disabled:opacity-60"
        >
          {connectionState === "requesting" ? "Opening device chooser..." : "🔗 Tap to Pair Pulse Sensor / Smartwatch"}
        </button>
        {errorMessage && <p className="max-w-md text-sm text-red-400">{errorMessage}</p>}
      </div>
    );
  }

  // connectionState === "connecting" | "connected"
  return (
    <div className="flex flex-col items-center gap-6 rounded-2xl bg-slate-900 p-8">
      <div className="flex w-full items-center justify-between">
        <p className="text-sm text-slate-400">
          {connectionState === "connecting" ? "Connecting..." : `Paired: ${deviceName}`}
        </p>
        {connectionState === "connected" && (
          <button type="button" onClick={handleDisconnect} className="text-sm text-slate-500 hover:text-slate-300">
            Disconnect
          </button>
        )}
      </div>

      <div className="grid w-full grid-cols-2 gap-4">
        <div className="rounded-2xl bg-slate-950 p-6 text-center ring-1 ring-slate-800">
          <p className="text-sm uppercase tracking-wide text-slate-500">Heart Rate</p>
          <p className={`mt-2 text-6xl font-bold text-rose-400 ${heartRate ? "animate-pulse" : ""}`}>
            {heartRate ?? "--"}
          </p>
          <p className="mt-1 text-sm text-slate-400">bpm</p>
        </div>

        <div className="rounded-2xl bg-slate-950 p-6 text-center ring-1 ring-slate-800">
          <p className="text-sm uppercase tracking-wide text-slate-500">SpO2</p>
          {spo2Supported ? (
            <>
              <p className="mt-2 text-6xl font-bold text-cyan-400">{spo2 ?? "--"}</p>
              <p className="mt-1 text-sm text-slate-400">%</p>
            </>
          ) : (
            <p className="mt-4 text-sm text-slate-500">Not available from this device</p>
          )}
        </div>
      </div>

      <div className="text-sm">
        {syncStatus === "idle" && <span className="text-slate-500">Waiting for a stable reading...</span>}
        {syncStatus === "syncing" && <span className="text-blue-400">Syncing vitals...</span>}
        {syncStatus === "synced" && (
          <span className="text-emerald-400">
            ✓ Synced{lastSyncedAt ? ` (${new Date(lastSyncedAt).toLocaleTimeString()})` : ""}
          </span>
        )}
        {syncStatus === "error" && <span className="text-red-400">Sync failed -- will retry automatically</span>}
      </div>
    </div>
  );
}
