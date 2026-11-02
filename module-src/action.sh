#!/system/bin/sh
# Preview-only action menu. This deliberately performs no device mutations.
MODDIR=${0%/*}
ENGINE="${MODDIR}/system/bin/op13-updater-engine"

echo "========================================================"
echo "  OP13 DualBoot Manager — read-only preview"
echo "========================================================"
"$ENGINE" status
echo "========================================================"
echo "Device writes, OTA installation, slot changes and reboot actions are disabled."
echo "See PROJECT_STATUS.md in the source repository for validation requirements."
