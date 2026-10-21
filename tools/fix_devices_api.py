import os

path = r"d:\Projects\FYP\Omnisense-\apps\backend\app\api\v1\devices.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

target = """from app.services.hardware_manager import hardware_manager"""
replacement = """import app.services.hardware_manager as hm_module"""

target_check = """    if hardware_manager:
        for node in hardware_manager.get_nodes_status():"""
replacement_check = """    if hm_module.hardware_manager:
        for node in hm_module.hardware_manager.get_nodes_status():"""

target_scan = """    if hardware_manager:
        await hardware_manager.force_scan()"""
replacement_scan = """    if hm_module.hardware_manager:
        await hm_module.hardware_manager.force_scan()"""

target_pause = """    if hardware_manager:
        hardware_manager.pause_serial()"""
replacement_pause = """    if hm_module.hardware_manager:
        hm_module.hardware_manager.pause_serial()"""

target_resume = """    if hardware_manager:
        hardware_manager.resume_serial()"""
replacement_resume = """    if hm_module.hardware_manager:
        hm_module.hardware_manager.resume_serial()"""

text = text.replace(target, replacement)
text = text.replace(target_check, replacement_check)
text = text.replace(target_scan, replacement_scan)
text = text.replace(target_pause, replacement_pause)
text = text.replace(target_resume, replacement_resume)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: devices.py updated to use hm_module.hardware_manager")
