#!/system/bin/sh
# ==============================================================================
# enter_headless.sh
# Runtime Android 16 (LineageOS 23.2) Userspace Decapitation & Oryon Tuning
# Target: OnePlus 13 (dodge / Snapdragon 8 Elite SM8750)
# Preserves Qualcomm Vendor HALs (Adreno 830 /dev/kgsl-3d0, Hexagon /dev/fastrpc-*)
# while freeing 3.5-5.5 GB RAM and eliminating all UI/Binder/GC jitter.
# ==============================================================================
set -e

MODE="${1:-start}"

if [ "$MODE" = "restore" ]; then
    echo "[*] Restoring Android 16 Userspace (Zygote & SurfaceFlinger)..."
    echo 0 > /sys/module/thermal_core/parameters/headless_thermal_bypass 2>/dev/null || true
    for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo "walt" > "$gov" 2>/dev/null || echo "schedutil" > "$gov" 2>/dev/null || true
    done
    start
    echo "[+] Android UI restored."
    exit 0
fi

echo "[*] 1. Ensuring Dropbear SSH / ADB TCP persistence before stopping Framework..."
if [ -x /data/glibc/bin/dropbear ]; then
    /data/glibc/bin/dropbear -R -p 2222
fi

echo "[*] 2. Stopping Android Java Runtime (Zygote), SurfaceFlinger & LMKD..."
setprop ctl.stop zygote
setprop ctl.stop zygote_secondary
setprop ctl.stop surfaceflinger
setprop ctl.stop lmkd
stop

echo "[*] 3. Terminating residual OPlus/Lineage telemetry & background daemons..."
pkill -9 -f "oplus" 2>/dev/null || true
pkill -9 -f "coloros" 2>/dev/null || true
pkill -9 -f "statsd" 2>/dev/null || true
pkill -9 -f "traced" 2>/dev/null || true

echo "[*] 4. Disabling zRAM compression overhead & zeroing swappiness..."
echo 0 > /proc/sys/vm/swappiness
swapoff /dev/block/zram0 2>/dev/null || true
echo 3 > /proc/sys/vm/drop_caches

echo "[*] 5. Locking Snapdragon 8 Elite (SM8750) Oryon Cores to Performance..."
# Cluster 0 (cpu0..cpu5): 6x Oryon Performance Cores @ 3.53 GHz
# Cluster 1 (cpu6..cpu7): 2x Oryon Prime Cores @ 4.32 GHz
for cpu_dir in /sys/devices/system/cpu/cpu[0-7]/cpufreq; do
    if [ -d "$cpu_dir" ]; then
        echo "performance" > "$cpu_dir/scaling_governor" 2>/dev/null || true
        max_freq=$(cat "$cpu_dir/cpuinfo_max_freq" 2>/dev/null || echo "")
        if [ -n "$max_freq" ]; then
            echo "$max_freq" > "$cpu_dir/scaling_min_freq" 2>/dev/null || true
        fi
    fi
done

echo "[*] 6. Locking Adreno 830 GPU (/sys/class/kgsl/kgsl-3d0) to low-latency state..."
if [ -d /sys/class/kgsl/kgsl-3d0/devfreq ]; then
    echo "performance" > /sys/class/kgsl/kgsl-3d0/devfreq/governor 2>/dev/null || true
    echo 0 > /sys/class/kgsl/kgsl-3d0/force_bus_on 2>/dev/null || true
    echo 1 > /sys/class/kgsl/kgsl-3d0/force_clk_on 2>/dev/null || true
fi

echo "[*] 7. Enabling Kernel Thermal Soft-Trip Bypass (Requires External Peltier Cooler!)..."
echo 1 > /sys/module/thermal_core/parameters/headless_thermal_bypass 2>/dev/null || true
stop thermal-engine 2>/dev/null || true

echo "[+] OnePlus 13 is now in Pure Headless Linux Mode."
free -m
