import os

modal_content = '''"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Usb,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  X,
  Radio,
  Eye,
  EyeOff,
  Sparkles,
  Wifi,
  WifiOff,
  ArrowRight,
  Activity,
  Check,
  Loader2,
  Server,
  ShieldCheck,
  Laptop,
} from "lucide-react";

export interface ScannedNetwork {
  ssid: string;
  rssi: number;
  secure: boolean;
}

export interface RegisteredRoom {
  id: string;
  roomLabel: string;
}

interface WebSerialProvisionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  availableRooms?: RegisteredRoom[];
}

interface WifiLiveStatus {
  phase: "SAVING_NVS" | "ASSOCIATING" | "DHCP" | "VERIFYING" | "CONNECTED" | "FAILED";
  attempt: number;
  maxAttempts: number;
  progress: number;
  elapsedSeconds: number;
  message: string;
  ip?: string;
  rssi?: number;
}

export function WebSerialProvisionModal({
  isOpen,
  onClose,
  onSuccess,
  availableRooms = [],
}: WebSerialProvisionModalProps) {
  const [isSupported, setIsSupported] = useState(true);
  const [logs, setLogs] = useState<string[]>([]);

  const [step, setStep] = useState<
    "READY" | "SCANNING" | "CONFIG" | "SAVING" | "CONNECTING_WIFI" | "SUCCESS" | "ERROR"
  >("READY");
  const [wifiDetails, setWifiDetails] = useState<{
    ip?: string;
    room?: string;
    server?: string;
    error?: string;
    rssi?: number;
  }>({});
  const [statusMessage, setStatusMessage] = useState("");
  const [networks, setNetworks] = useState<ScannedNetwork[]>([]);
  const [selectedSsid, setSelectedSsid] = useState("");
  const [customSsid, setCustomSsid] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [room, setRoom] = useState("");
  const [serverHost, setServerHost] = useState("");
  const [registeredRooms, setRegisteredRooms] = useState<RegisteredRoom[]>(availableRooms);

  // Live Wi-Fi association state
  const [liveStatus, setLiveStatus] = useState<WifiLiveStatus>({
    phase: "ASSOCIATING",
    attempt: 0,
    maxAttempts: 30,
    progress: 5,
    elapsedSeconds: 0,
    message: "Initializing Wi-Fi hardware...",
  });

  const portRef = useRef<any>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const writerRef = useRef<WritableStreamDefaultWriter<Uint8Array> | null>(null);
  const isPortOpenRef = useRef(false);
  const isConnectingWifiRef = useRef(false);

  // Suggest local LAN IP or current hostname
  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsSupported("serial" in navigator);
      const host = window.location.hostname;
      if (host === "localhost" || host === "127.0.0.1") {
        setServerHost("192.168.100.128");
      } else {
        setServerHost(host);
      }
    }
  }, []);

  // Sync available rooms passed from parent or fetch dynamically
  useEffect(() => {
    if (!isOpen) return;

    if (availableRooms && availableRooms.length > 0) {
      setRegisteredRooms(availableRooms);
      setRoom((prev) =>
        prev && availableRooms.some((r) => r.roomLabel === prev) ? prev : availableRooms[0].roomLabel
      );
    } else {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL || "";
      if (!base) return;
      fetch(`${base}/devices`)
        .then((r) => r.json())
        .then((data: any) => {
          const list = Array.isArray(data) ? data : data?.value || [];
          if (Array.isArray(list) && list.length > 0) {
            setRegisteredRooms(list);
            setRoom((prev) =>
              prev && list.some((r: any) => r.roomLabel === prev) ? prev : list[0].roomLabel
            );
          }
        })
        .catch(() => {});
    }
  }, [isOpen, availableRooms]);

  const addLog = useCallback((msg: string) => {
    setLogs((prev) => [...prev.slice(-60), `[${new Date().toLocaleTimeString()}] ${msg}`]);
  }, []);

  // Safe stream release without throwing errors on pending reads
  const releaseStreams = useCallback(async () => {
    if (readerRef.current) {
      try {
        await readerRef.current.cancel();
      } catch {}
      try {
        readerRef.current.releaseLock();
      } catch {}
      readerRef.current = null;
    }
    if (writerRef.current) {
      try {
        await writerRef.current.close();
      } catch {}
      try {
        writerRef.current.releaseLock();
      } catch {}
      writerRef.current = null;
    }
  }, []);

  // Safe port teardown
  const closePort = useCallback(async () => {
    await releaseStreams();
    if (portRef.current) {
      try {
        if (isPortOpenRef.current) {
          await portRef.current.close();
          addLog("Serial port closed cleanly.");
        }
      } catch (err: any) {
        addLog(`Port close info: ${err.message}`);
      }
    }
    portRef.current = null;
    isPortOpenRef.current = false;
  }, [releaseStreams, addLog]);

  // Ask backend to release COM port before browser claims it
  const releaseBackendSerial = useCallback(async () => {
    const base = process.env.NEXT_PUBLIC_API_BASE_URL || "";
    if (!base) return;
    try {
      await fetch(`${base}/devices/usb/release`, { method: "POST" });
      addLog("Backend USB serial paused — browser can now claim the port.");
    } catch {
      addLog("Could not contact backend to release USB port (non-fatal).");
    }
  }, [addLog]);

  // Tell backend to resume COM port scanning after we're done
  const resumeBackendSerial = useCallback(async () => {
    const base = process.env.NEXT_PUBLIC_API_BASE_URL || "";
    if (!base) return;
    try {
      await fetch(`${base}/devices/usb/resume`, { method: "POST" });
    } catch {}
  }, []);

  const handleClose = useCallback(async () => {
    isConnectingWifiRef.current = false;
    await closePort();
    await resumeBackendSerial();
    setStep("READY");
    setNetworks([]);
    setLogs([]);
    onClose();
  }, [closePort, resumeBackendSerial, onClose]);

  // Completely resets serial handles so the user can pick the port again if needed
  const resetPortState = useCallback(async () => {
    isConnectingWifiRef.current = false;
    await closePort();
    portRef.current = null;
    isPortOpenRef.current = false;
    setStep("READY");
    setLogs([]);
  }, [closePort]);

  // Robust port acquisition handling Windows USB-CDC disconnects & already-open errors
  const acquirePort = useCallback(
    async (baud = 115200): Promise<boolean> => {
      try {
        await releaseStreams();

        let port = portRef.current;
        if (!port) {
          addLog("Prompting user to choose COM port...");
          port = await (navigator as any).serial.requestPort();
          portRef.current = port;
        }

        const isOpen = Boolean(port.readable || port.writable);
        if (!isOpen) {
          try {
            await port.open({ baudRate: baud });
            addLog(`Connected to ESP32 at ${baud.toLocaleString()} baud.`);
          } catch (openErr: any) {
            if (openErr.message && openErr.message.includes("already open")) {
              addLog("Port is already open — continuing with active session.");
            } else {
              throw openErr;
            }
          }
        } else {
          addLog("Reusing open serial port connection.");
        }

        isPortOpenRef.current = true;

        if (port.writable && !writerRef.current) {
          writerRef.current = port.writable.getWriter();
        }

        if (port.readable && !readerRef.current) {
          readerRef.current = port.readable.getReader();
        }

        return true;
      } catch (err: any) {
        addLog(`Port connection error: ${err.message}`);
        portRef.current = null;
        isPortOpenRef.current = false;
        return false;
      }
    },
    [releaseStreams, addLog]
  );

  const writeLine = useCallback(async (text: string) => {
    if (writerRef.current) {
      await writerRef.current.write(new TextEncoder().encode(text + "\\n"));
    }
  }, []);

  // Multi-line stream reader that filters intermediate status lines and waits for wifi_scan
  const readWifiScanResult = useCallback(
    (timeoutMs = 12000): Promise<ScannedNetwork[] | null> => {
      return new Promise((resolve) => {
        let buf = "";
        let timedOut = false;
        const timer = setTimeout(() => {
          timedOut = true;
          resolve(null);
        }, timeoutMs);
        const dec = new TextDecoder();

        (async () => {
          if (!readerRef.current) {
            clearTimeout(timer);
            resolve(null);
            return;
          }
          try {
            while (!timedOut) {
              const { value, done } = await readerRef.current.read();
              if (done) break;
              if (value) {
                buf += dec.decode(value, { stream: true });
                const lines = buf.split("\\n");
                buf = lines.pop() || "";
                for (const rawLine of lines) {
                  const ln = rawLine.trim();
                  if (!ln) continue;
                  addLog(`← ESP32: ${ln.length > 80 ? ln.substring(0, 80) + "..." : ln}`);
                  if (ln.startsWith("{") && ln.endsWith("}")) {
                    try {
                      const parsed = JSON.parse(ln);
                      if (parsed.type === "wifi_scan" && Array.isArray(parsed.networks)) {
                        clearTimeout(timer);
                        resolve(parsed.networks);
                        return;
                      }
                    } catch {}
                  }
                }
              }
            }
          } catch (err: any) {
            addLog(`Read error: ${err.message}`);
          }
          clearTimeout(timer);
          resolve(null);
        })();
      });
    },
    [addLog]
  );

  const startScan = useCallback(async () => {
    setStep("SCANNING");
    setNetworks([]);
    setStatusMessage("Connecting to serial port...");

    await closePort();
    await releaseBackendSerial();
    await new Promise((r) => setTimeout(r, 800));

    const ok = await acquirePort(115200);
    if (!ok) {
      setStatusMessage("Could not open serial port. Ensure USB cable is plugged in.");
      setStep("ERROR");
      await resumeBackendSerial();
      return;
    }

    try {
      setStatusMessage("Instructing ESP32 to scan 2.4 GHz airwaves...");
      addLog("Sending command: SCAN_WIFI");
      await writeLine("SCAN_WIFI");

      addLog("Awaiting real-time Wi-Fi network list from ESP32...");
      const scanList = await readWifiScanResult(12000);

      if (scanList && scanList.length > 0) {
        addLog(`Discovered ${scanList.length} actual Wi-Fi network(s).`);
        setNetworks(scanList);
        setSelectedSsid(scanList[0]?.ssid ?? "");
      } else {
        addLog("Scan complete or manual entry needed. Enter your SSID below.");
        setSelectedSsid("__custom__");
        setStatusMessage("Enter your Wi-Fi SSID manually below.");
      }
      setStep("CONFIG");
    } catch (err: any) {
      addLog(`Scan error: ${err.message}`);
      setStatusMessage(err.message);
      setStep("ERROR");
      await resumeBackendSerial();
    }
  }, [closePort, releaseBackendSerial, resumeBackendSerial, acquirePort, writeLine, readWifiScanResult, addLog]);

  // Saves credentials to NVS and actively streams live Wi-Fi status until connected
  const handleSaveConfig = useCallback(async () => {
    const ssid = selectedSsid === "__custom__" ? customSsid.trim() : selectedSsid.trim();
    if (!ssid) {
      alert("Please enter a Wi-Fi SSID.");
      return;
    }

    if (!portRef.current || !isPortOpenRef.current) {
      setStatusMessage("Serial port disconnected. Please reconnect.");
      setStep("ERROR");
      return;
    }

    setStep("CONNECTING_WIFI");
    isConnectingWifiRef.current = true;
    setLiveStatus({
      phase: "SAVING_NVS",
      attempt: 0,
      maxAttempts: 30,
      progress: 5,
      elapsedSeconds: 0,
      message: "Writing credentials to ESP32 permanent NVS memory...",
    });

    try {
      const payload = {
        cmd: "CONFIGURE",
        ssid,
        pass: password,
        room: room || "Living Room",
        server: serverHost,
      };

      addLog(`Flashing configuration to NVS: SSID="${ssid}", Room="${payload.room}", Server="${serverHost}"`);
      await writeLine(JSON.stringify(payload));

      const startTime = Date.now();
      let connectedConfirmed = false;

      // Watchdog ticker & backend online check interval
      const timerInterval = setInterval(async () => {
        if (!isConnectingWifiRef.current || connectedConfirmed) {
          clearInterval(timerInterval);
          return;
        }

        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        setLiveStatus((prev) => ({
          ...prev,
          elapsedSeconds: elapsed,
        }));

        // After 4s, also check if backend auto-discovered the node online
        if (elapsed >= 4) {
          const base = process.env.NEXT_PUBLIC_API_BASE_URL || "";
          if (base) {
            try {
              const res = await fetch(`${base}/devices`);
              const data = await res.json();
              const list = Array.isArray(data) ? data : data?.value || [];
              const onlineNode = list.find((n: any) => n.status === "online");
              if (onlineNode && isConnectingWifiRef.current) {
                connectedConfirmed = true;
                clearInterval(timerInterval);
                const assignedIp = onlineNode.endpoint && onlineNode.endpoint !== "None" ? onlineNode.endpoint : "Connected";
                setLiveStatus((prev) => ({
                  ...prev,
                  phase: "CONNECTED",
                  progress: 100,
                  ip: assignedIp,
                  message: `Verified online via backend (${assignedIp})!`,
                }));
                setWifiDetails({
                  ip: assignedIp,
                  room: onlineNode.roomLabel || room,
                  server: serverHost,
                });
                addLog(`Backend confirmed node online: ${assignedIp}`);
                setTimeout(async () => {
                  await closePort();
                  await resumeBackendSerial();
                  setStep("SUCCESS");
                  onSuccess?.();
                }, 1400);
              }
            } catch {}
          }
        }

        // Timeout check (35s)
        if (elapsed > 35 && !connectedConfirmed) {
          clearInterval(timerInterval);
          isConnectingWifiRef.current = false;
          setStatusMessage("Wi-Fi association timed out after 35s. Please verify your SSID password and signal strength.");
          await closePort();
          await resumeBackendSerial();
          setStep("ERROR");
        }
      }, 1000);

      // Actively read live JSON status stream directly from ESP32 serial port
      let buf = "";
      const dec = new TextDecoder();

      while (isConnectingWifiRef.current && !connectedConfirmed && readerRef.current) {
        const { value, done } = await readerRef.current.read();
        if (done) break;
        if (value) {
          buf += dec.decode(value, { stream: true });
          const lines = buf.split("\\n");
          buf = lines.pop() || "";

          for (const rawLine of lines) {
            const ln = rawLine.trim();
            if (!ln) continue;
            addLog(`← ESP32: ${ln.length > 90 ? ln.substring(0, 90) + "..." : ln}`);

            if (ln.startsWith("{") && ln.endsWith("}")) {
              try {
                const parsed = JSON.parse(ln);

                // Handle configuration ACK
                if (parsed.type === "configured" && parsed.status === "ok") {
                  setLiveStatus((prev) => ({
                    ...prev,
                    phase: "ASSOCIATING",
                    progress: 10,
                    message: `Credentials saved to NVS. Associating with "${ssid}"...`,
                  }));
                }

                // Handle live Wi-Fi Status updates
                if (parsed.type === "wifi_status") {
                  if (parsed.status === "connecting") {
                    const maxA = parsed.max_attempts || 30;
                    const att = parsed.attempt || 1;
                    const prog = parsed.progress || Math.round((att / maxA) * 90);
                    setLiveStatus((prev) => ({
                      ...prev,
                      phase: att > 12 ? "DHCP" : "ASSOCIATING",
                      attempt: att,
                      maxAttempts: maxA,
                      progress: prog,
                      message: parsed.msg || `Attempt ${att}/${maxA}: Associating with ${ssid}...`,
                    }));
                  } else if (parsed.status === "connected") {
                    connectedConfirmed = true;
                    clearInterval(timerInterval);
                    isConnectingWifiRef.current = false;

                    setLiveStatus((prev) => ({
                      ...prev,
                      phase: "CONNECTED",
                      progress: 100,
                      ip: parsed.ip,
                      rssi: parsed.rssi,
                      message: `Successfully connected! Assigned IP: ${parsed.ip}`,
                    }));

                    setWifiDetails({
                      ip: parsed.ip,
                      room: parsed.room || room,
                      server: parsed.server || serverHost,
                      rssi: parsed.rssi,
                    });

                    addLog(`Wi-Fi Connected! IP: ${parsed.ip}, RSSI: ${parsed.rssi} dBm`);

                    // Brief delay so the user sees the 100% progress checkmark before transition
                    setTimeout(async () => {
                      await closePort();
                      await resumeBackendSerial();
                      setStep("SUCCESS");
                      onSuccess?.();
                    }, 1400);
                    return;
                  } else if (parsed.status === "failed") {
                    connectedConfirmed = true;
                    clearInterval(timerInterval);
                    isConnectingWifiRef.current = false;

                    setLiveStatus((prev) => ({
                      ...prev,
                      phase: "FAILED",
                      message: parsed.reason || "Connection failed.",
                    }));

                    setStatusMessage(
                      parsed.reason ||
                        "Wi-Fi connection timed out. Check SSID password or move the module closer to the router."
                    );
                    await closePort();
                    await resumeBackendSerial();
                    setStep("ERROR");
                    return;
                  }
                }
              } catch {}
            }
          }
        }
      }
    } catch (err: any) {
      addLog(`Save error: ${err.message}`);
      setStatusMessage("Failed to save credentials: " + err.message);
      setStep("ERROR");
      await closePort();
      await resumeBackendSerial();
    }
  }, [selectedSsid, customSsid, password, room, serverHost, writeLine, closePort, resumeBackendSerial, addLog, onSuccess]);

  const bars = (rssi: number) =>
    rssi >= -50 ? "▂▄▆█" : rssi >= -65 ? "▂▄▆░" : rssi >= -75 ? "▂▄░░" : "▂░░░";

  if (!isOpen) return null;

  const inputCls =
    "w-full bg-[#120a0c] border border-rose-950/80 rounded-xl px-3 py-2.5 text-xs text-white focus:outline-none focus:border-rose-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/75 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg bg-[#1a0f12] border border-rose-950/60 rounded-3xl shadow-2xl overflow-hidden text-slate-100 flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="p-5 border-b border-rose-950/40 flex items-center justify-between bg-gradient-to-r from-[#2a1318] to-[#1a0f12] flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
              <Usb className="w-5 h-5" />
            </div>
            <div>
              <span className="text-[10px] font-black uppercase tracking-widest text-rose-400 block">
                Web Serial API · Zero-IDE Setup
              </span>
              <h2 className="text-lg font-black text-white leading-tight">Provision Radar Controller</h2>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="w-8 h-8 rounded-full bg-white/5 hover:bg-white/10 flex items-center justify-center text-slate-400 hover:text-white transition-all cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1">
          {!isSupported ? (
            <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/20 space-y-3">
              <div className="flex items-center gap-2 text-amber-400 font-bold text-sm">
                <AlertTriangle className="w-4 h-4" /> Web Serial API not supported in this browser
              </div>
              <p className="text-xs text-slate-300 leading-relaxed">
                Please use <strong>Google Chrome</strong> or <strong>Microsoft Edge</strong> to provision the controller directly via USB.
              </p>
              <div className="p-3 bg-black/30 rounded-xl text-xs">
                <span className="font-bold text-amber-300 block mb-1">Wireless Hotspot Alternative</span>
                <span className="text-slate-400">
                  Power on the ESP32, connect your phone or laptop to the Wi-Fi hotspot <strong>OmniSense-Radar-Setup</strong>, and open <strong>http://192.168.4.1</strong> in your browser.
                </span>
              </div>
            </div>
          ) : (
            <>
              {step === "READY" && (
                <div className="space-y-4">
                  <div className="p-4 rounded-2xl bg-rose-500/5 border border-rose-500/20 space-y-2">
                    <span className="text-xs font-black text-rose-300 flex items-center gap-2">
                      <Sparkles className="w-3.5 h-3.5" />
                      Zero-IDE Wi-Fi Provisioning
                    </span>
                    <ol className="text-xs text-slate-300 space-y-2 list-decimal list-inside leading-relaxed">
                      <li>Plug the ESP32-S3 radar module into your computer using a USB-C data cable.</li>
                      <li>Flash the firmware binary below (or proceed to Step 2 if already installed).</li>
                      <li>The controller will scan for live 2.4 GHz Wi-Fi networks in your room.</li>
                      <li>Select your network, enter the password, and flash credentials directly into permanent memory.</li>
                    </ol>
                  </div>

                  {/* Step 1: Flash Firmware Binary via ESP Web Tools */}
                  <div className="p-4 rounded-2xl bg-gradient-to-br from-rose-950/30 to-purple-950/20 border border-rose-500/30 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-black text-rose-300 flex items-center gap-1.5">
                        <Sparkles className="w-3.5 h-3.5 text-rose-400" />
                        Step 1: Flash Firmware Binary (Zero-IDE)
                      </span>
                      <span className="text-[10px] bg-rose-500/20 text-rose-300 font-bold px-2 py-0.5 rounded-full border border-rose-500/30">
                        ESP32-S3 Binary
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-300 leading-relaxed">
                      Flashes the complete compiled binary (Bootloader + Partitions + App) directly to your ESP32-S3 from this browser using ESP Web Tools.
                    </p>
                    <div className="flex justify-center pt-1 pb-1">
                      {React.createElement(
                        "esp-web-install-button",
                        { manifest: "/firmware/manifest.json" },
                        <button
                          slot="activate"
                          className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-rose-600 to-rose-700 hover:from-rose-500 hover:to-rose-600 text-white font-black py-3 px-6 rounded-2xl text-xs shadow-lg shadow-rose-950/50 transition-all cursor-pointer"
                        >
                          <Usb className="w-4 h-4" /> Install / Flash OmniSense Firmware
                        </button>,
                        <span slot="unsupported" className="text-xs text-amber-400 font-semibold">
                          Web Serial not supported in this browser. Please use Chrome or Edge.
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Step 2: Configure Wi-Fi Credentials over Serial */}
                  <div className="p-4 rounded-2xl bg-white/5 border border-white/10 space-y-2">
                    <span className="text-xs font-black text-slate-200 block">
                      Step 2: Enter Wi-Fi Credentials & Provision
                    </span>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Connects to your flashed ESP32 to query local Wi-Fi networks and save your SSID, password, room, and server host.
                    </p>
                    <button
                      onClick={startScan}
                      className="w-full flex items-center justify-center gap-2 bg-white/10 hover:bg-white/15 text-white font-bold py-2.5 px-4 rounded-xl text-xs transition-all cursor-pointer"
                    >
                      <Wifi className="w-3.5 h-3.5" /> Enter Wi-Fi & Setup Node
                    </button>
                  </div>
                </div>
              )}

              {step === "SCANNING" && (
                <div className="text-center py-10 space-y-4">
                  <div className="relative w-16 h-16 mx-auto flex items-center justify-center">
                    <div className="absolute inset-0 rounded-full border-2 border-rose-500/20 border-t-rose-500 animate-spin" />
                    <Radio className="w-7 h-7 text-rose-400 animate-pulse" />
                  </div>
                  <div>
                    <h3 className="text-sm font-black text-white">Scanning 2.4 GHz Airwaves</h3>
                    <p className="text-xs text-slate-400 mt-1">{statusMessage}</p>
                  </div>
                </div>
              )}

              {step === "CONFIG" && (
                <div className="space-y-4 animate-in fade-in duration-200">
                  {networks.length === 0 ? (
                    <div className="p-3 rounded-xl bg-orange-500/10 border border-orange-500/20 text-xs text-orange-300 leading-relaxed">
                      {statusMessage}
                    </div>
                  ) : (
                    <div className="flex items-center justify-between pb-2 border-b border-rose-950/40">
                      <span className="text-xs font-black text-emerald-400 flex items-center gap-1.5">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        {networks.length} Wi-Fi network{networks.length !== 1 ? "s" : ""} discovered
                      </span>
                      <button
                        onClick={startScan}
                        className="text-[10px] text-rose-400 hover:text-rose-300 flex items-center gap-1 cursor-pointer"
                      >
                        <RefreshCw className="w-3 h-3" /> Rescan
                      </button>
                    </div>
                  )}

                  {/* Network SSID */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-bold text-slate-300 block">2.4 GHz Wi-Fi Network</label>
                    {networks.length > 0 ? (
                      <select
                        value={selectedSsid}
                        onChange={(e) => setSelectedSsid(e.target.value)}
                        className={inputCls}
                      >
                        {[...networks]
                          .sort((a, b) => b.rssi - a.rssi)
                          .map((n, i) => (
                            <option key={i} value={n.ssid}>
                              {bars(n.rssi)} {n.ssid} ({n.rssi} dBm) {n.secure ? "🔒" : "🔓"}
                            </option>
                          ))}
                        <option value="__custom__">+ Enter Network SSID Manually</option>
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={customSsid}
                        onChange={(e) => setCustomSsid(e.target.value)}
                        placeholder="Enter Wi-Fi SSID"
                        className={inputCls}
                      />
                    )}
                  </div>

                  {selectedSsid === "__custom__" && networks.length > 0 && (
                    <div className="space-y-1.5">
                      <label className="text-xs font-bold text-slate-300 block">Wi-Fi SSID</label>
                      <input
                        type="text"
                        value={customSsid}
                        onChange={(e) => setCustomSsid(e.target.value)}
                        placeholder="Enter Wi-Fi SSID"
                        className={inputCls}
                      />
                    </div>
                  )}

                  {/* Password */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-bold text-slate-300 block">Wi-Fi Password</label>
                    <div className="relative">
                      <input
                        type={showPassword ? "text" : "password"}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="Network password"
                        className={`${inputCls} pr-10`}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                      >
                        {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {/* Room Assignment */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-bold text-slate-300 block">Room Assignment</label>
                    <select value={room} onChange={(e) => setRoom(e.target.value)} className={inputCls}>
                      {registeredRooms.length > 0 ? (
                        registeredRooms.map((n) => (
                          <option key={n.id} value={n.roomLabel}>
                            {n.roomLabel} ({n.id})
                          </option>
                        ))
                      ) : (
                        <option value="Living Room">Living Room</option>
                      )}
                    </select>
                  </div>

                  {/* MQTT / Cloud Host */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between items-center">
                      <label className="text-xs font-bold text-slate-300 block">MQTT / Server Host</label>
                      <span className="text-[10px] text-rose-300 font-mono">LAN IP or Cloud Domain</span>
                    </div>
                    <input
                      type="text"
                      value={serverHost}
                      onChange={(e) => setServerHost(e.target.value)}
                      placeholder="e.g. 192.168.100.128 or api.omnisense-care.com"
                      className={`${inputCls} font-mono`}
                    />
                    <p className="text-[10px] text-slate-400">
                      Use your computer's LAN IP (<code>192.168.100.128</code>) for local testing, or your server's domain in production.
                    </p>
                  </div>

                  {/* Action Buttons */}
                  <div className="pt-2 flex gap-3">
                    <button
                      onClick={handleClose}
                      className="flex-1 bg-white/5 hover:bg-white/10 text-slate-300 font-bold py-3 rounded-2xl text-xs cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSaveConfig}
                      className="flex-[2] bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-black py-3 px-4 rounded-2xl text-xs shadow-lg transition-all active:scale-[0.98] cursor-pointer flex items-center justify-center gap-2"
                    >
                      <Sparkles className="w-4 h-4" />
                      Flash Credentials to ESP32
                    </button>
                  </div>
                </div>
              )}

              {/* LIVE WI-FI ASSOCIATION DISPLAY */}
              {step === "CONNECTING_WIFI" && (
                <div className="py-4 space-y-5 animate-in fade-in duration-200">
                  {/* Central Radar Wi-Fi Pulse Graphic */}
                  <div className="relative w-20 h-20 mx-auto flex items-center justify-center">
                    <div className="absolute inset-0 rounded-full border-2 border-emerald-500/20 border-t-emerald-400 animate-spin" />
                    <div className="absolute inset-2 rounded-full border border-teal-500/30 animate-ping opacity-30" />
                    <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-inner">
                      <Wifi className="w-6 h-6 animate-pulse" />
                    </div>
                  </div>

                  {/* Header text */}
                  <div className="text-center space-y-1">
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-widest bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                      Live Hardware Association
                    </span>
                    <h3 className="text-base font-black text-white">
                      Connecting to {selectedSsid === "__custom__" ? customSsid : selectedSsid}
                    </h3>
                    <p className="text-xs text-emerald-300 font-medium">
                      {liveStatus.message}
                    </p>
                  </div>

                  {/* Dynamic Progress Bar */}
                  <div className="space-y-1.5 px-2">
                    <div className="flex justify-between items-center text-[11px]">
                      <span className="text-slate-400 font-medium flex items-center gap-1.5">
                        <Activity className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
                        {liveStatus.attempt > 0
                          ? `Attempt ${liveStatus.attempt} of ${liveStatus.maxAttempts}`
                          : "Initializing..."}
                      </span>
                      <span className="font-mono font-bold text-emerald-300">
                        {liveStatus.elapsedSeconds}s elapsed · {liveStatus.progress}%
                      </span>
                    </div>
                    <div className="w-full h-2.5 bg-black/60 rounded-full overflow-hidden border border-emerald-950/80 p-0.5">
                      <div
                        className="h-full bg-gradient-to-r from-emerald-500 via-teal-400 to-emerald-300 rounded-full transition-all duration-300 ease-out"
                        style={{ width: `${Math.min(100, Math.max(5, liveStatus.progress))}%` }}
                      />
                    </div>
                  </div>

                  {/* Live Association Checkpoints */}
                  <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                    <div
                      className={`p-2 rounded-xl border transition-colors ${
                        liveStatus.phase === "SAVING_NVS"
                          ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                          : "bg-black/30 border-white/5 text-slate-400"
                      }`}
                    >
                      <span className="font-bold block">1. NVS Flash</span>
                      <span className="text-[9px] opacity-75">Saved ✓</span>
                    </div>
                    <div
                      className={`p-2 rounded-xl border transition-colors ${
                        liveStatus.phase === "ASSOCIATING"
                          ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300 font-bold"
                          : liveStatus.phase === "DHCP" || liveStatus.phase === "CONNECTED"
                          ? "bg-black/30 border-white/5 text-emerald-400"
                          : "bg-black/30 border-white/5 text-slate-400"
                      }`}
                    >
                      <span className="font-bold block">2. Association</span>
                      <span className="text-[9px] opacity-75">
                        {liveStatus.phase === "CONNECTED" ? "Verified ✓" : "In Progress..."}
                      </span>
                    </div>
                    <div
                      className={`p-2 rounded-xl border transition-colors ${
                        liveStatus.phase === "CONNECTED"
                          ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-300 font-black"
                          : "bg-black/30 border-white/5 text-slate-500"
                      }`}
                    >
                      <span className="font-bold block">3. DHCP & Telemetry</span>
                      <span className="text-[9px] opacity-75">
                        {liveStatus.phase === "CONNECTED" ? liveStatus.ip || "Online" : "Waiting..."}
                      </span>
                    </div>
                  </div>

                  {/* Target Profile Card */}
                  <div className="p-3.5 rounded-2xl bg-black/50 border border-white/10 text-left text-xs space-y-2">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400">Target SSID:</span>
                      <span className="font-bold text-white font-mono">
                        {selectedSsid === "__custom__" ? customSsid : selectedSsid}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400">Assigned Room:</span>
                      <span className="font-bold text-rose-300">{room}</span>
                    </div>
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400">Target MQTT Broker:</span>
                      <span className="font-bold text-white font-mono">{serverHost}:1883</span>
                    </div>
                  </div>

                  <div className="pt-1">
                    <button
                      onClick={handleClose}
                      className="w-full bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white font-bold py-2 rounded-xl text-xs transition-colors cursor-pointer"
                    >
                      Cancel Association
                    </button>
                  </div>
                </div>
              )}

              {step === "SUCCESS" && (
                <div className="text-center py-6 space-y-4 animate-in fade-in duration-200">
                  <div
                    className={`w-14 h-14 mx-auto rounded-full flex items-center justify-center ${
                      wifiDetails.error
                        ? "bg-amber-500/20 border border-amber-500/40 text-amber-400"
                        : "bg-emerald-500/20 border border-emerald-500/40 text-emerald-400"
                    }`}
                  >
                    {wifiDetails.error ? <WifiOff className="w-8 h-8" /> : <CheckCircle2 className="w-8 h-8" />}
                  </div>

                  <div>
                    <h3 className="text-base font-black text-white">
                      {wifiDetails.error ? "Credentials Saved — Checking Connection" : "Wi-Fi Connected & Verified Online!"}
                    </h3>
                    <p className="text-xs text-slate-300 max-w-xs mx-auto mt-1 leading-relaxed">
                      {wifiDetails.error
                        ? wifiDetails.error
                        : "Your ESP32 radar node has associated with the Wi-Fi network and is streaming live telemetry."}
                    </p>
                  </div>

                  {!wifiDetails.error && (
                    <div className="p-4 rounded-2xl bg-emerald-950/30 border border-emerald-500/30 text-left text-xs space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-400">Live Device IP / Endpoint:</span>
                        <span className="font-bold font-mono text-emerald-300">
                          {wifiDetails.ip || "Connected (Active)"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-slate-400">Monitored Room:</span>
                        <span className="font-bold text-white">{wifiDetails.room || room}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-slate-400">MQTT Broker:</span>
                        <span className="font-bold font-mono text-white">
                          {wifiDetails.server || serverHost}:1883
                        </span>
                      </div>
                      {wifiDetails.rssi !== undefined && (
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Signal Strength (RSSI):</span>
                          <span className="font-bold text-emerald-300 font-mono">
                            {wifiDetails.rssi} dBm
                          </span>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="p-3.5 rounded-2xl bg-black/40 border border-rose-950/50 text-left text-xs space-y-1.5">
                    <span className="font-black text-rose-300 block">Next Steps for Deployment</span>
                    <ul className="text-slate-300 space-y-1 list-disc list-inside">
                      <li>
                        You can now unplug the USB cable and power the module via any 5V USB wall socket in{" "}
                        <strong>{room}</strong>.
                      </li>
                      <li>It will automatically reconnect to your Wi-Fi and stream radar targets continuously.</li>
                    </ul>
                  </div>

                  <button
                    onClick={handleClose}
                    className="w-full bg-[#6B1E2E] hover:bg-[#521725] text-white font-black py-3 rounded-2xl text-xs transition-all active:scale-[0.98] cursor-pointer"
                  >
                    Done &amp; View Live Devices
                  </button>
                </div>
              )}

              {step === "ERROR" && (
                <div className="text-center py-6 space-y-4">
                  <div className="w-12 h-12 mx-auto rounded-full bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-rose-400">
                    <AlertTriangle className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="text-sm font-black text-white">Connection Error</h3>
                    <p className="text-xs text-rose-300 mt-1 max-w-xs mx-auto">{statusMessage}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-black/40 border border-rose-950/50 text-xs text-slate-400 text-left space-y-1">
                    <span className="font-bold text-rose-300 block mb-1">Troubleshooting Checklist</span>
                    <p>• Verify your Wi-Fi password is correct.</p>
                    <p>• Ensure your router broadcasts a <strong>2.4 GHz</strong> network (ESP32-S3 cannot connect to 5 GHz only SSIDs).</p>
                    <p>• If signal RSSI is weaker than -85 dBm, move the module closer to your Wi-Fi access point.</p>
                  </div>
                  <div className="flex gap-3">
                    <button
                      onClick={handleClose}
                      className="flex-1 bg-white/5 hover:bg-white/10 text-slate-300 font-bold py-2.5 rounded-xl text-xs cursor-pointer"
                    >
                      Close
                    </button>
                    <button
                      onClick={() => setStep("CONFIG")}
                      className="flex-1 bg-rose-600 hover:bg-rose-700 text-white font-bold py-2.5 rounded-xl text-xs cursor-pointer"
                    >
                      Try Again
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {logs.length > 0 && (
            <div className="mt-3 pt-3 border-t border-white/5">
              <span className="text-[10px] font-black uppercase text-slate-500 block mb-1.5">
                Serial Communication Log
              </span>
              <div className="p-2.5 rounded-xl bg-black/70 font-mono text-[10px] text-slate-400 space-y-0.5 max-h-28 overflow-y-auto">
                {logs.map((log, i) => (
                  <div key={i} className="leading-tight">
                    {log}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
'''

target_path = r"d:\Projects\FYP\Omnisense-\apps\web\src\components\devices\WebSerialProvisionModal.tsx"
with open(target_path, "w", encoding="utf-8") as f:
    f.write(modal_content)

print("SUCCESS: WebSerialProvisionModal.tsx updated with React.createElement!")
