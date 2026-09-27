# Мониторинг RAID-массивов

## Определения

**Мониторинг RAID (Redundant Array of Independent Disks / Избыточный массив независимых дисков)** — процесс непрерывного контроля состояния дискового массива, отдельных накопителей и фоновых операций (ресинхронизация, восстановление, изменение конфигурации) для предотвращения деградации системы и потери данных.

**S.M.A.R.T. (Self-Monitoring, Analysis and Reporting Technology)** — аппаратно-программная система самодиагностики накопителей (HDD/SSD), предоставляющая данные о физическом износе, ошибках позиционирования, температуре и прогнозируемом выходе из строя.

---

## Основные концепции

### Источники данных и инструменты мониторинга

| Источник | Команда / Метод | Назначение |
| :--- | :--- | :--- |
| **Интерфейс ядра (sysfs)** | `cat /proc/mdstat` | Мгновенный статус всех активных массивов в системе. |
| **Утилита mdadm** | `mdadm --detail /dev/mdX` | Исчерпывающие данные о конкретном устройстве, его компонентах и метаданных. |
| **Суперблок** | `mdadm --examine /dev/sdX1` | Анализ метаданных на физическом разделе (используется, если массив не собирается). |
| **Система SMART** | `smartctl -a /dev/sdX` | Глубокая диагностика физического состояния конкретного диска. |
| **Журнал событий** | `journalctl -u mdmonitor` | Логи демона мониторинга mdadm. |

---

## Практические сценарии

### Анализ состояния через /proc/mdstat

Файл `/proc/mdstat` является наиболее быстрым способом оценки состояния массивов.

```bash
cat /proc/mdstat
```

**Разбор ключевых флагов:**
*   `[UU]` — массив исправен (Up/Up). В RAID 5 из 4 дисков будет `[UUUU]`.
*   `[_U]` или `[U_]` — массив деградирован (Degraded). Символ `_` указывает на отсутствующий или сбойный диск.
*   `(S)` — диск помечен как Spare (горячий резерв).
*   `(F)` — диск помечен как Failed (сбойный).
*   `(P)` — диск помечен как Partitially sync (частично синхронизирован, актуально для PPL).

**Мониторинг в реальном времени:**
```bash
watch -n 1 cat /proc/mdstat
```

### Диагностика деградации через mdadm

Если массив перешел в состояние `degraded`, необходимо выяснить причину:

```bash
sudo mdadm --detail /dev/md0
```

**Критичные поля:**
*   **State:** `clean, degraded` (массив работает, но без избыточности) или `active, checking` (идет проверка).
*   **Working Devices:** Количество исправных дисков.
*   **Failed Devices:** Количество дисков, исключенных из работы из-за ошибок.
*   **Rebuild Status:** Прогресс восстановления в процентах (если запущен процесс восстановления на Spare диск).

### Проверка целостности данных (Scrubbing)

Scrubbing — это процесс фонового пересчета контрольных сумм и сравнения блоков для выявления «тихой» порчи данных (bit rot).

**Запуск проверки:**
```bash
echo check | sudo tee /sys/block/md0/md/sync_action
```

**Анализ результатов:**
После завершения (когда `sync_action` вернет `idle`) проверьте наличие несоответствий:
```bash
cat /sys/block/md0/md/mismatch_cnt
```
*   **0** — массив консистентен.
*   **Значение > 0** — обнаружены расхождения. В RAID 1 это означает, что копии различаются; в RAID 5/6 — чётность не совпадает с данными.

> **Важно:** Команда `check` только сообщает об ошибках. Для их исправления (перезаписи неверных блоков данными/чётностью) используется команда `repair`, но её следует применять с осторожностью, так как она может перезаписать верные данные неверными, если причина в ошибке чтения.

### Управление плохими блоками (Bad Block Log)

Современные версии `mdadm` (метаданные 1.2+) ведут список плохих блоков на уровне массива.

```bash
# Просмотр списка плохих блоков для конкретного диска в массиве
sudo mdadm --examine-badblocks /dev/sdb1
```
Если количество плохих блоков растет, это явный признак необходимости замены диска, даже если SMART еще не выдает критических предупреждений.

---

## Продвинутый мониторинг

### Настройка уведомлений и автоматизации

Демон `mdmonitor` (часть пакета mdadm) обеспечивает фоновый мониторинг и выполнение действий при событиях (отказ диска, начало восстановления).

1.  **Настройка mdadm.conf:**
    ```text
    # /etc/mdadm/mdadm.conf
    MAILADDR admin@example.com
    # Скрипт, который будет запущен при событии
    PROGRAM /usr/local/bin/raid-event-handler.sh
    ```

2.  **Тестирование отправки уведомлений:**
    ```bash
    sudo mdadm --monitor --scan --test --oneshot
    ```

### Тюнинг скорости фоновых операций

При активном мониторинге можно обнаружить, что процесс `resync` или `check` сильно замедляет работу приложений. Скорость можно ограничить или увеличить через sysfs:

```bash
# Минимальная скорость (по умолчанию 1000 КБ/с)
echo 50000 | sudo tee /proc/sys/dev/raid/speed_limit_min
# Максимальная скорость (по умолчанию 200000 КБ/с)
echo 100000 | sudo tee /proc/sys/dev/raid/speed_limit_max
```

### Мониторинг Write-intent Bitmap

Если в массиве используется bitmap для ускорения восстановления после сбоя питания, его состояние также доступно для мониторинга:

```bash
sudo mdadm --examine /dev/sdX1 | grep -i bitmap
```
Наличие активного bitmap в выводе `cat /proc/mdstat` отображается как строка `bitmap: ...`.

---

## Интеграция с системами мониторинга

### Prometheus и Grafana

Для централизованного мониторинга RAID-массивов в инфраструктуре bare metal используется связка **Prometheus** (сбор метрик) + **Grafana** (визуализация и алертинг).

#### Экспорт метрик RAID

**mdadm-exporter** — специализированный экспортер для программных RAID-массивов:

```bash
# Установка (Go binary)
wget https://github.com/conga/master_exporter/releases/download/v0.2.0/mdadm_exporter-0.2.0.linux-amd64.tar.gz
tar xzf mdadm_exporter-*.tar.gz
sudo mv mdadm_exporter /usr/local/bin/

# Запуск (слушает на :9271)
sudo /usr/local/bin/mdadm_exporter --web.listen-address=":9271"
```

**node_exporter** с текстовым файловым коллектором — альтернативный подход:

```bash
# Создание скрипта сбора метрик
cat <<'EOF' > /usr/local/bin/raid_metrics.sh
#!/bin/bash
METRICS_FILE="/var/lib/node_exporter/textfile/raid.prom"

echo "# HELP node_mdraid_disks_total Total number of disks in MD arrays" > ${METRICS_FILE}.tmp
echo "# TYPE node_mdraid_disks_total gauge" >> ${METRICS_FILE}.tmp

for md in /sys/block/md*; do
    [ -d "$md" ] || continue
    ARRAY=$(basename $md)
    DISKS=$(cat ${md}/md/disks 2>/dev/null || echo 0)
    DEGRADED=$(cat ${md}/md/degraded 2>/dev/null || echo 0)
    STATE=$(cat ${md}/md/array_state 2>/dev/null || echo "unknown")
    
    echo "node_mdraid_disks_total{array=\"${ARRAY}\"} ${DISKS}" >> ${METRICS_FILE}.tmp
    echo "node_mdraid_degraded{array=\"${ARRAY}\"} ${DEGRADED}" >> ${METRICS_FILE}.tmp
    echo "node_mdraid_state{array=\"${ARRAY}\",state=\"${STATE}\"} 1" >> ${METRICS_FILE}.tmp
done

mv ${METRICS_FILE}.tmp ${METRICS_FILE}
EOF

chmod +x /usr/local/bin/raid_metrics.sh
```

#### Ключевые метрики для алертинга

| Метрика | Описание | Пороговое значение |
| :--- | :--- | :--- |
| `node_mdraid_state{state="active"}` | Массив активен | == 0 (критично) |
| `node_mdraid_degraded` | Количество деградированных массивов | > 0 |
| `node_mdraid_disks` | Общее количество дисков | Сравнение с ожидаемым |
| `node_md_level` | Уровень RAID | Информационная |
| `node_mdraid_blocks_total` | Общий размер массива | Информационная |
| `smartctl_device_temperature_celsius` | Температура диска | > 50 (HDD), > 70 (NVMe) |
| `smartctl_device_percentage_used` | Износ SSD | > 80 |

#### Примеры PromQL-запросов

```promql
# Массив деградирован
node_mdraid_degraded > 0

# Массив неактивен (критично)
node_mdraid_state == 0

# Температура дисков в RAID превышает порог
smartctl_device_temperature_celsius > 50

# Все диски массива доступны
sum by (array) (node_mdraid_disks) < 2

# Время до замены SSD (RESV)
smartctl_device_percentage_used > 80
```

#### Пример alerting-правил (Prometheus rules)

```yaml
groups:
  - name: raid_alerts
    rules:
      - alert: RaidArrayDegraded
        expr: node_mdraid_degraded > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "RAID array {{ $labels.array }} is degraded"
          description: "Array has {{ $value }} degraded component(s)"

      - alert: RaidArrayDown
        expr: node_mdraid_state == 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "RAID array {{ $labels.array }} is DOWN"
          description: "Array is inactive, data at risk"

      - alert: DiskTemperatureHigh
        expr: smartctl_device_temperature_celsius > 55
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk {{ $labels.device }} temperature high"
          description: "Temperature is {{ $value }}°C"
```

#### Настройка mdadm.conf для Prometheus

```bash
# Включить сбор метрик через sysfs
echo 'options md_mod start_ro=0' | sudo tee /etc/modprobe.d/md.conf

# Убедиться, что sysfs доступен
ls /sys/block/md*/md/
```

### Zabbix и Nagios

Для сред с Zabbix или Nagios доступны специализированные плагины:

```bash
# Zabbix: проверка через userparameter
cat <<'EOF' >> /etc/zabbix/zabbix_agentd.d/mdadm.conf
UserParameter=mdadm.discovery,/usr/local/bin/zabbix_mdadm_discovery.sh
UserParameter=mdadm.status[*],/usr/local/bin/zabbix_mdadm_status.sh $1
EOF

# Nagios: плагин check_mdadm
./check_mdadm --device /dev/md0 --warning degraded --critical down
```

---

## Скрипты автоматизации мониторинга

### Комплексная проверка всех массивов

```bash
#!/bin/bash
# /usr/local/bin/raid_health_check.sh
# Проверка состояния всех RAID-массивов

LOG_FILE="/var/log/raid_health.log"
ALERT_EMAIL="admin@example.com"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

check_arrays() {
    local status=0
    
    for md in /sys/block/md*; do
        [ -d "$md" ] || continue
        ARRAY=$(basename $md)
        
        STATE=$(cat ${md}/md/array_state 2>/dev/null)
        DEGRADED=$(cat ${md}/md/degraded 2>/dev/null)
        LEVEL=$(cat ${md}/md/level 2>/dev/null)
        
        # Проверка на деградацию
        if [ "$DEGRADED" -gt 0 ]; then
            echo "${TIMESTAMP} WARNING: ${ARRAY} (level=${LEVEL}) is degraded (${DEGRADED} devices)" >> ${LOG_FILE}
            status=1
        fi
        
        # Проверка на неактивное состояние
        if [ "$STATE" != "active" ]; then
            echo "${TIMESTAMP} CRITICAL: ${ARRAY} is in state: ${STATE}" >> ${LOG_FILE}
            status=2
        fi
    done
    
    return $status
}

# Запуск проверки
check_arrays
EXIT_CODE=$?

if [ $EXIT_CODE -eq 2 ]; then
    echo "CRITICAL: RAID array(s) in bad state" | mail -s "RAID CRITICAL" ${ALERT_EMAIL}
elif [ $EXIT_CODE -eq 1 ]; then
    echo "WARNING: RAID array(s) degraded" | mail -s "RAID WARNING" ${ALERT_EMAIL}
fi

exit $EXIT_CODE
```

### Проверка SMART для всех дисков в RAID

```bash
#!/bin/bash
# /usr/local/bin/raid_smart_check.sh
# Проверка SMART для дисков, входящих в RAID-массивы

LOG_FILE="/var/log/raid_smart.log"
ALERT_EMAIL="admin@example.com"

check_raid_disks_smart() {
    # Получение списка физических дисков в RAID
    DISKS=$(cat /proc/mdstat | grep -oP 'sd[a-z]' | sort -u)
    
    for DISK in $DISKS; do
        DEVICE="/dev/${DISK}"
        
        # Проверка здоровья
        HEALTH=$(sudo smartctl -H $DEVICE 2>/dev/null | grep -i "result" | awk '{print $NF}')
        
        if [ "$HEALTH" != "PASSED" ]; then
            echo "$(date): SMART FAILED on $DEVICE" >> ${LOG_FILE}
            echo "SMART FAILED on $DEVICE" | mail -s "Disk SMART FAILED" ${ALERT_EMAIL}
        fi
        
        # Проверка температуры
        TEMP=$(sudo smartctl -A $DEVICE 2>/dev/null | grep -i "temperature" | awk '{print $10}')
        if [ -n "$TEMP" ] && [ "$TEMP" -gt 55 ]; then
            echo "$(date): High temperature on $DEVICE: ${TEMP}°C" >> ${LOG_FILE}
        fi
        
        # Проверка переназначенных секторов
        REALLOC=$(sudo smartctl -A $DEVICE 2>/dev/null | grep -i "reallocated" | awk '{print $10}')
        if [ -n "$REALLOC" ] && [ "$REALLOC" -gt 0 ]; then
            echo "$(date): Reallocated sectors on $DEVICE: ${REALLOC}" >> ${LOG_FILE}
        fi
    done
}

check_raid_disks_smart
```

### Скрипт мониторинга восстановления (rebuild)

```bash
#!/bin/bash
# /usr/local/bin/raid_rebuild_monitor.sh
# Мониторинг прогресса восстановления массива

ARRAY="${1:-/dev/md0}"
LOG_FILE="/var/log/raid_rebuild.log"
INTERVAL=30

monitor_rebuild() {
    while true; do
        REBUILD_PROGRESS=$(cat /sys/block/$(basename $ARRAY)/md/rebuild_info 2>/dev/null || echo "idle")
        
        if [ "$REBUILD_PROGRESS" = "idle" ]; then
            echo "$(date): Rebuild completed on $ARRAY" >> ${LOG_FILE}
            break
        fi
        
        echo "$(date): Rebuild progress on $ARRAY: ${REBUILD_PROGRESS}%" >> ${LOG_FILE}
        sleep $INTERVAL
    done
}

monitor_rebuild
```

---

## Периодический мониторинг

### Cron-задачи

Для автоматического запуска проверок по расписанию:

```bash
# Редактирование crontab root
sudo crontab -e

# Ежедневная проверка SMART (3:00)
0 3 * * * /usr/local/bin/raid_smart_check.sh >> /var/log/raid_smart_cron.log 2>&1

# Еженедельный scrubbing (воскресенье, 2:00)
0 2 * * 0 echo check | tee /sys/block/md*/md/sync_action >> /var/log/raid_scrub.log 2>&1

# Ежечасная проверка состояния
0 * * * * /usr/local/bin/raid_health_check.sh >> /var/log/raid_health_cron.log 2>&1

# Ежемесячный запуск long SMART теста (1-е число, 1:00)
0 1 1 * * for disk in $(cat /proc/mdstat | grep -oP 'sd[a-z]' | sort -u); do sudo smartctl -t long /dev/$disk; done
```

### Systemd Timer (современный подход)

Для дистрибутивов с systemd.timer:

```ini
# /etc/systemd/system/raid-check.timer
[Unit]
Description=RAID Array Health Check Timer

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/raid-check.service
[Unit]
Description=RAID Array Health Check

[Service]
Type=oneshot
ExecStart=/usr/local/bin/raid_health_check.sh
StandardOutput=journal
StandardError=journal
```

```bash
# Активация таймера
sudo systemctl daemon-reload
sudo systemctl enable --now raid-check.timer

# Проверка статуса
sudo systemctl list-timers | grep raid
```

### Автоматический scrubbing через systemd

```ini
# /etc/systemd/system/raid-scrub.timer
[Unit]
Description=RAID Scrubbing Timer

[Timer]
OnCalendar=Sun *-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/raid-scrub.service
[Unit]
Description=RAID Scrubbing

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'for md in /sys/block/md*; do echo check > $md/md/sync_action; done'
StandardOutput=journal
StandardError=journal
```

---

## Расширенные告ажные сценарии

### Интеграция с Alertmanager

Для маршрутизации алертов из Prometheus:

```yaml
# /etc/alertmanager/alertmanager.yml
global:
  resolve_timeout: 5m

route:
  receiver: 'raid-ops'
  group_by: ['alertname', 'array']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: 'raid-ops'
    email_configs:
      - to: 'ops-team@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
    webhook_configs:
      - url: 'http://localhost:9095/alert'
        send_resolved: true

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'array']
```

### Telegram-уведомления

```bash
#!/bin/bash
# /usr/local/bin/raid_telegram_alert.sh
# Отправка алертов в Telegram

BOT_TOKEN="YOUR_BOT_TOKEN"
CHAT_ID="YOUR_CHAT_ID"
ARRAY="$1"
STATUS="$2"

send_telegram() {
    local MESSAGE="$1"
    curl -s -X POST \
        "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d chat_id="${CHAT_ID}" \
        -d text="${MESSAGE}" \
        -d parse_mode="HTML"
}

case "$STATUS" in
    "degraded")
        send_telegram "<b>RAID WARNING</b>\nArray: ${ARRAY}\nStatus: Degraded\nTime: $(date)"
        ;;
    "down")
        send_telegram "<b>RAID CRITICAL</b>\nArray: ${ARRAY}\nStatus: DOWN\nTime: $(date)"
        ;;
    "rebuilt")
        send_telegram "<b>RAID INFO</b>\nArray: ${ARRAY}\nStatus: Rebuild Complete\nTime: $(date)"
        ;;
esac
```

### Webhook-интеграция

```bash
#!/bin/bash
# /usr/local/bin/raid_webhook_alert.sh
# Универсальный webhook для алертов

WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"
ARRAY="$1"
STATUS="$2"
DETAILS="$3"

PAYLOAD=$(cat <<EOF
{
    "text": "RAID Alert",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*RAID ${STATUS^^}*\n*Array:* ${ARRAY}\n*Details:* ${DETAILS}\n*Time:* $(date)"
            }
        }
    ]
}
EOF
)

curl -s -X POST \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" \
    "${WEBHOOK_URL}"
```

### Интеграция с灵狐 (Jira/ServiceNow)

```bash
#!/bin/bash
# /usr/local/bin/raid_ticket_create.sh
# Автоматическое создание тикета при деградации

JIRA_URL="https://jira.example.com"
JIRA_USER="admin"
JIRA_TOKEN="YOUR_TOKEN"
ARRAY="$1"

# Проверка, открыт ли уже тикет
EXISTING=$(curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
    "${JIRA_URL}/rest/api/2/search?jql=project=OPS+AND+summary~'RAID+${ARRAY}'+AND+status!=Done" \
    | jq -r '.total')

if [ "$EXISTING" -eq 0 ]; then
    curl -s -X POST \
        -u "${JIRA_USER}:${JIRA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{
            "fields": {
                "project": {"key": "OPS"},
                "summary": "RAID Array Degraded: '"${ARRAY}"'",
                "description": "RAID array '"${ARRAY}"' is degraded. Immediate attention required.",
                "issuetype": {"name": "Incident"},
                "priority": {"name": "High"}
            }
        }' \
        "${JIRA_URL}/rest/api/2/issue"
fi
```

---

## Troubleshooting мониторинга

### Проблемы с mdmonitor

**Симптом:** Демон `mdmonitor` не отправляет уведомления.

```bash
# 1. Проверка статуса демона
sudo systemctl status mdadm-monitor.service

# 2. Если не активен — запуск
sudo systemctl start mdadm-monitor.service
sudo systemctl enable mdadm-monitor.service

# 3. Проверка логов
sudo journalctl -u mdadm-monitor.service -f

# 4. Проверка конфигурации
cat /etc/mdadm/mdadm.conf | grep -E "MAILADDR|PROGRAM"

# 5. Тестовый запуск
sudo mdadm --monitor --scan --test --oneshot
```

### Проблемы с метриками Prometheus

**Симптом:** Метрики RAID не появляются в Prometheus.

```bash
# 1. Проверка доступности экспортера
curl http://localhost:9271/metrics | grep md

# 2. Проверка настроек collectd
cat /etc/collectd/collectd.conf | grep -A5 mdadm

# 3. Проверка sysfs
ls -la /sys/block/md*/

# 4. Проверка прав доступа
sudo -u nobody curl http://localhost:9271/metrics
```

### Проблемы с scrubbing

**Симптом:** Scrubbing не запускается или зависает.

```bash
# 1. Проверка текущего статуса
cat /sys/block/md0/md/sync_action
# → idle (готов к запуску) или check/repair (выполняется)

# 2. Если завис — принудительная остановка
echo idle | sudo tee /sys/block/md0/md/sync_action

# 3. Проверка прогресса
cat /sys/block/md0/md/sync_completed

# 4. Проверка ошибок после scrubbing
cat /sys/block/md0/md/mismatch_cnt
```

### Восстановление метаданных массива

**Симптом:** Массив не определяется после обновления ядра или замены контроллера.

```bash
# 1. Поиск суперблоков
sudo mdadm --examine /dev/sd?

# 2. Сборка из найденных компонентов
sudo mdadm --assemble --scan

# 3. Если не помогло — ручная сборка
sudo mdadm --assemble /dev/md0 /dev/sdb1 /dev/sdc1

# 4. Обновление initramfs после восстановления
sudo update-initramfs -u
```

### Логирование и аудит

```bash
# Настройка аудита событий RAID
sudo auditctl -w /sys/block -p rwxa -k raid_monitor

# Просмотр аудит-логов
sudo ausearch -k raid_monitor

# Централизованное логирование
cat <<'EOF' > /etc/rsyslog.d/raid.conf
:programname, isequal, "mdadm" /var/log/mdadm.log
& stop
EOF
sudo systemctl restart rsyslog
```

---

## Дополнительная информация

### См. также
* [Обзор RAID и mdadm](./overview.md) — основы архитектуры и управления.
* [Уровни RAID](./raid-levels.md) — детальное сравнение производительности и рисков.
* [Аппаратные RAID-контроллеры](./hardware-raid.md) — мониторинг через storcli/MegaCLI.
* [Тюнинг производительности](./raid-performance-tuning.md) — chunk size, I/O scheduler, sysctl.
* [Диагностика дисков (smartctl)](../../Diagnostics/Hardware/smartctl/index.md) — глубокий анализ состояния оборудования.
* [Node Exporter](../../Prometheus/Exporters/node_exporter.md) — метрики хоста для Prometheus.
