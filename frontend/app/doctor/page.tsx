"use client";

/**
 * Doctor's OPD review dashboard (Next.js 14 App Router page).
 *
 * This page owns data fetching/mutation (the patient queue, loading one
 * case's detail, persisting doctor edits, and pushing the final FHIR
 * bundle); the actual editable summary UI is the modular
 * components/DoctorDesk.tsx, which owns its own local edit state and only
 * talks back to this page through props/callbacks.
 *
 * Backend contract this page expects (see app/routes/queue.py, app/main.py):
 *   GET  /queue/active                -> DoctorQueueEntry[]  (sidebar list)
 *   GET  /queue/patient/{session_id}  -> DoctorQueueEntry     (fresh detail on selection)
 *   PUT  /queue/patient/{session_id}  -> DoctorQueueEntry     (persist doctor edits before export)
 *   POST /fhir/generate               -> FHIR R4 Bundle       (see app/fhir_engine.py)
 *
 * KNOWN DATA GAP: app/database.py's `sessions` table stores only `abha_id`,
 * not the patient's name/age/gender in a fully reliable way for every
 * session (see app/routes/auth.py's OTP verification flow, which does
 * persist them when the kiosk check-in completes) -- until every session
 * has gone through that flow, expect `name`/`age`/`gender` to render blank
 * for older/incomplete sessions.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Clock,
  Inbox,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Siren,
  User,
} from "lucide-react";
import DoctorDesk, {
  type ClinicalState,
  type ExportPayload,
  type OcrData,
  type PatientInfo,
} from "../../components/DoctorDesk";

// --------------------------------------------------------------------------
// Types (mirrors intake-engine/app/database.py's serialized session record)
// --------------------------------------------------------------------------

interface DoctorQueueEntry extends ClinicalState {
  session_id: string;
  abha_id: string | null;
  name: string | null;
  age: number | null;
  gender: string | null;
  language: string;
  consent_given: boolean;
  status: "in_progress" | "completed" | "transferred_to_doctor";
  created_at: string;
  ocr_data: OcrData;
  trigger_red_flag: boolean;
}

const DEFAULT_API_BASE =
  typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_BASE_URL
    ? process.env.NEXT_PUBLIC_API_BASE_URL
    : "http://127.0.0.1:8001";

function timeAgo(isoTimestamp: string): string {
  const diffMs = Date.now() - new Date(isoTimestamp).getTime();
  const minutes = Math.max(0, Math.floor(diffMs / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// --------------------------------------------------------------------------
// Main page
// --------------------------------------------------------------------------

export default function DoctorPage() {
  const apiBaseUrl = DEFAULT_API_BASE;

  const [queue, setQueue] = useState<DoctorQueueEntry[]>([]);
  const [isLoadingQueue, setIsLoadingQueue] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [activeCase, setActiveCase] = useState<DoctorQueueEntry | null>(null);
  const [isLoadingCase, setIsLoadingCase] = useState(false);
  const [caseError, setCaseError] = useState<string | null>(null);

  const [isEscalated, setIsEscalated] = useState(false);

  const loadQueue = useCallback(async () => {
    setIsLoadingQueue(true);
    setQueueError(null);
    try {
      const resp = await fetch(`${apiBaseUrl}/queue/active`);
      if (!resp.ok) throw new Error(`Queue request failed (${resp.status})`);
      const data: DoctorQueueEntry[] = await resp.json();
      setQueue(data);
    } catch (err) {
      setQueueError(err instanceof Error ? err.message : "Could not load the patient queue.");
      setQueue([]);
    } finally {
      setIsLoadingQueue(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  // Fetches the freshest detail for whichever patient is selected, rather
  // than trusting the (possibly stale) copy already in the queue list --
  // another kiosk/device could have updated this session since the list
  // was loaded.
  useEffect(() => {
    if (!selectedSessionId) {
      setActiveCase(null);
      return;
    }

    let cancelled = false;
    setIsLoadingCase(true);
    setCaseError(null);
    setIsEscalated(false);

    (async () => {
      try {
        const resp = await fetch(`${apiBaseUrl}/queue/patient/${selectedSessionId}`);
        if (!resp.ok) throw new Error(`Failed to load patient detail (${resp.status})`);
        const data: DoctorQueueEntry = await resp.json();
        if (!cancelled) setActiveCase(data);
      } catch (err) {
        if (!cancelled) setCaseError(err instanceof Error ? err.message : "Could not load patient detail.");
      } finally {
        if (!cancelled) setIsLoadingCase(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [selectedSessionId, apiBaseUrl]);

  // Persists the doctor's edits to app.database, then generates the FHIR
  // bundle -- passed to DoctorDesk as onApproveAndPushFHIR so this page
  // (not DoctorDesk, which only holds local edit state) owns both writes.
  const handleApproveAndPushFHIR = useCallback(
    async (payload: ExportPayload): Promise<Record<string, unknown>> => {
      if (!activeCase) throw new Error("No patient selected");

      try {
        const putResp = await fetch(`${apiBaseUrl}/queue/patient/${activeCase.session_id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chief_complaint: payload.intake_state.chief_complaint,
            socrates: payload.intake_state.socrates,
            ayush_parameters: payload.intake_state.ayush_parameters,
            ocr_data: payload.ocr_data,
          }),
        });
        if (putResp.ok) {
          const updated: DoctorQueueEntry = await putResp.json();
          setActiveCase(updated);
          setQueue((prev) => prev.map((entry) => (entry.session_id === updated.session_id ? updated : entry)));
        }
        // A failed PUT here doesn't block the export below -- the doctor's
        // edits are still included in the FHIR bundle itself either way;
        // only the persisted copy in app.database would remain stale.
      } catch {
        // Same reasoning as above: persistence is best-effort here, export is not.
      }

      const resp = await fetch(`${apiBaseUrl}/fhir/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body?.message || `FHIR generation failed (${resp.status})`);
      }
      return resp.json();
    },
    [apiBaseUrl, activeCase]
  );

  const handleEscalate = () => {
    // No staff-alerting backend endpoint exists yet -- this is a local
    // acknowledgement so the doctor gets visible confirmation the action
    // registered. Wire this to a real paging/SMS integration in production.
    setIsEscalated(true);
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      {/* -------------------- Patient Queue Sidebar -------------------- */}
      <aside className="flex w-80 shrink-0 flex-col border-r border-slate-800 bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <h1 className="text-lg font-bold">Patient Queue</h1>
          <button
            type="button"
            onClick={() => void loadQueue()}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white"
            aria-label="Refresh queue"
          >
            <RefreshCw className={`h-4 w-4 ${isLoadingQueue ? "animate-spin" : ""}`} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoadingQueue && (
            <div className="flex items-center gap-2 p-4 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading queue...
            </div>
          )}

          {!isLoadingQueue && queueError && (
            <div className="m-3 rounded-lg bg-amber-950/50 p-3 text-xs text-amber-300">
              {queueError}
              <div className="mt-1 text-amber-400/70">Expected: GET {apiBaseUrl}/queue/active</div>
            </div>
          )}

          {!isLoadingQueue && !queueError && queue.length === 0 && (
            <div className="flex flex-col items-center gap-2 p-8 text-center text-slate-500">
              <Inbox className="h-8 w-8" />
              <p className="text-sm">No patients waiting.</p>
            </div>
          )}

          {queue.map((entry) => (
            <button
              key={entry.session_id}
              type="button"
              onClick={() => setSelectedSessionId(entry.session_id)}
              className={`block w-full border-b border-slate-800/70 p-4 text-left transition ${
                selectedSessionId === entry.session_id ? "bg-slate-800" : "hover:bg-slate-800/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-slate-400">{entry.abha_id ?? "No ABHA"}</span>
                {entry.trigger_red_flag && (
                  <span className="flex items-center gap-1 rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white">
                    <AlertTriangle className="h-3 w-3" /> URGENT
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-slate-300">
                {entry.age ?? "-"} yrs &middot; {entry.gender ?? "-"}
              </p>
              {entry.chief_complaint && (
                <span className="mt-2 inline-block rounded-full bg-blue-950 px-2 py-0.5 text-xs text-blue-300">
                  {entry.chief_complaint}
                </span>
              )}
              <p className="mt-2 flex items-center gap-1 text-[11px] text-slate-500">
                <Clock className="h-3 w-3" /> {timeAgo(entry.created_at)}
              </p>
            </button>
          ))}
        </div>
      </aside>

      {/* -------------------- Active Case -------------------- */}
      <main className="flex flex-1 flex-col overflow-y-auto">
        {isLoadingCase && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-slate-500">
            <Loader2 className="h-8 w-8 animate-spin" />
            <p>Loading patient detail...</p>
          </div>
        )}

        {!isLoadingCase && caseError && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center text-red-400">
            <AlertTriangle className="h-8 w-8" />
            <p>{caseError}</p>
          </div>
        )}

        {!isLoadingCase && !caseError && !activeCase && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-slate-500">
            <User className="h-10 w-10" />
            <p>Select a patient from the queue to begin review.</p>
          </div>
        )}

        {!isLoadingCase && !caseError && activeCase && (
          <>
            <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 bg-slate-900 px-6 py-4">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-bold">{activeCase.name ?? "Unknown Patient"}</h2>
                  <span className="font-mono text-sm text-slate-400">{activeCase.abha_id ?? "No ABHA ID"}</span>
                </div>
                <p className="mt-1 flex items-center gap-2 text-sm text-slate-400">
                  <Clock className="h-4 w-4" /> Visited {timeAgo(activeCase.created_at)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {activeCase.consent_given ? (
                  <span className="flex items-center gap-1.5 rounded-full bg-emerald-950 px-3 py-1.5 text-xs font-semibold text-emerald-400">
                    <ShieldCheck className="h-4 w-4" /> Consent Verified
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 rounded-full bg-red-950 px-3 py-1.5 text-xs font-semibold text-red-400">
                    <AlertTriangle className="h-4 w-4" /> Consent Not Given
                  </span>
                )}
                {activeCase.trigger_red_flag && (
                  <span className="flex items-center gap-1.5 rounded-full bg-red-600 px-3 py-1.5 text-xs font-bold text-white">
                    <Siren className="h-4 w-4" /> Red Flag
                  </span>
                )}
                {activeCase.trigger_red_flag && (
                  <button
                    type="button"
                    onClick={handleEscalate}
                    disabled={isEscalated}
                    className="flex items-center gap-1.5 rounded-full bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Siren className="h-4 w-4" /> {isEscalated ? "Escalated" : "Escalate Emergency"}
                  </button>
                )}
              </div>
            </header>

            <DoctorDesk
              key={activeCase.session_id}
              apiBaseUrl={apiBaseUrl}
              initialPatient={
                {
                  abha_id: activeCase.abha_id ?? "",
                  name: activeCase.name ?? "",
                  age: activeCase.age ?? "",
                  gender: activeCase.gender ?? "",
                } satisfies PatientInfo
              }
              initialIntakeState={
                {
                  chief_complaint: activeCase.chief_complaint,
                  socrates: activeCase.socrates,
                  ayush_parameters: activeCase.ayush_parameters,
                } satisfies ClinicalState
              }
              initialOcrData={
                {
                  patient_name: activeCase.ocr_data?.patient_name ?? null,
                  prescribed_medicines: activeCase.ocr_data?.prescribed_medicines ?? [],
                  ayush_formulations: activeCase.ocr_data?.ayush_formulations ?? [],
                  vitals_noted: activeCase.ocr_data?.vitals_noted ?? {},
                  raw_text_extracted: activeCase.ocr_data?.raw_text_extracted ?? "",
                } satisfies OcrData
              }
              onApproveAndPushFHIR={handleApproveAndPushFHIR}
            />
          </>
        )}
      </main>
    </div>
  );
}
