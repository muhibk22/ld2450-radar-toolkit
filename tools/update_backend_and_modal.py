import os

# Update hardware_manager.py
hm_path = r"d:\Projects\FYP\Omnisense-\apps\backend\app\services\hardware_manager.py"
with open(hm_path, "r", encoding="utf-8") as f:
    hm_content = f.read()

# 1. Update _connect_tcp_radar with read timeout
old_tcp_radar = """            while self.running:
                data = await reader.read(1024)
                if not data:
                    print(f"[HardwareManager:WiFi] ESP32 at {host}:{port} disconnected.")
                    break
                await self._handle_raw_bytes(data, node_id=node_id)

            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False
        finally:
            if node:
                node.status = "offline\""""

new_tcp_radar = """            while self.running:
                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=8.0)
                except asyncio.TimeoutError:
                    print(f"[HardwareManager:WiFi] Timeout reading from {host}:{port}. Reconnecting...")
                    break
                if not data:
                    print(f"[HardwareManager:WiFi] ESP32 at {host}:{port} disconnected.")
                    break
                await self._handle_raw_bytes(data, node_id=node_id)

            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
            except Exception:
                pass
            return True
        except Exception:
            return False
        finally:
            if node:
                if time.time() - node.last_seen > 10.0:
                    node.status = "offline\""""

assert old_tcp_radar in hm_content, "old_tcp_radar block not found in hardware_manager.py"
hm_content = hm_content.replace(old_tcp_radar, new_tcp_radar)

# 2. Update _handle_raw_bytes so any received bytes immediately refresh node.status to online
old_handle_raw = """    async def _handle_raw_bytes(self, data: bytes, node_id: str):
        now = time.time()
        node = self.nodes.get(node_id)
        if node:
            node.bytes_received += len(data)
            node.last_seen = now"""

new_handle_raw = """    async def _handle_raw_bytes(self, data: bytes, node_id: str):
        now = time.time()
        node = self.nodes.get(node_id)
        if node:
            node.bytes_received += len(data)
            node.last_seen = now
            node.status = "online\""""

assert old_handle_raw in hm_content, "old_handle_raw block not found in hardware_manager.py"
hm_content = hm_content.replace(old_handle_raw, new_handle_raw)

# 3. Update health monitor threshold from 5.0 to 15.0 seconds
old_health = """    async def _run_health_monitor(self):
        \"\"\"Monitors node heartbeats; marks nodes offline if silent for > 5 seconds.\"\"\"
        while self.running:
            now = time.time()
            for node_id, node in self.nodes.items():
                if node.status == "online" and (now - node.last_seen > 5.0):
                    node.status = "offline"
                    node.fps = 0.0
            await asyncio.sleep(2.0)"""

new_health = """    async def _run_health_monitor(self):
        \"\"\"Monitors node heartbeats; marks nodes offline if silent for > 15 seconds.\"\"\"
        while self.running:
            now = time.time()
            for node_id, node in self.nodes.items():
                if node.status == "online" and (now - node.last_seen > 15.0):
                    node.status = "offline"
                    node.fps = 0.0
            await asyncio.sleep(2.0)"""

assert old_health in hm_content, "old_health block not found in hardware_manager.py"
hm_content = hm_content.replace(old_health, new_health)

# 4. Add connect_node_endpoint method
old_methods_anchor = """    def get_nodes_status(self) -> List[Dict[str, Any]]:"""

new_method = """    async def connect_node_endpoint(self, node_id: str, ip: str, port: int = 8888):
        \"\"\"Registers and immediately connects to an ESP32 node via TCP.\"\"\"
        node = self.nodes.get(node_id)
        if not node:
            node = NodeState(
                node_id=node_id,
                room_label="Living Room",
                connection_type="Wi-Fi TCP",
                status="online",
                endpoint=f"{ip}:{port}"
            )
            self.nodes[node_id] = node
        else:
            node.endpoint = f"{ip}:{port}"
            node.connection_type = "Wi-Fi TCP"
            node.status = "online"
            node.last_seen = time.time()
        print(f"[HardwareManager] Triggering direct TCP connection to {node_id} at {ip}:{port}...")
        asyncio.create_task(self._connect_tcp_radar(ip, port, node_id))

    def get_nodes_status(self) -> List[Dict[str, Any]]:"""

assert old_methods_anchor in hm_content, "old_methods_anchor block not found in hardware_manager.py"
hm_content = hm_content.replace(old_methods_anchor, new_method)

with open(hm_path, "w", encoding="utf-8") as f:
    f.write(hm_content)
print("Updated hardware_manager.py successfully.")

# 5. Update devices.py
dev_path = r"d:\Projects\FYP\Omnisense-\apps\backend\app\api\v1\devices.py"
with open(dev_path, "r", encoding="utf-8") as f:
    dev_content = f.read()

# Fix NameError on lines with "if hardware_manager and"
dev_content = dev_content.replace("if hardware_manager and", "if hm_module.hardware_manager and")

# Add ConnectNodeRequest and connect_device endpoint
old_scan_endpoint = """@router.post("/scan")
async def scan_hardware():"""

new_connect_endpoint = """class ConnectNodeRequest(BaseModel):
    ip: str
    port: int = 8888
    roomLabel: Optional[str] = None


@router.post("/{node_id}/connect")
async def connect_device(
    node_id: str,
    payload: ConnectNodeRequest,
    db: AsyncSession = Depends(get_db)
):
    \"\"\"
    Directly register and connect to an ESP32 radar node by its IP address.
    Called automatically by WebSerialProvisionModal upon successful Wi-Fi association.
    \"\"\"
    result = await db.execute(select(RadarNode).where(RadarNode.id == node_id))
    db_node = result.scalars().first()
    if not db_node:
        db_node = RadarNode(
            id=node_id,
            room_label=payload.roomLabel or "Living Room",
            patient_id="pat_1",
            status="online"
        )
        db.add(db_node)
    else:
        if payload.roomLabel:
            db_node.room_label = payload.roomLabel
        db_node.status = "online"
    await db.commit()

    import app.services.hardware_manager as hm_module
    if hm_module.hardware_manager:
        await hm_module.hardware_manager.connect_node_endpoint(node_id, payload.ip, payload.port)

    return {"status": "connected", "nodeId": node_id, "endpoint": f"{payload.ip}:{payload.port}"}


@router.post("/scan")
async def scan_hardware():"""

assert old_scan_endpoint in dev_content, "old_scan_endpoint not found in devices.py"
dev_content = dev_content.replace(old_scan_endpoint, new_connect_endpoint)

with open(dev_path, "w", encoding="utf-8") as f:
    f.write(dev_content)
print("Updated devices.py successfully.")

# 6. Update WebSerialProvisionModal.tsx
modal_path = r"d:\Projects\FYP\Omnisense-\apps\web\src\components\devices\WebSerialProvisionModal.tsx"
with open(modal_path, "r", encoding="utf-8") as f:
    modal_content = f.read()

old_success_block = """                    setWifiDetails({
                      ip: parsed.ip,
                      room: parsed.room || room,
                      server: parsed.server || serverHost,
                      rssi: parsed.rssi,
                    });

                    addLog(`Wi-Fi Connected! IP: ${parsed.ip}, RSSI: ${parsed.rssi} dBm`);"""

new_success_block = """                    setWifiDetails({
                      ip: parsed.ip,
                      room: parsed.room || room,
                      server: parsed.server || serverHost,
                      rssi: parsed.rssi,
                    });

                    addLog(`Wi-Fi Connected! IP: ${parsed.ip}, RSSI: ${parsed.rssi} dBm`);

                    // Immediately register and connect to ESP32 on backend
                    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "";
                    if (apiBase && parsed.ip) {
                      try {
                        await fetch(`${apiBase}/devices/node_1/connect`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            ip: parsed.ip,
                            port: 8888,
                            roomLabel: parsed.room || room || "Living Room",
                          }),
                        });
                        addLog(`Backend successfully linked to node at ${parsed.ip}:8888!`);
                      } catch (notifyErr: any) {
                        addLog(`Backend link info: ${notifyErr.message}`);
                      }
                    }"""

assert old_success_block in modal_content, "old_success_block not found in WebSerialProvisionModal.tsx"
modal_content = modal_content.replace(old_success_block, new_success_block)

with open(modal_path, "w", encoding="utf-8") as f:
    f.write(modal_content)
print("Updated WebSerialProvisionModal.tsx successfully.")
