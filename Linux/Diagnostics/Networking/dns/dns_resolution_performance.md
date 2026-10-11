# Производительность DNS-резолвинга

## Определения

**DNS-латентность** — временной интервал между инициированием запроса на разрешение имени и получением IP-адреса. Это критический компонент «первого байта» (TTFB), так как любая задержка здесь блокирует установление TCP/QUIC-соединения.

**Хвостовая латентность (Tail Latency, p95/p99)** — задержка для самых медленных запросов. В DNS она часто вызвана таймаутами при опросе нескольких серверов (nameservers), потерями UDP-пакетов или неоптимальными настройками `ndots`.

**DNS over QUIC (DoQ)** — современный стандарт (RFC 9250), обеспечивающий минимальную латентность за счет исключения head-of-line blocking (в отличие от DoH/DoT) и поддержки 0-RTT возобновления соединений.

**Отрицательное кэширование (Negative Caching)** — механизм сохранения ответов `NXDOMAIN` (домен не существует) или `NODATA` в локальном кэше. Позволяет избежать повторных запросов к upstream для несуществующих доменов в течение TTL-периода. В `systemd-resolved` управляется автоматически, в `nscd` — параметром `negative-time-to-live` (см. **[nscd](../../../Networking/Services/nscd.md)**).

**Блокирующий резолвер (Blocking Resolver)** — стандартная реализация `getaddrinfo()` в **glibc**, которая останавливает поток приложения до завершения DNS-запроса. В **musl** (Alpine) поведение отличается: запросы A и AAAA отправляются параллельно, что может снижать задержку при корректно настроенной сети, но увеличивает её при сбоях IPv6. Детали: **[glibc vs musl](../../../Core/glibc_vs_musl.md)**.

**UDP-фрагментация и MTU** — DNS по умолчанию использует UDP. Если ответ превышает MTU (обычно 1500 байт), происходит фрагментация на уровне IP. Блокирывающие фаерволы или NAT могут отбрасывать фрагменты, что приводит к таймауту и переходу на TCP (задержка +300–500 мс). Критично для DNSSEC-ответов (>512 байт) и записей с большим количеством IP (Headless Service в K8s).

## Архитектура разрешения имён

Понимание уровней DNS-резолвинга необходимо для диагностики задержек:

```
Приложение (getaddrinfo / nslookup / dig)
    │
    ▼
┌─────────────────────────────────────────┐
│ Уровень 1: Прикладной резолвер          │
│ • glibc getaddrinfo() — блокирующий    │
│ • musl — параллельные A/AAAA запросы    │
│ • Go/Java — встроенные резолверы        │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ Уровень 2: NSS (/etc/nsswitch.conf)    │
│ • files → /etc/hosts                    │
│ • resolve → systemd-resolved (D-Bus)   │
│ • dns → /etc/resolv.conf → UDP/TCP     │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ Уровень 3: Локальный кэш / Стаб         │
│ • systemd-resolved (127.0.0.53)        │
│ • nscd (legacy)                         │
│ • unbound (sidecar)                     │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ Уровень 4: Upstream DNS                  │
│ • Классический UDP/TCP (порт 53)        │
│ • DoT (порт 853)                        │
│ • DoH (порт 443)                        │
│ • DoQ (порт 853/udp)                    │
└─────────────────────────────────────────┘
```

## Базовые концепции

### Механизмы возникновения задержек

В Linux стандартный резолвер `getaddrinfo()` является **блокирующим**. Это означает, что поток приложения простаивает до завершения DNS-запроса. Для минимизации этого влияния современные приложения используют асинхронные библиотеки (например, `c-ares`, встроенные резолверы в Go или Node.js).

### Ключевые факторы замедления

| Фактор | Механизм влияния | Типичное влияние (2026) |
| :--- | :--- | :--- |
| **Множественные nameserver** | Опрос следующего сервера только после таймаута предыдущего. | +1000–5000 мс при сбое основного DNS. |
| **Параметр ndots и search** | В K8s (`ndots:5`) запрос `api.v1` сначала проверяется как `api.v1.svc.cluster.local`, затем `api.v1.cluster.local` и т.д. | Каскад из 3–5 лишних запросов на каждое имя. |
| **Happy Eyeballs (v2)** | Параллельный запрос A и AAAA записей. Если IPv6-префикс анонсирован, но не маршрутизируется, клиент ждет ответа. | +50–200 мс (в зависимости от реализации libc). |
| **conntrack race condition** | Состояние гонки в ядре при параллельных UDP-запросах с одного сокета. | Задержки ровно по 1000 мс или 5000 мс (таймауты ретрансмиссии). |
| **EDNS0 и ECS** | Client Subnet позволяет возвращать IP ближайшего CDN, но увеличивает размер пакета. | Возможная фрагментация UDP или переключение на медленный TCP. |
| **Негативное кэширование** | Кэширование ответов `NXDOMAIN` (домен не существует). | Если отключено — повторный проход по всей цепочке при каждой ошибке. |
| **MTU и фрагментация** | Большие ответы (DNSSEC, множественные A-записи) фрагментируются или переключаются на TCP. | +300–500 мс при переходе на TCP, полная потеря пакетов при блокировке фрагментов. |
| **DNSSEC валидация** | Проверка подписей RRSIG добавляет вычислительную нагрузку на резолвер. | +10–50 мс на резолвер (зависит от длины цепочки доверия). |

### Влияние MTU и фрагментации

Стандартный DNS-over-UDP предполагает ответы до 512 байт (без EDNS0) или до 4096 байт (с EDNS0). При превышении этих значений:

1. **IP-фрагментация:** Ответ разбивается на несколько IP-фактов. Среднее оборудование (CPE, фаерволы) часто отбрасывает фрагменты по соображениям безопасности.
2. **Truncation (TC-флаг):** Резолвер может установить флаг TC, signalling клиенту повторить запрос по TCP.
3. **Переключение на TCP:** Создаёт новое соединение, трёхстороннее рукопожатие + TLS (если DoT/DoH), что добавляет минимум 1 RTT.

**Диагностика фрагментации:**
```bash
# Проверка максимального размера UDP-ответа
dig +bufsize=4096 example.com A

# Перехват фрагментированных пакетов
sudo tcpdump -i any port 53 -nn -v | grep -i "frag\|reassembled"
```

### Оптимизация параметров resolv.conf

- **`options timeout:1`**: Снижение ожидания до 1 секунды (критично для микросервисов).
- **`options attempts:2`**: Ограничение попыток для предотвращения бесконечного ожидания в p99.
- **`options rotate`**: Балансировка нагрузки между указанными серверами (nameservers).
- **`options trust-ad`**: Позволяет приложению доверять флагу аутентичности DNSSEC от резолвера, пропуская локальную проверку.
- **`options single-request-reopen`**: Переоткрытие сокета для A и AAAA запросов (решает проблему conntrack race — только в glibc; musl/Alpine игнорирует эту опцию).
- **`options use-vc`**: Принудительное использование TCP для всех запросов (устраняет проблемы с UDP-фрагментацией, но увеличивает латентность).

*Из перечисленных опций musl (Alpine) поддерживает только `timeout`, `attempts` и `ndots`; `rotate`, `trust-ad`, `use-vc` и `single-request-reopen` — только glibc.*

## Инструменты: сравнение

Для детального бенчмаркинга DNS-серверов см. **[Тестирование производительности DNS](../../../../Networking/Protocols/DNS/dns_performance_testing.md)**. Ниже — инструменты для клиентской диагностики:

| Инструмент | Уровень | Что измеряет | Применение |
| :--- | :--- | :--- | :--- |
| **dig +stats** | Клиентский | RTT, коды ответов, размер ответа | Быстрая точечная проверка |
| **resolvectl statistics** | Системный | Hit/Miss ratio кэша systemd-resolved | Аудит локального кэша |
| **dnspyre** | Нагрузочный | p50/p95/p99, QPS, failed | Бенчмаркинг конкретного резолвера |
| **gethostlatency (bcc)** | Ядерный | Задержка getaddrinfo() на процесс | Поиск «злоупотребляющих» приложений |
| **tcpdump / Wireshark** | Сетевой | Анализ UDP/TCP, фрагментация, потери | Детальная инкапсуляция |
| **ss -unp** | Системный | Состояние UDP-сокетов, conntrack | Проверка exhaustion |

## Сводная таблица ошибок

| Симптом | RCODE / Код | Вероятная причина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- | :--- |
| Задержка ровно 1000/5000 мс | (no RCODE) | conntrack race, таймаут ретрансмиссии | `dmesg \| grep conntrack` | NodeLocal DNSCache, `single-request-reopen` (только glibc) |
| Запросы к одному домену идут каскадом | (no RCODE) | `ndots:5` + неполное имя | `cat /etc/resolv.conf \| grep ndots` | FQDN с точкой, `ndots:1` |
| `NXDOMAIN` для существующего домена | NXDOMAIN | `ndots` исказил имя, stale NXDOMAIN в кэше | `dig +trace <fqdn>.`, `resolvectl flush-caches` | FQDN, сброс кэша |
| `SERVFAIL` | SERVFAIL | Upstream недоступен, DNSSEC-ошибка | `dig @<upstream> <domain> +dnssec` | Исправить upstream, откатить DNSSEC |
| Запрос зависает на 5 секунд | (timeout) | Happy Eyeballs, сбой IPv6 | `dig A <domain>`, `dig AAAA <domain>` | Отключить AAAA через `gai.conf` |
| Медленный DNS (>200 мс p99) | (no RCODE) | Множественные nameserver, conntrack | `dig +stats`, `resolvectl statistics` | Уменьшить `timeout`, `ndots`, NodeLocal |
| Большие ответы теряются | (timeout) | Фрагментация UDP, MTU | `tcpdump -i any port 53` | Увеличить MTU, перейти на TCP/DoQ |
| `REFUSED` | REFUSED | Резолвер перегружен или закрыт | `dig @<server> <domain>` | Масштабировать резолвер, проверить ACL |

## Практические сценарии

### Сценарий 1: Дифференциальная диагностика (NSS vs Upstream)

Если `dig` работает быстро, а приложение «тормозит», проверьте цепочку разрешения в ОС.

```bash
# 1. Проверка через системный резолвер (учитывает /etc/nsswitch.conf)
getent hosts example.com

# 2. Проверка через прямой DNS запрос
dig @8.8.8.8 example.com
```
**Анализ:** Если `getent` значительно медленнее `dig`, проверьте `/etc/nsswitch.conf`. Присутствие `mdns4_minimal` или некорректная настройка `systemd-resolved` могут добавлять сотни миллисекунд. Детали: **[Порядок разрешения имён](./name_resolution.md)**.

### Сценарий 2: Бенчмаркинг и нагрузочное тестирование

Для оценки производительности DNS-инфраструктуры используйте специализированные инструменты вместо циклов с `dig`.

```bash
# Использование dnspyre (современный инструмент на Go)
dnspyre --server 10.96.0.10 --queries 1000 --concurrency 10 example.com
```
**Метрики:** Обращайте внимание на `p99` и количество `timeouts`. В стабильной сети `p99` не должен превышать RTT * 1.5. Полный методология бенчмаркинга: **[Тестирование производительности DNS](../../../../Networking/Protocols/DNS/dns_performance_testing.md)**.

### Сценарий 3: Трассировка задержек на уровне ядра (eBPF)

Использование `gethostlatency` из пакета `bcc-tools` для выявления приложений, злоупотребляющих DNS.

```bash
sudo gethostlatency
# Программа покажет задержку (LATms) для каждого процесса в системе
```

### Сценарий 4: Анализ эффективности кэширования (systemd-resolved)

Проверьте, не является ли причиной латентности постоянные промахи в кэше (cache misses).

```bash
resolvectl statistics
# Метрика "Current Cache Size" и "Hits/Misses"
```
**Совет:** Если количество промахов (Misses) растет пропорционально запросам, возможно, ваше приложение генерирует уникальные поддомены, что делает кэширование бесполезным.

### Сценарий 5: Борьба с conntrack race в высоконагруженных контейнерах

Если вы видите задержки ровно в 1 или 5 секунд в Kubernetes:

1. **Решение (Node-level):** Внедрите **NodeLocal DNSCache**. Это переведет трафик с UDP на TCP для связи с CoreDNS.
2. **Решение (Pod-level):** Добавьте параметры в `dnsConfig` (опция `single-request-reopen` действует только в glibc-образах; для Alpine/musl она игнорируется — используйте NodeLocal DNSCache или исправьте сеть):
```yaml
dnsConfig:
  options:
    - name: single-request-reopen
    - name: timeout
      value: "1"
```

### Сценарий 6: Измерение базовой латентности (Baseline)

Перед оптимизацией зафиксируйте текущие метрики:

```bash
# 1. Замер через системный резолвер (с NSS)
time getent hosts kubernetes.default.svc.cluster.local

# 2. Замер через dig (обходит NSS, прямой UDP/TCP)
dig kubernetes.default.svc.cluster.local +stats

# 3. Замер через Corefile с trace
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=0 | grep "<domain>"
```

**Ожидаемые значения (on-premise K8s):** p50 < 2 мс, p99 < 10 мс. Если p99 > 50 мс — проблема в conntrack или перегрузке CoreDNS.

### Сценарий 7: Отрицательное кэширование и NXDOMAIN-шторм

При массовом опросе несуществующих доменов (например, ботнет атака или ошибка конфигурации):

```bash
# 1. Проверка частоты NXDOMAIN
resolvectl query nonexistent.example.com
# → NXDOMAIN (проверьте, кэшируется ли)

# 2. Проверка статистики кэша
resolvectl statistics | grep -i "nxdom\|negative"

# 3. Проверка через CoreDNS метрики
kubectl -n kube-system exec <coredns-pod> -- \
  wget -qO- http://localhost:9153/metrics | \
  grep coredns_dns_response_rcode_count_total{rcode="NXDOMAIN"}
```

**Решение:** Настроить `negative-ttl` в Corefile или настроить `cache 30` для увеличения TTL отрицательных ответов. Мониторинг: **[Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md)**.

### Сценарий 8: Влияние MTU и фрагментации UDP

Если большие DNS-ответы (DNSSEC, Headless Service с >20 подов) теряются:

```bash
# 1. Проверка размера ответа
dig +bufsize=4096 example.com A

# 2. Перехват фрагментированных пакетов
sudo tcpdump -i any port 53 -nn -v 2>&1 | grep -i "frag\|reassembled\|truncated"

# 3. Проверка MTU на интерфейсе
ip link show eth0 | grep mtu
# → mtu 1500

# 4. Проверка дропов фрагментов
nft list ruleset | grep -i "frag"
# или
iptables -L -n -v | grep -i "frag"
```

**Решение:** Увеличить `net.ipv4.ipfrag_time` или перейти на DNS over TCP (`options use-vc`). Для Kubernetes: настройте `mtu` в CNI (Calico: `1635` для WireGuard, `1450` для VXLAN).

### Сценарий 9: Happy Eyeballs и задержки IPv6

Если сеть не поддерживает IPv6, но клиенты получают AAAA-записи:

```bash
# 1. Проверка AAAA-записей
dig example.com AAAA +short
# → 2001:db8::1 (если нет маршрута — зависание)

# 2. Измерение влияния Happy Eyeballs
time curl -s -o /dev/null -w "%{time_total}" http://example.com
time curl -s -o /dev/null -w "%{time_total}" -4 http://example.com
# → Разница > 0.1 сек указывает на проблему IPv6

# 3. Проверка приоритетов в gai.conf
grep precedence /etc/gai.conf
# → precedence ::ffff:0:0/96  100 (IPv4 имеет приоритет)
```

**Решение:** Установить `precedence ::ffff:0:0/96  100` в `/etc/gai.conf` или отключить IPv6 на уровне CNI/системы.

### Сценарий 10: Влияние DNSSEC на латентность

Сравнение производительности с включенной/выключенной DNSSEC-валидацией:

```bash
# 1. Замер с DNSSEC (флаг +AD)
dig example.com +AD +stats
# → Query time: 15 msec

# 2. Замер без DNSSEC (флаг +CD)
dig example.com +CD +stats
# → Query time: 2 msec

# 3. Проверка размера ответа
dig example.com +dnssec +bufsize=4096
# → ;; flags:; rd; ra; ad; (ad = authentic data)
```

**Анализ:** Разница >10 мс указывает на нагрузку от DNSSEC. Для высоконагруженных внутренних сервисов рассмотрите отключение валидации на уровне локального резолвера (unbound) и делегирование проверки upstream.

### Сценарий 11: Оптимизация ndots в Kubernetes

Измерение влияния `ndots:5` на реальном workload:

```bash
# 1. Создание пода с дефолтными настройками
kubectl run dns-test --image=busybox:1.37 --rm -it -- sh -c "time nslookup my-service"

# 2. Создание пода с оптимизированными настройками
kubectl run dns-test-fast --image=busybox:1.37 --rm -it --dns-config=dnsConfig-opt.json \
  -- sh -c "time nslookup my-service"

# dnsConfig-opt.json:
# {
#   "options": [{"name": "ndots", "value": "2"}, {"name": "timeout", "value": "2"}]
# }
```

**Ожидаемый результат:** Снижение p99 с 50–100 мс до 5–10 мс для внешних доменов. Детали: **[DNS в Kubernetes: глубокое погружение](../../../../Kubernetes/Networking/dns_deep_dive.md)**.

### Сценарий 12: DNS over TCP vs UDP

TCP необходим для ответов >512 байт (EDNS0) или при блокировке UDP фаерволом:

```bash
# 1. Принудительный TCP через dig
dig example.com +tcp +stats

# 2. Измерение латентности TCP vs UDP
for proto in udp tcp; do
  dig example.com +${proto} +stats 2>&1 | grep "Query time"
done

# 3. Проверка, используется ли TCP в systemd-resolved
resolvectl query example.com | grep -i "tcp\|udp"
```

**Влияние на латентность:** TCP добавляет минимум 1 RTT (handshake) + overhead TLS (если DoT). Для высоконагруженных сред рассмотрите DoQ (RFC 9250), который сохраняет 0-RTT для повторных соединений.

### Сценарий 13: Аудит DNS-запросов приложения через eBPF

Идентификация приложений, генерирующих избыточные DNS-запросы:

```bash
# 1. Запуск gethostlatency
sudo gethostlatency

# Пример вывода:
# COMM             PID    LATms  NAME
# my-app           1234   450    api.v1.default.svc.cluster.local
# node-exporter    5678   12     prometheus-k8s.monitoring.svc.cluster.local

# 2. Сбор статистики за 60 секунд
sudo gethostlatency 60 | awk '{print $1, $4}' | sort | uniq -c | sort -rn | head -20
```

**Действие:** Если приложение запрашивает одно и то же имя >10 раз в секунду, проверьте его кэширование DNS на уровне приложения (JVM: `-Dnetworkaddress.cache.ttl=30`, Go: `net.Resolver` с PrefetchGo).

### Сценарий 14: Анализ перегрузки conntrack

При высокой плотности контейнеров/Kubernetes таблица conntrack может исчерпываться:

```bash
# 1. Проверка заполнения conntrack
sysctl net.netfilter.nf_conntrack_count
sysctl net.netfilter.nf_conntrack_max
# → count близок к max = проблема

# 2. Проверка дропов
cat /proc/net/stat/nf_conntrack | awk '{print $2}' | \
  awk -F' ' '{for(i=1;i<=NF;i++) sum+=$i} END {print sum}'
# или
dmesg | grep -i "nf_conntrack: table full"

# 3. Увеличение лимита (временное)
sudo sysctl -w net.netfilter.nf_conntrack_max=262144
```

**Постоянное решение:** NodeLocal DNSCache (переводит трафик на TCP), увеличение `nf_conntrack_max` в sysctl, оптимизация TTL для уменьшения частоты запросов.

### Сценарий 15: Восстановление после сбоя кэша (Cache Stampede)

При сбросе кэша CoreDNS или systemd-resolved возникает шторм запросов к upstream:

```bash
# 1. Имитация сброса кэша
resolvectl flush-caches

# 2. Мониторинг всплеска
watch -n1 "resolvectl statistics | grep -E 'Cache|Transactions'"

# 3. Проверка upstream DNS
dig @10.0.0.2 example.com +stats
```

**Защита от Stampede:**
- Настройка `cache 30` в Corefile CoreDNS с prefetching (автоматическое обновление записей за 10% TTL).
- Использование `unbound` как локального кэша с агрессивным TTL.
- На клиенте: `options timeout:2 attempts:2` для предотвращения каскадных таймаутов.

## Стратегии оптимизации (SRE-чеклист 2026)

1. **Локальное кэширование:** Использование `systemd-resolved` на хостах или `unbound` в качестве sidecar-контейнера.
2. **DNS over QUIC (DoQ):** Переход на DoQ для внешних запросов для минимизации потерь при переключении сетей.
3. **Оптимизация ndots:** Установка `ndots:1` в Kubernetes для внешних доменов (использование FQDN с точкой в конце: `google.com.`).
4. **Асинхронные резолверы:** Настройка приложений на использование библиотек, не блокирующих основной Event Loop (например, `ares` в Node.js).
5. **Префетчинг (Prefetching):** Настройка резолвера на обновление популярных записей в кэше до истечения их TTL.
6. **NodeLocal DNSCache:** Обязательное развертывание в production-кластерах K8s (>10 узлов).
7. **Кэширование через nscd:** Для `nscd` убедитесь, что параметры `positive-time-to-live` и `negative-time-to-live` соответствуют политикам обновления записей. Детали: **[nscd](../../../Networking/Services/nscd.md)**.
8. **Мониторинг p99:** Алерт при `p99 > 200 мс` или `error rate > 0.1%`. Метрики Prometheus: см. **[Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md)**.
9. **Аудит resolv.conf в контейнерах:** Регулярная проверка, что корпоративные DNS не заменены на публичные. Детали: **[DNS в Docker](../../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md)**.
10. **Снижение DNSSEC-нагрузки:** Для внутренних сервисов используйте локальный валидирующий резолвер (unbound) вместо валидации на каждом клиенте.

## Best Practices

### Конфигурация

1. **Всегда используйте FQDN с точкой** (`example.com.`) в скриптах и конфигурациях для исключения влияния `search`-доменов.
2. **Настройте таймауты:** `options timeout:1 attempts:2 rotate` в `resolv.conf` снижает p99-задержку при сбое одного сервера.
3. **Управляйте ndots через `dnsConfig`** в Kubernetes, а не глобально на уровне хоста.
4. **Используйте `single-request-reopen`** при проблемах с conntrack в glibc-образах (в musl/Alpine опция игнорируется — там помогает только NodeLocal DNSCache или исправление сети).
5. **Не смешивайте nscd и systemd-resolved:** одновременный запуск приводит к двойному кэшированию и конфликтам.

### Мониторинг

1. **DNS Success Rate:** Алерт при < 99.9% успешных запросов. Детали: **[Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md)**.
2. **DNS Latency:** Алерт при p99 > 200 мс.
3. **Cache Hit Ratio:** Должен быть > 90% при наличии кэша. Если ниже — проверьте TTL и уникальность поддоменов.
4. **conntrack usage:** Алерт при заполнении таблицы > 80%.
5. **CoreDNS Saturation:** Мониторинг `coredns_dns_requests_total` и `coredns_forward_request_duration_seconds`. Детали: **[DNS в Kubernetes](../../../../Kubernetes/Networking/dns_deep_dive.md)**.

### Производительность

1. **Снимайте baseline:** Всегда измеряйте текущую производительность перед любыми изменениями. Используйте `dig +stats` и `dnspyre`.
2. **Тестируйте в условиях, приближенных к production:** VPN, overlay-сети, фаерволы.
3. **Проверяйте glibc vs musl:** В Alpine-контейнерах поведение резолвера отличается (параллельные запросы).
4. **Избегайте избыточных DNSSEC-запросов:** Для внутренних сервисов используйте локальный кэш без валидации.
5. **Prefetching:** Включите `prefetch` в `systemd-resolved` или настройте CoreDNS плагин `cache` с `prefetch 5 10m` (обновлять запись, когда TTL истечёт на 50%, если она запрашивалась за последние 10 минут).

## Дополнительная информация

- **[Конфигурация DNS-клиента](./configuration.md)** — глубокий тюнинг параметров.
- **[Диагностика DNS в контейнерах](./container_diagnostics.md)** — специфика Docker и K8s.
- **[Инструмент dig](./dig_tool.md)** — продвинутый анализ ответов.
- **[Обзор диагностики DNS](./overview.md)** — архитектура и уровни взаимодействия.
- **[DNS-клиент в Linux](../../../Networking/Concepts/dns_client.md)** — конфигурация и принципы работы.
- **[nscd](../../../Networking/Services/nscd.md)** — устаревший демон кэширования (legacy).
- **[glibc vs musl](../../../Core/glibc_vs_musl.md)** — различия в поведении резолвера.
- **[Тестирование производительности DNS](../../../../Networking/Protocols/DNS/dns_performance_testing.md)** — бенчмаркинг dnsperf/queryperf/dnspyre.
- **[DNS в Kubernetes](../../../../Kubernetes/Networking/dns_deep_dive.md)** — CoreDNS, NodeLocal DNSCache, ndots.
- **[DNS и Service Discovery в Docker](../../../../Docker/Docker_network/dns_and_service_discovery.md)** — архитектура Docker DNS.
- **[Проблемы с DNS в Docker](../../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md)** — Docker-специфичные проблемы.
- **[Диагностика DNS-мисконфигурации](../../../../Networking/Troubleshooting/real_case_troubleshooting_dns_misconfig.md)** — практические кейсы.
- **[Диагностика Tail Latency](../../../Diagnostics/Performance/diagnosing_tail_latency.md)** — общая методология диагностики хвостовой задержки.
- **[Управление задержками](../../../../Concepts/High_Availability/tail_latency_mitigation.md)** — архитектурные паттерны борьбы с p99.
- **[Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md)** — SLA, метрики, алертинг.
