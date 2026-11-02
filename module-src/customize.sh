#!/system/bin/sh
# ==============================================================================
# customize.sh — Module Installation Script (KernelSU / APatch / Magisk)
# Target: OnePlus 13 (dodge / Snapdragon 8 Elite SM8750)
# ==============================================================================
SKIPUNZIP=0

ui_print "========================================================"
ui_print "  OnePlus 13 DualBoot Manager — PREVIEW ONLY           "
ui_print "  KernelSU-Next • APatch • Magisk v26+                 "
ui_print "========================================================"

SOC="$(getprop ro.board.platform 2>/dev/null || true)"
DEVICE="$(getprop ro.product.device 2>/dev/null || true)"
SLOT="$(getprop ro.boot.slot_suffix 2>/dev/null || true)"

ui_print "[*] Reported Platform : ${SOC:-unknown} (${DEVICE:-unknown})"
ui_print "[*] Reported Boot Slot : ${SLOT:-unknown}"

# Set executable permissions on module scripts and binaries
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm_recursive "$MODPATH/system/bin" 0 0 0755 0755
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
set_perm "$MODPATH/action.sh" 0 0 0755
set_perm "$MODPATH/uninstall.sh" 0 0 0755

ui_print "[!] READ-ONLY PREVIEW: boot/OTA writes, slot changes, and reboot are disabled."
ui_print "[i] The WebUI is static and does not connect to a root command bridge."
ui_print "[i] Do not treat this module as an installer or protection mechanism."
ui_print "========================================================"
