# TuneD — динамическая оптимизация производительности системы

## Определения

**TuneD** — адаптивный демон в Linux для автоматической оптимизации производительности системы. Он управляет параметрами ядра, сети, дисков, питания и процессора, используя **профили** — наборы декларативных конфигураций, адаптированных под конкретные сценарии использования.

В современной экосистеме Linux (ядра 6.x+, дистрибутивы Fedora 41+, RHEL 9+) TuneD стал универсальным бэкендом для управления питанием и производительностью, вытесняя или интегрируя `power-profiles-daemon` (PPD).

**Динамический тюнинг (Dynamic Tuning)** — режим работы TuneD, при котором демон отслеживает нагрузку на систему в реальном времени и корректирует параметры (например, агрессивность энергосбережения или частоту CPU) на лету.

---

## Основные концепции

### Модульная архитектура (Плагины)

TuneD использует систему плагинов для взаимодействия с различными подсистемами ядра и оборудования:

| Плагин | Сфера влияния | Технические детали |
| :--- | :--- | :--- |
| **`cpu`** | Частота и состояния сна | Управляет драйверами `intel_pstate`, `amd-pstate`, `acpi-cpufreq`. Настраивает `governor` и `energy_perf_bias`. |
| **`uncore`** | L3 кэш и контроллер памяти | (Новое) Позволяет фиксировать или ограничивать частоту Uncore для снижения задержек (latency). |
| **`disk`** | Блочные устройства | Настраивает планировщики I/O (`mq-deadline`, `kyber`), параметры `readahead` и агрессивность ALPM. |
| **`net`** | Сетевые интерфейсы | Использует `ethtool` для управления очередями, прерываниями и параметрами энергосбережения сетевых карт. |
| **`sysctl`** | Параметры ядра | Прямое изменение значений в `/proc/sys`. |
| **`bootloader`** | Параметры загрузки | Добавляет аргументы в командную строку ядра через GRUB (требует перезагрузки для применения). |
| **`script`** | Кастомная логика | Выполняет внешние Shell или Python скрипты при смене профиля. |

### Иерархия и структура профилей

Профили TuneD поддерживают **наследование**, что позволяет создавать специализированные конфигурации на базе стандартных без дублирования кода.

**Места хранения:**
- `/usr/lib/tuned/` — системные профили (не редактировать).
- `/etc/tuned/` — кастомные профили и переопределения.

**Пример структуры `tuned.conf`:**
```ini
[main]
summary=Оптимизация для высоконагруженных БД
include=throughput-performance  # Базовый профиль

[sysctl]
# Переопределение параметров ядра
vm.swappiness = 10
kernel.sched_min_granularity_ns = 10000000

[cpu]
# Фиксация производительности
governor=performance
energy_perf_bias=performance

[bootloader]
# Параметры будут добавлены в GRUB_CMDLINE_LINUX
cmdline=intel_iommu=on isolcpus=1-3
```

### Механизм Vigilant Mode (Контроль дрейфа)

Введенный в версии 2.27, **Vigilant Mode** позволяет TuneD периодически проверять состояние параметров системы. Если стороннее приложение или администратор вручную изменили параметр, который жестко задан в активном профиле, TuneD вернет его в исходное состояние. Это критично для поддержания консистентности в кластерах и HPC-средах.

### Движок рекомендаций (recommend.conf)

TuneD может автоматически выбирать профиль при установке или по запросу `tuned-adm recommend`. Логика выбора описана в `/usr/lib/tuned/recommend.conf` и базируется на:
- Наличии специфических файлов в `/sys` (например, признаки виртуализации).
- Модели CPU и наличии GPU.
- Содержимом `/proc/cmdline`.

### Архитектура и жизненный цикл демона

**Процесс tuned** является `systemd`-сервисом (`tuned.service`). Его архитектура состоит из:

1. **Главный процесс (main daemon)** — парсит конфигурации, загружает плагины, координирует применение профилей.
2. **Плагин-воркеры** — каждый плагин выполняется в контексте главного процесса (не в отдельных процессах), но имеет изолированную логику применения настроек.
3. **D-Bus интерфейс** — `org.freedesktop.tuned` на системной шине. Позволяет внешним инструментам (GNOME Power Profiler, tuned-gui) запрашивать текущий профиль, активные параметры и переключать профили программно.
4. **Мониторинг нагрузки** — в режиме dynamic tuning демон собирает метрики (загрузка CPU, активность дисков, прерывания) через `/proc` и `sysfs`, принимая решения об изменении параметров без участия администратора.

**Последовательность применения профиля:**
```
tuned-adm profile X
    ↓
Остановка текущего профиля (вызов cleanup() у всех плагинов)
    ↓
Загрузка конфигурации X
    ↓
Наследование от include-профилей (если указано)
    ↓
Вызов apply() у каждого плагина в порядке:
  1. bootloader (если есть параметры ядра)
  2. uncore
  3. cpu
  4. disk
  5. net
  6. sysctl
  7. script
    ↓
Включение Vigilant Mode (если active)
```

### Внутренности плагинов

#### Плагин `cpu`

Управляет частотой и энергопотреблением процессора. Поддерживает три драйвера:
- **`intel_pstate`** — активирован по умолчанию на большинстве современных Intel CPU. Поддерживает два режима: `active` (полный контроль частоты через MSR) и `passive` (через стандартный `cpufreq`). TuneD предпочитает `active`, так как он позволяет точнее управлять `energy_performance_preference` (EPP).
- **`amd-pstate`** — аналогичный механизм для AMD Zen 2+. Поддерживает `active` и `passive` режимы. На ядрах 6.3+ активируется автоматически на поддерживаемом железе.
- **`acpi-cpufreq`** — универсальный драйвер через ACPI, используется как запасной вариант.

**Важные параметры:**
- `governor` — политика частоты (`performance`, `ondemand`, `conservative`, `schedutil`). Для серверов рекомендуется `performance` или `schedutil`.
- `energy_perf_bias` (Intel) / `power_perf_preference` (AMD) — баланс между производительностью и энергопотреблением. Значения: `performance`, `balance_performance`, `default`, `balance_power`, `power`.

#### Плагин `disk`

Настраивает параметры блочных устройств. **Алгоритм выбора планировщика I/O:**
1. Определяет тип устройства (SSD, NVMe, HDD) через `/sys/block/<dev>/queue/rotational`.
2. Для NVMe/SSD: `mq-deadline` или `none` (если устройство явно указано в профиле).
3. Для HDD: `bfq` или `mq-deadline` в зависимости от загрузки.
4. Устанавливает `readahead` (количество килобайт для предварительного чтения): 4KB для SSD, 256KB для HDD.
5. Управляет ALPM (Aggressive Link Power Management) для SATA-дисков через `hdparm` или `sysfs`.

**Ограничение:** Плагин `disk` не трогает устройства, которые смонтированы или используются LVM/multipath. Для таких сценариев используйте правила `udev` или кастомные скрипты.

#### Плагин `net`

Использует `ethtool` для управления сетевыми интерфейсами. **Что настраивает:**
- **Очереди (queues):** Количество transmit/receive queues через `ethtool -L`. На серверах с многоядерными CPU рекомендуется выравнивать количество очередей по количеству NUMA-узлов.
- **Coalescing:** Объединение прерываний для снижения overhead (`ethtool -C`). Для низколатентных приложений — отключено; для фоновой передачи — агрессивное объединение.
- **Energy-Efficient Ethernet (EEE):** Отключается на серверных картах, так как вызывает задержки.
- **Wake-on-LAN (WoW):** Отключается на серверах для снижения энергопотребления.
- **Размеры колец (ring buffers):** Увеличиваются для высоконагруженных интерфейсов, чтобы избежать packet drop.

**Важно:** Плагин применяет настройки только к интерфейсам, указанным в параметре `devices` (по умолчанию — все, исключая loopback). Для bond/vlan интерфейсов указывайте базовый физический интерфейс или используйте `script` плагин.

### D-Bus API и программное управление

TuneD exposes системный интерфейс D-Bus, что позволяет интегрировать его в панели управления и скрипты:

```bash
# Получить текущий профиль через D-Bus
busctl get-property org.freedesktop.tuned /org/freedesktop/tuned org.freedesktop.tuned Manager Profile
# → s "throughput-performance"

# Получить список доступных профилей
busctl call org.freedesktop.tuned /org/freedesktop/tuned org.freedesktop.tuned Manager ListProfiles
```

Для Python-скриптов можно использовать `pydbus` или `dbus-next` для автоматического переключения профилей на основе внешних триггеров (например, при подключении зарядного устройства ноутбука).

---

## Практические сценарии

### 1. Управление через CLI (tuned-adm)

```bash
# Список всех профилей и текущий активный
tuned-adm list

# Рекомендация профиля на основе аппаратного обеспечения
tuned-adm recommend

# Активация профиля
sudo tuned-adm profile throughput-performance

# Проверка консистентности (сравнение реальных настроек с профилем)
tuned-adm verify
# → Verification succeeded (все настройки соответствуют профилю)
```

### 2. Изоляция ядер для Real-time нагрузок

Профиль `cpu-partitioning` — один из самых мощных инструментов TuneD. Он позволяет изолировать ядра от прерываний и планировщика ОС без ручной правки GRUB.

1.  Укажите ядра в `/etc/tuned/cpu-partitioning-variables.conf`:
    ```ini
    isolated_cores=1-3
    ```
2.  Активируйте профиль:
    ```bash
    sudo tuned-adm profile cpu-partitioning
    ```
3.  **Перезагрузитесь** (так как профиль правит параметры загрузки ядра).

### 3. Генерация профиля на лету (powertop2tuned)

Если вам нужно максимально продлить жизнь ноутбука от батареи:
```bash
# Генерация профиля на основе анализа энергопотребления
sudo powertop2tuned laptop-battery-saver
# Активация
sudo tuned-adm profile laptop-battery-saver
```

### 4. Создание кастомного профиля для веб-сервера

```bash
sudo mkdir -p /etc/tuned/web-server
sudo tee /etc/tuned/web-server/tuned.conf << 'EOF'
[main]
summary=Optimized for Nginx/Angie high load
include=throughput-performance

[sysctl]
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 8192
vm.swappiness = 5

[net]
# Отключение агрессивного энергосбережения сетевой карты
devices=eth*
dynamic_tuning=0
EOF

sudo tuned-adm profile web-server
```

### 5. Профиль для сервера баз данных

Серверы баз данных (PostgreSQL, MySQL, MariaDB) чувствительны к задержкам дисков, планированию I/O и изоляции ядер. Ключевые моменты:
- Отключение энергосбережения дисков (ALPM).
- Установка `vm.swappiness = 10` и увеличение `vm.dirty_ratio`/`vm.dirty_background_ratio` для batch-записи.
- Использование `deadline` или `bfq` планировщика для SATA HDD, `none` для NVMe.
- Опционально: изоляция ядер для фоновых операций (VACUUM в PostgreSQL).

```bash
sudo tee /etc/tuned/postgres-server/tuned.conf << 'EOF'
[main]
summary=Optimized for PostgreSQL/MySQL on HDD/NVMe
include=throughput-performance

[sysctl]
vm.swappiness = 10
vm.dirty_ratio = 20
vm.dirty_background_ratio = 5
kernel.sched_min_granularity_ns = 10000000

[disk]
# Отключение ALPM для снижения задержек
alpm=disable

[bootloader]
# Изоляция ядер 4-7 для фоновых задач
cmdline=isolcpus=4-7
EOF

sudo tuned-adm profile postgres-server
```

### 6. Мониторинг и проверка конфигурации

После применения профиля необходимо убедиться, что настройки действительно применились. TuneD не всегда выводит подробный отчет по умолчанию.

```bash
# Текущий активный профиль
tuned-adm active
# → Current active profile: throughput-performance

# Детальная проверка (все параметры)
tuned-adm verify
# → Verification succeeded

# Примененные параметры sysctl
sysctl -a | grep -E "vm.swappiness|kernel.sched"

# Текущий governor CPU
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# → performance

# Планировщик диска
cat /sys/block/sda/queue/scheduler
# → [mq-deadline] kyber bfq none

# Параметры ethtool для интерфейса
ethtool -k eth0 | grep -E "tcp-segmentation-offload|generic-receive-offload"

# Логи tuned (отладка)
journalctl -u tuned -f
# → ... profile 'postgres-server' applied successfully
```

### 7. Динамическое переключение без перезагрузки

Большинство изменений TuneD применяются мгновенно. Перезагрузка требуется **только** для параметров, добавленных через плагин `bootloader` (например, `isolcpus`, `intel_iommu=on`).

```bash
# Переключение на другой профиль "на лету"
sudo tuned-adm profile latency-performance

# Проверка, что CPU governor изменился
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# → performance

# Если нужно откатить изменения bootloader — редактируем GRUB вручную
# и перезагружаемся. TuneD не откатывает cmdline автоматически.
```

### 8. Интеграция с Ansible и GitOps

В инфраструктуре как код конфигурации TuneD должны храниться в репозитории и развертываться через CI/CD.

```yaml
# tasks/tuned.yml
- name: Deploy custom tuned profile
  copy:
    src: tuned/profiles/postgres-server/
    dest: /etc/tuned/postgres-server/
    owner: root
    group: root
    mode: '0644'

- name: Activate postgres-server profile
  command: tuned-adm profile postgres-server
  register: tuned_result
  changed_when: "'already active' not in tuned_result.stdout"

- name: Verify tuned profile
  command: tuned-adm verify
  register: tuned_verify
  changed_when: false
  failed_when: tuned_verify.rc != 0
```

```bash
# В Dockerfile для контейнеров с приложениями (bare-metal хост)
# TuneD управляется на хосте, но контейнер должен знать о governor
LABEL tuned.governor="performance"
```

### 9. Профиль для файлового сервера (NFS/SMB)

Файловые серверы требуют оптимизации сетевого стека и параметров файловой системы. TuneD управляет только частью этих параметров; остальные настраиваются через `sysctl` и `mount` опции.

```bash
sudo tee /etc/tuned/nfs-server/tuned.conf << 'EOF'
[main]
summary=NFS/SMB server with high throughput
include=throughput-performance

[sysctl]
# Увеличение размера таблицы хэшей для отслеживания соединений
net.netfilter.nf_conntrack_max = 1048576
# Увеличение лимитов файловых дескрипторов для Samba
fs.file-max = 2097152
# Swappiness минимальный — данные должны оставаться в page cache
vm.swappiness = 5
vm.dirty_ratio = 30
vm.dirty_background_ratio = 10

[net]
# Отключение энергосбережения на всех интерфейсах
devices=enp*
dynamic_tuning=0
EOF

sudo tuned-adm profile nfs-server
```

**Дополнительно (вне TuneD):**
```bash
# Опции монтирования NFS экспорта (на стороне сервера)
# /etc/exports
/srv/nfs *(rw,sync,no_root_squash,no_subtree_check)

# mount опции на клиенте
# /etc/fstab
nfs-server:/srv/nfs /mnt/nfs nfs defaults,_netdev,rsize=1048576,wsize=1048576,vers=4.2 0 0
```

### 10. Профиль для CI/CD раннера

CI/CD раннеры имеют burst-нагрузку: короткие периоды 100% загрузки CPU и I/O, чередующиеся с простоями. Цель — минимизировать время выполнения задач без перегрева.

```bash
sudo tee /etc/tuned/ci-runner/tuned.conf << 'EOF'
[main]
summary=CI/CD runner with burst performance
include=latency-performance

[sysctl]
# Очередь задач ядра — меньше задержек для коротких процессов
kernel.sched_wakeup_granularity_ns = 1500000
# Ограничение количества одновременно запущенных процессов CI
# (контролируется через systemd, здесь только swappiness)
vm.swappiness = 10

[script]
# Очистка кэша после завершения джобы (вызывается при переключении профиля)
# execute script only when leaving profile
exec=!/usr/local/bin/ci-cache-cleanup.sh

[cpu]
# Использование schedutil вместо performance — позволяет CPU спать между джобами
governor=schedutil
EOF

sudo tuned-adm profile ci-runner
```

**Скрипт очистки:**
```bash
#!/bin/bash
# /usr/local/bin/ci-cache-cleanup.sh
sync
echo 3 > /proc/sys/vm/drop_caches
```

## Взаимодействие и конфликты

| Инструмент | Характер взаимодействия | Рекомендация |
| :--- | :--- | :--- |
| **sysctl.d** | Прямой конфликт. | Настройки из `/etc/sysctl.conf` и `/etc/sysctl.d/` имеют высший приоритет. TuneD не сможет их переопределить. |
| **TLP** | Полный дубликат функций. | Не использовать одновременно. TuneD предпочтительнее для серверов, TLP — для старых ноутбуков. |
| **PPD** | Сосуществование. | На современных дистрибутивах (Fedora 41+) TuneD выступает бэкендом для PPD через пакет `tuned-ppd`. |
| **GRUB** | Интеграция. | TuneD правит `/etc/default/grub` через плагин `bootloader`. Всегда делайте бэкап GRUB перед использованием этого плагина. |

---

## Поиск и устранение неисправностей

### Типичные ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `tuned-adm verify` выдает ошибку | Конфликт с ручными настройками sysctl. | Удалите настройки из `/etc/sysctl.d/` или добавьте их в профиль TuneD. |
| Профиль не меняется после `tuned-adm profile` | Ошибка в синтаксисе `tuned.conf` или скрипте плагина. | Проверьте логи: `journalctl -u tuned`. |
| Параметры `bootloader` не применились | Система не была перезагружена. | Выполните `reboot`. Проверьте `/proc/cmdline`. |
| Высокое потребление CPU самим демоном | Включен слишком агрессивный `dynamic_tuning`. | Установите `dynamic_tuning=0` в `[main]` секции профиля. |
| Плагин `net` не применяет настройки к VLAN/bond | Плагин работает только с базовыми физическими интерфейсами. | Используйте `script` плагин для вызова `ethtool` на slave-интерфейсах. |
| CPU frequency не меняется | Драйвер `intel_pstate` заблокирован в `active` режиме, или HWP не поддерживается. | Проверьте `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver`. При необходимости используйте `intel_pstate=passive` в kernel cmdline. |
| Изменения sysctl не сохраняются после перезагрузки | Плагин `sysctl` применяет только runtime-значения. Для persistence используйте `/etc/sysctl.d/99-tuned.conf` или включите `[sysctl]` секцию в профиль с параметрами. | Добавьте параметры в `[sysctl]` секцию профиля. |
| TuneD игнорирует настройки диска | Устройство смонтировано, используется LVM или multipath. | Примените настройки через `udev` правила или `script` плагин до монтирования. |

### Методология отладки

1. **Проверка состояния демона:**
```bash
systemctl status tuned
journalctl -u tuned --since "1 hour ago"
# → ищите ошибки плагинов, синтаксические ошибки в tuned.conf
```

2. **Пошаговая диагностика плагина:**
```bash
# Включите отладочный режим (временно)
export TUNED_DEBUG=1
sudo tuned-adm profile throughput-performance

# Проверьте, какие параметры действительно применились
sysctl -a | grep -E "vm\.|kernel\.|net\.|fs\."
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
cat /sys/block/sd*/queue/scheduler
ethtool -k eth0
```

3. **Изоляция конфликтующих компонентов:**
```bash
# Отключите другие демоны управления питанием
sudo systemctl mask power-profiles-daemon
sudo systemctl mask tlp

# Очистите ручные настройки sysctl
sudo rm -f /etc/sysctl.d/99-custom.conf
sudo sysctl --system
```

4. **Проверка Vigilant Mode:**
```bash
# Если Vigilant Mode не работает — проверьте его статус
tuned-adm verify
# Или в логах:
journalctl -u tuned | grep -i vigilant
```

### Граничные случаи и ограничения

- **LVM/multipath:** Плагин `disk` пропускает устройства под управлением LVM или multipath. Настройки планировщика нужно применять через `udev` на базовые устройства (`/dev/sdX`) до создания VG.
- **Дублирующиеся серийные номера:** Для USB-накопителей с одинаковым серийным номером TuneD может применить настройки к неправильному устройству. Используйте `by-id` путь или WWN.
- **Горячее подключение:** TuneD не реагирует на hotplug автоматически. После добавления нового диска/интерфейса перезапустите профиль: `tuned-adm profile <name>`.
- **Виртуальные машины:** В гостевых ОС профиль `virtual-guest` обычно оптимален. Не пытайтесь настроить host-level параметры (Uncore, ALPM) внутри ВМ — они либо не работают, либо вредят.
- **Два CPU с разной топологией:** Если NUMA-узлы имеют разное количество ядер, параметр `isolated_cores` нужно указывать аккуратно, чтобы не изолировать ядра на одном узле, оставив другой не изолированным.

## Лучшие практики

### Change Management

1. **Тестируйте профили в staging перед production.** Используйте `tuned-adm verify` и `tuned-adm active` для валидации.
2. **Версионируйте профили.** Храните кастомные профили в Git с понятными именами: `prod-db-postgres-01`, `web-frontend-03`.
3. **Документируйте отклонения.** Если базовый профиль переопределяет параметры, добавьте комментарии в `tuned.conf` с ссылкой на тикет или причину.
4. **Используйте `include` вместо копирования.** Всегда наследуйтесь от системных профилей (`throughput-performance`, `latency-performance`), чтобы получать обновления при обновлении пакета tuned.

### Безопасность и аудит

- **Не храните секреты в `script` плагинах.** Если скрипт требует пароли или ключи, используйте файлы с ограниченными правами (`600`) и SELinux/AppArmor контексты.
- **Аудит изменений.** Включите логирование journald с ротацией, чтобы отслеживать смену профилей:
```ini
# /etc/systemd/journald.conf
SystemMaxUse=1G
MaxRetentionSec=30day
```
- **Ограничьте `tuned-adm` через sudoers.** На production-серверах только указанные пользователи или automation-сервис должны иметь право смены профиля:
```
# /etc/sudoers.d/tuned
%ops ALL=(ALL) NOPASSWD: /usr/sbin/tuned-adm profile *
```

### Мониторинг и оповещения

Интегрируйте TuneD в вашу систему мониторинга. Ниже — пример Prometheus exporter:

```bash
#!/bin/bash
# /usr/local/bin/tuned_exporter.sh
PROFILE=$(tuned-adm active | awk '{print $NF}')
VERIFY=$(tuned-adm verify 2>&1)
if [[ $VERIFY == *"succeeded"* ]]; then STATUS=0; else STATUS=1; fi

cat <<EOF
# HELP tuned_active_profile Current active tuned profile
# TYPE tuned_active_profile gauge
tuned_active_profile{profile="$PROFILE"} 1

# HELP tuned_verify_status Verification status (0=ok, 1=fail)
# TYPE tuned_verify_status gauge
tuned_verify_status $STATUS
EOF
```

Или используйте готовые экспортеры: `tuned-exporter` (Go), node_exporter с системными метриками.

**Алерты:**
- `tuned_verify_status == 1` — профиль применен с ошибками, требуется вмешательство.
- Изменение `tuned_active_profile` без Change Managment тикета.
- `governor` не совпадает с ожидаемым для активного профиля.

---

## Дополнительная информация

### Связанные темы

- **[Настройка параметров ядра (sysctl)](./kernel/sysctl.md)** — база, на которой работает TuneD.
- **[Оптимизация памяти (Memory Tuning)](./memory/performance_tuning.md)** — детальная настройка RAM.
- **[Оптимизация файловых систем](../FileSystems/performance_tuning.md)** — подробнее о планировщиках I/O.
- **[Привязка процессов (CPU Pinning)](./cpu_pinning.md)** — ручной контроль ядер (альтернатива `cpu-partitioning`).
- **[Обзор Systemd](./systemd/overview.md)** — управление жизненным циклом демона.
