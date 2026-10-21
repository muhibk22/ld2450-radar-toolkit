import os

modal_path = r"d:\Projects\FYP\Omnisense-\apps\web\src\components\devices\WebSerialProvisionModal.tsx"
with open(modal_path, "r", encoding="utf-8") as f:
    text = f.read()

# Resolve Conflict 1
c1_old = """<<<<<<< HEAD
                        { manifest: "/firmware/manifest.json" },
=======
                        { manifest: "/firmware/manifest.json" } as any,
>>>>>>> 06c131a7ab01a24b8263de9b18036c22c43f5f10"""

c1_new = """                        { manifest: "/firmware/manifest.json" } as any,"""

assert c1_old in text, "Conflict 1 not found"
text = text.replace(c1_old, c1_new)

# Resolve Conflict 2
c2_old = """<<<<<<< HEAD
                        className="text-[10px] text-rose-400 hover:text-rose-300 flex items-center gap-1 cursor-pointer"
                      >
                        <RefreshCw className="w-3 h-3" /> Rescan
=======
                        className="text-[11px] text-rose-400 hover:text-rose-300 flex items-center gap-1 font-bold cursor-pointer"
                      >
                        <RefreshCw className="w-3 h-3" /> Rescan Airwaves
>>>>>>> 06c131a7ab01a24b8263de9b18036c22c43f5f10"""

c2_new = """                        className="text-[11px] text-rose-400 hover:text-rose-300 flex items-center gap-1 font-bold cursor-pointer"
                      >
                        <RefreshCw className="w-3 h-3" /> Rescan Airwaves"""

assert c2_old in text, "Conflict 2 not found"
text = text.replace(c2_old, c2_new)

with open(modal_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully resolved merge conflicts in WebSerialProvisionModal.tsx!")
