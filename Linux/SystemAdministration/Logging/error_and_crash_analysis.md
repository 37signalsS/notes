# Анализ ошибок и сбоев (Error and Crash Analysis)

## Определения

**Анализ сбоев (Crash Analysis)** — процесс систематической диагностики причин аварийного завершения программного обеспечения или операционной системы. В отличие от стандартного мониторинга, фокус здесь смещен на **Root Cause Analysis (RCA)** критических инцидентов, приводящих к остановке процессов (`SIGSEGV`, `SIGABRT`) или краху всей системы (**Kernel Panic**).

**Классификация критических сбоев:**

| Тип инцидента | Проявление | Механизм фиксации | Основной документ |
| :--- | :--- | :--- | :--- |
| **Application Crash** | Остановка процесса (Segmentation Fault) | Coredump (дамп памяти) | [Отладка через Coredump](../../Core/processes/Troubleshooting/debugging.md) |
| **OOM (Out Of Memory)** | Процесс «исчезает» (убит ядром) | Системный лог (dmesg) | [Механизм OOM Killer](../../Core/processes/oom_killer_mechanism.md) |
| **Kernel Panic** | Система зависает или перезагружается | kdump (vmcore), pstore | [Паника ядра](../../Core/kernel/kernel_panic.md) |
| **Container Crash** | Состояние `CrashLoopBackOff` в K8s | `kubectl logs --previous` | [Диагностика CrashLoopBackOff](../../../Kubernetes/Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) |
| **Watchdog Reset** | Мгновенная перезагрузка без логов | IPMI SEL, Hardware Logs | [Диагностика перезагрузки](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) |

**Сигналы падения (Crash Signals):** Стандартные сигналы, генерирующие core dump: `SIGSEGV` (обращение к неверному адресу памяти), `SIGABRT` (аварийный abort из приложения), `SIGBUS` (невыравненный доступ или физическая ошибка), `SIGFPE` (деление на ноль, переполнение), `SIGILL` (недопустимая машинная инструкция), `SIGTRAP` (точка останова отладчика). Ядро создает дамп только для сигналов с действием `Core`.

**Дамп памяти (Core Dump):** Снимок адресного пространства процесса в момент аварии. По умолчанию использует формат ELF: сегмент `PT_NOTE` хранит метаданные (регистры, PID, сигнал), сегменты `PT_LOAD` — копии страниц памяти. В systemd-средах обработка делегируется `systemd-coredump`.

**CoredumpFilter:** Битовый массив в `/proc/<PID>/coredump_filter`, управляющий, какие сегменты памяти попадают в дамп. Значение по умолчанию `0x33` включает анонимные приватные страницы и их файловые отображения. Полный дамп (`0xFF`) может быть в несколько раз больше размера RSS процесса.

**vmcore:** Полный дамп оперативной памяти всей системы, создаваемый `kdump`. Содержит состояние всех процессов, ядра, аппаратных регистров и буферов устройств. Для анализа требуется утилита `crash` и нестриpped `vmlinux` или пакет `kernel-debuginfo`.

**pstore / Ramoops:** Механизм сохранения логов ядра (`dmesg`) в энергонезависимую память (NVRAM, EFI переменные или зарезервированная RAM). Доступен после перезагрузки через `/sys/fs/pstore/`. Критичен, если диск был недоступен в момент Kernel Panic.

**kdump / kexec:** `kdump` — механизм захвата дампа при панике. Использует `kexec` для загрузки «аварийного» ядра напрямую из памяти текущего, минуя POST/BIOS. Требует резервирования RAM через параметр `crashkernel=` в загрузчике.

**ABRT / Apport:** Системы автоматического сбора дампов и отправки баг-репортов. ABRT — стандарт для RHEL/Fedora, Apport — для Debian/Ubuntu. Оба используют pipe-обработчики для перехвата дампов.

## Базовые концепции

### Сбои в пользовательском пространстве (User Space)

Возникают при нарушении логики работы с памятью или явном вызове `abort()`. Современным стандартом сбора данных является **`systemd-coredump`**.

1.  **Автоматизация:** При крахе ядро передает управление обработчику `systemd-coredump`, который сжимает дамп и сохраняет его в `/var/lib/systemd/coredump/`.
2.  **Метаданные:** В журнал `journald` записываются расширенные данные: регистры процессора, список загруженных библиотек и базовая трассировка стека.
3.  **Доступ:** Инструмент `coredumpctl` позволяет мгновенно найти нужный сбой без ручного поиска файлов.

**Жизненный цикл дампа в systemd-coredump:**
1.  Процесс получает сигнал с действием Core (`SIGSEGV`, `SIGABRT` и др.).
2.  Ядро проверяет `RLIMIT_CORE` (`ulimit -c`) и флаг `dumpable` процесса.
3.  Если `/proc/sys/kernel/core_pattern` указывает на `|/usr/lib/systemd/systemd-coredump`, ядро передает дамп через pipe.
4.  `systemd-coredump` сжимает дамп (zstd по умолчанию), сохраняет в `/var/lib/systemd/coredump/` или внешнее хранилище.
5.  В journald создается структурированная запись с полями: `MESSAGE=Coredump`, `COREDUMP_PID`, `COREDUMP_UID`, `COREDUMP_SIGNAL`, `COREDUMP_EXE`.

**Управление `coredump_filter` через systemd:**
```ini
# /etc/systemd/system/critical-service.service.d/coredump.conf
[Service]
CoredumpFilter=0xFF
```
Значение `0xFF` включает все сегменты памяти (анонимные, файловые отображения, shared memory, ELF-заголовки). Используйте для глубокой отладки, но учитывайте размер дампа.

### Сбои на уровне ядра (Kernel Space)

Любой критический баг в драйвере или модуле ядра приводит к немедленной остановке системы (**Kernel Panic**).

*   **Механизм kdump:** Резервирует часть RAM для «аварийного» ядра, которое сохраняет состояние упавшей системы в файл `vmcore` на диск.
*   **Механизм pstore (Ramoops):** Позволяет сохранять последние сообщения `dmesg` в специальной области памяти, которая не очищается при мягкой перезагрузке. Это критично, если диск был недоступен в момент сбоя.

**Детализация жизненного цикла паники:**
1.  Вызов `panic()` в `kernel/panic.c` останавливает планировщик и прерывания.
2.  Выполняются колбэки из `panic_notifier_list` (IPMI, гашение дисков, отключение StorPort).
3.  Если включен `ramoops`, `log_buf` копируется в зарезервированную RAM.
4.  Если kdump активен, `crash_kexec()` переключается в аварийное ядро.
5.  По умолчанию: halt или перезагрузка через `kernel.panic` секунд.

**Требования к kdump:**
- Резервирование RAM через `crashkernel=256M` (или больше для production) в параметрах загрузчика.
- Отдельный initramfs для kdump (`mkinitrd -kdump` на RHEL, `mkinitcpio -k` на Arch).
- Свободное место на диске или сетевом хранилище для vmcore. Размер обычно равен размеру RAM, но `makedumpfile` сжимает до 10–30%.

### Ошибки нехватки памяти (OOM)

Важно различать два типа OOM:
*   **System OOM:** Исчерпана вся физическая память сервера.
*   **Memcg OOM (Cgroup/Container):** Процесс превысил лимит контейнера (например, в Kubernetes). В логах dmesg ищите строку `oom-kill:constraint=CONSTRAINT_MEMCG`.

**Механизм выбора жертвы OOM Killer:**
Ядро вычисляет `oom_score` для каждого процесса на основе его потребления памяти и `oom_score_adj`. Процесс с наивысшим `oom_score` убивается первым. Это эвристический алгоритм, поэтому критичные сервисы требуют ручной корректировки.

**Защита критических сервисов:**
```bash
# Ручная установка oom_score_adj (требует root)
echo -1000 > /proc/<PID>/oom_score_adj

# Через systemd unit (предпочтительно)
# /etc/systemd/system/sshd.service.d/oom.conf
[Service]
OOMScoreAdjust=-1000
```

## Практические сценарии

### Алгоритм первичной диагностики (RCA)

Если сервер внезапно перезагрузился или «пропал» критический процесс:

1.  **Проверка триггера OOM:**
    ```bash
    # Поиск в journald текущей сессии
    journalctl -k -g "Out of memory"

    # Поиск в предыдущей сессии (если система перезагрузилась)
    journalctl -b -1 -k -g "Out of memory"
    ```
2.  **Поиск дампов пользовательских процессов:**
    ```bash
    # Список всех дампов
    coredumpctl list

    # Фильтрация по бинарнику
    coredumpctl list /usr/bin/nginx

    # Информация о последнем дампе
    coredumpctl info
    ```
3.  **Проверка факта Kernel Panic (kdump):**
    ```bash
    ls -R /var/crash/
    # → /var/crash/2026-09-14-12:00:00/vmcore

    # Проверка размера (должен быть близок к размеру RAM)
    du -sh /var/crash/*
    ```
4.  **Чтение «посмертных» логов (pstore):**
    ```bash
    # Монтирование pstore (не требует корневой ФС)
    mount -t pstore pstore /sys/fs/pstore 2>/dev/null || true

    # Просмотр dmesg ramoops
    cat /sys/fs/pstore/dmesg-ramoops-0 2>/dev/null || echo "Ramoops пуст"
    ```
5.  **Анализ логов предыдущей сессии:**
    ```bash
    # Все ошибки предыдущего boot
    journalctl -p err -b -1

    # Только критические события
    journalctl -b -1 -p crit
    ```

### Настройка systemd-coredump для production

```bash
# /etc/systemd/coredump.conf
[Coredump]
Storage=external
Compress=yes
ProcessSizeMax=2G
ExternalSizeMax=10G
JournalSizeMax=200M
MaxUse=50G
KeepFree=20G

# Применение конфигурации
systemctl daemon-reload

# Проверка параметров
coredumpctl info
```

**Важные замечания:**
- `Storage=external` сохраняет дампы отдельно от journald, предотвращая разрастание журнала.
- `ProcessSizeMax` ограничивает размер одного дампа (защита от зомби-процессов с гигантской памятью).
- `MaxUse`/`KeepFree` управляют квотой на диске. Настройте под размер вашего хранилища.
- Дампы по умолчанию сжимаются через zstd. Для совместимости можно использовать `Compress=xz` (лучшее сжатие, выше CPU).

### Настройка kdump

```bash
# RHEL/CentOS/Fedora
# /etc/sysconfig/kdump
KDUMP_COREDIR="/var/crash"
KDUMP_KERNELVER="$(uname -r)"
KDUMP_CMD_LINE_ROOT="root=/dev/sda1 rootfstype=ext4"
KDUMP_CMD_LINE_APPEND="irqpoll nr_cpus=1 reset_devices"

# Включение и запуск
systemctl enable --now kdump

# Проверка статуса
systemctl status kdump
kdumpctl status
```

**Сетевой сбор vmcore (если локальный диск мал):**
```bash
# /etc/kdump.conf
path /var/crash
core_collector makedumpfile -l --message-level 1 -d 31 -c
# Для NFS:
# path nfs://backup-server/export/crash
```

**Тестирование kdump (осторожно в production):**
```bash
# Эмуляция паники (система перезагрузится)
echo c > /proc/sysrq-trigger

# Или тест без перезагрузки (RHEL 8+)
kdumpctl test
```

### Настройка pstore/ramoops

```bash
# Создать конфигурацию модуля
echo "options ramoops mem_size=0x200000 mem_address=0x20000000" > /etc/modprobe.d/ramoops.conf

# Перезагрузить модуль (если не используется в initramfs)
modprobe -r ramoops 2>/dev/null || true
modprobe ramoops

# Или через boot параметр GRUB
# GRUB_CMDLINE_LINUX="... ramoops.mem_size=0x200000 ramoops.mem_address=0x20000000"
```

**Проверка:**
```bash
# Размер зарезервированной области
cat /sys/module/ramoops/parameters/mem_size
# → 2097152 (2 MB)

# Доступные записи
ls -la /sys/fs/pstore/
# → dmesg-ramoops-0  dmesg-ramoops-1
```

### Анализ краха приложения в контейнере (Kubernetes)

```bash
# 1. Посмотреть логи предыдущей инстанции упавшего пода
kubectl logs <pod_name> --previous --tail=100

# 2. Проверить причину завершения
kubectl get pod <pod_name> -o jsonpath='{.status.containerStatuses[0].state.terminated.reason}'
# → OOMKilled / Error / Completed

# 3. Проверить лимиты памяти
kubectl describe pod <pod_name> | grep -A5 "Limits\|Requests"

# 4. Для глубокой диагностики: ephemeral container
kubectl debug -it <pod_name> --image=ubuntu --target=<container_name> -- bash
```

### Интеграция crash-данных в centralized logging

Для SRE важно иметь единый поток crash-событий в центральный лог-менеджер:

```bash
# /etc/systemd/journald.conf
[Journal]
Storage=persistent
ForwardToSyslog=yes
ForwardToWall=yes
MaxRetentionSec=30day

# В rsyslog: импорт journald crash events
# /etc/rsyslog.d/crash-events.conf
if $programname == "systemd-coredump" then {
    action(type="omfwd" target="log-collector" port="514" protocol="tcp")
    stop
}
```

**Structured logging для crash events:**
- Используйте `JSON=yes` в journald для машинночитаемых записей.
- В Loki/Grafana создайте правила алертинга на `MESSAGE="Coredump"` или `oom-kill`.
- В Elasticsearch настройте ingest pipeline для обогащения crash-записей тегами окружения.

### Мониторинг и алертинг

```promql
# Алерт на новые coredumps (через Loki LogQL)
count_over_time({job="journald"} |= "Coredump" [5m]) > 0

# Алерт на OOM Kill
count_over_time({job="journald"} |= "oom-kill" [5m]) > 0

# Алерт на активацию kdump (через journald или dmesg)
count_over_time({job="journald"} |= "kdump" [5m]) > 0

# OOMKilled поды в Kubernetes (Prometheus)
kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0
```

**Рекомендуемые дашборды:**
- Количество coredumps по сервисам (поле `COREDUMP_EXE`).
- OOM Kill rate по хостам.
- MTBF (Mean Time Between Failures) для Kernel Panic.
- Распределение сигналов (`SIGSEGV` vs `SIGABRT` vs `SIGBUS`).

### Пост-мортем процесс

```yaml
# Шаблон пост-мортем отчета
title: "Post-Mortem: <Инцидент>"
date: "2026-09-14"
severity: SEV-1 | SEV-2 | SEV-3
incident_id: "INC-2026-001"

## Timeline
- HH:MM — Обнаружение (алерт/мониторинг)
- HH:MM — Начало диагностики
- HH:MM — Root Cause Identified
- HH:MM — Восстановление (Service Restored)
- HH:MM — Полное восстановление (All Clear)

## Root Cause
- Краткое описание первопричины.
- Ссылка на coredump/vmcore/logs.

## Impact
- Затронутые сервисы/хосты.
- Длительность простоя (MTTD + MTTR).
- Данные: потеряны/не затронуты.

## Action Items
| Действие | Ответственный | Дедлайн | Статус |
|----------|--------------|---------|--------|
| Исправить конфигурацию OOM | @user | 2026-09-21 | Open |
| Включить kdump на всех хостах | @user | 2026-09-28 | Open |
| Добавить алерт на coredumps | @user | 2026-09-21 | Open |
```

**Blameless Post-Mortem принципы:**
- Фокус на системных проблемах, а не на людях.
- Документируйте все инциденты SEV-1/SEV-2.
- Срок публикации отчета: 48 часов после инцидента.
- Review action items на следующей инженерной встрече.

### Сценарий: Защита критических сервисов от OOM

```bash
# Защита системных сервисов через OOMScoreAdjust
for service in sshd cron containerd kubelet; do
    mkdir -p /etc/systemd/system/${service}.service.d/
    cat > /etc/systemd/system/${service}.service.d/oom.conf <<EOF
[Service]
OOMScoreAdjust=-1000
EOF
done

systemctl daemon-reload
systemctl restart sshd cron containerd kubelet

# Проверка
systemctl show sshd -p OOMScoreAdjust
# → OOMScoreAdjust=-1000
```

**Для контейнеров в Kubernetes:**
```yaml
# Защита через QoS Guaranteed (requests == limits)
apiVersion: v1
kind: Pod
metadata:
  name: critical-db
  namespace: production
spec:
  containers:
  - name: postgres
    image: postgres:16
    resources:
      requests:
        memory: "4Gi"
        cpu: "2"
      limits:
        memory: "4Gi"
        cpu: "2"
  priorityClassName: system-cluster-critical
```

## Устранение неполадок

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `coredumpctl list` пуст | Процесс падает, но дампов нет | `Storage=none` в `coredump.conf` или `LimitCORE=0` | Проверить `/etc/systemd/coredump.conf`, `systemctl show <service> -p LimitCORE` |
| Дамп создан, но `coredumpctl info` не работает | `coredumpctl: не найден` | Дамп записан в файл, а не в systemd-coredump | Проверить `/proc/sys/kernel/core_pattern`, переключить на `|/usr/lib/systemd/systemd-coredump` |
| `crash: compressed kdump not supported` | Ошибка при открытии vmcore | `makedumpfile` создал сжатый дамп без поддержки | Пересоздать дамп с `makedumpfile -F` или использовать `makedumpfile -R vmcore < /proc/vmcore` |
| kdump не создает vmcore | Паника, но `/var/crash` пуст | Недостаточно памяти для kdump, `crashkernel` не указан | Проверить `dmesg \| grep -i crash`, `kdumpctl status`, добавить `crashkernel=256M` в GRUB |
| pstore пуст после перезагрузки | `/sys/fs/pstore/` пуст | `ramoops` не загружен или `mem_size=0` | Проверить `lsmod \| grep ramoops`, `cat /sys/module/ramoops/parameters/mem_size` |
| OOM Kill без записи в dmesg | Silent OOM (cgroup v2) | `memory.oom.group=1` не установлен | Добавить `--cgroup-conf=memory.oom.group=1` в Docker или `oomGroup: true` в K8s |
| Container OOMKilled, но лимиты не превышены | OOM на уровне узла | Node-pressure eviction | Проверить `kubectl describe node`, `kubectl top nodes`, `kubectl get events --field-selector reason=OOMKilling` |
| Kernel Panic при загрузке модуля | `BUG: unable to handle kernel NULL pointer` | Драйвер с багом, Tainted ядро | Проверить `cat /proc/sys/kernel/tainted`, откатить модуль, включить kdump |
| `coredumpctl debug` падает | `gdb: fatal error: Unable to open ...` | Отсутствуют символы (`vmlinux` или debuginfo) | Установить `kernel-debuginfo`, `glibc-debuginfo`, `systemd-debuginfo` |
| Дамп огромного размера (несколько GB) | `ProcessSizeMax` превышен, диск заполняется | `CoredumpFilter=0xFF` на прожорливом процессе | Установить `ProcessSizeMax` в `coredump.conf`, настроить `CoredumpFilter=0x33` |
| vmcore поврежден / неполный | `crash` падает с ошибкой чтения | Диск переполнен во время записи, сбой NFS | Настроить `MaxUse`/`KeepFree`, использовать локальный диск для kdump |

## Рекомендации

### На production-хостах
1.  **Всегда включайте kdump** и тестируйте его раз в квартал. Включите `kdumpctl test` в维护窗口.
2.  **Настройте systemd-coredump** с внешним хранилищем и лимитами (`ProcessSizeMax`, `MaxUse`). Мониторьте заполнение диска.
3.  **Установите `OOMScoreAdjust=-1000`** для критических сервисов (sshd, monitoring agents, database proxies).
4.  **Используйте `makedumpfile`** для сжатия vmcore (снижает время записи и размер в 5–10 раз).
5.  **Настройте pstore/ramoops** как запасной вариант, если kdump не сработал из-за нехватки памяти или проблем с диском.
6.  **Интегрируйте crash-события в centralized logging** (journald → rsyslog → Loki/ELK). Это позволяет искать паттерны падений через весь кластер.
7.  **Создавайте алерты** на новые coredumps, OOM Kill и активацию kdump.
8.  **Ведите пост-мортем** для каждого SEV-1/SEV-2 инцидента. Используйте шаблон выше.

### Для Kubernetes
1.  Используйте `priorityClassName: system-cluster-critical` для системных подов (coredns, kube-proxy).
2.  Настройте `requests == limits` для памяти в production (QoS Guaranteed).
3.  Используйте `LimitRange` и `ResourceQuota` для защиты namespace от OOM.
4.  Мониторьте `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`.

### Для Bare Metal и Виртуализации
1.  Настройте IPMI / iDRAC / iLO для автоматического захвата SEL (Hardware Logs) при Watchdog Reset.
2.  Используйте EFI persistent storage для pstore вместо RAM, если firmware поддерживает.
3.  Настройте netconsole для отправки dmesg по сети при Kernel Panic (когда kdump недоступен).

## Матрица инструментов

| Задача | Инструмент | Уровень | Примечание |
| :--- | :--- | :--- | :--- |
| Поиск coredump | `coredumpctl` | User Space | Требует systemd-coredump |
| Генерация дампа live-процесса | `gcore` (GDB) | User Space | Ptrace, требует root или того же UID |
| Пакетный анализ стека | `gdb -batch` | User Space | Для CI/CD пайплайнов |
| Анализ vmcore | `crash` | Kernel Space | Требует vmlinux или kernel-debuginfo |
| Сжатие vmcore | `makedumpfile` | Kernel Space | Рекомендуется для production |
| Восстановление логов | `pstore / ramoops` | Kernel Space | Работает без корневой ФС |
| Анализ OOM | `dmesg`, `journalctl`, `/proc/<PID>/oom_score` | Ядро / Контейнеры | |
| Анализ lockup | `bpftrace`, `perf` | Ядро | Для Soft/Hard Lockup |
| Автоотчеты | `ABRT`, `Apport` | User Space | RHEL vs Debian/Ubuntu |
| Анализ дампов через journald | `journalctl -u systemd-coredump` | User Space | Structured logging |
| Анализ coredump в Kubernetes | `kubectl logs --previous` | K8s API | Требует previous=true в pod spec |

### Интеграция логов с метриками (Logs-to-Metrics)

**Logs-to-Metrics** — преобразование логовых событий в числовые метрики для дашбордов и алертинга в Prometheus/Grafana. Позволяет строить графики на основе событий (количество ошибок, латентность из access-логов, распределение сигналов).

| Инструмент | Механизм | Пример |
|:---|:---|:---|
| **Vector** | `log_to_metric` transform | `counter`/`histogram`/`gauge` из полей лога |
| **Promtail** | `metrics` pipeline stage | `count` по label |
| **Loki** | Recording rules (LogQL) | `sum(rate(...))` → метрика |
| **Fluent Bit** | `metrics` filter | `counter`/`gauge` |

**Vector: logs-to-metrics:**

```yaml
transforms:
  # Счетчик ошибок по сервисам
  error_count:
    type: log_to_metric
    inputs: [app_logs]
    metrics:
      - field: message
        name: app_errors_total
        type: counter
        tags:
          service: .service
          level: .level
          host: .host

  # Латентность из access-логов (nginx)
  request_duration:
    type: log_to_metric
    inputs: [nginx_access]
    metrics:
      - field: request_time
        name: http_request_duration_seconds
        type: histogram
        buckets: [0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
        tags:
          method: .method
          status: .status
          path: .path

  # Количество OOM Kill событий
  oom_kill_count:
    type: log_to_metric
    inputs: [dmesg_errors]
    metrics:
      - field: message
        name: kernel_oom_kills_total
        type: counter
        tags:
          host: .host
```

**Loki: recording rules для метрик из логов:**

```yaml
# recording_rules.yaml
groups:
  - name: logs_as_metrics
    interval: 15s
    rules:
      # Количество ошибок по сервисам (за 5 минут)
      - record: app:errors:rate5m
        expr: |
          sum by (service) (
            rate({job="app"} | json | level="error" [5m])
          )

      # Количество HTTP 5xx ответов
      - record: http:errors_5xx:rate5m
        expr: |
          sum by (service, method, path) (
            rate({job="nginx"} | json | status >= 500 [5m])
          )

      # Количество OOM Kill
      - record: kernel:oom_kills:total
        expr: |
          sum(count_over_time({job="dmesg"} |~ "oom-kill" [1h]))
```

**Применение метрик из логов:**

```promql
# Dashboard: Errors per second (из логов)
app:errors:rate5m

# Alert: Error rate > 1% от общего трафика
app:errors:rate5m / (app:errors:rate5m + http:requests:rate5m) > 0.01

# Dashboard: OOM Kill trend
kernel:oom_kills:total

# Dashboard: P99 latency из access-логов
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
```

**Корреляция логов и метрик в Grafana:**

1. **Dashboard: Логи + Метрики** — два panel рядом: график метрики (Prometheus) + table логов (Loki)
2. **Anomaly detection** — spike на графике → клик → фильтр по времени в Loki
3. **Rich annotations** — аннотации на графиках из логовых событий (deploy, crash, OOM)

**Пример dashboard layout:**

```
┌─────────────────────────────────────────────┐
│ Request Rate (from access logs)             │
│ ████████████████████░░░░░ 200 req/s         │
├─────────────────────────────────────────────┤
│ Error Rate (from error logs)                │
│ ███░░░░░░░░░░░░░░░░░░░░░ 5 err/s  ← spike │
├─────────────────────────────────────────────┤
│ Recent Errors (Loki query)                  │
│ 10:23 ERROR connection_timeout service=api  │
│ 10:23 ERROR nil_pointer service=worker      │
│ 10:22 ERROR timeout service=payment         │
└─────────────────────────────────────────────┘
```

## См. также
- [**Обзор системы логирования**](./logging_overview.md) — архитектура сбора и централизация логов.
- [**Диагностика OOM Killer**](../../Core/processes/oom_killer_mechanism.md) — механизм выбора жертвы и управление `oom_score_adj`.
- [**Паника ядра: механизмы и анализ**](../../Core/kernel/kernel_panic.md) — kdump, pstore, утилита `crash`.
- [**Структурированное логирование**](./structured_logging.md) — JSON-формат для logs-to-metrics.
- [**Vector: log_to_metric**](../../../Vector/vector_overview.md) — трансформации VRL.
