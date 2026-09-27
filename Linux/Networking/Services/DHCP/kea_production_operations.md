# Kea DHCP: Production Operations и Troubleshooting

---

## Определения

**Day-2 Operations** — операции по поддержанию работоспособности сервиса после развёртывания: мониторинг, обновление, масштабирование, отработка инцидентов.

**Capacity Planning** — планирование ёмкости: прогнозирование роста пула адресов, нагрузки на БД, сетевого трафика.

**Runbook** — пошаговая инструкция для оператора по обработке типичных инцидентов.

**SLA (Service Level Agreement)** — соглашение об уровне сервиса: доступность DHCP-сервера, latency выдачи адресов.

---

## Основные концепции

### SLA для DHCP-сервиса

| Метрика | Target | Critical |
|:--- |:--- |:--- |
| Доступность DHCP-сервера | 99.99% | >99.9% |
| Latency DORA (DISCOVER → ACK) | <500ms | >2s |
| Packet loss | <0.1% | >1% |
| Pool utilization | <80% | >90% |
| HA failover time | <30s | >60s |

### Мониторинг: ключевые метрики

#### Через REST API

```bash
# 1. Количество активных leases
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# 2. Packet rate
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].reclaimed-leases"}}' | jq

# 3. HA state
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "ha-state"}}' | jq

# 4. Все статистики
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get-all"}' | jq
```

#### Prometheus exporter

```yaml
# prometheus.yml
- job_name: 'kea-dhcp'
  static_configs:
    - targets: ['dhcp-1:9547', 'dhcp-2:9547']
  metrics_path: /metrics
```

#### Ключевые PromQL-запросы

```promql
# Pool utilization
kea_dhcp_leases_assigned{subnet="10.0.10.0/24"} / kea_dhcp_leases_total{subnet="10.0.10.0/24"} * 100

# Packet rate
rate(kea_dhcp_packets_received_total[5m])

# Error rate
rate(kea_dhcp_packets_sent_total{type="nack"}[5m]) / rate(kea_dhcp_packets_sent_total{type="ack"}[5m])

# HA state (0=normal, 1=communications-interrupted, 2=partner-down)
kea_dhcp_ha_state
```

---

## Практические сценарии

### 1. Runbook: Pool Exhaustion

**Симптомы:** Клиенты не получают IP, DHCPNAK rate растёт.

**Диагностика:**
```bash
# 1. Проверка utilisation
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# 2. Поиск "мёртвых" leases
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-get-all"}' | jq '.arguments.leases[] | select(.state == "expired")' | wc -l

# 3. Поиск abandoned leases
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-get-all"}' | jq '.arguments.leases[] | select(.state == "abandoned")' | wc -l
```

**Решения:**
```bash
# Краткосрочное: сократить lifetime
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "config-set", "arguments": {"Dhcp4": {"valid-lifetime": 3600}}}' | jq

# Очистка expired
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-del", "arguments": {"state": "expired"}}' | jq

# Добавление временного пула
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "subnet4-add", "arguments": {"subnet4": [{"id": 99, "subnet": "10.0.100.0/24", "pools": [{"pool": "10.0.100.1 - 10.0.100.254"}]}]}}' | jq
```

**Долгосрочное:** расширить CIDR, настроить IPAM.

### 2. Runbook: HA degraded (communications-interrupted)

**Симптомы:** Один из серверов не отвечает, логи показывают `communications-interrupted`.

**Диагностика:**
```bash
# 1. Проверка HA state
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "ha-state"}}' | jq

# 2. Проверка доступности второго сервера
curl -s http://10.0.0.11:8000/ | jq

# 3. Проверка network connectivity
ping -c 3 10.0.0.11
nc -zv 10.0.0.11 8000

# 4. Проверка MySQL доступности
mysql -h 10.0.0.100 -u kea -p -e "SELECT COUNT(*) FROM kea.lease4;"
```

**Решения:**
```bash
# Если второй сервер недоступен:
# Primary продолжает работать, берёт на себя 100% нагрузки
# Дождаться восстановления или исправить проблему

# Если проблема с MySQL:
# Проверить replication, connection pooling
systemctl restart mysql
```

### 3. Runbook: Kea не запускается

**Симптомы:** `systemctl status kea-dhcp4` показывает failed.

**Диагностика:**
```bash
# 1. Логи
journalctl -u kea-dhcp4 --since "10 min ago"

# 2. Валидация конфигурации
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf

# 3. Проверка прав
ls -la /etc/kea/ /var/lib/kea/ /var/log/kea/
# Должны принадлежать kea:kea или root:root

# 4. Проверка hook-библиотек
ls -la /usr/lib/kea/hooks/
# Все .so файлы должны быть доступны для чтения

# 5. Запуск в foreground для отладки
kea-dhcp4 -d -c /etc/kea/kea-dhcp4.conf
```

**Решения:**
- Ошибка JSON → исправить синтаксис
- Permission denied → `chown -R kea:kea /var/lib/kea/`
- Hook not found → проверить путь в `hooks-libraries`
- Port in use → `ss -nlup | grep :67`

### 4. Runbook: Медленный DORA (latency >2s)

**Симптомы:** Клиенты получают IP через 2+ секунды вместо <500ms.

**Диагностика:**
```bash
# 1. Замер latency через tcpdump
tcpdump -i eth0 -n udp port 67 -c 100 -tttt | \
  awk '/DHCPDISCOVER/{t1=$1} /DHCPOFFER/{t2=$1; print "Latency:", t2-t1, "sec"}'

# 2. Проверка нагрузки на CPU
top -bn1 | grep kea

# 3. Проверка I/O на диск
iostat -x 1 5

# 4. Проверка размера lease-файла
ls -lh /var/lib/kea/kea-leases4.csv
# >100MB = проблема

# 5. Проверка hook-библиотек
journalctl -u kea-dhcp4 | grep -i "hook\|slow"
```

**Решения:**
- Lease-файл >100MB → запустить `kea-lfc`
- High I/O → перейти на MySQL backend
- High CPU → уменьшить debuglevel, увеличить batch size
- Hook slow → отключить debug logging для hooks

### 5. Runbook: DHCP Snooping conflicts

**Симптомы:** Коммутатор не пропускает трафик после миграции ISC → Kea.

**Диагностика:**
```bash
# 1. Проверка DHCP Snooping bindings на коммутаторе
show ip dhcp snooping binding

# 2. Проверка Option 82 в логах Kea
journalctl -u kea-dhcp4 | grep -i "option 82\|relay"

# 3. Проверка giaddr в tcpdump
tcpdump -i eth0 -n udp port 67 -v | grep "giaddr"
```

**Решения:**
```bash
# Очистить DHCP Snooping bindings
clear ip dhcp snooping binding

# Убедиться, что Option 82 обрабатывается через hooks
# В kea-dhcp4.conf:
"hooks-libraries": [
    {"library": "/usr/lib/kea/hooks/libdhcp_flex_id.so"}
]
```

### 6. Runbook: DDNS не обновляется

**Симптомы:** DNS-записи не создаются/обновляются при выдаче lease.

**Диагностика:**
```bash
# 1. Проверка DDNS hook
journalctl -u kea-dhcp4 | grep -i "ddns\|dns"

# 2. Проверка kea-dhcp-ddns статус
systemctl status kea-dhcp-ddns

# 3. Проверка TSIG-ключа
dig -y hmac-sha256:ddns-key:secret corp.example.com SOA

# 4. Проверка zones
nsupdate -l
> zone corp.example.com
> send
```

**Решения:**
```bash
# Проверить конфигурацию DDNS hook
# Убедиться, что TSIG-ключ совпадает с BIND
# Проверить права на зонный файл
chown bind:bind /etc/bind/db.corp.example.com
```

### 7. Runbook: Kea не запускается после изменения конфигурации

**Симптомы:** `systemctl status kea-dhcp4` показывает failed.

**Диагностика:**
```bash
# 1. Валидация JSON-синтаксиса
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf
# → Покажет строку с ошибкой

# 2. Проверка JSON через jq
jq . /etc/kea/kea-dhcp4.conf > /dev/null

# 3. Проверка прав на файлы
ls -la /etc/kea/ /var/lib/kea/ /var/log/kea/
# Должны принадлежать kea:kea или root:root

# 4. Проверка hook-библиотек
ls -la /usr/lib/kea/hooks/
# Все .so файлы должны быть доступны для чтения

# 5. Запуск в foreground для отладки
kea-dhcp4 -d -c /etc/kea/kea-dhcp4.conf
```

Типичные ошибки JSON:
- Завершающая запятая (trailing comma)
- Неэкранированные кавычки
- Комментарии `//` (не поддерживаются в JSON)

### 8. Runbook: Клиенты не получают IP-адреса

**Симптомы:** Клиенты получают APIPA (169.254.x.x) или не получают адрес.

**Диагностика:**
```bash
# 1. Статус сервиса
systemctl status kea-dhcp4
journalctl -u kea-dhcp4 --since "5 min ago"

# 2. Валидация конфигурации
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf

# 3. Прослушивание трафика
tcpdump -i eth0 -n udp port 67 -c 20
# Ожидаем: DHCPDISCOVER → DHCPOFFER → DHCPREQUEST → DHCPACK

# 4. Проверка интерфейсов
ip -4 addr show
# Убедиться, что интерфейс в interfaces-config существует

# 5. Проверка через REST API
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# 6. Firewall
ss -nlup | grep :67
nft list ruleset | grep 67
```

Типичные причины:
- Интерфейс не указан в `interfaces-config`
- Raw sockets требуют root
- Firewall блокирует UDP 67/68
- Hook-библиотека не загружается

---

## Дополнительная информация

### Backup и Recovery

```bash
# Ежедневный бэкап (cron)
0 2 * * * tar czf /backup/kea-$(date +\%Y\%m\%d).tar.gz /etc/kea/ /var/lib/kea/

# Бэкап MySQL
mysqldump -u kea -p kea > /backup/kea-db-$(date +%Y%m%d).sql

# Восстановление
tar xzf /backup/kea-YYYYMMDD.tar.gz -C /
systemctl restart kea-dhcp4
```

### Capacity Planning формулы

```
Pool Size = Active Devices × (1 + Growth Rate × Months) × Safety Factor (1.2)

Lease DB Size = Active Leases × Record Size (~200 bytes)
MySQL RAM = Pool Size × Connections × 2MB per connection

Network Bandwidth = Request Rate × Packet Size (~300 bytes)
```

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полный обзор.
- **[Kea DHCP: Миграция с ISC](./kea_dhcp_migration.md)** — пошаговая миграция.
- **[Kea DHCP: Управление через Ansible](./kea_ansible_management.md)** — IaC.
- **[Kea DHCP: Безопасность и Hardening](./kea_security_hardening.md)** — TLS, SELinux, firewall.
- **[Kea DHCP: Docker/Podman](./kea_docker_deployment.md)** — контейнерное развертывание.
- **[DHCP: Инциденты и playbook'и](./dhcp_incident_playbook.md)** — реальные сценарии.
- **[Kea DHCP Documentation](https://kea.readthedocs.io/)** — официальная документация.
