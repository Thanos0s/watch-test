/**
 * Unit tests for SmartwatchBridge component - Bluetooth pairing, vitals capture,
 * and auto-sync logic.
 * 
 * Tests cover:
 * - GATT payload parsing (Heart Rate, SpO2)
 * - Stability detection algorithm
 * - Bluetooth API integration with mocked navigator.bluetooth
 * - Auto-sync cooldown and triggering logic
 * - Error handling and unsupported browser detection
 */

import { describe, it, expect, beforeEach, afterEach, vi, Mock } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import SmartwatchBridge from '../components/SmartwatchBridge';

// Mock Web Bluetooth API types
interface MockBleCharacteristic extends EventTarget {
  value: DataView | null;
  startNotifications: Mock;
  stopNotifications: Mock;
}

interface MockBleService {
  getCharacteristic: Mock;
}

interface MockBleRemoteGATTServer {
  connected: boolean;
  connect: Mock;
  disconnect: Mock;
  getPrimaryService: Mock;
}

interface MockBleDevice extends EventTarget {
  name?: string;
  gatt?: MockBleRemoteGATTServer;
}

interface MockBluetoothApi {
  requestDevice: Mock;
}

// Helper to create a mock BLE characteristic
function createMockCharacteristic(initialValue: DataView | null = null): MockBleCharacteristic {
  const characteristic = new EventTarget() as MockBleCharacteristic;
  characteristic.value = initialValue;
  characteristic.startNotifications = vi.fn().mockResolvedValue(characteristic);
  characteristic.stopNotifications = vi.fn().mockResolvedValue(characteristic);
  return characteristic;
}

// Helper to create a mock GATT server with full device hierarchy
function createMockGattServer(options: {
  heartRateValue?: DataView;
  hasPulseOximeter?: boolean;
  spo2Value?: DataView;
} = {}): MockBleRemoteGATTServer {
  const hrCharacteristic = createMockCharacteristic(options.heartRateValue || null);
  const plxCharacteristic = createMockCharacteristic(options.spo2Value || null);

  const heartRateService: MockBleService = {
    getCharacteristic: vi.fn().mockResolvedValue(hrCharacteristic),
  };

  const pulseOxService: MockBleService = {
    getCharacteristic: vi.fn().mockResolvedValue(plxCharacteristic),
  };

  const server: MockBleRemoteGATTServer = {
    connected: true,
    connect: vi.fn(function(this: MockBleRemoteGATTServer) {
      return Promise.resolve(this);
    }),
    disconnect: vi.fn(),
    getPrimaryService: vi.fn((serviceId: string) => {
      if (serviceId === 'heart_rate') return Promise.resolve(heartRateService);
      if (serviceId === 'pulse_oximeter') {
        if (options.hasPulseOximeter) return Promise.resolve(pulseOxService);
        return Promise.reject(new Error('Service not found'));
      }
      return Promise.reject(new Error('Unknown service'));
    }),
  };

  // Bind connect to return the server instance
  server.connect = vi.fn().mockResolvedValue(server);

  return server;
}

// Helper to create Heart Rate Measurement DataView (GATT spec format)
function createHeartRateDataView(bpm: number, is16Bit = false): DataView {
  const buffer = new ArrayBuffer(is16Bit ? 3 : 2);
  const view = new DataView(buffer);
  view.setUint8(0, is16Bit ? 0x01 : 0x00); // flags byte
  if (is16Bit) {
    view.setUint16(1, bpm, true); // little-endian
  } else {
    view.setUint8(1, bpm);
  }
  return view;
}

// Helper to create PLX Continuous Measurement DataView (IEEE-11073 SFLOAT)
function createSpo2DataView(spo2Percent: number): DataView {
  const buffer = new ArrayBuffer(5);
  const view = new DataView(buffer);
  view.setUint8(0, 0x00); // flags
  
  // Encode SpO2 as SFLOAT: mantissa=spo2Percent, exponent=0
  const sfloat = spo2Percent & 0x0fff; // mantissa in lower 12 bits, exponent 0
  view.setUint16(1, sfloat, true);
  
  // Pulse rate (not needed for SpO2 test, but required by spec)
  view.setUint16(3, 70, true); // dummy 70 bpm
  return view;
}

describe('SmartwatchBridge - GATT Payload Parsing', () => {
  it('should parse 8-bit heart rate measurement correctly', () => {
    const view = createHeartRateDataView(72, false);
    // Parse manually to test the algorithm
    const flags = view.getUint8(0);
    const is16Bit = (flags & 0x01) !== 0;
    const bpm = is16Bit ? view.getUint16(1, true) : view.getUint8(1);
    expect(bpm).toBe(72);
  });

  it('should parse 16-bit heart rate measurement correctly', () => {
    const view = createHeartRateDataView(180, true);
    const flags = view.getUint8(0);
    const is16Bit = (flags & 0x01) !== 0;
    const bpm = is16Bit ? view.getUint16(1, true) : view.getUint8(1);
    expect(bpm).toBe(180);
  });

  it('should parse SpO2 from PLX Continuous Measurement', () => {
    const view = createSpo2DataView(98);
    const rawSpo2 = view.getUint16(1, true);
    const mantissa = rawSpo2 & 0x0fff;
    expect(mantissa).toBe(98);
  });
});

describe('SmartwatchBridge - Stability Detection', () => {
  const STABILITY_WINDOW_SIZE = 5;
  const STABILITY_TOLERANCE_BPM = 4;

  function isStable(readings: number[]): boolean {
    if (readings.length < STABILITY_WINDOW_SIZE) return false;
    const window = readings.slice(-STABILITY_WINDOW_SIZE);
    return Math.max(...window) - Math.min(...window) <= STABILITY_TOLERANCE_BPM;
  }

  it('should return false when fewer than 5 readings', () => {
    expect(isStable([72])).toBe(false);
    expect(isStable([72, 73])).toBe(false);
    expect(isStable([72, 73, 74, 75])).toBe(false);
  });

  it('should return true when 5 readings within tolerance', () => {
    expect(isStable([70, 71, 72, 73, 74])).toBe(true); // range = 4
    expect(isStable([100, 101, 102, 103, 104])).toBe(true); // range = 4
  });

  it('should return false when readings exceed tolerance', () => {
    expect(isStable([70, 71, 72, 73, 75])).toBe(false); // range = 5
    expect(isStable([60, 65, 70, 75, 80])).toBe(false); // range = 20
  });

  it('should use only the last 5 readings for stability check', () => {
    // First 5 are unstable, last 5 are stable
    const readings = [50, 60, 70, 80, 90, 100, 101, 102, 103, 104];
    expect(isStable(readings)).toBe(true);
  });

  it('should handle edge case with exactly tolerance boundary', () => {
    expect(isStable([70, 71, 72, 73, 74])).toBe(true); // range = 4 (within)
    expect(isStable([70, 71, 72, 73, 75])).toBe(false); // range = 5 (exceeds)
  });
});

describe('SmartwatchBridge - Component Rendering', () => {
  let mockBluetooth: MockBluetoothApi;
  let originalNavigator: typeof navigator;

  beforeEach(() => {
    originalNavigator = global.navigator;
    mockBluetooth = {
      requestDevice: vi.fn(),
    };
    
    Object.defineProperty(global.navigator, 'bluetooth', {
      value: mockBluetooth,
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    global.navigator = originalNavigator;
    vi.clearAllMocks();
  });

  it('should show unsupported message when Web Bluetooth is not available', () => {
    Object.defineProperty(global.navigator, 'bluetooth', {
      value: undefined,
      writable: true,
      configurable: true,
    });

    render(<SmartwatchBridge sessionId="test-session" />);
    
    expect(screen.getByText(/Bluetooth pairing not supported/i)).toBeInTheDocument();
    expect(screen.getByText(/Use Chrome or Edge/i)).toBeInTheDocument();
  });

  it('should show pair button when Web Bluetooth is available', () => {
    render(<SmartwatchBridge sessionId="test-session" />);
    
    expect(screen.getByRole('button', { name: /Tap to Pair/i })).toBeInTheDocument();
  });

  it('should show device name after successful pairing', async () => {
    const mockDevice: MockBleDevice = new EventTarget() as MockBleDevice;
    mockDevice.name = 'Fitbit Charge 5';
    mockDevice.gatt = createMockGattServer({ hasPulseOximeter: false });

    mockBluetooth.requestDevice.mockResolvedValue(mockDevice);

    render(<SmartwatchBridge sessionId="test-session" />);
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      expect(screen.getByText(/Paired: Fitbit Charge 5/i)).toBeInTheDocument();
    });
  });

  it('should show SpO2 not available when device lacks pulse oximeter service', async () => {
    const mockDevice: MockBleDevice = new EventTarget() as MockBleDevice;
    mockDevice.name = 'Basic HR Monitor';
    mockDevice.gatt = createMockGattServer({ hasPulseOximeter: false });

    mockBluetooth.requestDevice.mockResolvedValue(mockDevice);

    render(<SmartwatchBridge sessionId="test-session" />);
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      expect(screen.getByText(/Not available from this device/i)).toBeInTheDocument();
    });
  });

  it('should handle user cancellation gracefully (NotFoundError)', async () => {
    const cancelError = new DOMException('User cancelled', 'NotFoundError');
    mockBluetooth.requestDevice.mockRejectedValue(cancelError);

    render(<SmartwatchBridge sessionId="test-session" />);
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      // Should return to idle state without error message
      expect(screen.getByRole('button', { name: /Tap to Pair/i })).toBeInTheDocument();
      expect(screen.queryByText(/Could not pair/i)).not.toBeInTheDocument();
    });
  });

  it('should show error message for actual pairing failures', async () => {
    const pairingError = new Error('Bluetooth adapter not found');
    mockBluetooth.requestDevice.mockRejectedValue(pairingError);

    render(<SmartwatchBridge sessionId="test-session" />);
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      expect(screen.getByText(/Bluetooth adapter not found/i)).toBeInTheDocument();
    });
  });
});

describe('SmartwatchBridge - Heart Rate Display and Notifications', () => {
  let mockBluetooth: MockBluetoothApi;
  let mockHrCharacteristic: MockBleCharacteristic;
  let originalNavigator: any;

  beforeEach(() => {
    originalNavigator = global.navigator;
    mockBluetooth = { requestDevice: vi.fn() };
    mockHrCharacteristic = createMockCharacteristic();
    
    Object.defineProperty(global, 'navigator', {
      value: { ...originalNavigator, bluetooth: mockBluetooth },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(global, 'navigator', {
      value: originalNavigator,
      writable: true,
      configurable: true,
    });
    vi.clearAllMocks();
  });

  it('should display heart rate when notification is received', async () => {
    // Create the characteristic that will be returned by the service
    const mockHrChar = createMockCharacteristic();
    
    const heartRateService: MockBleService = {
      getCharacteristic: vi.fn().mockResolvedValue(mockHrChar),
    };

    const mockGatt: MockBleRemoteGATTServer = {
      connected: true,
      connect: vi.fn(),
      disconnect: vi.fn(),
      getPrimaryService: vi.fn((serviceId: string) => {
        if (serviceId === 'heart_rate') return Promise.resolve(heartRateService);
        return Promise.reject(new Error('Service not found'));
      }),
    };
    mockGatt.connect = vi.fn().mockResolvedValue(mockGatt);

    const mockDevice: MockBleDevice = new EventTarget() as MockBleDevice;
    mockDevice.name = 'Test Device';
    mockDevice.gatt = mockGatt;

    mockBluetooth.requestDevice.mockResolvedValue(mockDevice);

    render(<SmartwatchBridge sessionId="test-session" />);
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      expect(screen.getByText(/Paired:/i)).toBeInTheDocument();
    });

    // Simulate heart rate notification using the same characteristic instance
    mockHrChar.value = createHeartRateDataView(75);
    const event = new Event('characteristicvaluechanged');
    Object.defineProperty(event, 'currentTarget', { value: mockHrChar });
    mockHrChar.dispatchEvent(event);

    await waitFor(() => {
      expect(screen.getByText('75')).toBeInTheDocument();
      expect(screen.getByText('bpm')).toBeInTheDocument();
    });
  });

  it('should display SpO2 when device supports it and notification is received', async () => {
    // Create the characteristics that will be returned by the services
    const mockHrChar = createMockCharacteristic();
    const mockPlxChar = createMockCharacteristic();
    
    const heartRateService: MockBleService = {
      getCharacteristic: vi.fn().mockResolvedValue(mockHrChar),
    };

    const pulseOxService: MockBleService = {
      getCharacteristic: vi.fn().mockResolvedValue(mockPlxChar),
    };

    const mockGatt: MockBleRemoteGATTServer = {
      connected: true,
      connect: vi.fn(),
      disconnect: vi.fn(),
      getPrimaryService: vi.fn((serviceId: string) => {
        if (serviceId === 'heart_rate') return Promise.resolve(heartRateService);
        if (serviceId === 'pulse_oximeter') return Promise.resolve(pulseOxService);
        return Promise.reject(new Error('Service not found'));
      }),
    };
    mockGatt.connect = vi.fn().mockResolvedValue(mockGatt);

    const mockDevice: MockBleDevice = new EventTarget() as MockBleDevice;
    mockDevice.name = 'Advanced Monitor';
    mockDevice.gatt = mockGatt;

    mockBluetooth.requestDevice.mockResolvedValue(mockDevice);

    render(<SmartwatchBridge sessionId="test-session" />);
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      expect(screen.getByText(/Paired:/i)).toBeInTheDocument();
    });

    // Simulate SpO2 notification using the same characteristic instance
    mockPlxChar.value = createSpo2DataView(98);
    const event = new Event('characteristicvaluechanged');
    Object.defineProperty(event, 'currentTarget', { value: mockPlxChar });
    mockPlxChar.dispatchEvent(event);

    await waitFor(() => {
      expect(screen.getByText('98')).toBeInTheDocument();
      expect(screen.getByText('%')).toBeInTheDocument();
    });
  });
});

describe('SmartwatchBridge - Auto-sync Logic', () => {
  let mockBluetooth: MockBluetoothApi;
  let mockFetch: Mock;
  let originalNavigator: any;
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalNavigator = global.navigator;
    originalFetch = global.fetch;
    
    mockBluetooth = { requestDevice: vi.fn() };
    mockFetch = vi.fn();
    
    Object.defineProperty(global, 'navigator', {
      value: { ...originalNavigator, bluetooth: mockBluetooth },
      writable: true,
      configurable: true,
    });
    
    global.fetch = mockFetch as any;
  });

  afterEach(() => {
    Object.defineProperty(global, 'navigator', {
      value: originalNavigator,
      writable: true,
      configurable: true,
    });
    global.fetch = originalFetch;
    vi.clearAllMocks();
  });

  it('should NOT auto-sync when readings are unstable', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        session_id: 'test',
        trigger_red_flag: false,
        red_flag_reason: null,
        nadi_trait_estimate: null,
        hrv_sdnn_ms: null,
        patient_record: {},
      }),
    });

    // Create the characteristic that will be returned by the service
    const mockHrChar = createMockCharacteristic();
    
    const heartRateService: MockBleService = {
      getCharacteristic: vi.fn().mockResolvedValue(mockHrChar),
    };

    const mockGatt: MockBleRemoteGATTServer = {
      connected: true,
      connect: vi.fn(),
      disconnect: vi.fn(),
      getPrimaryService: vi.fn((serviceId: string) => {
        if (serviceId === 'heart_rate') return Promise.resolve(heartRateService);
        return Promise.reject(new Error('Service not found'));
      }),
    };
    mockGatt.connect = vi.fn().mockResolvedValue(mockGatt);

    const mockDevice: MockBleDevice = new EventTarget() as MockBleDevice;
    mockDevice.name = 'Test Device';
    mockDevice.gatt = mockGatt;

    mockBluetooth.requestDevice.mockResolvedValue(mockDevice);

    render(<SmartwatchBridge sessionId="test-session" apiBaseUrl="http://localhost:8001" />);
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      expect(screen.getByText(/Paired:/i)).toBeInTheDocument();
    });

    // Simulate unstable readings (range > 4 bpm) using the same characteristic instance
    const unstableReadings = [60, 65, 70, 75, 80];
    
    for (const bpm of unstableReadings) {
      mockHrChar.value = createHeartRateDataView(bpm);
      const event = new Event('characteristicvaluechanged');
      Object.defineProperty(event, 'currentTarget', { value: mockHrChar });
      mockHrChar.dispatchEvent(event);
    }

    // Wait a bit to ensure no sync happens
    await new Promise(resolve => setTimeout(resolve, 100));

    expect(mockFetch).not.toHaveBeenCalled();
    expect(screen.getByText(/Waiting for a stable reading/i)).toBeInTheDocument();
  });

  it('should trigger red flag callback when vitals sync detects emergency', async () => {
    const onRedFlag = vi.fn();
    
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        session_id: 'test',
        trigger_red_flag: true,
        red_flag_reason: 'Critically high heart rate detected',
        nadi_trait_estimate: null,
        hrv_sdnn_ms: null,
        patient_record: {},
      }),
    });

    // Create the characteristic that will be returned by the service
    const mockHrChar = createMockCharacteristic();
    
    const heartRateService: MockBleService = {
      getCharacteristic: vi.fn().mockResolvedValue(mockHrChar),
    };

    const mockGatt: MockBleRemoteGATTServer = {
      connected: true,
      connect: vi.fn(),
      disconnect: vi.fn(),
      getPrimaryService: vi.fn((serviceId: string) => {
        if (serviceId === 'heart_rate') return Promise.resolve(heartRateService);
        return Promise.reject(new Error('Service not found'));
      }),
    };
    mockGatt.connect = vi.fn().mockResolvedValue(mockGatt);

    const mockDevice: MockBleDevice = new EventTarget() as MockBleDevice;
    mockDevice.name = 'Test Device';
    mockDevice.gatt = mockGatt;

    mockBluetooth.requestDevice.mockResolvedValue(mockDevice);

    render(
      <SmartwatchBridge 
        sessionId="test-session" 
        apiBaseUrl="http://localhost:8001"
        onRedFlag={onRedFlag}
      />
    );
    
    const pairButton = screen.getByRole('button', { name: /Tap to Pair/i });
    fireEvent.click(pairButton);

    await waitFor(() => {
      expect(screen.getByText(/Paired:/i)).toBeInTheDocument();
    });

    // Simulate stable readings that will trigger sync using the same characteristic instance
    const stableReadings = [160, 161, 162, 161, 160];
    
    for (const bpm of stableReadings) {
      mockHrChar.value = createHeartRateDataView(bpm);
      const event = new Event('characteristicvaluechanged');
      Object.defineProperty(event, 'currentTarget', { value: mockHrChar });
      mockHrChar.dispatchEvent(event);
    }

    await waitFor(() => {
      expect(onRedFlag).toHaveBeenCalledWith('Critically high heart rate detected');
    }, { timeout: 3000 });
  });
});
