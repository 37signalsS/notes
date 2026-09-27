# Централизованное логирование Proxmox VE

## Определения

**journald** -- системный сервис логирования в systemd. Собирает логи из всех сервисов, VM и контейнеров. Хранит логи в бинарном формате с индексацией.

**syslog** -- классический протокол и формат логирования (RFC 5424). Используется для пересылки логов на удаленные серверы. Устаревший стандарт, но все еще широко используемый.

**Loki** -- система агрегации логов от Grafana Labs. Хранит логи в виде индексированных метаданных (labels) без полного индексирования текста. Эффективнее ELK по стоимости хранения.

**Fluent Bit** -- lightweight агент для сбора и пересылки логов. Поддерживает множество входов (journald, files, containers) и выходов (Loki, Elasticsearch, S3).

**ELK Stack** -- Elasticsearch + Logstash + Kibana. Полнофункциональная стека для логирования с полнотекстовым поиском и визуализацией. Требует значительных ресурсов.

**Structured Logging** -- подход к логированию, при котором каждая запись представляет собой JSON объект с полями (timestamp, level, service, message, context). Упрощает парсинг и анализ.

## Теоретический блок

### Источники логов в Proxmox

| Источник | Сервис | Хранение | Описание |
|----------|--------|----------|----------|
| Proxmox API | pveproxy, pvedaemon | /var/log/pve/ | HTTP запросы, аутентификация |
| VM | qemu-system | journald | stdout/stderr VM |
| LXC | pct | journald | stdout/stderr контейнеров |
| Кластер | corosync | journalctl | Quorum, heartbeat |
| Хранилище | pvestatd, pvedaemon | /var/log/pve/ | Статус storage |
| Сеть | pve-firewall | /var/log/ | Firewall события |
| Ceph | ceph-mon, ceph-osd | journalctl | Cluster health |
| PBS | proxmox-backup-proxy | /var/log/proxmox-backup/ | Бэкапы |

### Архитектура централизованного логирования

```
Proxmox Hosts (n)          Log Aggregation        Storage & Visualization
┌──────────────────┐      ┌──────────────────┐    ┌──────────────────┐
│  journald        │      │  Fluent Bit      │    │  Loki            │
│  pve-proxy logs  │─────>│  (per node)      │───>│  (chunk store)   │
│  VM/LXC stdout   │      │  - journald      │    │  - labels index  │
│  auditd          │      │  - syslog        │    │  - compression   │
│  ceph logs       │      │  - files         │    │                  │
└──────────────────┘      └──────────────────┘    └──────────────────┘
                                                        │
                                                   ┌────▼────┐
                                                   │ Grafana │
                                                   │ Explore │
                                                   └─────────┘
```

## Практические сценарии

### 1. journald -- базовая настройка

```bash
# Проверка конфигурации journald
cat /etc/systemd/journald.conf

# Основные настройки
cat > /etc/systemd/journald.conf << 'EOF'
[Journal]
Storage=persistent
SystemMaxUse=4G
SystemMaxFileSize=256M
MaxRetentionSec=30day
MaxFileSec=1day
ForwardToSyslog=yes
RateLimitIntervalSec=30s
RateLimitBurst=10000
EOF

systemctl restart systemd-journald
```

### 2. journald -- ротация и мониторинг

```bash
# Проверка использования диска
journalctl --disk-usage

# Ручная очистка старых логов
journalctl --vacuum-size=2G
journalctl --vacuum-time=7d

# Мониторинг в реальном времени
journalctl -f
journalctl -u pveproxy -f
journalctl -u corosync -f

# Фильтрация по времени
journalctl --since "1 hour ago"
journalctl --since "2024-01-01" --until "2024-01-02"

# Экспорт в JSON
journalctl -o json-pretty --since "1 hour ago" > /tmp/logs.json
```

### 3. Syslog forwarding

```bash
# Настройка rsyslog для пересылки на удаленный сервер
cat > /etc/rsyslog.d/50-forward.conf << 'EOF'
# Отправка всех логов level>=info на syslog сервер
*.* @@logserver.internal:514

# Отправка только Proxmox логов
pveproxy.* @@logserver.internal:514
pvedaemon.* @@logserver.internal:514
corosync.* @@logserver.internal:514

# Фильтрация шума
:programname, isequal, "kernel" stop
:programname, isequal, "systemd" stop
EOF

systemctl restart rsyslog
```

### 4. Fluent Bit -- lightweight логирование

```bash
# Установка Fluent Bit
curl https://packages.fluentbit.io/fluentbit.key | gpg --dearmor > /usr/share/keyrings/fluentbit-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/fluentbit-keyring.gpg] https://packages.fluentbit.io/ubuntu/jammy jammy" > /etc/apt/sources.list.d/fluentbit.list
apt update && apt install -y fluent-bit

# Конфигурация Fluent Bit
cat > /etc/fluent-bit/fluent-bit.conf << 'EOF'
[SERVICE]
    Flush         5
    Log_Level     info
    Daemon        off
    Parsers_File  parsers.conf
    HTTP_Server   On
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020
    storage.path  /var/lib/fluent-bit/

# Вход: journald
[INPUT]
    Name          systemd
    Tag           proxmox.*
    Systemd_Filter _SYSTEMD_UNIT=pveproxy.service
    Systemd_Filter _SYSTEMD_UNIT=pvedaemon.service
    Systemd_Filter _SYSTEMD_UNIT=corosync.service
    Read_From_Tail On

# Вход: syslog
[INPUT]
    Name          tail
    Tag           syslog.*
    Path          /var/log/syslog
    Parser        syslog

# Вход: Proxmox API логи
[INPUT]
    Name          tail
    Tag           pve-api.*
    Path          /var/log/pveproxy/access.log
    Parser        pve-api

# Выход: Loki
[OUTPUT]
    Name          loki
    Match         proxmox.*
    Labels        job=proxmox, node=$HOSTNAME
    Label_Keys    $TAG
    Remove_Keys   TAG
    Auto_Kubernetes_Labels Off
    Tenant_ID     ""
    Batch_Wait    1s
    Batch_Size    1048576
    Line_Format   json
    Url           http://loki.internal:3100/loki/api/v1/push

# Выход: Console (для отладки)
[OUTPUT]
    Name          stdout
    Match         *

# Парсеры
[PARSER]
    Name          pve-api
    Format        regex
    Regex         ^(?<time>.*) (?<ip>.*) (?<user>.*) (?<method>.*) (?<uri>.*) (?<status>.*) (?<size>.*)$
    Time_Key      time
    Time_Format   %d/%b/%Y:%H:%M:%S %z
EOF

systemctl enable --now fluent-bit
```

### 5. Loki -- установка и настройка

```bash
# Установка Loki (single binary)
wget https://github.com/grafana/loki/releases/download/v2.9.4/loki-linux-amd64.zip
unzip loki-linux-amd64.zip
mv loki-linux-amd64 /usr/local/bin/loki

# Конфигурация Loki
cat > /etc/loki/config.yml << 'EOF'
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  path_prefix: /var/lib/loki
  storage:
    filesystem:
      chunks_directory: /var/lib/loki/chunks
      rules_directory: /var/lib/loki/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  retention_period: 720h

compactor:
  working_directory: /var/lib/loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  delete_request_store: filesystem
EOF

# Systemd unit
cat > /etc/systemd/system/loki.service << 'EOF'
[Unit]
Description=Loki Log Aggregation
After=network-online.target

[Service]
User=loki
Group=loki
Type=simple
ExecStart=/usr/local/bin/loki -config.file=/etc/loki/config.yml
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

useradd --system --no-create-home --shell /bin/false loki
mkdir -p /var/lib/loki
chown -R loki:loki /var/lib/loki
systemctl daemon-reload
systemctl enable --now loki
```

### 6. Grafana -- подключение Loki

```bash
# Добавление datasource в Grafana
# GUI: Configuration -> Data Sources -> Add -> Loki
# URL: http://loki.internal:3100

# Или через provisioning
cat > /etc/grafana/provisioning/datasources/loki.yml << 'EOF'
apiVersion: 1
datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki.internal:3100
    isDefault: false
    editable: true
EOF

systemctl restart grafana-server
```

### 7. LogQL запросы для Proxmox

```bash
# Все логи Proxmox
{job="proxmox"}

# Логи по ноду
{job="proxmox", node="pve-node1"}

# Ошибки Proxmox API
{job="proxmox"} |= "error" | json | level="error"

# Failed SSH attempts
{job="proxmox"} |= "authentication failure"

# Corosync heartbeat
{job="proxmox", service="corosync"} |~ "ring"

# VM логи
{job="proxmox"} | json | vmid="101"

# Firewall события
{job="proxmox"} |= "pve-firewall" | json

# Ceph health
{job="proxmox"} |= "ceph" | json | level="warning"

# Просмотр логов за последний час
{job="proxmox"} [1h]

# Подсчет ошибок по нодам
sum by (node) (count_over_time({job="proxmox"} |= "error" [1h]))
```

### 8. Логирование через Prometheus + Alertmanager

```bash
# Алерт на ошибки Proxmox
# prometheus-rules.yml
groups:
  - name: proxmox-logs
    rules:
      - alert: ProxmoxHighErrorRate
        expr: |
          sum by (node) (
            rate({job="proxmox"} |= "error" [5m])
          ) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.node }}"
          description: "More than 0.1 errors/sec for 5 minutes"

      - alert: ProxmoxSSHBruteForce
        expr: |
          sum by (node) (
            rate({job="proxmox"} |= "authentication failure" [5m])
          ) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "SSH brute force on {{ $labels.node }}"
          description: "Multiple failed SSH attempts detected"
```

### 9. Audit логи и поиск

```bash
# Аудит действий в Proxmox
ausearch -k proxmox_config --interpret
ausearch -k ssh_keys --interpret
aureport --summary

# Поиск в Proxmox API логах
zgrep "error" /var/log/pveproxy/access.log.*
grep "authentication" /var/log/pveproxy/access.log

# Поиск по времени
journalctl --since "2024-01-01 10:00" --until "2024-01-01 11:00" | grep -i error
```

### 10. Сжатие и архивация логов

```bash
# Настройка logrotate для Proxmox
cat > /etc/logrotate.d/proxmox << 'EOF'
/var/log/pve/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 root adm
    sharedscripts
    postrotate
        systemctl reload pveproxy > /dev/null 2>&1 || true
    endscript
}
EOF

# Ручная очистка
find /var/log/pve/ -name "*.gz" -mtime +30 -delete
journalctl --vacuum-size=2G
```

## Диагностика и устранение неполадок

### journald не записывает логи

```bash
# Проверка конфигурации
cat /etc/systemd/journald.conf | grep -v "^#" | grep -v "^$"

# Проверка использования диска
journalctl --disk-usage

# Перезапуск
systemctl restart systemd-journald

# Проверка storage
ls -la /var/log/journal/
```

### Fluent Bit не отправляет логи

```bash
# Проверка статуса
systemctl status fluent-bit

# Проверка логов Fluent Bit
journalctl -u fluent-bit --since "5 minutes ago"

# Проверка конфигурации
fluent-bit -c /etc/fluent-bit/fluent-bit.conf -T

# Проверка подключения к Loki
curl -v http://loki.internal:3100/ready
```

### Loki не индексирует логи

```bash
# Проверка готовности
curl http://localhost:3100/ready

# Проверка логов Loki
journalctl -u loki --since "5 minutes ago"

# Проверка дискового пространства
df -h /var/lib/loki/

# Проверка индексов
ls /var/lib/loki/index/
```

## Лучшие практики

1. **Структурированные логи**: Используйте JSON формат для всех логов. Упрощает парсинг и анализ.

2. **Labels**: Минимизируйте количество labels в Loki. Каждый уникальный комбинация labels создает новый stream.

3. **Retention**: Настройте ротацию логов. Для journald -- `MaxRetentionSec=30day`, для Loki -- `retention_period`.

4. **Мониторинг логов**: Алерты на аномальные паттерны логов (всплеск ошибок, brute-force).

5. **Безопасность**: Логи могут содержать конфиденциальные данные (пароли, токены). Ограничивайте доступ.

6. **Производительность**: Fluent Bit потребляет ~10 МБ RAM. Loki -- зависит от объема логов. Планируйте ресурсы.

7. **Бэкапы логов**: Для compliance requirements -- архивируйте логи в offsite storage.

8. **Корреляция**: Используйте одинаковые labels для корреляции логов с метриками (Prometheus + Loki).

9. **Тестирование**: Проверяйте pipeline логирования регулярно. Убедитесь, что логи доходят до Loki.

10. **Документация**: Опишите какие логи где хранятся, сколько времени, и кто имеет доступ.

## Граничные случаи

- **Loki и высокий cardinality labels**: Если создавать label для каждого уникального значения (vmid, user_id), Loki создаст миллионы streams. Используйте `|=` для фильтрации вместо labels.

- **journald и неструктурированные логи**: Proxmox API логи не структурированы по умолчанию. Используйте regex парсер в Fluent Bit.

- **Fluent Bit buffer overflow**: При недостатке памяти Fluent Bit может терять логи. Настройте `storage.path` для overflow.

- **Loki и disk usage**: Loki использует компрессию (snappy). 1 ГБ сырых логов = ~100 МБ в Loki. Планируйте место.

- **Syslog и TCP/UDP**: Используйте TCP для надежной доставки. UDP может терять пакеты при сетевых проблемах.

## Дополнительная информация

### Связанные темы

- [Proxmox Monitoring (Prometheus/Grafana)](./proxmox_monitoring.md)
- [journald (Linux)](../Linux/SystemAdministration/Logging/journald.md)
- [Loki (Linux)](../Linux/SystemAdministration/Logging/loki.md)
- [ELK Stack (Linux)](../Linux/SystemAdministration/Logging/elk.md)
- [Fluent Bit (Linux)](../Linux/SystemAdministration/Logging/fluent_bit.md)
- [Structured Logging](../Linux/SystemAdministration/Logging/structured_logging.md)
- [Security Hardening](./proxmox_security.md)
