# Диагностика GPU: NVIDIA, AMD и framebuffer

## Определения

**`nvidia-smi` (NVIDIA System Management Interface)** — утилита для мониторинга и управления GPU NVIDIA. Позволяет проверять температуру, утилизацию, память, processes и состояние драйвера. Поддерживает вывод в CSV/XML для автоматизации.

**XID Error** — внутренний код ошибки GPU NVIDIA, генерируемый драйвером в ответ на аппаратные или программные сбои. Коды XID классифицируются поseverity: от informational (31) до fatal (79).

**`nvidia-detect`** — утилита для автоматического определения модели GPU NVIDIA и рекомендации драйвера.

**`rocm-smi`** — аналог `nvidia-smi` для GPU AMD (ROCm stack). Предоставляет информацию о температуре, утилизации, памяти и power.

**DRM (Direct Rendering Manager)** — подсистема ядра Linux для управления GPU. Предоставляет интерфейс через `/sys/class/drm/card*/` для чтения состояния GPU без проприетарных драйверов.

**Framebuffer** — виртуальное устройство `/dev/fb0`, представляющее видео-буфер. Используется для текстовой консоли и framebuffer-based графики.

---

## Базовые концепции

### Типы GPU в серверах

| Тип | Примеры | Назначение | Драйвер |
| :--- | :--- | :--- | :--- |
| **NVIDIA Compute** | A100, H100, L40S | ML/HPC, CUDA | `nvidia-driver`, `nvidia-smi` |
| **NVIDIA vGPU** | A100-80GB, T4 | Виртуализация GPU | `nvidia-vgpu-mgr` |
| **AMD Compute** | MI250X, MI300X | ML/HPC, ROCm | `amdgpu`, `rocm-smi` |
| **Integrated GPU** | Intel UHD, AMD APU | Видеовыход | `i915`, `amdgpu` |
| **Framebuffer** | text-console | Консоль Linux | `fbdev`, `simpledrm` |

### Архитектура мониторинга GPU

```
Аппаратура GPU (NVIDIA/AMD)
    ↓
Драйвер ядра (nvidia, amdgpu, i915)
    ↓
/dev/nvidia*, /sys/class/drm/card*
    ↓
nvidia-smi / rocm-smi (пользовательский интерфейс)
    ↓
DCGM / Prometheus exporter (мониторинг в кластере)
```

### Ключевые метрики GPU

| Метрика | Описание | Критичность |
| :--- | :--- | :--- |
| **Temperature** | Температура GPU | Высокая (>85°C → throttling) |
| **GPU Utilization** | Процент утилизации CUDA-ядер | Информационный |
| **Memory Utilization** | Использование VRAM | Средняя (>95% → OOM) |
| **Power Draw** | Потребление энергии (W) | Средняя |
| **ECC Errors** | Ошибки памяти GPU (NVIDIA) | **Критическая** |
| **XID Errors** | Аппаратные ошибки GPU | **Критическая** |
| **Clock Throttling** | Причины снижения частоты | Средняя |

---

## Практические сценарии

### nvidia-smi: базовые команды

```bash
# Просмотр всех GPU
nvidia-smi
# → +-----------------------------------------------------------------------------+
# → | NVIDIA-SMI 535.129.03   Driver Version: 535.129.03   CUDA Version: 12.2    |
# → |-------------------------------+----------------------+----------------------+
# → | GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
# → |===============================+======================+======================|
# → |   0  NVIDIA A100-SXM4-80GB  On | 00000000:00:04.0 Off |                    0 |
# → |-------------------------------+----------------------+----------------------+
# → | GPU  Util.         Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
# → |===============================+======================+======================|
# → |   0     78%        300W/400W   |  74256MiB/81920MiB   |     89%      Default |
# → +-------------------------------+----------------------+----------------------+

# Краткий вывод (только GPU, без заголовков)
nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv
# → index, name, temperature.gpu, utilization.gpu, memory.used [MiB], memory.total [MiB]
# → 0, NVIDIA A100-SXM4-80GB, 62, 78, 74256, 81920

# Мониторинг в реальном времени (обновление каждую секунду)
watch -n1 nvidia-smi

# Просмотр процессов, использующих GPU
nvidia-smi pmon -c 1
# → c   0    12345   78   0   4567MiB   0MiB     python3
# → c   0    12346   12   0   2048MiB   0MiB     python3

# Детальная информация о GPU
nvidia-smi -q
# → Drivers: 535.129.03
# → CUDA: 12.2
# → GPU 0: NVIDIA A100-SXM4-80GB
#   FB Memory Usage: Total 81920MiB, Used 74256MiB
#   Temperature: 62°C
#   Power Draw: 300W
#   ECC Errors: 0 (Correctable), 0 (Uncorrectable)
```

### Диагностика XID ошибок

```bash
# Просмотр XID ошибок в dmesg
dmesg | grep -i "xid\|nvrm\|nvidia"
# → [  123.456] NVRM: GPU at PCI:0000:00:04: GPU-abc123
# → [  123.457] NVRM: Xid (PCI:0000:00:04): 79, pid=12345

# Расшифровка кодов XID:
# → 13  — GR Graphics Exception (программная ошибка)
# → 31  — GPU Memory Page Fault (программная ошибка)
# → 32  — Invalid/Corrupted Push Buffer (драйвер/железо)
# → 43  — GPU stopped processing (аппаратная ошибка)
# → 48  — Double Bit ECC Error (аппаратная ошибка, критично)
# → 63  — ECC Page Retirement (аппаратная ошибка)
# → 64  — ECC Page Retirement Warning (аппаратная ошибка)
# → 79  — GPU has fallen off the bus (аппаратная ошибка, критично)
# → 94  — Contained ECC Error (аппаратная ошибка)

# Проверка логов NVIDIA
journalctl -k | grep -i "xid\|nvidia\|nvrm"

# Проверка через nvidia-smi
nvidia-smi -q | grep -A5 "Xid"
```

### Мониторинг температуры и throttling

```bash
# Температура GPU
nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader
# → 62

# Причины throttling
nvidia-smi -q | grep -A10 "Clocks Throttle Reasons"
# → SW Power Cap: Active
# → HW Thermal Slowdown: Not Active
# → HW Power Brake: Not Active

# Мониторинг температуры NVMe GPU (через sysfs)
cat /sys/class/drm/card0/device/hwmon/hwmon*/temp1_input 2>/dev/null
```

### AMD GPU (rocm-smi)

```bash
# Установка ROCm
sudo apt install rocm-smi

# Просмотр GPU
rocm-smi
# → GPU  Temp   AvgPwr   SCLK    MCLK     Fan     Perf   PwrCap   VRAM%    GPU%
# → 0    62.0c  250.0W   1800Mhz 1200Mhz  0%      auto   300.0W   45%      78%

# Детальная информация
rocm-smi --showuse
rocm-smi --showmeminfo vram
rocm-smi --showtemp

# CSV вывод для автоматизации
rocm-smi --showuse --csv
```

### Проверка DRM через sysfs

```bash
# Список всех DRM-устройств
ls /sys/class/drm/
# → card0  card0-DP-1  card0-HDMI-A-1  renderD128

# Информация о GPU через DRM
cat /sys/class/drm/card0/vendor
# → 0x10de  (NVIDIA)
cat /sys/class/drm/card0/device
# → 0x20b2  (GA100)

# Статус дисплеев
cat /sys/class/drm/card0/card0-DP-1/status
# → connected

# ПроверкаVIDIA GPU через lspci
lspci | grep -i "vga\|3d\|display"
# → 00:04.0 VGA compatible controller: NVIDIA Corporation GA100 [A100 SXM4 80GB]
```

### Диагностика framebuffer

```bash
# Проверка framebuffer устройства
ls -la /dev/fb*
# → crw-rw---- 1 root video 29, 0 Mar 15 14:22 /dev/fb0

# Информация о framebuffer
cat /sys/class/graphics/fb0/name
# → EFIFB
cat /sys/class/graphics/fb0/bits_per_pixel
# → 32

# Проверка через fbset
sudo fbset -i
# → mode "1920x1080"
# → geometry 1920 1080 1920 1080 32
```

### Автоматизация мониторинга GPU

```bash
# Скрипт для проверки здоровья GPU
#!/bin/bash
LOG="/var/log/gpu_health.log"
DATE=$(date +%Y-%m-%d\ %H:%M)

# NVIDIA GPU
if command -v nvidia-smi &>/dev/null; then
  TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader)
  UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader | cut -d' ' -f1)
  MEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader | cut -d' ' -f1)
  XID=$(dmesg | grep -c "Xid" 2>/dev/null || echo 0)

  echo "$DATE NVIDIA: temp=${TEMP}C util=${UTIL}% mem=${MEM}MiB xid=${XID}" >> "$LOG"

  [ "${TEMP:-0}" -gt 85 ] && echo "WARN: GPU temp ${TEMP}°C" >&2
  [ "${XID:-0}" -gt 0 ] && echo "CRIT: XID errors detected!" >&2
fi

# AMD GPU
if command -v rocm-smi &>/dev/null; then
  TEMP=$(rocm-smi --showtemp --csv 2>/dev/null | tail -1 | cut -d',' -f2)
  echo "$DATE AMD GPU: temp=${TEMP}°C" >> "$LOG"
fi
```

### Интеграция с Prometheus (DCGM Exporter для NVIDIA)

```bash
# NVIDIA DCGM (Data Center GPU Manager) Exporter
# Установка через Docker
docker run -d --gpus all --restart=always \
  -p 9400:9400 \
  nvcr.io/nvidia/k8s/dcgm-exporter:3.3.5-3.4.0-ubuntu22.04

# Ключевые метрики Prometheus:
# DCGM_FI_DEV_GPU_UTIL — утилизация GPU (%)
# DCGM_FI_DEV_FB_USED — использованная VRAM (MiB)
# DCGM_FI_DEV_FB_FREE — свободная VRAM (MiB)
# DCGM_FI_DEV_TEMPERATURE — температура (°C)
# DCGM_FI_DEV_ECC_SBE — Single-Bit ECC Errors
# DCGM_FI_DEV_ECC_DBE — Double-Bit ECC Errors
```

**Алертинг:**
```yaml
groups:
  - name: gpu_alerts
    rules:
      - alert: GpuTemperatureHigh
        expr: DCGM_FI_DEV_TEMPERATURE > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GPU温度高: {{ $labels.gpu }} = {{ $value }}°C"

      - alert: GpuEccDoubleBit
        expr: DCGM_FI_DEV_ECC_DBE > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Double-Bit ECC Error на GPU {{ $labels.gpu }}!"

      - alert: GpuMemoryFull
        expr: (DCGM_FI_DEV_FB_USED / (DCGM_FI_DEV_FB_USED + DCGM_FI_DEV_FB_FREE)) * 100 > 95
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "VRAM заполнена на {{ $value }}% на {{ $labels.gpu }}"
```

---

## Дополнительная информация

### Типичные пороговые значения

| Параметр | Норма | Предупреждение | Критично |
| :--- | :--- | :--- | :--- |
| **Temperature** | 30–75°C | > 80°C | > 90°C |
| **Memory Usage** | < 80% | > 90% | > 95% |
| **Power Draw** | < 80% TDP | = 100% TDP | Thermal shutdown |
| **ECC Errors (CE)** | 0 | > 10/час | > 100/час |
| **ECC Errors (UE)** | 0 | **0** | > 0 (немедленная замена) |

### Связанные темы

- **[Инвентаризация: GPU](./hardware_listing.md)** — lspci, DRM, framebuffer.
- **[IPMI: удалённый доступ](./ipmi_bmc.md)** — KVM-over-IP для GPU-серверов.
- **[Thermal monitoring](./hardware_monitoring.md)** — hwmon, sensors, cooling devices.
- **[NVMe: диагностика](./nvme-errors-diagnostics.md)** — ошибки шины PCIe (распространены на GPU).
- **[dmesg: DRM errors](../Kernel/dmesg/usage.md)** — поиск ошибок GPU в kernel log.
