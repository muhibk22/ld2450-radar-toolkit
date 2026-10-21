import os

path = r"d:\Projects\FYP\Omnisense-\apps\backend\app\services\hardware_manager.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

target = """                # 1. Attempt discovery of ESP32 IP on local network
                discovered_ip = await self._discover_esp32_ip()
                target_ip = discovered_ip or settings.ESP32_HOST"""

replacement = """                # 1. Attempt discovery of ESP32 IP on local network
                discovered_ip = await self._discover_esp32_ip()
                last_ep = self.nodes.get("node_1").endpoint if "node_1" in self.nodes else None
                known_ip = last_ep.split(":")[0] if last_ep and last_ep not in ("None", "N/A") and "." in last_ep else None
                target_ip = discovered_ip or known_ip or settings.ESP32_HOST"""

if target in text:
    text = text.replace(target, replacement, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("SUCCESS: hardware_manager.py updated with known_ip fallback")
else:
    print("Target not found")
