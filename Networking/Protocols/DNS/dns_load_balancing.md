# Балансировка нагрузки через DNS

## Определения

**DNS Round-Robin** — метод балансировки нагрузки, при котором DNS-сервер возвращает несколько A/AAAA-записей для одного имени и циклически меняет их порядок. Клиент получает список IP и подключается к первому в списке. Не учитывает загрузку серверов или их доступность.

**Weighted DNS Round-Robin** — расширение обычного round-robin, при котором каждой A/AAAA-записи присваивается вес (weight). Сервер возвращает записи с учётом весов: запись с весом 70 вернётся в 70% случаев, запись с весом 30 — в 30%. Используется для распределения трафика между серверами разной мощности.

**DNS-based Failover** — механизм автоматического удаления нерабочих серверов из DNS-ответа на основе health checks. Если сервер не отвечает на проверочный запрос (ICMP ping, HTTP 200, TCP connect), его A-запись временно удаляется из зоны. При восстановлении — добавляется обратно.

**Health Check (проверка доступности)** — периодическая проверка состояния сервера. Типы: ICMP ping (низкоуровневый), TCP connect (проверка порта), HTTP/HTTPS (проверка приложения), DNS query (проверка DNS-сервера).

**TTL (Time To Live)** — время жизни DNS-записи в кэше клиента. При балансировке через DNS TTL определяет, как часто клиенты будут запрашивать новый список IP. Низкий TTL (60 сек) — быстрое переключение, но больше нагрузки на DNS. Высокий TTL (3600 сек) — меньше нагрузки, но медленное переключение.

---

## Базовые концепции

### Типы DNS-балансировки

| Метод | Механизм | Учёт загрузки | Health Check | Сложность | Использование |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Round-Robin** | Циклическая ротация A-записей | Нет | Нет | Низкая | Простые сценарии |
| **Weighted RR** | A-записи с весами | Нет | Нет | Низкая | Серверы разной мощности |
| **Geo-DNS** | A-записи по геолокации клиента | Нет | Нет | Средняя | CDN, глобальные сервисы |
| **Anycast** | BGP-ретрансляция одного IP | Да (сетевая) | Да (BGP) | Высокая | Крупные инфраструктуры |
| **GSLB** | Динамическое управление DNS | Да | Да | Высокая | Критические сервисы |

### Ограничения DNS-балансировки

DNS-балансировка — не замена специализированным LB (HAProxy, Nginx, Keepalived). Ключевые ограничения:

| Проблема | Описание | Решение |
| :--- | :--- | :--- |
| **Нет health awareness** | Round-Robin не проверяет доступность серверов | Используйте DNS Failover или GSLB |
| **Кэширование клиентов** | Клиент кэширует DNS-ответ на время TTL | Снизьте TTL до 60 сек |
| **Sticky sessions** | Клиент «прилипает» к одному IP до истечения TTL | Используйте cookie-based sticky sessions |
| **Разная загрузка серверов** | Round-Robin не учитывает мощность серверов | Используйте Weighted DNS или GSLB |
| **Медленное переключение** | При падении сервера клиенты продолжают слать трафик | Снизьте TTL + health checks |

### Архитектура DNS Load Balancing

```text
                        ┌──────────────────┐
                        │   DNS-сервер      │
                        │  (round-robin     │
                        │   или weighted)   │
                        └────────┬─────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼─────┐ ┌───▼───────┐ ┌──▼────────┐
              │ Server 1   │ │ Server 2  │ │ Server 3  │
              │ 192.0.2.1  │ │ 192.0.2.2 │ │ 192.0.2.3 │
              │ Weight: 70 │ │ Weight: 20│ │ Weight: 10│
              └────────────┘ └───────────┘ └───────────┘
```

---

## Практические сценарии

### Предусловия

```bash
# Установка инструментов
sudo apt install dnsutils bind9-utils

# Проверка текущих A-записей
dig example.com A +short
# → 192.0.2.1
# → 192.0.2.2
# → 192.0.2.3
```

### 1. Round-Robin в BIND

**Конфигурация зоны (`/etc/bind/zones/example.com.db`):**
```dns
$TTL 300
@   IN  SOA ns1.example.com. admin.example.com. (
        2026082501  ; Serial
        3600        ; Refresh
        900         ; Retry
        1209600     ; Expire
        300         ; Negative TTL
)

@       IN  NS  ns1.example.com.
ns1     IN  A   10.0.0.1

; Round-Robin: три A-записи для одного имени
www     IN  A   192.0.2.1
www     IN  A   192.0.2.2
www     IN  A   192.0.2.3
```

```bash
# Применение
sudo rndc reload example.com

# Проверка (каждый запрос возвращает разный порядок)
for i in $(seq 1 6); do
  dig @127.0.0.1 www.example.com +short
done
# → 192.0.2.1
# → 192.0.2.2
# → 192.0.2.3
# → 192.0.2.1
# → 192.0.2.2
# → 192.0.2.3
```

### 2. Weighted Round-Robin в BIND

**Конфигурация с весами:**
```dns
; Weighted: серверы разной мощности
www     IN  A   192.0.2.1    ; 70% трафика
www     IN  A   192.0.2.2    ; 20% трафика
www     IN  A   192.0.2.3    ; 10% трафика
```

**Проверка распределения:**
```bash
# Отправка 100 запросов и подсчёт распределения
for i in $(seq 1 100); do
  dig @127.0.0.1 www.example.com +short | head -1
done | sort | uniq -c | sort -rn
# → 71 192.0.2.1  (71% — сервер с весом 70)
# → 20 192.0.2.2  (20% — сервер с весом 20)
# →  9 192.0.2.3  (9% — сервер с весом 10)
```

### 3. DNS Failover через nsupdate (динамическое обновление)

**Скрипт health check + failover:**
```bash
#!/bin/bash
# dns-failover.sh — проверка доступности и удаление/добавление A-записей

ZONE="example.com"
RECORD="www"
TTL=60

# Функция проверки здоровья сервера
check_health() {
    local ip=$1
    # HTTP health check
    curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://$ip/health" | grep -q "200"
    return $?
}

# Проверка каждого сервера
for ip in 192.0.2.1 192.0.2.2 192.0.2.3; do
    if check_health $ip; then
        echo "OK: $ip is healthy"
        # Добавить запись, если отсутствует
        nsupdate -l << EOF
server 127.0.0.1
zone $ZONE
update add $RECORD.$ZONE $TTL A $ip
send
EOF
    else
        echo "FAIL: $ip is down"
        # Удалить запись
        nsupdate -l << EOF
server 127.0.0.1
zone $ZONE
update delete $RECORD.$ZONE A $ip
send
EOF
    fi
done
```

```bash
# Добавление в crontab (проверка каждые 30 сек)
* * * * * /opt/dns-failover.sh >> /var/log/dns-failover.log 2>&1
* * * * * sleep 30 && /opt/dns-failover.sh >> /var/log/dns-failover.log 2>&1
```

### 4. Несколько адресов под одним именем в Docker

Встроенный DNS Docker возвращает все адреса контейнеров, объявленных под одним сетевым псевдонимом, но **случайно перемешивает их порядок при каждом ответе** — в отличие от классического DNS round-robin, где позиция адреса определяется его весом или номером. Реальное распределение нагрузки выполняет клиент, перебирающий все адреса из ответа.

```bash
# Docker Network Alias: все адреса возвращаются, порядок меняется от запроса к запросу
docker run -d --name web1 --network-alias web nginx
docker run -d --name web2 --network-alias web nginx

# Проверка: оба адреса в ответе
dig @127.0.0.11 web +short
# → 172.18.0.2
# → 172.18.0.3

# Повторный запрос — порядок отличается, но не следует по кругу
dig @127.0.0.11 web +short
# → 172.18.0.3
# → 172.18.0.2
```

Ограничение: ответы по UDP при нехватке места усекаются удалением записей, поэтому при большом числе адресов клиент должен повторять запрос по TCP. Механика встроенного резолвера — в [Docker: DNS и Service Discovery](../../../Docker/Docker_network/dns_and_service_discovery.md).

### 5. Geo-DNS (географическая балансировка)

```dns
; Geo-DNS: разные ответы для разных регионов
$ORIGIN example.com.
$TTL 300

; Для клиентов из Европы
@       IN  A   192.0.2.10    ; EU server
        IN  A   192.0.2.11    ; EU backup

; Для клиентов из Азии (через ECS или Anycast)
; Определяется на уровне GSLB-сервера
```

**Диагностика Geo-DNS:**
```bash
# Проверка через разные клиентские подсети
dig @dns-server example.com +subnet=203.0.113.0/24 +short
# → 192.0.2.20  (Asia server)

dig @dns-server example.com +subnet=198.51.100.0/24 +short
# → 192.0.2.10  (EU server)
```

### 6. GSLB-сценарий с health check (базовый)

```bash
# Скрипт GSLB на bash (упрощённый)
#!/bin/bash
# gslb-check.sh

SERVERS=("192.0.2.1:80" "192.0.2.2:80" "192.0.2.3:80")
ZONE="example.com"
RECORD="api"
TTL=30

for server in "${SERVERS[@]}"; do
    ip=${server%%:*}
    port=${server##*:}

    if nc -z -w 2 $ip $port 2>/dev/null; then
        echo "UP: $ip:$port"
        nsupdate -l << EOF
server 127.0.0.1
zone $ZONE
update add $RECORD.$ZONE $TTL A $ip
send
EOF
    else
        echo "DOWN: $ip:$port"
        nsupdate -l << EOF
server 127.0.0.1
zone $ZONE
update delete $RECORD.$ZONE A $ip
send
EOF
    fi
done
```

---

## Лучшие практики

*   **Используйте TTL = 60 сек для критических сервисов:** Это обеспечивает быстрое переключение при отказе сервера. Для менее критичных сервисов — TTL 300-600 сек.
*   **Не полагайтесь на чистый Round-Robin:** Он не проверяет доступность серверов. Добавляйте health checks или используйте GSLB.
*   **Комбинируйте DNS + application-level LB:** DNS балансирует между кластерами (L3/L4), application-level LB — внутри кластера (L7).
*   **Мониторьте распределение трафика:** Если один сервер получает больше трафика — проверьте, не «застрял» ли кэш DNS у клиентов.
*   **Для Anycast используйте BGP + health checks:** Anycast — 가장 высокий уровень балансировки, но требует BGP-интеграции и мониторинга.
*   **Weighted DNS для canary-релизов:** Используйте вес 90/10 для постепенного rollout новой версии.
*   **Проверяйте DNS-ответы через разные резолверы:** Публичные резолверы (8.8.8.8, 9.9.9.9) могут кэшировать по-разному.

---

## Дополнительная информация

### Инструментарий

- **nsupdate:** Динамическое обновление DNS-записей (RFC 2136).
- **dig:** Проверка DNS-ответов и распределения.
- **curl / nc:** Health checks (HTTP и TCP).
- **dnspyre:** Бенчмаркинг DNS-балансировки.

### Ключевые RFC

- **RFC 1794:** DNS Support for Load Balancing.
- **RFC 2181:** Clarifications to the DNS Specification (TTL).
- **RFC 2136:** Dynamic Updates in the Domain Name System.
- **RFC 7871:** Client Subnet in DNS Queries (ECS).

### Связанные разделы

- [Продвинутые сценарии DNS](./dns_advanced.md) — Geo-DNS, GSLB, Anycast, ECS.
- [Зоны DNS и SOA](./dns_zones.md) — настройка зон и динамические обновления.
- [Тестирование производительности DNS](./dns_performance_testing.md) — бенчмаркинг DNS-балансировки.
- [Мониторинг DNS](./dns_monitoring.md) — проверка доступности серверов.
- [Docker: DNS и Service Discovery](../../../Docker/Docker_network/dns_and_service_discovery.md) — DNS round-robin в Docker.
