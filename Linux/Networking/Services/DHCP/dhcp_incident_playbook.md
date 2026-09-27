# DHCP: Реальные инциденты и Playbook'и

---

## Определения

**Incident Response (Реагирование на инциденты)** — процесс обнаружения, анализа, локализации и устранения инцидентов, связанных с DHCP-сервисом. Включает: время реакции (MTTR), влияние на пользователей, корневую причину и меры предотвращения.

**Playbook (Пособие по инцидентам)** — пошаговая инструкция для оператора, описывающая действия при определённом типе инцидента. Снижает время реакции и исключает пропуск критических шагов.

**Runbook (Рабочая инструкция)** — детализированная техническая инструкция для конкретного сервиса, включающая команды, ссылки на конфигурации и критерии успеха.

**MTTR (Mean Time To Repair)** — среднее время восстановления сервиса после инцидента. Для DHCP-сервера критичный порог: >5 минут = warning, >15 минут = critical.

**SLA (Service Level Agreement)** — соглашение об уровне сервиса. Для DHCP: доступность >99.9%, время отклика <500ms, потеря <0.1% аренд.

---

## Основные концепции

### Классификация DHCP-инцидентов

| Уровень | Тип инцидента | Влияние | MTTR Цель |
|:--- |:--- |:--- |:--- |
| **P1 (Critical)** | DHCP-сервер недоступен | Все клиенты без IP | <5 мин |
| **P1 (Critical)** | Pool exhaustion | Клиенты без IP | <10 мин |
| **P2 (High)** | Failover degraded | Работает 1 сервер | <15 мин |
| **P2 (High)** | Rogue DHCP | Клиенты с неверным IP | <10 мин |
| **P3 (Medium)** | DNS не обновляется | DDNS записи устарели | <30 мин |
| **P3 (Medium)** | Медленный DORA | Задержка >2 сек | <30 мин |
| **P4 (Low)** | Abandoned leases растёт | Медленное заполнение пула | <2 часа |

### Метрики для мониторинга инцидентов

| Метрика | Источник | Порог warning | Порог critical |
|:--- |:--- |:--- |:--- |
| `dhcp_leases_active / dhcp_leases_total` | Prometheus | >70% | >90% |
| `rate(dhcp_ack_total[5m])` | Prometheus | <10/min | ==0/min |
| `rate(dhcp_nak_total[5m]) / rate(dhcp_ack_total[5m])` | Prometheus | >5% | >20% |
| `dhcp_failover_state` | Kea REST API | != 0 (normal) | partner-down |
| `dhcp_response_time_avg` | tcpdump | >500ms | >2000ms |
| `dhcp_leases_abandoned` | Lease-файл | >5 | >20 |

---

## Практические сценарии: Playbook'и

### Playbook 1: DHCP-сервер недоступен (P1)

**Симптомы:** Клиенты получают APIPA (169.254.x.x), нет DHCPACK, логи пусты.

**Диагностика (5 шагов):**

```bash
# Шаг 1: Статус сервиса
systemctl status kea-dhcp4
# → Ожидаем: active (running)
# → Если failed: перейти к шагу 2

# Шаг 2: Проверка ошибок в логах
journalctl -u kea-dhcp4 --since "10 min ago" | grep -iE "error|fail|fatal"
# → Ожидаем: нет ошибок
# → Если есть: исправить и перезапустить

# Шаг 3: Проверка синтаксиса конфигурации
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf
# → Ожидаем: Ok
# → Если error: исправить JSON

# Шаг 4: Проверка портов
ss -nlup | grep -E ':67|:68|:8000'
# → Ожидаем: kea-dhcp4 слушает UDP 67/68

# Шаг 5: Проверка трафика
tcpdump -i any -n udp port 67 -c 5
# → Ожидаем: DHCPDISCOVER от клиентов
```

**Действия:**

| Шаг | Действие | Время |
|:--- |:--- |:--- |
| 1 | Перезапуск сервиса | 30 сек |
| 2 | Если не помогло — проверка конфигурации | 2 мин |
| 3 | Если конфиг невалиден — откат из Git | 5 мин |
| 4 | Если диск забит — очистка логов | 5 мин |
| 5 | Если сеть — проверка firewall/interfaces | 10 мин |

**Escalation:** Если за 5 минут не удалось восстановить → переход на резервный сервер (если HA) или откат на предыдущую конфигурацию.

### Playbook 2: Pool Exhaustion (P1)

**Симптомы:** `no free leases` в логах, клиенты не получают IP, лимит пула исчерпан.

**Диагностика:**

```bash
# Шаг 1: Подсчёт активных аренд
# ISC DHCP:
grep -c "binding state active" /var/lib/dhcp/dhcpd.leases

# Kea DHCP:
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# Шаг 2: Проверка размера пула
grep "range" /etc/kea/kea-dhcp4.conf
# Или Kea REST API:
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "subnet4-get", "args": {"id": 1}}' | jq

# Шаг 3: Поиск абонентов с длинной арендой
# Kea DHCP:
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-get-all"}' | jq '.arguments.leases[] | select(.valid-lft > 604800)'

# Шаг 4: Проверка на Rogue DHCP
tcpdump -i any -n "udp port 67 and udp[8:1] == 2" -c 10
# → Смотрим dhcp.option.dhcp_server_id — должен быть IP вашего сервера
```

**Решения (в порядке приоритета):**

| Действие | Описание | Время |
|:--- |:--- |:--- |
| 1 | Увеличить `range` в конфигурации | 2 мин |
| 2 | Сократить `valid-lifetime` (например, 86400 → 3600) | 2 мин |
| 3 | Очистить expired/abandoned через REST API | 1 мин |
| 4 | Проверить и удалить Rogue DHCP | 10 мин |

```bash
# Очистка expired leases (Kea)
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-del", "arguments": {"state": "expired"}}' | jq

# Временное сокращение аренды (без перезапуска)
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "config-set", "arguments": {"Dhcp4": {"valid-lifetime": 3600}}}' | jq
```

### Playbook 3: Failover Degraded (P2)

**Симптомы:** Один из серверов в `communications-interrupted` или `partner-down`.

**Диагностика:**

```bash
# Шаг 1: Проверка состояния failover
journalctl -u kea-dhcp4 --since "1 hour ago" | grep -i "ha\|failover\|partner"
# → Ожидаем: normal
# → Если communications-interrupted: проблема со связью

# Шаг 2: Проверка сетевой связности между серверами
ping -c 3 <partner_ip>
nc -zv <partner_ip> 647  # Для ISC DHCP
nc -zv <partner_ip> 8000  # Для Kea HA

# Шаг 3: Проверка версий Kea на обоих серверах
kea-dhcp4 --version
# → Версии должны совпадать

# Шаг 4: Проверка времени (NTP/Chrony)
chronyc tracking
# → Разница < 1 сек
```

**Действия:**

| Состояние | Действие |
|:--- |:--- |
| `communications-interrupted` | Проверить сеть, увеличить `max-response-delay` |
| `partner-down` | Проверить, что Primary вернулся, дождаться синхронизации |
| `recover` | Дождаться завершения синхронизации (не перезапускать!) |

```bash
# Принудительный переход в partner-down (Kea)
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "ha-sync", "arguments": {"server-name": "server-2", "timeout": 30000}}' | jq
```

### Playbook 4: Rogue DHCP (P2)

**Симптомы:** Клиенты получают IP из неожиданного диапазона, DNS-записи ведут на фишинговые серверы.

**Диагностика:**

```bash
# Шаг 1: Обнаружение всех DHCP-серверов
nmap --script broadcast-dhcp-discover 2>/dev/null | grep -A5 "Server"
# Или
sudo tcpdump -i any -n "udp port 67 and udp[8:1] == 2" -c 10
# → Смотрим Source IP всех OFFER

# Шаг 2: Определение MAC-адреса Rogue-сервера
tcpdump -i any -n "udp port 67" -vv | grep -E "chaddr|giaddr"
# → chaddr rogue-сервера

# Шаг 3: Поиск Rogue-сервера в сети
#arpa -a | grep <rogue_mac>
# Или
nmap -sP 10.0.0.0/24 && arp -a | grep <rogue_mac>
```

**Действия:**

| Шаг | Действие | Время |
|:--- |:--- |:--- |
| 1 | Найти физическое устройство по MAC | 5-30 мин |
| 2 | Отключить порт на коммутаторе | 1 мин |
| 3 | Включить DHCP Snooping (если не включён) | 10 мин |
| 4 | Проверить клиентов (смена DNS, шлюза) | 10 мин |

```bash
# Cisco: быстрое отключение Rogue-порта
interface <RoguePort>
  shutdown
  description "BLOCKED - Rogue DHCP detected $(date)"
```

### Playbook 5: Медленный DORA (P3)

**Симптомы:** Клиенты получают IP через 5-30 секунд вместо <1 секунды.

**Диагностика:**

```bash
# Шаг 1: Замер времени DORA
sudo tcpdump -i any -n "udp port 67" -vv -c 20 | grep -E "DHCPDISCOVER|DHCPOFFER|DHCPACK"
# → Замеряем время между DISCOVER и OFFER

# Шаг 2: Проверка дисковой подсистемы
iostat -x 1 5
# → Смотрим await (>20ms = проблема)

# Шаг 3: Проверка нагрузки на CPU
top -bn1 | head -5
# → dhcpd/kea-dhcp4 не должен потреблять >50% CPU

# Шаг 4: Проверка сложности классов
grep -c "class\|subclass" /etc/kea/kea-dhcp4.conf
# → >10 классов =潜在的 проблема
```

**Решения:**

| Причина | Решение |
|:--- |:--- |
| Медленный диск (HDD) | Перейти на SSD/NVMe для lease-файла |
| fsync в dhcpd (ISC) | Перейти на Kea (batch-запись) |
| Сложные class-выражения | Упростить логику классификации |
| Высокая нагрузка CPU | Разделить на несколько инстансов Kea |

### Playbook 6: DDNS не работает (P3)

**Симптомы:** DHCP выдаёт IP, но DNS-записи не обновляются.

**Диагностика:**

```bash
# Шаг 1: Проверка DDNS-конфигурации Kea
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "config-get"}' | jq '.arguments.Dhcp4.ddns-update-info'

# Шаг 2: Проверка TSIG-ключа в BIND
sudo named-checkconf /etc/bind/named.conf.local
dig -y hmac-sha256:ddns-key:secret @10.0.0.10 example.com SOA

# Шаг 3: Проверка логов DDNS
journalctl -u kea-dhcp-ddns -f | grep -i "update\|error"
# Или
grep -i "ddns\|dns" /var/log/kea/kea-dhcp4.log

# Шаг 4: Проверка прав доступа к зоне BIND
ls -la /etc/bind/db.corp.example.com
# → Должен принадлежать bind:bind
```

---

## Дополнительная информация

### Postmortem-шаблон

```markdown
# Postmortem: DHCP Pool Exhaustion

## Дата: 2026-09-15
## Инженер: [имя]
## MTTR: 12 минут

## Временная шкала
- 14:30 — Алерт: Pool utilization >90%
- 14:32 — Инженер начал диагностику
- 14:35 — Обнаружено: lease-time = 86400, пул = 100 адресов
- 14:38 — Увеличен пул до 200 адресов
- 14:42 — Пул восстановлен, клиенты получают IP

## Корневая причина
Пул на 100 адресов при 150 активных клиентах. lease-time = 24ч.

## Влияние
50 клиентов без IP в течение 12 минут.

## Действия
1. Увеличить пул до 200 адресов
2. Настроить алерт на 70% utilization
3. Рассмотреть сокращение lease-time для WiFi
```

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полная конфигурация Kea.
- **[Диагностика DHCP](../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)** — tcpdump, Wireshark, debug.
- **[Мониторинг DHCP](../../../Networking/Protocols/DHCP/dhcp_monitoring_observability.md)** — Prometheus, Grafana, SIEM.
- **[Безопасность DHCP](../../../Networking/Protocols/DHCP/dhcp_security.md)** — защита от Rogue DHCP.
- **[ISC DHCP: Failover](./isc_dhcp_server_failover.md)** — настройка отказоустойчивости.
- **[Kea DHCP: Миграция](./kea_dhcp_migration.md)** — пошаговая миграция.
