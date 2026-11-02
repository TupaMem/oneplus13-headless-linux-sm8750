# OnePlus 13 (Snapdragon 8 Elite / SM8750) — Headless Linux & Native Micro-Glibc Runtime (LineageOS 23.2 / Android 16)

> **EXPERIMENTAL / НЕ ГОТОВО К ПРОШИВКЕ.** Это импорт исходного прототипа, а не проверенное решение для OnePlus 13. Скрипты могут перезаписывать загрузочные разделы, отключать OTA и терморегулирование. WebUI частично имитирует успешные операции. Команды ниже и исходные заявления о производительности не подтверждены на устройстве. Перед использованием прочитайте [PROJECT_STATUS.md](PROJECT_STATUS.md).
>
> ZIP модуля из исходного архива: [`modules/OP13-DualBoot-Linux-OTA-Manager-v2.0-KSU-Magisk.zip`](modules/OP13-DualBoot-Linux-OTA-Manager-v2.0-KSU-Magisk.zip). Это непроверенный исходный артефакт, не рекомендованный установочный релиз. GitHub Actions при публикации отключены.

Полный инженерный проект, набор патчей ядра **LineageOS 23.2 (Android 16 QPR / ACK 6.6 GKI 2.0)**, скрипты купирования Android Userspace и микро-рантайм **GNU C Library (glibc)** для запуска нативных Linux-компонентов на **OnePlus 13 (`dodge`, SoC `SM8750` / `sun`)** без развертывания тяжеловесных гостевых дистрибутивов поверх Android.

## 1. Архитектура целевой платформы и репозиториев LineageOS

### Целевое аппаратное обеспечение: OnePlus 13 (`dodge` / `OP5D0DL1` / `OP5D55L1`)
| Компонент | Спецификация | Особенности в Linux / GKI 6.6 |
| :--- | :--- | :--- |
| **SoC** | Qualcomm Snapdragon 8 Elite (`SM8750-AB`, кодовое имя `sun`) | Техпроцесс TSMC N3E, 100% 64-битная архитектура (`AArch64-only`, аппаратная поддержка `AArch32` удалена) |
| **Кластер CPU 0 (Performance)** | 6x ядер Qualcomm Oryon-L (`cpu0..cpu5`) @ **3.53 ГГц** | Набор инструкций ARMv9.2-A / ARMv8.7-A (`+SVE2`, `+dotprod`, `+bf16`, `+i8mm`, `+crypto`), 12 МБ L2 кэша |
| **Кластер CPU 1 (Prime)** | 2x ядра Qualcomm Oryon-M (`cpu6..cpu7`) @ **4.32 ГГц** | 12 МБ L2 кэша, пиковая однопоточная производительность уровня десктопных процессоров |
| **GPU** | Qualcomm Adreno 830 (`kgsl-3d0`) | Прямой доступ из Linux через `/dev/kgsl-3d0`, `/vendor/lib64/libOpenCL.so` и `/vendor/lib64/hw/vulkan.adreno.so` |
| **NPU** | Qualcomm Hexagon NPU (Compute DSP) | Прямой доступ через `/dev/fastrpc-cdsp` и `/dev/fastrpc-cdsp-secure` (`libcdsprpc.so`) |
| **Память** | 12 / 16 / 24 ГБ LPDDR5X (5300 МГц) + UFS 4.0 | Корневая ФС смонтирована в `EROFS` (read-only), пользовательский раздел `/data` — `F2FS` |

### Официальные деревья LineageOS для OnePlus 13 (Android 16)
Для сборки ядра и базового окружения Android 16 (LineageOS 23.2) и более новых веток (`lineage-24.0`) используются следующие репозитории:
* **Ядро (ACK 6.6 GKI 2.0 + QCOM/OPlus патчи)**: `LineageOS/android_kernel_oneplus_sm8750` (ветка `lineage-23.2` для Android 16; платформа `msm.sun`, сборка через `build_with_bazel.py` и `build.config.msm.sun`).
* **Внешние модули ядра (`vendor_dlkm` / `system_dlkm`)**: `LineageOS/android_kernel_oneplus_sm8750-modules` (ветка `lineage-23.2`).
* **Деревья устройств (Device Trees / DTB)**: `LineageOS/android_kernel_oneplus_sm8750-devicetrees` (флаг `CONFIG_DODGE_DTB=y`).
* **Дерево устройства OnePlus 13 (`dodge`)**: `LineageOS/android_device_oneplus_dodge` и общее дерево платформы `LineageOS/android_device_oneplus_sm8750-common`.

## 2. Структура проекта

* `patches/0001-ANDROID-arm64-configs-sm8750-Enable-SysV-IPC-POSIX-M.patch` — git-патч для `arch/arm64/configs/gki_defconfig`, активирующий System V IPC (`CONFIG_SYSVIPC=y`), очереди сообщений POSIX (`CONFIG_POSIX_MQUEUE=y`), все пространства имен (`CONFIG_NAMESPACES=y`, `CONFIG_USER_NS=y`, `CONFIG_PID_NS=y`, `CONFIG_NET_NS=y`), `CONFIG_DEVTMPFS=y`, `CONFIG_BINFMT_MISC=y` и governor `performance` по умолчанию без нарушения KMI GKI 2.0.
* `patches/0002-ANDROID-thermal-qcom-sm8750-Add-sysfs-toggle-to-bypa.patch` — git-патч для подсистемы `drivers/thermal/thermal_core.c`, добавляющий параметр `/sys/module/thermal_core/parameters/headless_thermal_bypass` для отключения мягкого троттлинга частот Oryon при использовании активного охлаждения Пельтье с сохранением аппаратной защиты PMIC (`THERMAL_TRIP_CRITICAL` / `THERMAL_TRIP_HOT`).
* `patches/sm8750-headless-glibc.config` — изолированный Kconfig-фрагмент для слияния с `gki_defconfig` и `vendor/sun_GKI.config`.
* `scripts/import_and_patch_lineageos.sh` — автоматизированный скрипт клонирования `LineageOS/android_kernel_oneplus_sm8750` (ветка `lineage-23.2`), наложения патчей и интеграции `KernelSU-Next`.
* `scripts/enter_headless.sh` — скрипт перевода Android 16 в режим чистого Linux Headless на лету (остановка `zygote`, `surfaceflinger`, `lmkd`, демонов `oplus`, отключение `zRAM`, фиксация частот кластеров Oryon на 3.53 / 4.32 ГГц и перевод GPU Adreno 830 в режим `performance`) с возможностью мгновенного возврата (`enter_headless.sh restore`).
* `runtime/setup_micro_glibc.sh` — развертывание автономного **Micro-Glibc Runtime** в `/data/glibc` (< 25 МБ) с генерацией загрузчика `/data/glibc/bin/glibc-run`, настройкой статического DNS (`/data/glibc/etc/resolv.conf` в обход Android `netd`) и поддержкой монтирования через `tmpfs` / `binfmt_misc`.
* `tests/advanced_suite.c` — комплексный бенчмарк и валидатор на языке C (проверка версии и линкера `glibc`, верификация `shmget`/`shmat`/`semget` System V IPC, замер задержек вызовов `vDSO clock_gettime` и прямых `syscall(SYS_gettid)`, многопоточный стресс-тест `pthread` с привязкой к ядрам `pthread_setaffinity_np`, и матричный FP64 GEMM тест в GFLOPS).
* `tests/verify_kernel_patches.py` — автоматический валидатор наложения git-патчей и целостности Kconfig-символов.
* `.github/workflows/ci-sm8750-kernel-and-glibc.yml` — пайплайн GitHub Actions на базе ARM64 раннера (`ubuntu-24.04-arm`), выполняющий клонирование `LineageOS/android_kernel_oneplus_sm8750` (`lineage-23.2`), патчинг ядра, сборку `Micro-Glibc` и прогон `advanced_suite`.

## 3. Быстрый старт и запуск на GitHub / OnePlus 13

### Шаг 1. Импорт и патчинг ядра LineageOS 23.2 (Android 16)
```bash
git clone https://github.com/TupaMem/oneplus13-headless-linux-sm8750.git
cd oneplus13-headless-linux-sm8750
BRANCH=lineage-23.2 ENABLE_KSU=1 ./scripts/import_and_patch_lineageos.sh
```

### Шаг 2. Сборка GKI 2.0 ядра для OnePlus 13 (`sun` / `dodge`)
```bash
cd kernel_workspace/kernel
python3 build_with_bazel.py --target=sun --variant=perf
```
Прошивка собранного образа через Fastboot:
```bash
fastboot flash boot out/msm-kernel-sun-perf/dist/boot.img
```

### Шаг 3. Развертывание Micro-Glibc и вход в Headless-режим на устройстве
```bash
adb push scripts/enter_headless.sh /data/local/tmp/
adb push runtime/setup_micro_glibc.sh /data/local/tmp/
adb shell su -c "sh /data/local/tmp/setup_micro_glibc.sh && sh /data/local/tmp/enter_headless.sh"
```

### Шаг 4. Запуск нативных Linux-бинарников (glibc) с привязкой к ядрам Oryon
```bash
# Запуск на 2 Prime-ядрах Oryon (4.32 ГГц):
adb shell su -c "taskset -c 6,7 /data/glibc/bin/glibc-run /data/glibc/bin/advanced_suite"

# Запуск многопоточной задачи на всех 8 ядрах Oryon:
adb shell su -c "taskset -c 0-7 /data/glibc/bin/glibc-run /data/glibc/bin/advanced_suite"
```

## 4. Результаты продвинутого тестирования

| Тест | Проверяемый компонент | Статус | Измеренный результат (базовый стенд) | Ожидаемый профиль на SM8750 Oryon (4.32 ГГц) |
| :--- | :--- | :--- | :--- | :--- |
| **TEST 1: Glibc Runtime & Linker** | Прямой запуск через `ld-linux` и изолированный `GLIBC_ROOT/lib64` без дистрибутива | **PASS** | `glibc 2.36 stable`, 0 внешних зависимостей от `/system/lib64` | `glibc 2.38+` (`aarch64-linux-gnu`), 0% оверхеда трансляции |
| **TEST 2: System V IPC (`CONFIG_SYSVIPC=y`)** | Выделение 64 КБ разделяемой памяти (`shmget`/`shmat`) и операции с семафорами (`semget`/`semop`) | **PASS** | Полный цикл верификации за **580 мкс** | Полный цикл верификации за **< 45 мкс** в LPDDR5X |
| **TEST 3: Syscall & vDSO Latency** | Наносекундная задержка `clock_gettime` (vDSO) и прямого системного вызова `SYS_gettid` | **PASS** | vDSO: **40.51 нс/вызов** | vDSO: **~8.5 нс/вызов**, `SYS_gettid`: **~65 нс/вызов** (bare-metal ARM64 `svc #0`) |
| **TEST 4: Multi-Core Pthread & Atomics** | Масштабирование 8 потоков `pthread` с `pthread_setaffinity_np` и атомарным `atomic_fetch_add` | **PASS** | **1071.67 млн опер./сек** (625 000 атомарных транзакций) | **> 9 800 млн опер./сек** на 2x Prime + 6x Performance ядрах Oryon |
| **TEST 5: Dense FP64 GEMM Compute** | Умножение плотных матриц `256x256` двойной точности (FP64) с выравниванием 64 байта | **PASS** | **6.90 GFLOPS** (на одно ядро, контрольная сумма `470.69`) | **> 42 GFLOPS** (FP64 Single-Core) / **> 1.8 TFLOPS** (FP16/BF16 SVE2/NEON) |
