# Определения

**Мониторинг сетевых монтирований (Network Mount Monitoring)** — комплексный подход к контролю доступности, производительности и целостности файловых систем, смонтированных по сети (NFS, CIFS/SMB, iSCSI). Включает проверку здоровья точек монтирования, обнаружение зависших (stale) монтирований, алертинг и восстановление.

Отличается от мониторинга NFS/CIFS на стороне сервера ([nfs_monitoring.md](../../../Networking/Services/nfs/nfs_monitoring.md), [samba_monitoring.md](../../../Networking/Services/samba/samba_monitoring.md)): фокусируется на клиентской стороне — доступности точек монтирования и их влиянии на приложения.

# Основные концепции

## Проблемы сетевых монтирований

| Проблема | Симптомы | Причины | Влияние |
| :--- | :--- | :--- | :--- |
| **Stale mount** | `Stale file handle`, `ls` зависает, приложения получают I/O ошибки | Сервер перезапущен, экспорт изменён, переименование каталога на сервере | Полная потеря доступа к данным |
| **Hang (зависание)** | Процессы в состоянии `D` (uninterruptible sleep), `iowait` растёт | Сервер недоступен, сеть потеряна, NFS с опцией `hard` | Блокировка всех процессов, обращающихся к ФС |
| **Performance degradation** | Медленный `ls`, высокий latency операций | Перегрузка сервера, медленная сеть, мелкие `rsize/wsize` | Замедление приложений |
| **Capacity exhaustion** | `No space left on device`, но `df` показывает место | Переполнение на сервере, quota, лимиты | Невозможность записи |
| **Permission denied** | `Permission denied` при обращении к ранее доступным файлам | Изменение ACL/прав на сервере, истечение Kerberos-тикета | Потеря доступа к данным |

## Классификация проверок

| Тип проверки | Периодичность | Инструменты | Критичность |
| :--- | :--- | :--- | :--- |
| **Existence** — существует ли точка монтирования | Непрерывно | `mountpoint -q`, `findmnt` | Критичная |
| **Accessibility** — доступна ли ФС для чтения/записи | Раз в 30–60 сек | `test -r`, `stat`, `df` | Критичная |
| **Freshness** — не является ли mount stale | Раз в 60 сек | `stat` на корень, `cat /proc/mounts` | Критичная |
| **Performance** — не превышен ли latency | Раз в 5 мин | `nfsiostat`, `smbstatus`, custom script | Средняя |
| **Capacity** — не заканчивается ли место | Раз в 5 мин | `df -h`, `node_filesystem_avail_bytes` | Высокая |

## Stale mount: механика

**Stale file handle** возникает, когда NFS-сервер удаляет или изменяет экспорт, а клиент продолжает использовать устаревший file handle. Ядро возвращает ошибку `ESTALE` (code 116).

```
Клиент                    Сервер
  │                          │
  ├── getattr(handle) ──────►│
  │◄── NFS OK ──────────────┤
  │                          │
  │          Сервер перезапускается / exportfs -ra
  │                          │
  ├── read(handle) ─────────►│
  │◄── ESTALE (handle not found) ─┤
  │                          │
  │  ФС помечена как stale   │
  │  Все операции = ESTALE   │
```

**Восстановление:** Повторное монтирование (`umount -l && mount`) или `exportfs -ra` на сервере.

# Практические сценарии

## 1. Health-check скрипт для сетевых монтирований

Идемпотентный скрипт, проверяющий все критичные точки монтирования:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Конфигурация: монтирования для проверки
# Формат: mount_point:expected_fstype:timeout_seconds
CHECKED_MOUNTS=(
    "/mnt/nfs_logs:nfs4:10"
    "/mnt/smb_backups:cifs:15"
    "/mnt/san_data:ext4:5"
)

# Счётчики
OK=0
FAIL=0
WARN=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok()   { echo -e "${GREEN}[OK]${NC}   $*"; ((OK++)); }
log_fail() { echo -e "${RED}[FAIL]${NC} $*"; ((FAIL++)); }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; ((WARN++)); }

for entry in "${CHECKED_MOUNTS[@]}"; do
    IFS=':' read -r mountpoint expected_fstype timeout <<< "$entry"

    # Проверка 1: Точка монтирования существует
    if [[ ! -d "$mountpoint" ]]; then
        log_fail "$mountpoint — директория не существует"
        continue
    fi

    # Проверка 2: ФС смонтирована
    if ! mountpoint -q "$mountpoint" 2>/dev/null; then
        log_fail "$mountpoint — не смонтировано"
        continue
    fi

    # Проверка 3: Тип ФС соответствует ожидаемому
    actual_fstype=$(findmnt -no FSTYPE "$mountpoint" 2>/dev/null || echo "unknown")
    if [[ "$actual_fstype" != "$expected_fstype" ]]; then
        log_warn "$mountpoint — тип $actual_fstype вместо $expected_fstype"
    fi

    # Проверка 4: ФС доступна (чтение/запись)
    if ! timeout "$timeout" stat "$mountpoint" >/dev/null 2>&1; then
        log_fail "$mountpoint — ФС недоступна (timeout ${timeout}s)"
        continue
    fi

    # Проверка 5: Доступно место (>10%)
    usage_pct=$(df --output=pcent "$mountpoint" 2>/dev/null | tail -1 | tr -d ' %')
    if [[ -n "$usage_pct" ]] && (( usage_pct >= 90 )); then
        log_warn "$mountpoint — использование ${usage_pct}% (критично)"
    elif [[ -n "$usage_pct" ]] && (( usage_pct >= 80 )); then
        log_warn "$mountpoint — использование ${usage_pct}% (внимание)"
    fi

    # Проверка 6: Нет ошибок в dmesg за последние 5 минут
    errors=$(dmesg --time-format iso 2>/dev/null | tail -100 | \
        grep -ciE "ESTALE|stale file handle|I/O error.*$(basename "$mountpoint")" || true)
    if (( errors > 0 )); then
        log_warn "$mountpoint — обнаружены ошибки в dmesg ($errors)"
    fi

    log_ok "$mountpoint — OK (fstype=$actual_fstype, usage=${usage_pct:-?}%)"
done

echo ""
echo "Итого: OK=$OK, FAIL=$FAIL, WARN=$WARN"

# Выходной код для мониторинга
if (( FAIL > 0 )); then
    exit 2  # CRITICAL
elif (( WARN > 0 )); then
    exit 1  # WARNING
else
    exit 0  # OK
fi
```

**Использование в cron:**
```bash
# Раз в минуту
* * * * * /usr/local/bin/check_mounts.sh >> /var/log/mount_health.log 2>&1
```

## 2. Обнаружение и восстановление stale NFS-монтирований

```bash
#!/usr/bin/env bash
set -euo pipefail

# Проверка всех NFS-монтирований на stale
NFS_MOUNTS=$(findmnt -t nfs4,nfs -no TARGET 2>/dev/null || true)

if [[ -z "$NFS_MOUNTS" ]]; then
    echo "NFS-монтирования не найдены"
    exit 0
fi

for mp in $NFS_MOUNTS; do
    # Попытка доступа к корню точки монтирования
    if ! timeout 5 stat "$mp" >/dev/null 2>&1; then
        echo "WARN: $mp — potential stale mount"

        # Проверка через /proc/mounts (без обращения к ФС)
        source=$(findmnt -no SOURCE "$mp" 2>/dev/null || echo "unknown")

        # Проверка, что сервер доступен
        server=$(echo "$source" | cut -d: -f1)
        if ! ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
            echo "  → Сервер $server недоступен. Ожидание..."
            # Не размонтируем — сервер может вернуться
            continue
        fi

        # Сервер доступен, но stale — повторное монтирование
        echo "  → Сервер доступен. Повторное монтирование..."
        umount -l "$mp" 2>/dev/null || true
        sleep 2

        # Попытка монтирования из fstab
        if mount "$mp" 2>/dev/null; then
            echo "  → Восстановлено: $mp"
        else
            echo "  → ОШИБКА: Не удалось восстановить $mp"
        fi
    fi
done
```

## 3. Мониторинг через findmnt и Prometheus node_exporter

### Быстрая проверка всех точек монтирования

```bash
# Все смонтированные сетевые ФС с опциями и состоянием
findmnt -t nfs4,nfs,cifs -o TARGET,SOURCE,FSTYPE,OPTIONS,PROPAGATION

# Пример вывода:
# TARGET          SOURCE                      FSTYPE OPTIONS
# /mnt/nfs_logs   nas01:/exports/logs         nfs4   rw,relatime,vers=4.2,rsize=1048576,...
# /mnt/smb        //server/share              cifs   rw,relatime,vers=3.1.1,sec=ntlmssp,...

# Проверка, что automount работает
findmnt -t autofs
# → /home           autofs rw,relatime,fd=0,pgrp=1,...

# Проверка propagation flags (важно для контейнеров)
findmnt -o TARGET,PROPAGATION | grep -E 'shared|slave|private'
```

### Интеграция с Prometheus (использование node_exporter)

node_exporter автоматически экспортирует метрики для всех смонтированных ФС через коллекторы `nfs` и `nfsd`. Для мониторинга клиентских монтирований используйте стандартные `node_filesystem_*` метрики:

```yaml
# prometheus.yml — scrape config
scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['node1:9100']
    metric_relabel_configs:
      # Фильтруем только интересующие точки монтирования
      - source_labels: [mountpoint]
        regex: '/mnt/.*'
        target_label: __name__
        replacement: 'node_filesystem_${1}'
```

### Ключевые PromQL запросы

```promql
# Доступное место на NFS-монтированиях (в процентах)
100 - (node_filesystem_avail_bytes{fstype=~"nfs4?|cifs",mountpoint="/mnt/.*"}
       / node_filesystem_size_bytes{fstype=~"nfs4?|cifs",mountpoint="/mnt/.*"} * 100)

# Монтирования в read-only (потенциальная проблема)
node_filesystem_readonly{mountpoint="/mnt/.*"} == 1

# Предсказание заполнения диска на NFS за 4 часа
predict_linear(
  node_filesystem_avail_bytes{fstype="nfs4",mountpoint="/mnt/nfs_logs"}[1h], 4*3600
) < 0

# NFS retransmissions (клиентские ошибки)
rate(node_nfs_network totalTime{export!=""}[5m]) > 0.1

# Количество активных NFS-монтирований
node_filesystem_files{fstype="nfs4"} - node_filesystem_files_free{fstype="nfs4"}
```

### Алерты для Prometheus

```yaml
groups:
  - name: network_mount_alerts
    rules:
      - alert: NetworkMountReadOnly
        expr: node_filesystem_readonly{mountpoint="/mnt/.*"} == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Монтирование {{ $labels.mountpoint }} в read-only"
          description: "ФС {{ $labels.device }} на {{ $labels.instance }} смонтирована в RO. Возможна аппаратная проблема или повреждение журнала."

      - alert: NetworkMountStale
        expr: |
          count by (instance, mountpoint) (
            node_filesystem_readonly{fstype=~"nfs4?|cifs"} == 0
            and
            changes(node_filesystem_files_free{fstype=~"nfs4?|cifs",mountpoint="/mnt/.*"}[5m]) == 0
          )
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Возможно stale монтирование {{ $labels.mountpoint }}"
          description: "Количество свободных inodes не изменялось 10 минут. Проверьте доступность ФС."

      - alert: NetworkMountDiskSpaceLow
        expr: |
          (node_filesystem_avail_bytes{fstype=~"nfs4?|cifs",mountpoint="/mnt/.*"}
           / node_filesystem_size_bytes{fstype=~"nfs4?|cifs",mountpoint="/mnt/.*"} * 100) < 15
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Мало места на {{ $labels.mountpoint }}"
          description: "Доступно {{ $value | printf \"%.1f\" }}% на {{ $labels.device }}."

      - alert: NetworkMountDown
        expr: |
          node_filesystem_files{fstype=~"nfs4?|cifs",mountpoint="/mnt/.*"} == 0
          or
          absent(node_filesystem_files{fstype=~"nfs4?|cifs",mountpoint="/mnt/.*"})
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Монтирование {{ $labels.mountpoint }} недоступно"
          description: "ФС не смонтирована или недоступна более 2 минут."
```

## 4. Проверка здоровья NFS через nfsiostat

```bash
# Текущая статистика всех NFS-монтирований
nfsiostat

# Пример вывода:
# syscall  connect  auth  read  write  readdir  commit
# s:       0.00     0.00  12.34  5.67   0.00     0.00
# t:       0.00     0.00  0.52  1.23   0.00     0.00

# Детальная статистика конкретного монтирования
nfsiostat /mnt/nfs_logs 5 3
# → 5-секундные интервалы, 3 замера

# Проверка retransmissions (ключевой индикатор проблем)
grep -E 'retrans|auth|connect' /proc/self/mountstats | head -20
```

**Интерпретация ключевых полей:**
- `connect` — время на установление RPC-соединения. >100ms = проблема с сетью
- `auth` — время аутентификации. >50ms = проблема с Kerberos/KDC
- `read` — среднее время чтения. >20ms для SSD = проблема
- `commit` — время фиксации на сервере. >50ms = перегрузка сервера
- `retrans` — количество повторных RPC-запросов. >0 за 5 минут = проблема

## 5. Проверка здоровья CIFS через smbstatus

```bash
# Активные сессии
smbstatus -b

# Проверка подключения с деталями шифрования
smbstatus -v | grep -E 'Encryption|Signing|Protocol'

# Мониторинг через cifsiostat (пакет sysstat)
cifsiostat 5 3
```

## 6. Автоматическое восстановление при падении NFS-сервера

```bash
#!/usr/bin/env bash
# Автоматическое восстановление NFS после перезапуска сервера
# Запускать через cron каждые 5 минут

set -euo pipefail

NFS_SERVERS=("nas01" "nas02")

for server in "${NFS_SERVERS[@]}"; do
    # Проверка доступности сервера
    if ! ping -c 1 -W 3 "$server" >/dev/null 2>&1; then
        continue
    fi

    # Проверка NFS-экспорта
    if ! showmount -e "$server" >/dev/null 2>&1; then
        continue
    fi

    # Поиск stale монтирований с этим сервером
    while IFS= read -r mountpoint; do
        [[ -z "$mountpoint" ]] && continue

        # Попытка доступа
        if ! timeout 5 stat "$mountpoint" >/dev/null 2>&1; then
            echo "$(date): Восстановление $mountpoint (сервер $server)"

            # Ленивое размонтирование
            umount -l "$mountpoint" 2>/dev/null || true
            sleep 3

            # Повторное монтирование
            if mount "$mountpoint" 2>/dev/null; then
                echo "$(date): OK — $mountpoint восстановлено"
                logger -t mount-recovery "Restored $mountpoint from $server"
            else
                echo "$(date): FAIL — не удалось восстановить $mountpoint"
                logger -t mount-recovery "FAILED to restore $mountpoint from $server"
            fi
        fi
    done < <(findmnt -t nfs4,nfs -no TARGET -S "$server" 2>/dev/null)
done
```

## 7. Мониторинг через systemd mount-юниты

Systemd автоматически отслеживает состояние mount-юнитов. Используйте это для мониторинга:

```bash
# Список всех mount-юнитов и их состояние
systemctl list-units --type=mount --all

# Пример вывода:
# UNIT              LOAD   ACTIVE SUB   DESCRIPTION
# mnt-nfs.mount     loaded active mounted NFS Share
# mnt-smb.mount     loaded active mounted SMB Share
# mnt-backup.mount  loaded failed failed Backup Mount

# Проверка конкретного юнита
systemctl is-active mnt-nfs.mount
# → active / inactive / failed

# Просмотр логов ошибок
journalctl -u mnt-nfs.mount -b --no-pager -p err

# Сброс failed-состояния и повторная попытка
systemctl reset-failed mnt-nfs.mount
systemctl start mnt-nfs.mount
```

## 8. Анализ /proc/self/mountinfo для диагностики

```bash
# Расширенная информация о всех монтированиях (включая propagation)
cat /proc/self/mountinfo | grep -E 'nfs|cifs'

# Пример вывода:
# 123 45 0:50 / /mnt/nfs rw,relatime shared:1 - nfs4 nas01:/exports/logs rw,...

# Поля (важные для диагностики):
# major:minor — идентификатор устройства (для NFS = 0:50)
# mount root — корень экспорта внутри ФС
# mount point — точка монтирования
# mount options — опции + propagation flags
# filesystem type + mount source

# Определение, какие процессы используют NFS
lsof +D /mnt/nfs_logs 2>/dev/null | head -20

# Поиск процессов в состоянии D (зависшие на I/O)
ps aux | awk '$8 ~ /D/ {print $0}'
```

# Диагностика и типичные ошибки

| Ошибка | Вероятная причина | Быстрая проверка | Решение |
| :--- | :--- | :--- | :--- |
| `Stale file handle` | Сервер перезапущен / exportfs -ra | `showmount -e server` | `umount -l && mount point` |
| `Permission denied` | Изменение прав / Kerberos тикет | `klist` (Kerberos), `smbstatus` (CIFS) | Обновить тикет / проверить ACL |
| `Connection timed out` | Сервер недоступен / firewall | `ping server`, `ss -tnp \| grep 2049` | Проверить сеть / firewall |
| `No such file or directory` | Экспорт удалён на сервере | `showmount -e server` | Восстановить экспорт на сервере |
| `No space left on device` | Переполнение на сервере | `df -h` на сервере | Очистить место / расширить |
| `Read-only file system` | Аппаратная ошибка / journal corruption | `dmesg \| grep -i error` | fsck / проверить диск |
| `mount: wrong fs type` | Не установлен пакет ФС | `rpm -q nfs-utils` / `dpkg -l nfs-common` | Установить пакет |

# Дополнительная информация

## Ссылки на углублённые материалы
- **NFS мониторинг (сервер):** [nfs_monitoring.md](../../../Networking/Services/nfs/nfs_monitoring.md) — Prometheus/Grafana, алерты, метрики
- **NFS troubleshooting:** [nfs_troubleshooting.md](../../../Networking/Services/nfs/nfs_troubleshooting.md) — stale mount, D-state, RPC ошибки
- **NFS performance:** [nfs_performance.md](../../../Networking/Services/nfs/nfs_performance.md) — rsize/wsize, nconnect, actimeo
- **Samba мониторинг (сервер):** [samba_monitoring.md](../../../Networking/Services/samba/samba_monitoring.md) — smbstatus, Prometheus/Grafana
- **Samba troubleshooting:** [samba_troubleshooting.md](../../../Networking/Services/samba/samba_troubleshooting.md) — NT_STATUS, idmap, Winbind
- **Node Exporter:** [node_exporter.md](../../../Prometheus/Exporters/node_exporter.md) — node_filesystem_* метрики

## Ссылки на связанные файлы в mounting/
- **Systemd mount units:** [systemd_mount.md](./systemd_mount.md) — health-check через systemctl
- **Autofs:** [autofs_mount.md](./autofs_mount.md) — мониторинг autofs-монтирований
- **Remount:** [../remount.md](../remount.md) — изменение опций без размонтирования
- **Команды:** [../commands.md](../commands.md) — findmnt, mountpoint, fuser
