/**
 * Mock response builders for PrakritiDesk's backend API.
 *
 * Shapes here mirror the real Pydantic/TypeScript contracts exactly (see
 * intake-engine/app/schema.py, app/routes/auth.py, app/routes/queue.py,
 * app/routes/vitals.py, and frontend/components/KioskUI.tsx /
 * DoctorDesk.tsx) so a test failure means the UI genuinely broke against a
 * realistic payload, not that the mock drifted from reality.
 *
 * These are used with Playwright's `page.route()` to intercept calls to
 * the FastAPI backend so E2E tests run fast and deterministically, without
 * needing a live Groq/Bhashini/ABDM connection -- exactly the "mock
 * network requests for heavy AI APIs" requirement.
 */

export interface MockSocratesSlots {
  site: string | null;
  onset: string | null;
  character: string | null;
  radiation: string | null;
  associations: string | null;
  timing: string | null;
  exacerbating_relieving: string | null;
  severity: string | null;
}

export interface MockAyushParameters {
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

export const EMPTY_SOCRATES: MockSocratesSlots = {
  site: null,
  onset: null,
  character: null,
  radiation: null,
  associations: null,
  timing: null,
  exacerbating_relieving: null,
  severity: null,
};

export const EMPTY_AYUSH: MockAyushParameters = {
  dupshya: null,
  desha: null,
  bala: null,
  kala: null,
  anala_agni: null,
  prakriti: null,
  vaya: null,
  sattva: null,
  satmya: null,
  ahara: null,
};

/** POST /auth/abha/init-otp */
export function mockInitOtpResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    txn_id: "mock-txn-e2e-test",
    message: "OTP sent to registered mobile",
    gateway_mode: "simulated",
    sandbox_otp_hint: "123456",
    disclaimer: "Simulated ABDM Gateway - Production requires certified M1/M2 CM-ID credentials.",
    ...overrides,
  };
}

/** POST /auth/abha/verify-otp */
export function mockVerifyOtpResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    verification_status: "mock_verified",
    is_mock: true,
    gateway_mode: "simulated",
    session_id: "e2e-test-session",
    abha_id_or_mobile: "9876543210",
    patient_record: {
      session_id: "e2e-test-session",
      abha_id: "9876543210",
      patient_name: "Ramesh Kumar",
      age: 45,
      gender: "male",
      abha_address: "ramesh01@abdm",
      consent_given: false,
      status: "in_progress",
    },
    disclaimer: "Simulated ABDM Gateway - Production requires certified M1/M2 CM-ID credentials.",
    ...overrides,
  };
}

/** GET /intake/opening-question and POST /intake/turn share this response shape. */
export function mockIntakeTurnResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    audio_prompt_text: "What is bothering you today?",
    touch_options: ["Pain", "Fever", "Cough/Cold", "Other/Describe"],
    updated_clinical_state: {
      chief_complaint: null,
      socrates: EMPTY_SOCRATES,
      ayush_parameters: EMPTY_AYUSH,
    },
    is_complete: false,
    trigger_red_flag: false,
    red_flag_reason: null,
    ...overrides,
  };
}

/** The same shape, but for a turn that trips the deterministic red-flag safety net. */
export function mockRedFlagTurnResponse(reason = "Possible acute coronary event (chest pain with radiation)") {
  return mockIntakeTurnResponse({
    audio_prompt_text: "Please stay seated. A staff member is being called to see you right now.",
    touch_options: ["Call staff now"],
    trigger_red_flag: true,
    red_flag_reason: reason,
  });
}

/** POST /vitals/sync */
export function mockVitalsSyncResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    session_id: "e2e-test-session",
    trigger_red_flag: false,
    red_flag_reason: null,
    nadi_trait_estimate: "Sama Agni / Balanced Pulse",
    hrv_sdnn_ms: null,
    patient_record: {},
    ...overrides,
  };
}

/** One entry of GET /queue/active's response array / GET /queue/patient/{id}'s response. */
export function mockDoctorQueueEntry(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    session_id: "e2e-test-session",
    abha_id: "9876543210",
    name: "Ramesh Kumar",
    age: 45,
    gender: "male",
    language: "Hindi",
    consent_given: true,
    status: "transferred_to_doctor",
    created_at: new Date().toISOString(),
    chief_complaint: "Chest discomfort",
    socrates: { ...EMPTY_SOCRATES, site: "Central chest", severity: "Severe (8-10)" },
    ayush_parameters: EMPTY_AYUSH,
    ocr_data: {
      patient_name: null,
      prescribed_medicines: [],
      ayush_formulations: [],
      vitals_noted: {},
      raw_text_extracted: "",
    },
    trigger_red_flag: false,
    ...overrides,
  };
}

/** A second, non-urgent queue entry -- useful for asserting the urgent
 * badge only appears on the flagged patient, not on every entry. */
export function mockNormalQueueEntry(overrides: Partial<Record<string, unknown>> = {}) {
  return mockDoctorQueueEntry({
    session_id: "e2e-normal-session",
    abha_id: "9876500000",
    name: "Sunita Sharma",
    chief_complaint: "Mild headache",
    trigger_red_flag: false,
    status: "in_progress",
    ...overrides,
  });
}

/** POST /fhir/generate */
export function mockFhirBundle(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    resourceType: "Bundle",
    id: "mock-bundle-id",
    type: "collection",
    timestamp: new Date().toISOString(),
    entry: [
      { fullUrl: "urn:uuid:mock-patient", resource: { resourceType: "Patient", id: "mock-patient", gender: "male" } },
      {
        fullUrl: "urn:uuid:mock-condition",
        resource: { resourceType: "Condition", id: "mock-condition", code: { text: "Chest discomfort" } },
      },
    ],
    ...overrides,
  };
}

/** A short, valid, silent WAV clip -- for mocking POST /audio/synthesize
 * without needing a real Bhashini call. Matches what
 * app/audio_engine.py's _generate_silent_wav_bytes() fallback produces:
 * a standard RIFF/WAVE header around PCM silence. */
export function mockSilentWavBytes(): Buffer {
  const sampleRate = 16000;
  const numSamples = Math.floor(sampleRate * 0.2); // 200ms
  const dataSize = numSamples * 2; // 16-bit mono
  const buffer = Buffer.alloc(44 + dataSize);

  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20); // PCM
  buffer.writeUInt16LE(1, 22); // mono
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);
  // remaining bytes default to 0 (silence)

  return buffer;
}
