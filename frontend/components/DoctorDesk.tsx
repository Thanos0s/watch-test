"use client";

/**
 * DoctorDesk - review screen the OPD physician sees before a consultation.
 *
 * Shows everything the kiosk (intake-engine) and prescription OCR
 * (app/ocr_engine.py) gathered, lets the doctor correct any field, and
 * pushes the doctor-approved result to ABDM via POST /fhir/generate
 * (app/fhir_engine.py's generate_fhir_bundle).
 *
 * Nothing here is sent to ABDM until the doctor explicitly approves and
 * clicks Export -- this component never auto-submits.
 */

import { useMemo, useState } from "react";

// --------------------------------------------------------------------------
// Types (mirrors intake-engine/app/schema.py, app/ocr_engine.py, app/fhir_engine.py)
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

interface PrescribedMedicine {
  name: string;
  dosage: string | null;
  frequency: string | null;
  duration: string | null;
}

interface AyushFormulation {
  herb_or_churn: string;
  anupana: string | null;
  timing: string | null;
}

export interface OcrData {
  patient_name: string | null;
  prescribed_medicines: PrescribedMedicine[];
  ayush_formulations: AyushFormulation[];
  vitals_noted: Record<string, string>;
  raw_text_extracted: string;
}

export interface PatientInfo {
  abha_id: string;
  name: string;
  age: number | "";
  gender: string;
}

export interface ExportPayload {
  patient: { abha_id: string; name: string; age: number | null; gender: string };
  intake_state: ClinicalState;
  ocr_data: OcrData;
}

export interface DoctorDeskProps {
  apiBaseUrl?: string;
  initialPatient: PatientInfo;
  initialIntakeState: ClinicalState;
  initialOcrData: OcrData;
  onExported?: (bundle: Record<string, unknown>) => void;
  /** If provided, "Approve & Push to ABDM" calls this instead of DoctorDesk
   * POSTing to /fhir/generate itself -- lets a parent page own the network
   * call (e.g. to also persist the doctor's edits via PUT
   * /queue/patient/{id} before generating the bundle, since this
   * component only ever edits its own local state). Must resolve to the
   * generated FHIR bundle, or throw/reject to report a failure. Falls
   * back to DoctorDesk's own internal fetch when omitted, so it still
   * works standalone. */
  onApproveAndPushFHIR?: (payload: ExportPayload) => Promise<Record<string, unknown>>;
}

const DEFAULT_API_BASE =
  typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_BASE_URL
    ? process.env.NEXT_PUBLIC_API_BASE_URL
    : "http://127.0.0.1:8001";

const SOCRATES_LABELS: Record<keyof SocratesSlots, string> = {
  site: "Site",
  onset: "Onset",
  character: "Character",
  radiation: "Radiation",
  associations: "Associations",
  timing: "Timing",
  exacerbating_relieving: "Exacerbating / Relieving",
  severity: "Severity",
};

const AYUSH_LABELS: Record<keyof AyushParameters, string> = {
  dupshya: "Dushya (Dosha/Dhatu)",
  desha: "Desha (Habitat/Climate)",
  bala: "Bala (Physical Strength)",
  kala: "Kala (Season/Time)",
  anala_agni: "Agni (Digestive Fire)",
  prakriti: "Prakriti (Constitution)",
  vaya: "Vaya (Age Group)",
  sattva: "Sattva (Mental Temperament)",
  satmya: "Satmya (Tolerance)",
  ahara: "Ahara (Diet/Bowel Pattern)",
};

type FieldStatus = "ok" | "missing" | "uncertain";

/** No per-field OCR confidence score is available from the backend today, so
 * this is a lightweight heuristic: empty, very short, or containing
 * non-printable/garbled characters is treated as worth a second look. */
function isLowConfidenceOcrText(value: string | null | undefined): boolean {
  if (!value || value.trim().length < 2) return true;
  // eslint-disable-next-line no-control-regex
  const hasGarbledChars = /[^\x20-\x7Eऀ-ॿ]/.test(value);
  return hasGarbledChars;
}

// --------------------------------------------------------------------------
// Small presentational pieces
// --------------------------------------------------------------------------

function statusClasses(status: FieldStatus): string {
  switch (status) {
    case "missing":
      return "border-red-500/70 bg-red-950/30";
    case "uncertain":
      return "border-yellow-500/70 bg-yellow-950/30";
    default:
      return "border-slate-700 bg-slate-900";
  }
}

function EditableField({
  label,
  value,
  onChange,
  status = "ok",
}: {
  label: string;
  value: string | null;
  onChange: (value: string) => void;
  status?: FieldStatus;
}) {
  return (
    <div className={`rounded-lg border-2 p-3 ${statusClasses(status)}`}>
      <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">{label}</label>
      <input
        type="text"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={status === "missing" ? "Not collected - ask patient" : ""}
        className="mt-1 w-full bg-transparent text-base text-white outline-none placeholder:text-slate-500"
      />
      {status === "missing" && <p className="mt-1 text-xs text-red-400">⚠ Missing from intake</p>}
      {status === "uncertain" && <p className="mt-1 text-xs text-yellow-400">⚠ Verify - low OCR confidence</p>}
    </div>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="w-full rounded-2xl bg-slate-950 p-6 shadow-lg ring-1 ring-slate-800">
      <h2 className="mb-4 text-lg font-bold text-slate-200">{title}</h2>
      {children}
    </section>
  );
}

// --------------------------------------------------------------------------
// Main component
// --------------------------------------------------------------------------

export default function DoctorDesk({
  apiBaseUrl = DEFAULT_API_BASE,
  initialPatient,
  initialIntakeState,
  initialOcrData,
  onExported,
  onApproveAndPushFHIR,
}: DoctorDeskProps) {
  const [patient, setPatient] = useState<PatientInfo>(initialPatient);
  const [intakeState, setIntakeState] = useState<ClinicalState>(initialIntakeState);
  const [ocrData, setOcrData] = useState<OcrData>(initialOcrData);

  const [isApproved, setIsApproved] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportedBundle, setExportedBundle] = useState<Record<string, unknown> | null>(null);
  const [showRawOcr, setShowRawOcr] = useState(false);

  const missingCount = useMemo(() => {
    let count = intakeState.chief_complaint ? 0 : 1;
    count += Object.values(intakeState.socrates).filter((v) => !v).length;
    count += Object.values(intakeState.ayush_parameters).filter((v) => !v).length;
    return count;
  }, [intakeState]);

  const uncertainOcrCount = useMemo(() => {
    let count = 0;
    for (const med of ocrData.prescribed_medicines) {
      if (isLowConfidenceOcrText(med.name)) count += 1;
      if (isLowConfidenceOcrText(med.dosage)) count += 1;
      if (isLowConfidenceOcrText(med.frequency)) count += 1;
      if (isLowConfidenceOcrText(med.duration)) count += 1;
    }
    for (const formulation of ocrData.ayush_formulations) {
      if (isLowConfidenceOcrText(formulation.herb_or_churn)) count += 1;
      if (isLowConfidenceOcrText(formulation.anupana)) count += 1;
      if (isLowConfidenceOcrText(formulation.timing)) count += 1;
    }
    for (const value of Object.values(ocrData.vitals_noted)) {
      if (isLowConfidenceOcrText(value)) count += 1;
    }
    return count;
  }, [ocrData]);

  // ------------------------------------------------------------------
  // Field update helpers (all immutable)
  // ------------------------------------------------------------------

  const updateSocrates = (field: keyof SocratesSlots, value: string) => {
    setIsApproved(false);
    setIntakeState((prev) => ({ ...prev, socrates: { ...prev.socrates, [field]: value || null } }));
  };

  const updateAyush = (field: keyof AyushParameters, value: string) => {
    setIsApproved(false);
    setIntakeState((prev) => ({
      ...prev,
      ayush_parameters: { ...prev.ayush_parameters, [field]: value || null },
    }));
  };

  const updateMedicine = (index: number, field: keyof PrescribedMedicine, value: string) => {
    setIsApproved(false);
    setOcrData((prev) => {
      const next = [...prev.prescribed_medicines];
      next[index] = { ...next[index], [field]: value };
      return { ...prev, prescribed_medicines: next };
    });
  };

  const removeMedicine = (index: number) => {
    setIsApproved(false);
    setOcrData((prev) => ({
      ...prev,
      prescribed_medicines: prev.prescribed_medicines.filter((_, i) => i !== index),
    }));
  };

  const addMedicine = () => {
    setIsApproved(false);
    setOcrData((prev) => ({
      ...prev,
      prescribed_medicines: [...prev.prescribed_medicines, { name: "", dosage: "", frequency: "", duration: "" }],
    }));
  };

  const updateFormulation = (index: number, field: keyof AyushFormulation, value: string) => {
    setIsApproved(false);
    setOcrData((prev) => {
      const next = [...prev.ayush_formulations];
      next[index] = { ...next[index], [field]: value };
      return { ...prev, ayush_formulations: next };
    });
  };

  const removeFormulation = (index: number) => {
    setIsApproved(false);
    setOcrData((prev) => ({
      ...prev,
      ayush_formulations: prev.ayush_formulations.filter((_, i) => i !== index),
    }));
  };

  const addFormulation = () => {
    setIsApproved(false);
    setOcrData((prev) => ({
      ...prev,
      ayush_formulations: [...prev.ayush_formulations, { herb_or_churn: "", anupana: "", timing: "" }],
    }));
  };

  const updateVital = (key: string, value: string) => {
    setIsApproved(false);
    setOcrData((prev) => ({ ...prev, vitals_noted: { ...prev.vitals_noted, [key]: value } }));
  };

  const renameVitalKey = (oldKey: string, newKey: string) => {
    if (!newKey || newKey === oldKey) return;
    setIsApproved(false);
    setOcrData((prev) => {
      const entries = Object.entries(prev.vitals_noted).map(([k, v]) => (k === oldKey ? [newKey, v] : [k, v]));
      return { ...prev, vitals_noted: Object.fromEntries(entries) };
    });
  };

  const removeVital = (key: string) => {
    setIsApproved(false);
    setOcrData((prev) => {
      const { [key]: _removed, ...rest } = prev.vitals_noted;
      return { ...prev, vitals_noted: rest };
    });
  };

  const addVital = () => {
    setIsApproved(false);
    let key = "New vital";
    let suffix = 1;
    while (key in ocrData.vitals_noted) {
      key = `New vital ${suffix}`;
      suffix += 1;
    }
    setOcrData((prev) => ({ ...prev, vitals_noted: { ...prev.vitals_noted, [key]: "" } }));
  };

  // ------------------------------------------------------------------
  // Export to ABDM
  // ------------------------------------------------------------------

  const handleExport = async () => {
    setIsExporting(true);
    setExportError(null);
    const payload: ExportPayload = {
      patient: {
        abha_id: patient.abha_id,
        name: patient.name,
        age: patient.age === "" ? null : patient.age,
        gender: patient.gender,
      },
      intake_state: intakeState,
      ocr_data: ocrData,
    };

    try {
      let bundle: Record<string, unknown>;
      if (onApproveAndPushFHIR) {
        bundle = await onApproveAndPushFHIR(payload);
      } else {
        const resp = await fetch(`${apiBaseUrl}/fhir/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(body?.message || `FHIR generation failed (${resp.status})`);
        }

        bundle = await resp.json();
      }

      setExportedBundle(bundle);
      onExported?.(bundle);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Failed to export FHIR bundle.");
    } finally {
      setIsExporting(false);
    }
  };

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 bg-slate-900 p-6 text-slate-100">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Doctor&apos;s Review Desk</h1>
          <p className="text-sm text-slate-400">
            {missingCount > 0 && (
              <span className="mr-3 text-red-400">⚠ {missingCount} intake field(s) missing</span>
            )}
            {uncertainOcrCount > 0 && (
              <span className="text-yellow-400">⚠ {uncertainOcrCount} OCR field(s) need verification</span>
            )}
            {missingCount === 0 && uncertainOcrCount === 0 && (
              <span className="text-emerald-400">✓ Nothing flagged</span>
            )}
          </p>
        </div>
      </header>

      <SectionCard title="Patient">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <EditableField
            label="ABHA ID"
            value={patient.abha_id}
            onChange={(v) => setPatient((p) => ({ ...p, abha_id: v }))}
            status={patient.abha_id ? "ok" : "missing"}
          />
          <EditableField
            label="Name"
            value={patient.name}
            onChange={(v) => setPatient((p) => ({ ...p, name: v }))}
            status={patient.name ? "ok" : "missing"}
          />
          <EditableField
            label="Age"
            value={patient.age === "" ? null : String(patient.age)}
            onChange={(v) => setPatient((p) => ({ ...p, age: v === "" ? "" : Number(v) || "" }))}
            status={patient.age !== "" ? "ok" : "missing"}
          />
          <EditableField
            label="Gender"
            value={patient.gender}
            onChange={(v) => setPatient((p) => ({ ...p, gender: v }))}
            status={patient.gender ? "ok" : "missing"}
          />
        </div>
      </SectionCard>

      <SectionCard title="Chief Complaint">
        <EditableField
          label="Chief Complaint"
          value={intakeState.chief_complaint}
          onChange={(v) => {
            setIsApproved(false);
            setIntakeState((prev) => ({ ...prev, chief_complaint: v || null }));
          }}
          status={intakeState.chief_complaint ? "ok" : "missing"}
        />
      </SectionCard>

      <SectionCard title="SOCRATES - History of Present Illness">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(Object.keys(SOCRATES_LABELS) as (keyof SocratesSlots)[]).map((field) => (
            <EditableField
              key={field}
              label={SOCRATES_LABELS[field]}
              value={intakeState.socrates[field]}
              onChange={(v) => updateSocrates(field, v)}
              status={intakeState.socrates[field] ? "ok" : "missing"}
            />
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Dashavidha Pariksha - AYUSH Examination">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(Object.keys(AYUSH_LABELS) as (keyof AyushParameters)[]).map((field) => (
            <EditableField
              key={field}
              label={AYUSH_LABELS[field]}
              value={intakeState.ayush_parameters[field]}
              onChange={(v) => updateAyush(field, v)}
              status={intakeState.ayush_parameters[field] ? "ok" : "missing"}
            />
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Prescribed Medicines (OCR)">
        <div className="flex flex-col gap-4">
          {ocrData.prescribed_medicines.length === 0 && (
            <p className="text-sm text-slate-500">No medicines extracted from the uploaded document.</p>
          )}
          {ocrData.prescribed_medicines.map((med, index) => (
            <div key={index} className="grid grid-cols-1 gap-3 rounded-xl bg-slate-800/50 p-4 sm:grid-cols-5">
              <EditableField
                label="Name"
                value={med.name}
                onChange={(v) => updateMedicine(index, "name", v)}
                status={isLowConfidenceOcrText(med.name) ? "uncertain" : "ok"}
              />
              <EditableField
                label="Dosage"
                value={med.dosage}
                onChange={(v) => updateMedicine(index, "dosage", v)}
                status={isLowConfidenceOcrText(med.dosage) ? "uncertain" : "ok"}
              />
              <EditableField
                label="Frequency"
                value={med.frequency}
                onChange={(v) => updateMedicine(index, "frequency", v)}
                status={isLowConfidenceOcrText(med.frequency) ? "uncertain" : "ok"}
              />
              <EditableField
                label="Duration"
                value={med.duration}
                onChange={(v) => updateMedicine(index, "duration", v)}
                status={isLowConfidenceOcrText(med.duration) ? "uncertain" : "ok"}
              />
              <div className="flex items-end">
                <button
                  type="button"
                  onClick={() => removeMedicine(index)}
                  className="w-full rounded-lg bg-rose-900/60 px-3 py-2 text-sm text-rose-200 hover:bg-rose-800"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={addMedicine}
            className="self-start rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            + Add Medicine
          </button>
        </div>
      </SectionCard>

      <SectionCard title="AYUSH Formulations (OCR)">
        <div className="flex flex-col gap-4">
          {ocrData.ayush_formulations.length === 0 && (
            <p className="text-sm text-slate-500">No AYUSH formulations extracted from the uploaded document.</p>
          )}
          {ocrData.ayush_formulations.map((formulation, index) => (
            <div key={index} className="grid grid-cols-1 gap-3 rounded-xl bg-slate-800/50 p-4 sm:grid-cols-4">
              <EditableField
                label="Herb / Churna"
                value={formulation.herb_or_churn}
                onChange={(v) => updateFormulation(index, "herb_or_churn", v)}
                status={isLowConfidenceOcrText(formulation.herb_or_churn) ? "uncertain" : "ok"}
              />
              <EditableField
                label="Anupana"
                value={formulation.anupana}
                onChange={(v) => updateFormulation(index, "anupana", v)}
                status={isLowConfidenceOcrText(formulation.anupana) ? "uncertain" : "ok"}
              />
              <EditableField
                label="Timing"
                value={formulation.timing}
                onChange={(v) => updateFormulation(index, "timing", v)}
                status={isLowConfidenceOcrText(formulation.timing) ? "uncertain" : "ok"}
              />
              <div className="flex items-end">
                <button
                  type="button"
                  onClick={() => removeFormulation(index)}
                  className="w-full rounded-lg bg-rose-900/60 px-3 py-2 text-sm text-rose-200 hover:bg-rose-800"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={addFormulation}
            className="self-start rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            + Add Formulation
          </button>
        </div>
      </SectionCard>

      <SectionCard title="Vitals / Labs (OCR)">
        <div className="flex flex-col gap-3">
          {Object.entries(ocrData.vitals_noted).length === 0 && (
            <p className="text-sm text-slate-500">No vitals extracted from the uploaded document.</p>
          )}
          {Object.entries(ocrData.vitals_noted).map(([key, value]) => (
            <div key={key} className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
              <input
                type="text"
                defaultValue={key}
                onBlur={(e) => renameVitalKey(key, e.target.value)}
                className="rounded-lg border-2 border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
              />
              <input
                type="text"
                value={value}
                onChange={(e) => updateVital(key, e.target.value)}
                className={`rounded-lg border-2 px-3 py-2 text-sm text-white ${
                  isLowConfidenceOcrText(value) ? "border-yellow-500/70 bg-yellow-950/30" : "border-slate-700 bg-slate-900"
                }`}
              />
              <button
                type="button"
                onClick={() => removeVital(key)}
                className="rounded-lg bg-rose-900/60 px-3 py-2 text-sm text-rose-200 hover:bg-rose-800"
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addVital}
            className="self-start rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            + Add Vital
          </button>
        </div>
      </SectionCard>

      <SectionCard title="Raw OCR Text">
        <button
          type="button"
          onClick={() => setShowRawOcr((v) => !v)}
          className="mb-2 text-sm text-blue-400 hover:text-blue-300"
        >
          {showRawOcr ? "Hide" : "Show"} raw extracted text
        </button>
        {showRawOcr && (
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-black/40 p-4 text-xs text-slate-300">
            {ocrData.raw_text_extracted || "(no raw text captured)"}
          </pre>
        )}
      </SectionCard>

      <SectionCard title="Approve & Export to ABDM">
        <label className="mb-4 flex items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={isApproved}
            onChange={(e) => setIsApproved(e.target.checked)}
            className="h-5 w-5"
          />
          I have reviewed and verified this summary. It is accurate and ready to send.
        </label>

        {exportError && (
          <div className="mb-4 rounded-lg bg-red-950/50 p-3 text-sm text-red-300">{exportError}</div>
        )}

        <button
          type="button"
          onClick={handleExport}
          disabled={!isApproved || isExporting}
          className="rounded-xl bg-emerald-600 px-6 py-3 text-lg font-semibold text-white shadow-lg
            transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {isExporting ? "Generating FHIR bundle..." : "📤 Export to ABDM (FHIR)"}
        </button>

        {exportedBundle && (
          <div className="mt-4">
            <p className="mb-2 text-sm text-emerald-400">✓ FHIR bundle generated successfully.</p>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-black/40 p-4 text-xs text-slate-300">
              {JSON.stringify(exportedBundle, null, 2)}
            </pre>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
