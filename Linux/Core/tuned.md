# TuneD — оптимизация производительности системы

## Определения

**TuneD** — адаптивный демон в Linux для автоматической оптимизации производительности системы. Он управляет параметрами ядра, сети, дисков, питания и процессора, используя **профили** — наборы предустановленных конфигураций.

В современных дистрибутивах (например, Fedora 41+) TuneD заменил `power-profiles-daemon` (PPD), став стандартным инструментом управления питанием и производительностью как на серверах, так и на десктопах.

**Профиль производительности** — декларативное описание настроек (sysctl, параметры модулей, планировщики), оптимизированное под конкретный сценарий (высокая пропускная способность, низкая задержка, энергосбережение).

## Основные концепции

### Возможности TuneD

| Возможность | Описание |
| :--- | :--- |
| **Готовые профили** | Оптимизированы для БД, виртуализации, AI/ML, десктопов и реального времени. |
| **Иерархия (Наследование)** | Новые профили могут расширять существующие через директиву `include`. |
| **Динамическая настройка** | Адаптация параметров под текущую нагрузку (динамический тюнинг). |
| **Vigilant Mode (2.27+)** | Механизм контроля «дрейфа» настроек: предотвращает ручное переопределение параметров, заданных профилем. |
| **D-Bus API** | Интеграция с графическими оболочками (GNOME, KDE) и панелями управления (Cockpit). |
| **Плагины** | Модульная архитектура для управления CPU (частоты, Uncore, P-state), дисками (I/O scheduler, ALPM), сетью и загрузчиком. |

### Структура профиля

**Расположение профилей:**

- **Системные (ReadOnly):** `/usr/lib/tuned/`
- **Кастомные (Приоритетные):** `/etc/tuned/`

**Файл конфигурации (`tuned.conf`):**

```ini
[main]
summary=Описание профиля
include=throughput-performance  # Наследование

[sysctl]
vm.swappiness = 10

[cpu]
# Поддержка современных драйверов intel_pstate и amd-pstate
governor = performance
energy_perf_bias = performance

[disk]
# Динамический выбор планировщика (mq-deadline для SSD/NVMe)
elevator = mq-deadline

[network]
# Оптимизация под высокую пропускную способность
runtime = 1
```

**Ключевые плагины:**
* `cpu`: управление частотой, состоянием сна (C-states) и драйверами P-state.
* `uncore`: (новое) управление частотой кэша L3 и контроллера памяти.
* `disk`: настройка I/O планировщиков и управления питанием SATA/NVMe.
* `net`: тюнинг сетевых интерфейсов через `ethtool`.
* `sysctl`: прямое управление параметрами `/proc/sys`.
* `bootloader`: добавление параметров в командную строку GRUB.
* `script`: выполнение произвольных Shell/Python скриптов при активации профиля.

## Практические сценарии

### 1. Установка и запуск

```bash
# RHEL / Fedora / AlmaLinux / Rocky
sudo dnf install tuned
# На Fedora 41+ также стоит установить tuned-ppd для совместимости с GUI
sudo dnf install tuned-ppd

# Debian / Ubuntu
sudo apt install tuned

# Запуск и включение автозапуска
sudo systemctl enable --now tuned
```

### 2. Управление профилями через tuned-adm

```bash
# Просмотр всех доступных профилей
tuned-adm list

# Рекомендация профиля на основе типа системы (физическая/виртуальная)
tuned-adm recommend

# Активация профиля
sudo tuned-adm profile throughput-performance

# Просмотр активного профиля и статуса его применения
tuned-adm active
# → Current active profile: throughput-performance

# Проверка, что все настройки применились корректно
tuned-adm verify
# → Verification succeeded, current system settings match the profile.
```

### 3. Основные профили и их назначение

| Профиль | Назначение | Ключевые настройки |
| :--- | :--- | :--- |
| `balanced` | Баланс производительности и питания. | По умолчанию для десктопов и общих задач. |
| `throughput-performance` | Максимальная пропускная способность. | Тюнинг дисковых очередей, `governor=performance`. |
| `latency-performance` | Минимальные задержки. | Отключение глубоких C-states, агрессивный CPU. |
| `network-latency` | Низкие сетевые задержки. | Основан на `latency-performance`, тюнинг TCP/IP. |
| `virtual-guest` | Гостевая ОС в виртуализации. | Тюнинг памяти, снижение агрессивности I/O. |
| `cpu-partitioning` | Изоляция ядер CPU. | Разделение ядер на "системные" и "изолированные". |
| `accelerator-performance` | Для систем с GPU/FPGA. | Тюнинг PCI-E и задержек CPU. |
| `ai-ml` | (Новое) Нагрузки ИИ. | Отключение NUMA balancing и Transparent Huge Pages. |

### 4. Специализированные инструменты

#### powertop2tuned
Утилита позволяет сгенерировать профиль TuneD на основе рекомендаций `powertop`.
```bash
# Создание профиля на основе текущих рекомендаций энергосбережения
sudo powertop2tuned my-power-profile
# Активация
sudo tuned-adm profile my-power-profile
```

#### Изоляция ядер (cpu-partitioning)
Используется в высокочастотном трейдинге (HFT) или при обработке пакетов (DPDK).
Для настройки требуется указать изолируемые ядра в файле `/etc/tuned/cpu-partitioning-variables.conf`:
```ini
isolated_cores=1-3,5-7
```

### 5. Конфликты и сосуществование

*   **PPD (power-profiles-daemon):** На новых системах TuneD работает как бэкенд через `tuned-ppd`. Не запускайте оба сервиса одновременно в "чистом" виде, если не используется прослойка совместимости.
*   **Manual Sysctl:** Параметры в `/etc/sysctl.d/` имеют приоритет над TuneD. Если `tuned-adm verify` выдает ошибку, проверьте ручные конфиги.
*   **TLP / Laptop Mode Tools:** Могут конфликтовать с TuneD. Рекомендуется использовать что-то одно.

### 6. Создание кастомного профиля

```bash
# 1. Создать директорию
sudo mkdir -p /etc/tuned/my-profile

# 2. Создать tuned.conf
sudo tee /etc/tuned/my-profile/tuned.conf << 'EOF'
[main]
summary=My Custom Performance Profile
include=latency-performance

[sysctl]
vm.swappiness = 10
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 8192

[cpu]
governor = performance

[disk]
elevator = deadline
EOF

# 3. Активировать профиль
sudo tuned-adm profile my-profile

# 4. Проверить
tuned-adm active
```

### 7. Устранение неполадок

| Проблема | Решение |
| :--- | :--- |
| Профиль не применяется | Проверить `systemctl status tuned`, `journalctl -u tuned` |
| `tuned-adm verify` выдаёт ошибки | Параметры переопределены вручную в `/etc/sysctl.conf` или `/etc/sysctl.d/` |
| Демон не запускается | Проверить конфликты с другими сервисами оптимизации (например, TLP, LMT) |
| Настройки сбрасываются после перезагрузки | Убедиться, что профиль включён через `tuned-adm` и сервис `tuned` в автозагрузке |

## Дополнительная информация

### Связанные темы

- **[Настройка параметров ядра (sysctl)](./kernel/sysctl.md)** — ручное управление параметрами через sysctl.
- **[Оптимизация памяти (Memory Tuning)](./memory/performance_tuning.md)** — глубокая настройка подсистемы памяти, которую TuneD автоматизирует.
- **[Оптимизация файловых систем](../FileSystems/performance_tuning.md)** — планировщики I/O и опции монтирования.
- **[CPU Pinning](./cpu_pinning.md)** — изоляция и привязка процессов к ядрам CPU (дополнение к `cpu-partitioning`).
- **[Обзор Systemd](./systemd/overview.md)** — управление службой `tuned.service`.
