# Consul DNS Caching Strategies

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

## Определения

**Consul DNS Caching** — совокупность механизмов кэширования DNS-ответов Consul на трех уровнях: агент Consul (Agent Cache), локальный DNS-резолвер ОС и клиентское приложение. Правильная конфигурация снижает нагрузку на Control Plane, уменьшает задержку service discovery и повышает отказоустойчивость при частичной недоступности кластера.

**Agent Cache** — локальный кэш на Consul-агенте, хранящий результаты HTTP API и DNS-запросов. Поддерживает background refresh и stale-if-error. TTL по умолчанию 72 часа.

**DNS TTL** — поле Time-To-Live в DNS-ответе, которое указывает downstream-резолверам, как долго кэшировать запись. Consul по умолчанию возвращает TTL=0, предотвращая кэширование на стороне клиента.

**Stale Query** — DNS-запрос, обработанный не лидером, а follower-сервером. Данные могут отличаться от актуальных на величину `max_stale`. Включается флагом `allow_stale` и ограничивается `max_stale`.

**Cache Max Age** — максимальный возраст записи в Agent Cache, после которого агент запрашивает обновление у серверов. В DNS-контексте управляется параметром `cache_max_age` в `dns_config`.

**Split-horizon DNS (DNS Views)** — Enterprise-фича, возвращающая разные IP для одного сервиса в зависимости от Admin Partition или исходного IP-диапазона.

## Основные концепции

### Уровни кэширования

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Application                        │
│                         │                                    │
│                         ▼                                    │
│              ┌──────────────────┐                            │
│              │  OS DNS Cache    │                            │
│              │  (systemd-       │                            │
│              │   resolved /     │                            │
│              │   dnsmasq)       │                            │
│              └────────┬─────────┘                            │
│                       │                                      │
│                       ▼                                      │
│              ┌──────────────────┐                            │
│              │  Consul Agent    │                            │
│              │  Cache (72h TTL) │                            │
│              │  + DNS Config    │                            │
│              │  (TTL, stale)    │                            │
│              └────────┬─────────┘                            │
│                       │                                      │
│                       ▼                                      │
│              ┌──────────────────┐                            │
│              │  Consul Server   │                            │
│              │  (authoritative) │                            │
│              └──────────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

### Consul DNS TTL

Consul по умолчанию возвращает TTL=0 для всех DNS-записей. Это предотвращает любое кэширование downstream и гарантирует актуальность данных, но создает максимальную нагрузку на серверы и увеличивает задержку каждого запроса.

Для production сред настраиваются TTL в конфигурации агента:

- **`dns_config.node_ttl`** — TTL для записей узлов (`node.service.consul`). Значение по умолчанию `0`.
- **`dns_config.service_ttl`** — карта TTL по сервисам или wildcard (`*`). Значение по умолчанию `0`.
- **`dns_config.prepared_query_ttl`** — TTL для Prepared Queries. Значение по умолчанию `0`.

### Stale чтения в DNS

Stale чтения позволяют follower-серверам отвечать на DNS-запросы, снижая нагрузку на лидера и сохраняя работоспособность при авариях.

- **`dns_config.allow_stale`** — включить stale чтения. По умолчанию `true` с Consul 0.7.1.
- **`dns_config.max_stale`** — максимально допустимая степень устаревания данных. По умолчанию `"87600h"` (10 лет), что фактически отключает ограничение.

### Agent Cache для DNS

Consul агент может кэшировать результаты DNS-запросов локально, минуя повторные обращения к серверам:

- **`dns_config.use_cache`** — включить кэширование DNS-запросов через Agent Cache. Подразумевает `allow_stale = true`.
- **`dns_config.cache_max_age`** — максимальный возраст кэшированной записи, после которого агент запрашивает обновление. В отличие от HTTP `max-age`, значение `0` означает "без ограничения" ("no max age"). Для принудительного обновления используйте `"1ns"`.

### Клиентское кэширование

Ниже уровня Consul агента кэширование происходит на узле:

- **systemd-resolved:** встроенный кэш + stub resolver. Начиная с systemd 248, caching для localhost-серверов отключен по умолчанию (`CacheFromLocalhost=no`). Для Consul DNS требуется явно включить `CacheFromLocalhost=yes`, иначе Consul DNS (127.0.0.1#8600) не будет кэшироваться.
- **dnsmasq:** локальный кэширующий DNS-резолвер. Конфигурируется через `cache-size`, `neg-ttl`, `max-ttl`.
- **nscd:** Name Service Cache Daemon. Устарел, не рекомендуется для новых развертываний.
- **Клиентское приложение:** внутренний resolver cache (например, Go `net`, glibc). Разработчики часто забывают об этом уровне.

## Практические сценарии

### 1. Конфигурация Consul Agent Cache (DNS)

```hcl
# В конфигурации агента (client.hcl)
dns_config {
  # Включить stale чтения для DNS
  allow_stale = true
  max_stale   = "10m"

  # Включить кэширование DNS через Agent Cache
  use_cache       = true
  cache_max_age   = "72h"

  # TTL для ответов DNS (по умолчанию 0s — без кэширования)
  node_ttl           = "5s"
  service_ttl {
    "*"           = "5s"
    "critical-*"  = "0s"
  }
  prepared_query_ttl = "5s"
}
```

```bash
# Применение: reload агента
consul reload

# Проверка конфигурации
consul validate /etc/consul.d/client.hcl
# → Configuration is valid

# Проверка логов агента
journalctl -u consul -f | grep -i "dns"
```

> **Важно:** `use_cache = true` подразумевает `allow_stale = true`. Если нужно строгое согласие для DNS, используйте `allow_stale = false` и настройте TTL на стороне клиента.

### 2. Настройка systemd-resolved

```ini
# /etc/systemd/resolved.conf
[Resolve]
DNS=127.0.0.1
Domains=consul
Cache=yes
CacheFromLocalhost=yes
```

```bash
# Применение
systemctl restart systemd-resolved

# Проверка
resolvectl status
# → проверяйте DNS=127.0.0.1 и Domains=consul
```

> **Важно:** `CacheFromLocalhost=yes` обязателен для Consul DNS (127.0.0.1#8600), иначе systemd-resolved не будет кэшировать ответы от localhost-серверов. Параметр `CacheFromNetwork=` не является стандартным; используйте только документированные директивы.

### 3. Настройка dnsmasq

```bash
# /etc/dnsmasq.d/consul.conf
server=/consul/127.0.0.1#8600
cache-size=1000
neg-ttl=0
max-ttl=60
local-ttl=5

# Перезапуск
systemctl restart dnsmasq

# Проверка
dig @127.0.0.1 web.service.consul A +short
# → 10.0.1.50

# Проверка TTL
dig @127.0.1.1 web.service.consul A
# → проверяйте поле TTL в ANSWER SECTION
```

### 4. Валидация кэша и TTL

```bash
# Проверка TTL DNS-записи
dig @127.0.0.1 -p 8600 web.service.consul A
# → ANSWER SECTION:
#   web.service.consul. 0 IN A 10.0.1.50
#   (TTL=0 означает, что Consul не рекомендует кэширование)

# Проверка, что TTL из dns_config.service_ttl применяется
dig @127.0.0.1 -p 8600 web.service.consul A
# → TTL должен соответствовать значению в service_ttl (например, 5s)

# Проверка заголовка Age (HTTP API)
curl -I "http://localhost:8500/v1/catalog/service/web?cached"
# → Age: 45 (секунд с момента последнего обновления от сервера)

# Проверка количества stale DNS-запросов (метрика)
curl -s http://localhost:8500/v1/metrics | grep 'consul\.dns\.stale_queries'
```

### 5. Валидация конфигурации DNS

```bash
# Проверка синтаксиса HCL перед применением
consul validate /etc/consul.d/client.hcl
# → Configuration is valid

# Проверка DNS-резолвинга
dig @127.0.0.1 -p 8600 consul.service.consul A
# → должен вернуть IP локального агента

# Проверка health-фильтрации
dig @127.0.0.1 -p 8600 web.service.consul A
# → только инстансы со status passing
```

## Валидация и мониторинг

### Команды валидации

| Команда | Назначение |
| :--- | :--- |
| `consul validate <file>` | Проверка синтаксиса конфигурации агента |
| `dig @127.0.0.1 -p 8600 <service>.service.consul A` | Проверка DNS-резолвинга |
| `dig @127.0.0.1 -p 8600 <service>.service.consul A +stats` | Проверка времени отклика и TTL |
| `consul reload` | Reload конфигурации без перезапуска агента |
| `resolvectl query <service>.service.consul` | Проверка через systemd-resolved |

### Мониторинг DNS-метрик

```bash
# Список DNS-метрик
curl -s http://localhost:8500/v1/metrics | grep '^consul\.dns\.'
```

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `consul.dns.lookups` | Counter | Общее количество DNS-запросов |
| `consul.dns.stale_queries` | Counter | Количество DNS-запросов, обслуженных с задержкой >5s |
| `consul.dns.software` | Counter | DNS-запросы, обработанные программно (не по кэшу) |
| `consul.dns.cached` | Counter | DNS-запросы, обслуженные из кэша |

### Настройка алертов (Prometheus)

```yaml
groups:
  - name: consul_dns
    rules:
      - alert: ConsulDNSHighStaleQueries
        expr: rate(consul_dns_stale_queries[5m]) > 0.1 * rate(consul_dns_lookups[5m])
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Высокий процент stale DNS-запросов"
          description: "{{ $value | humanizePercentage }} DNS-запросов обслуживаются устаревшими данными"

      - alert: ConsulDNSLookupSpike
        expr: rate(consul_dns_lookups[5m]) > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Всплеск DNS-запросов к Consul"
```

## Устранение неполадок

### Клиенты получают устаревшие IP

- **Причина:** Слишком высокий TTL в OS DNS кэше (systemd-resolved или dnsmasq).
- **Диагностика:**
  ```bash
  dig @127.0.0.1 -p 8600 web.service.consul A +stats
  # → проверяйте поле TTL; если TTL > 0, значит Consul возвращает кэшируемые записи

  resolvectl query web.service.consul
  # → проверяете TTL в ответе systemd-resolved
  ```
- **Решение:** Уменьшите `dns_config.service_ttl` или `dns_config.node_ttl` до `"1s"`–`"5s"`. Убедитесь, что `CacheFromLocalhost=yes` включен в systemd-resolved.

### DNS возвращает пустой ответ при недоступности серверов

- **Причина:** Кэш агента истек (`cache_max_age` exceeded), а серверы недоступны. Consul не может обновить кэш и возвращает ошибку.
- **Диагностика:**
  ```bash
  dig @127.0.0.1 -p 8600 web.service.consul A
  # → NXDOMAIN или SERVFAIL

  consul monitor -log-level=debug
  # → ищите ошибки подключения к серверам
  ```
- **Решение:** Уменьшите `cache_max_age` до разумного значения (например, `"72h"`). Для HTTP API используйте `Cache-Control: max-age=30, stale-if-error=259200`. Для DNS включите `use_cache = true` и `allow_stale = true`.

### Высокая нагрузка на Consul серверы

- **Диагностика:**
  ```bash
  curl -s http://localhost:8500/v1/metrics | grep '^consul\.dns\.'
  # → consul_dns_lookups высокий

  consul monitor
  # → ищите высокую утилизацию CPU/лидера
  ```
- **Решение:** 
  1. Увеличьте `dns_config.service_ttl` и `node_ttl` на агентах (например, `"10s"`).
  2. Включите `use_cache = true` для локального кэширования на агентах.
  3. Разместите `dnsmasq` или `systemd-resolved` между приложениями и Consul DNS.
  4. Увеличьте количество серверов для распределения нагрузки.

### DNS возвращает только subset сервисов

- **Причина:** По умолчанию Consul DNS возвращает только инстансы со статусом `passing`. Сервисы в `warning` или `critical` исключаются.
- **Диагностика:**
  ```bash
  dig @127.0.0.1 -p 8600 web.service.consul A
  # → пустой ответ, хотя сервис зарегистрирован

  consul catalog service web -node-address
  # → проверяйте статус checks
  ```
- **Решение:** Исправьте failing checks. Для диагностики можно использовать HTTP API с `?passing=false`:
  ```bash
  curl "http://localhost:8500/v1/catalog/service/web?passing=false"
  ```

### Разная консистентность между DNS и HTTP API

- **Причина:** DNS по умолчанию использует `allow_stale`, а HTTP API может использоваться с `consistent` режимом. Лидер и followers могут расходиться на несколько миллисекунд.
- **Диагностика:**
  ```bash
  dig @127.0.0.1 -p 8600 web.service.consul A +short
  curl -s "http://localhost:8500/v1/catalog/service/web?passing" | jq '.[].ServiceAddress'
  ```
- **Решение:** Для строгой консистентности в DNS установите `dns_config.allow_stale = false`. Это увеличит нагрузку на лидера, но гарантирует согласованность.

## Лучшие практики

- **Zero TTL по умолчанию:** Consul возвращает TTL=0. Это правильно для динамических сред. Кэшируйте на стороне клиента.
- **TTL стратегия:**
  - Production: DNS TTL `"0s"`–`"5s"` + OS cache `5s`–`10s`.
  - Staging: DNS TTL `"5s"`–`"10s"` допустим.
  - Static services: DNS TTL `"30s"`–`"60s"`.
- **Stale чтения:** Для production включите `allow_stale = true` и `max_stale = "10m"`. Это сохраняет работоспособность DNS при авариях кластера.
- **Agent Cache:** Включайте `use_cache = true` на агентах для снижения числа обращений к серверам. Настройте `cache_max_age` в зависимости от tolerances к устареванию.
- **OS DNS cache:** Всегда размещайте `systemd-resolved` или `dnsmasq` между приложениями и Consul DNS (порт 8600). Не обращайтесь напрямую к 8600 из приложений без локального кэша.
- **CacheFromLocalhost=yes:** В systemd-resolved включите кэширование для localhost-серверов, иначе Consul DNS не будет кэшироваться.
- **Мониторинг:** Отслеживайте `consul.dns.stale_queries` и `consul.dns.lookups`. Рост stale-доли выше 10% указывает на проблемы с кворумом или сетью.
- **Валидация:** Всегда проверяйте TTL через `dig` после изменения конфигурации. Используйте `consul validate` перед reload.
- **Health checks:** DNS возвращает только passing-инстансы. Для troubleshooting добавляйте `?passing=false` к HTTP API запросам.
- **Разделение TTL:** Используйте wildcard `*` в `service_ttl` для общих настроек и конкретные префиксы для критичных сервисов. Устанавливайте `"0s"` для сервисов, где устаревание недопустимо.
- **Rollback plan:** При изменении TTL мониторьте `consul.dns.lookups` и latency. Если нагрузка растет — откатывайте изменения через `consul reload` с предыдущей конфигурацией.

## Граничные случаи

- **Zero TTL:** Consul возвращает TTL=0 по умолчанию. Клиенты должны кэшировать агрессивно, иначе возникает шторм запросов к серверам.
- **Large clusters (>5000 узлов):** Gossip-обновления и DNS-запросы создают пиковую нагрузку. Увеличивайте TTL, используйте `use_cache = true` и `stale` чтения.
- **Multi-DC:** DNS-запросы возвращают сервисы только локального ДЦ. Для cross-DC discovery используйте Prepared Queries или explicit DC в запросе.
- **Stale on leader:** Флаг `allow_stale` на лидере не имеет эффекта — лидер всегда отвечает согласованными данными. Stale срабатывает только на followers.
- **Enterprise-only:** DNS Views (Split-horizon DNS) доступны только в Consul Enterprise. Для Community Edition используйте отдельные кластеры или prefixes.
- **Agent Cache vs DNS Cache:** `use_cache` включает Agent Cache для DNS, но TTL в DNS-ответе (node_ttl/service_ttl) управляет кэшированием downstream-резолверами. Это независимые механизмы.
- **cache_max_age = 0:** В Consul значение `0` означает "no max age" (без ограничения срока), в отличие от стандартного HTTP `max-age=0` (принудительное обновление). Для принудительного обновления используйте `"1ns"`.
- **systemd-resolved + Consul DNS:** Начиная с systemd 248, `CacheFromLocalhost=no` по умолчанию. Если Consul DNS слушает на 127.0.0.1, кэширование отключено. Явно установите `CacheFromLocalhost=yes`.
- **Prepared Queries и TTL:** `prepared_query_ttl` управляет TTL только для Prepared Queries, не для обычных сервисных записей.
- **Конфликт с static config:** Если агент запущен со статическими флагами `-dns-port` или `-recursor`, они переопределяют соответствующие поля в конфигурации файла. Используйте один подход.
- **Гибридные топологии (K8s + VM):** В Kubernetes Consul Dataplane управляет DNS через CoreDNS/Envoy. Настройки `dns_config` применяются к Consul Dataplane и client agent'ам на узлах. Убедитесь, что TTL согласованы между уровнями.

## Дополнительная информация

- **[Consul DNS Configuration](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/dns)** — справочник `dns_config`.
- **[Consul DNS Caching](https://developer.hashicorp.com/consul/docs/discover/dns/scale)** — масштабирование DNS через кэширование.
- **[Agent Caching](https://developer.hashicorp.com/consul/api-docs/features/caching)** — HTTP API кэширование (содержит `stale-if-error`).
- **[Consul DNS Interface](./consul_service_catalog.md)** — обзор DNS-интерфейса и types запросов.
- **[Consul Service Catalog](./consul_service_catalog.md)** — каталог сервисов, DNS Views (Enterprise).
- **[Consul Consistency](./consul_consensus.md)** — режимы консистентности, stale чтения в Raft.
- **[Consul CLI Reference](./consul_cli_reference.md)** — флаг `-stale` для CLI и HTTP API.
- **[Consul Telemetry Reference](./consul_telemetry.md)** — метрики `consul.dns.*`.
- **[Consul Health Checks](./consul_health_checks.md)** — влияние health checks на DNS-ответы.
- **[Consul Service Mesh](./consul_service_mesh.md)** — Service Mesh и DNS в контексте Connect.
