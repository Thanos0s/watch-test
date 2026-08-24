"use client";

/**
 * KioskUI - PrakritiDesk OPD kiosk touch + voice interface.
 *
 * Flow: check-in (ABHA ID/mobile) -> OTP verification -> DPDP consent ->
 * vitals & pulse check (smartwatch pairing, optional) -> conversational
 * intake (SOCRATES + AYUSH) -> completion or red-flag alert.
 *
 * Designed for low-literacy accessibility:
 *   - every screen leans on large icons/color, not paragraphs of text
 *   - answers can always be given by touch (big buttons) OR voice (hold-to-speak)
 *   - every spoken prompt is auto-played through Bhashini TTS, not just shown as text
 *   - nothing proceeds into the clinical interview without an explicit,
 *     audibly-confirmed DPDP consent step
 *   - the vitals step never blocks the flow -- "Enter Manually" and "Skip"
 *     are always available for patients without a paired wearable
 *
 * Backend contract (see intake-engine/app/main.py and app/routes/*.py):
 *   POST /auth/abha/init-otp    {abha_id_or_mobile, session_id} -> {txn_id, sandbox_otp_hint, ...}
 *   POST /auth/abha/verify-otp  {txn_id, otp}                   -> {patient_record, ...}
 *   POST /vitals/sync           {session_id, heart_rate_bpm?, ...} -> VitalsSyncResult
 *   GET  /intake/opening-question                          -> IntakeTurnResponse (first question)
 *   POST /intake/turn        {session_id, user_input, selected_language} -> IntakeTurnResponse
 *   POST /audio/transcribe   multipart "file" + "language"                -> {transcript}
 *   POST /audio/synthesize   {text, language}                             -> audio/wav bytes
 */

import { useCallback, useEffect, useRef, useState } from "react";
import SmartwatchBridge, { type VitalsSyncResult } from "./SmartwatchBridge";

// --------------------------------------------------------------------------
// Types (mirrors intake-engine/app/schema.py, app/routes/auth.py)
// --------------------------------------------------------------------------

interface SocratesSlots {
  site: string | null;
  onset: string | null;
  character: string | null;
  radiation: string | null;
  associations: string | null;
  timing: string | null;
  exacerbating_relieving: string | null;
  severity: string | null;
}

interface AyushParameters {
  dupshya: string | null;
  desha: string | null;
  bala: string | null;
  kala: string | null;
  anala_agni: string | null;
  prakriti: string | null;
  vaya: string | null;
  sattva: string | null;
  satmya: string | null;
  ahara: string | null;
}

export interface ClinicalState {
  chief_complaint: string | null;
  socrates: SocratesSlots;
  ayush_parameters: AyushParameters;
}

interface IntakeTurnResponse {
  audio_prompt_text: string;
  touch_options: string[];
  updated_clinical_state: ClinicalState;
  is_complete: boolean;
  trigger_red_flag: boolean;
  red_flag_reason: string | null;
}

interface InitOtpResponse {
  txn_id: string;
  message: string;
  gateway_mode: string;
  sandbox_otp_hint: string | null;
  disclaimer: string;
}

interface VerifyOtpResponse {
  verification_status: string;
  is_mock: boolean;
  gateway_mode: string;
  session_id: string;
  abha_id_or_mobile: string;
  patient_record: Record<string, unknown>;
  disclaimer: string;
}

interface DeviceVitalsSummary {
  heart_rate_bpm?: number;
  spo2_percent?: number;
  systolic_bp?: number;
  diastolic_bp?: number;
  nadi_trait_estimate?: string;
}

type Screen = "checkin" | "otp" | "consent" | "vitals" | "intake" | "complete" | "redflag";

export interface KioskUIProps {
  /** Base URL of the intake-engine FastAPI service. */
  apiBaseUrl?: string;
  /** Human-readable language name, matches selected_language in the API contract. */
  language?: string;
  /** Called once the interview finishes normally (is_complete: true). */
  onComplete?: (finalState: ClinicalState, abhaId: string) => void;
  /** Called if a red-flag emergency is detected, so the host app can alert staff. */
  onRedFlag?: (reason: string, abhaId: string) => void;
}

const DEFAULT_API_BASE =
  typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_BASE_URL
    ? process.env.NEXT_PUBLIC_API_BASE_URL
    : "http://127.0.0.1:8001";

const CONSENT_TEXT: Record<string, string> = {
  Hindi:
    "आपकी सेहत की जानकारी आज के डॉक्टर परामर्श के लिए सुरक्षित रूप से उपयोग की जाएगी। क्या आप सहमत हैं?",
  English:
    "Your health information will be used securely, only for today's doctor consultation. Do you agree?",
};

function getConsentText(language: string): string {
  return CONSENT_TEXT[language] ?? CONSENT_TEXT.English;
}

// --------------------------------------------------------------------------
// Small presentational pieces
// --------------------------------------------------------------------------

function WaveBars({ active, levels }: { active: boolean; levels: number[] }) {
  return (
    <div className="flex items-end justify-center gap-1.5 h-16">
      {levels.map((level, i) => (
        <div
          key={i}
          className={`w-2.5 rounded-full transition-all duration-75 ${
            active ? "bg-emerald-400" : "bg-slate-600"
          }`}
          style={{ height: `${active ? Math.max(8, level) : 8}px` }}
        />
      ))}
    </div>
  );
}

function BigButton({
  children,
  onClick,
  colorClass = "bg-blue-600 hover:bg-blue-500 active:bg-blue-700",
  disabled = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  colorClass?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`min-h-[88px] w-full rounded-2xl px-6 py-4 text-2xl font-semibold text-white shadow-lg
        transition-transform active:scale-95 disabled:opacity-40 disabled:pointer-events-none ${colorClass}`}
    >
      {children}
    </button>
  );
}

// --------------------------------------------------------------------------
// Main component
// --------------------------------------------------------------------------

export default function KioskUI({
  apiBaseUrl = DEFAULT_API_BASE,
  language = "Hindi",
  onComplete,
  onRedFlag,
}: KioskUIProps) {
  const [screen, setScreen] = useState<Screen>("checkin");
  const [abhaId, setAbhaId] = useState("");
  const [sessionId] = useState<string>(() =>
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `session-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );

  const [audioPromptText, setAudioPromptText] = useState("");
  const [touchOptions, setTouchOptions] = useState<string[]>([]);
  const [clinicalState, setClinicalState] = useState<ClinicalState | null>(null);
  const [redFlagReason, setRedFlagReason] = useState<string | null>(null);

  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [waveLevels, setWaveLevels] = useState<number[]>(Array(12).fill(8));
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // ABHA OTP verification
  const [otpTxnId, setOtpTxnId] = useState<string | null>(null);
  const [otpValue, setOtpValue] = useState("");
  const [otpHint, setOtpHint] = useState<string | null>(null);
  const [otpError, setOtpError] = useState<string | null>(null);
  const [isSendingOtp, setIsSendingOtp] = useState(false);
  const [isVerifyingOtp, setIsVerifyingOtp] = useState(false);
  const [patientRecord, setPatientRecord] = useState<Record<string, unknown> | null>(null);

  // Vitals & pulse check
  const [vitalsSummary, setVitalsSummary] = useState<DeviceVitalsSummary | null>(null);
  const [showManualVitals, setShowManualVitals] = useState(false);
  const [manualHr, setManualHr] = useState("");
  const [manualSpo2, setManualSpo2] = useState("");
  const [manualSystolic, setManualSystolic] = useState("");
  const [manualDiastolic, setManualDiastolic] = useState("");
  const [isSubmittingManualVitals, setIsSubmittingManualVitals] = useState(false);
  const [manualVitalsError, setManualVitalsError] = useState<string | null>(null);

  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafIdRef = useRef<number | null>(null);

  // ------------------------------------------------------------------
  // Backend calls
  // ------------------------------------------------------------------

  const playAudioPrompt = useCallback(
    async (text: string) => {
      if (!text.trim() || !audioElementRef.current) return;
      try {
        const resp = await fetch(`${apiBaseUrl}/audio/synthesize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, language }),
        });
        if (!resp.ok) throw new Error(`TTS request failed: ${resp.status}`);
        const audioBlob = await resp.blob();
        const url = URL.createObjectURL(audioBlob);
        audioElementRef.current.src = url;
        await audioElementRef.current.play();
      } catch {
        // Autoplay/TTS is a convenience layer, not a blocker: the prompt is
        // always shown as large on-screen text too, and a visible "Replay"
        // button lets the patient trigger playback manually.
      }
    },
    [apiBaseUrl, language]
  );

  // ------------------------------------------------------------------
  // ABHA OTP verification
  // ------------------------------------------------------------------

  const sendOtp = useCallback(async () => {
    setIsSendingOtp(true);
    setOtpError(null);
    try {
      const resp = await fetch(`${apiBaseUrl}/auth/abha/init-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ abha_id_or_mobile: abhaId, session_id: sessionId }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body?.message || `Could not send OTP (${resp.status})`);
      }
      const data: InitOtpResponse = await resp.json();
      setOtpTxnId(data.txn_id);
      setOtpHint(data.sandbox_otp_hint);
      setOtpValue("");
      setScreen("otp");
    } catch (err) {
      setOtpError(err instanceof Error ? err.message : "Could not send OTP. Please try again.");
    } finally {
      setIsSendingOtp(false);
    }
  }, [apiBaseUrl, abhaId, sessionId]);

  const verifyOtp = useCallback(async () => {
    if (!otpTxnId || !otpValue.trim()) return;
    setIsVerifyingOtp(true);
    setOtpError(null);
    try {
      const resp = await fetch(`${apiBaseUrl}/auth/abha/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ txn_id: otpTxnId, otp: otpValue.trim() }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body?.message || `OTP verification failed (${resp.status})`);
      }
      const data: VerifyOtpResponse = await resp.json();
      setPatientRecord(data.patient_record);
      setScreen("consent");
    } catch (err) {
      setOtpError(err instanceof Error ? err.message : "OTP verification failed. Please try again.");
    } finally {
      setIsVerifyingOtp(false);
    }
  }, [apiBaseUrl, otpTxnId, otpValue]);

  const handleBypassCheckin = useCallback(() => {
    const fallbackId = abhaId.trim() || `GUEST-${Math.floor(100000 + Math.random() * 900000)}`;
    setAbhaId(fallbackId);
    setScreen("consent");
  }, [abhaId]);

  // ------------------------------------------------------------------
  // Conversational intake
  // ------------------------------------------------------------------

  const applyTurnResponse = useCallback(
    (data: IntakeTurnResponse) => {
      setAudioPromptText(data.audio_prompt_text);
      setTouchOptions(data.touch_options);
      setClinicalState(data.updated_clinical_state);

      if (data.trigger_red_flag) {
        setRedFlagReason(data.red_flag_reason);
        setScreen("redflag");
        onRedFlag?.(data.red_flag_reason ?? "Emergency symptoms detected", abhaId);
      } else if (data.is_complete) {
        setScreen("complete");
        onComplete?.(data.updated_clinical_state, abhaId);
      } else {
        setScreen("intake");
      }

      void playAudioPrompt(data.audio_prompt_text);
    },
    [abhaId, onComplete, onRedFlag, playAudioPrompt]
  );

  const startIntake = useCallback(async () => {
    setIsProcessing(true);
    setErrorMessage(null);
    try {
      const resp = await fetch(`${apiBaseUrl}/intake/opening-question`);
      if (!resp.ok) throw new Error(`Failed to start intake: ${resp.status}`);
      const data: IntakeTurnResponse = await resp.json();
      applyTurnResponse(data);
    } catch {
      setErrorMessage("Could not reach the kiosk service. Please tell a staff member.");
    } finally {
      setIsProcessing(false);
    }
  }, [apiBaseUrl, applyTurnResponse]);

  // ------------------------------------------------------------------
  // Vitals & pulse check
  // ------------------------------------------------------------------

  const goToIntakeFromVitals = useCallback(() => {
    setScreen("intake");
    void startIntake();
  }, [startIntake]);

  const handleVitalsRedFlag = useCallback(
    (reason: string) => {
      setRedFlagReason(reason);
      setScreen("redflag");
      onRedFlag?.(reason, abhaId);
    },
    [abhaId, onRedFlag]
  );

  const handleVitalsCaptured = useCallback((result: VitalsSyncResult) => {
    const deviceVitals = result.patient_record?.device_vitals as DeviceVitalsSummary | undefined;
    if (deviceVitals) setVitalsSummary(deviceVitals);
    // trigger_red_flag/red_flag_reason from a device sync are handled by
    // SmartwatchBridge's own onRedFlag callback (wired below), not here --
    // this callback only needs to record the reading for display.
  }, []);

  const submitManualVitals = useCallback(async () => {
    const body: Record<string, number> = {};
    if (manualHr.trim()) body.heart_rate_bpm = Number(manualHr);
    if (manualSpo2.trim()) body.spo2_percent = Number(manualSpo2);
    if (manualSystolic.trim()) body.systolic_bp = Number(manualSystolic);
    if (manualDiastolic.trim()) body.diastolic_bp = Number(manualDiastolic);

    if (Object.keys(body).length === 0) {
      goToIntakeFromVitals();
      return;
    }

    setIsSubmittingManualVitals(true);
    setManualVitalsError(null);
    try {
      const resp = await fetch(`${apiBaseUrl}/vitals/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, ...body }),
      });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        throw new Error(errBody?.message || `Could not save vitals (${resp.status})`);
      }
      const result: VitalsSyncResult = await resp.json();
      if (result.trigger_red_flag && result.red_flag_reason) {
        handleVitalsRedFlag(result.red_flag_reason);
        return;
      }
      goToIntakeFromVitals();
    } catch (err) {
      setManualVitalsError(err instanceof Error ? err.message : "Could not save vitals.");
    } finally {
      setIsSubmittingManualVitals(false);
    }
  }, [
    apiBaseUrl,
    sessionId,
    manualHr,
    manualSpo2,
    manualSystolic,
    manualDiastolic,
    goToIntakeFromVitals,
    handleVitalsRedFlag,
  ]);

  // ------------------------------------------------------------------
  // Voice answers (hold-to-speak)
  // ------------------------------------------------------------------

  const submitTurn = useCallback(
    async (userInput: string) => {
      if (!userInput.trim()) return;
      setIsProcessing(true);
      setErrorMessage(null);
      try {
        const resp = await fetch(`${apiBaseUrl}/intake/turn`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            user_input: userInput,
            selected_language: language,
          }),
        });
        if (!resp.ok) throw new Error(`Turn request failed: ${resp.status}`);
        const data: IntakeTurnResponse = await resp.json();
        applyTurnResponse(data);
      } catch {
        setErrorMessage("Something went wrong. Please try again or call a staff member.");
      } finally {
        setIsProcessing(false);
      }
    },
    [apiBaseUrl, applyTurnResponse, language, sessionId]
  );

  const transcribeAndSubmit = useCallback(
    async (audioBlob: Blob) => {
      setIsProcessing(true);
      setErrorMessage(null);
      try {
        const form = new FormData();
        form.append("file", audioBlob, "answer.webm");
        form.append("language", language);
        const resp = await fetch(`${apiBaseUrl}/audio/transcribe`, { method: "POST", body: form });
        if (!resp.ok) throw new Error(`Transcription failed: ${resp.status}`);
        const data: { transcript: string } = await resp.json();
        await submitTurn(data.transcript);
      } catch {
        setErrorMessage("Could not understand the recording. Please try again or use the buttons.");
        setIsProcessing(false);
      }
    },
    [apiBaseUrl, language, submitTurn]
  );

  // ------------------------------------------------------------------
  // Hold-to-speak recording, with a live waveform driven by the mic input
  // ------------------------------------------------------------------

  const stopWaveformLoop = useCallback(() => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    setWaveLevels(Array(12).fill(8));
  }, []);

  const startWaveformLoop = useCallback((stream: MediaStream) => {
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 64;
    source.connect(analyser);
    audioContextRef.current = audioContext;
    analyserRef.current = analyser;

    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteFrequencyData(dataArray);
      const bars = 12;
      const step = Math.floor(dataArray.length / bars) || 1;
      const levels = Array.from({ length: bars }, (_, i) => {
        const value = dataArray[i * step] ?? 0;
        return 8 + (value / 255) * 56; // 8px..64px
      });
      setWaveLevels(levels);
      rafIdRef.current = requestAnimationFrame(tick);
    };
    rafIdRef.current = requestAnimationFrame(tick);
  }, []);

  const startRecording = useCallback(async () => {
    if (isProcessing || isRecording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      recordedChunksRef.current = [];

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recordedChunksRef.current.push(event.data);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();

      startWaveformLoop(stream);
      setIsRecording(true);
      setErrorMessage(null);
    } catch {
      setErrorMessage("Microphone access is needed to speak your answer. You can also use the buttons.");
    }
  }, [isProcessing, isRecording, startWaveformLoop]);

  const stopRecording = useCallback(() => {
    if (!isRecording || !mediaRecorderRef.current) return;

    const recorder = mediaRecorderRef.current;
    recorder.onstop = () => {
      const blob = new Blob(recordedChunksRef.current, { type: "audio/webm" });
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      audioContextRef.current?.close().catch(() => {});
      stopWaveformLoop();
      void transcribeAndSubmit(blob);
    };
    recorder.stop();
    setIsRecording(false);
  }, [isRecording, stopWaveformLoop, transcribeAndSubmit]);

  useEffect(() => {
    return () => {
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
      audioContextRef.current?.close().catch(() => {});
    };
  }, []);

  // ------------------------------------------------------------------
  // Screens
  // ------------------------------------------------------------------

  if (screen === "checkin") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-slate-950 px-6 py-10 text-white">
        <h1 className="text-4xl font-bold">🏥 Welcome to PrakritiDesk</h1>
        <p className="text-xl text-slate-300">Please enter your ABHA ID or mobile number</p>
        <input
          type="text"
          inputMode="numeric"
          value={abhaId}
          onChange={(e) => setAbhaId(e.target.value)}
          placeholder="XX-XXXX-XXXX-XXXX or mobile number"
          className="w-full max-w-md rounded-2xl border-4 border-slate-700 bg-slate-900 px-6 py-5
            text-center text-2xl tracking-widest text-white placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
        />
        {otpError && (
          <div className="flex max-w-md flex-col items-center gap-2">
            <p className="text-center text-red-400">{otpError}</p>
            <button
              type="button"
              onClick={handleBypassCheckin}
              className="text-sm font-semibold text-amber-400 underline hover:text-amber-300"
            >
              ⚡ Server offline? Click here to bypass and continue as Guest
            </button>
          </div>
        )}
        <div className="flex w-full max-w-md flex-col gap-4">
          <BigButton onClick={() => void sendOtp()} disabled={abhaId.trim().length < 4 || isSendingOtp}>
            {isSendingOtp ? "Sending OTP..." : "Continue with ABHA ➜"}
          </BigButton>
          <button
            type="button"
            onClick={handleBypassCheckin}
            className="w-full rounded-2xl border-2 border-slate-700 bg-slate-900/80 px-6 py-4 text-lg font-medium text-slate-300 transition-colors hover:border-slate-500 hover:bg-slate-800 hover:text-white"
          >
            ⚡ Continue as Guest (Skip ABHA) ➜
          </button>
        </div>
      </div>
    );
  }

  if (screen === "otp") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-slate-950 px-6 py-10 text-white">
        <h1 className="text-3xl font-bold">🔐 Verify Your Identity</h1>
        <p className="max-w-md text-center text-lg text-slate-300">
          Enter the OTP sent to your registered mobile number.
        </p>
        {otpHint && (
          <p className="max-w-md text-center text-sm text-amber-400">Sandbox mode -- demo OTP: {otpHint}</p>
        )}
        <input
          type="text"
          inputMode="numeric"
          value={otpValue}
          onChange={(e) => setOtpValue(e.target.value)}
          placeholder="6-digit OTP"
          className="w-full max-w-xs rounded-2xl border-4 border-slate-700 bg-slate-900 px-6 py-5
            text-center text-3xl tracking-[0.5em] text-white placeholder:tracking-normal placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
        />
        {otpError && <p className="max-w-md text-center text-red-400">{otpError}</p>}
        <div className="grid w-full max-w-md grid-cols-1 gap-4 sm:grid-cols-2">
          <BigButton
            onClick={() => void sendOtp()}
            disabled={isSendingOtp}
            colorClass="bg-slate-700 hover:bg-slate-600 active:bg-slate-800"
          >
            {isSendingOtp ? "Resending..." : "Resend OTP"}
          </BigButton>
          <BigButton onClick={() => void verifyOtp()} disabled={isVerifyingOtp || otpValue.trim().length < 4}>
            {isVerifyingOtp ? "Verifying..." : "Verify ➜"}
          </BigButton>
        </div>
        <div className="flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={handleBypassCheckin}
            className="text-sm font-semibold text-blue-400 hover:text-blue-300 underline"
          >
            ⚡ Skip OTP (Continue as Guest) ➜
          </button>
          <button
            type="button"
            onClick={() => setScreen("checkin")}
            className="text-sm text-slate-500 hover:text-slate-300"
          >
            ← Back
          </button>
        </div>
      </div>
    );
  }

  if (screen === "consent") {
    const consentText = getConsentText(language);
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-slate-950 px-6 py-10 text-white">
        <h1 className="text-3xl font-bold">🔒 Your Privacy</h1>
        <div className="max-w-xl rounded-2xl bg-slate-900 p-8 text-center text-2xl leading-relaxed">
          {consentText}
        </div>
        <BigButton
          onClick={() => void playAudioPrompt(consentText)}
          colorClass="bg-slate-700 hover:bg-slate-600 active:bg-slate-800"
        >
          🔊 Listen Again
        </BigButton>
        <div className="grid w-full max-w-xl grid-cols-1 gap-4 sm:grid-cols-2">
          <BigButton
            onClick={() => setScreen("vitals")}
            colorClass="bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700"
          >
            ✅ I Agree
          </BigButton>
          <BigButton
            onClick={() => setScreen("checkin")}
            colorClass="bg-rose-600 hover:bg-rose-500 active:bg-rose-700"
          >
            ❌ I Do Not Agree
          </BigButton>
        </div>
        <audio ref={audioElementRef} className="hidden" />
      </div>
    );
  }

  if (screen === "vitals") {
    return (
      <div className="flex min-h-screen flex-col items-center gap-6 overflow-y-auto bg-slate-950 px-6 py-10 text-white">
        <h1 className="text-3xl font-bold text-center">💓 Vitals &amp; Pulse Check</h1>
        <p className="max-w-xl text-center text-lg text-slate-300">
          {patientRecord?.patient_name ? `Welcome, ${patientRecord.patient_name}. ` : ""}
          If you&apos;re wearing a smartwatch or pulse sensor, tap below to pair it. This step is optional.
        </p>

        <div className="w-full max-w-xl">
          <SmartwatchBridge
            apiBaseUrl={apiBaseUrl}
            sessionId={sessionId}
            onSynced={handleVitalsCaptured}
            onRedFlag={handleVitalsRedFlag}
          />
        </div>

        {vitalsSummary && (
          <div className="w-full max-w-xl rounded-2xl bg-emerald-950/60 p-4 text-center text-emerald-300">
            ✓ Vitals recorded
            {typeof vitalsSummary.heart_rate_bpm === "number" && <span> — HR {vitalsSummary.heart_rate_bpm} bpm</span>}
            {typeof vitalsSummary.spo2_percent === "number" && <span>, SpO2 {vitalsSummary.spo2_percent}%</span>}
          </div>
        )}

        {!showManualVitals ? (
          <div className="grid w-full max-w-xl grid-cols-1 gap-4 sm:grid-cols-2">
            <BigButton
              onClick={() => setShowManualVitals(true)}
              colorClass="bg-slate-700 hover:bg-slate-600 active:bg-slate-800"
            >
              ✍️ Enter Manually
            </BigButton>
            <BigButton onClick={goToIntakeFromVitals} colorClass="bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700">
              {vitalsSummary ? "Continue to Symptoms ➜" : "Skip for now ➜"}
            </BigButton>
          </div>
        ) : (
          <div className="w-full max-w-xl space-y-4 rounded-2xl bg-slate-900 p-6">
            <div className="grid grid-cols-2 gap-4">
              <label className="text-sm text-slate-400">
                Heart rate (bpm)
                <input
                  type="number"
                  inputMode="numeric"
                  value={manualHr}
                  onChange={(e) => setManualHr(e.target.value)}
                  className="mt-1 w-full rounded-xl border-2 border-slate-700 bg-slate-950 px-4 py-3 text-xl text-white"
                />
              </label>
              <label className="text-sm text-slate-400">
                SpO2 (%)
                <input
                  type="number"
                  inputMode="numeric"
                  value={manualSpo2}
                  onChange={(e) => setManualSpo2(e.target.value)}
                  className="mt-1 w-full rounded-xl border-2 border-slate-700 bg-slate-950 px-4 py-3 text-xl text-white"
                />
              </label>
              <label className="text-sm text-slate-400">
                Systolic BP
                <input
                  type="number"
                  inputMode="numeric"
                  value={manualSystolic}
                  onChange={(e) => setManualSystolic(e.target.value)}
                  className="mt-1 w-full rounded-xl border-2 border-slate-700 bg-slate-950 px-4 py-3 text-xl text-white"
                />
              </label>
              <label className="text-sm text-slate-400">
                Diastolic BP
                <input
                  type="number"
                  inputMode="numeric"
                  value={manualDiastolic}
                  onChange={(e) => setManualDiastolic(e.target.value)}
                  className="mt-1 w-full rounded-xl border-2 border-slate-700 bg-slate-950 px-4 py-3 text-xl text-white"
                />
              </label>
            </div>
            {manualVitalsError && <p className="text-center text-sm text-red-400">{manualVitalsError}</p>}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <BigButton
                onClick={() => setShowManualVitals(false)}
                colorClass="bg-slate-700 hover:bg-slate-600 active:bg-slate-800"
              >
                Back
              </BigButton>
              <BigButton
                onClick={() => void submitManualVitals()}
                disabled={isSubmittingManualVitals}
                colorClass="bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700"
              >
                {isSubmittingManualVitals ? "Saving..." : "Save & Continue ➜"}
              </BigButton>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (screen === "redflag") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-red-700 px-6 py-10 text-white">
        <div className="text-7xl">🚨</div>
        <h1 className="text-4xl font-bold text-center">Please stay seated.</h1>
        <p className="text-2xl text-center">A staff member is being called to see you right now.</p>
        {redFlagReason && (
          <p className="max-w-lg text-center text-lg text-red-100 opacity-80">{redFlagReason}</p>
        )}
        <audio ref={audioElementRef} className="hidden" />
      </div>
    );
  }

  if (screen === "complete") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-emerald-800 px-6 py-10 text-white">
        <div className="text-7xl">✅</div>
        <h1 className="text-4xl font-bold text-center">Thank you!</h1>
        <p className="text-2xl text-center">Please wait, the doctor will see you shortly.</p>
        <audio ref={audioElementRef} className="hidden" />
      </div>
    );
  }

  // screen === "intake"
  return (
    <div className="flex min-h-screen flex-col items-center gap-8 bg-slate-950 px-6 py-10 text-white">
      <audio ref={audioElementRef} className="hidden" />

      <div className="w-full max-w-2xl rounded-3xl bg-slate-900 p-8 text-center shadow-xl">
        <p className="text-3xl font-semibold leading-snug">{audioPromptText || "..."}</p>
        <button
          type="button"
          onClick={() => void playAudioPrompt(audioPromptText)}
          className="mt-4 text-xl text-blue-400 hover:text-blue-300"
        >
          🔊 Replay
        </button>
      </div>

      {errorMessage && (
        <div className="w-full max-w-2xl rounded-xl bg-amber-900/60 p-4 text-center text-lg text-amber-200">
          {errorMessage}
        </div>
      )}

      <div className="grid w-full max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
        {touchOptions.map((option) => (
          <BigButton key={option} onClick={() => void submitTurn(option)} disabled={isProcessing || isRecording}>
            {option}
          </BigButton>
        ))}
      </div>

      <div className="mt-4 flex flex-col items-center gap-4">
        <WaveBars active={isRecording} levels={waveLevels} />
        <button
          type="button"
          onPointerDown={startRecording}
          onPointerUp={stopRecording}
          onPointerLeave={() => isRecording && stopRecording()}
          disabled={isProcessing}
          aria-label="Hold to speak your answer"
          className={`flex h-32 w-32 items-center justify-center rounded-full text-5xl shadow-2xl
            transition-transform active:scale-90 disabled:opacity-40 ${
              isRecording ? "bg-rose-600 animate-pulse" : "bg-blue-600 hover:bg-blue-500"
            }`}
        >
          🎤
        </button>
        <p className="text-lg text-slate-400">
          {isProcessing ? "Please wait..." : isRecording ? "Listening... release to send" : "Hold to speak"}
        </p>
      </div>
    </div>
  );
}
