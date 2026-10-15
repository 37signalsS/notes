# Диагностика DNS-серверов: BIND, Unbound, CoreDNS

## Определения

**DNS Server Health Check** — проверка работоспособности DNS-сервера, включающая проверку состояния процесса, доступности портов, целостности зон и корректности конфигурации.

**unbound-control** — утилита управления сервером Unbound. Предоставляет доступ к статистике, управлению кэшем, перезагрузке конфигурации и мониторингу состояния.

**CoreDNS Plugin Interface** — модульная архитектура CoreDNS, где каждый плагин отвечает за конкретную функцию (forward, cache, prometheus, log, errors). Диагностика CoreDNS сводится к анализу логов плагинов и их взаимодействия.

**DNS Server Saturation** — состояние, при котором DNS-сервер не способен обрабатывать поступающие запросы из-за исчерпания ресурсов (CPU, память, файловые дескрипторы, UDP-буферы). Проявляется ростом латентности, таймаутами и снижением QPS.

## Базовые концепции

### Алгоритм диагностики DNS-сервера (SRE-чеклист)

| Шаг | Действие | BIND | Unbound | CoreDNS |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Статус службы | `systemctl status named` | `systemctl status unbound` | `kubectl get pods -n kube-system -l k8s-app=kube-dns` |
| **2** | Доступность порта | `ss -ulnp \| grep :53` | `ss -ulnp \| grep :53` | `kubectl exec <pod> -- nc -zv localhost 53` |
| **3** | Валидация конфига | `named-checkconf` | `unbound-checkconf` | `coredns -conf Corefile -validate` |
| **4** | Анализ логов | `journalctl -u named -f` | `journalctl -u unbound -f` | `kubectl logs -n kube-system -l k8s-app=kube-dns -f` |
| **5** | Тест запроса | `dig @127.0.0.1 example.com` | `dig @127.0.0.1 example.com` | `kubectl exec <pod> -- dig @localhost example.com` |
| **6** | Статистика | `rndc status` | `unbound-control stats_noreset` | `curl -s http://localhost:9153/metrics` |
| **7** | Ресурсы | `top -p $(pidof named)` | `top -p $(pidof unbound)` | `kubectl top pod -n kube-system -l k8s-app=kube-dns` |

### Типичные симптомы серверных проблем

| Симптом | Вероятная причина | Как проверить |
| :--- | :--- | :--- |
| **Все клиенты получают SERVFAIL** | Конфигурационная ошибка, повреждённая зона | `named-checkconf && named-checkzone example.com /etc/bind/zones/example.com.zone` |
| **Некоторые домены не резолвятся** | Проблема с рекурсией или forwarder | `dig @server example.com +trace` — найти точку обрыва |
| **Высокая латентность (>100мс)** | Перегрузка CPU, переполнение кэша, conntrack | `top -p $(pidof named)`, `rndc status`, `dmesg \| grep conntrack` |
| **Сервер не запускается** | Ошибка синтаксиса конфига, занятый порт | `journalctl -u named -n 50`, `named-checkconf` |
| **Сбои периодические** | OOM killer, нехватка fd, DNSSEC-ошибки | `dmesg \| grep -i oom`, `cat /proc/$(pidof named)/limits` |
| **Зоны не обновляются** | Сбой трансфера, неверный serial | `dig @master example.com SOA +short`, проверка journal-файлов |

### Мониторинг ресурсов DNS-сервера

**Ключевые метрики для алертинга:**

```bash
# BIND: проверка использования памяти
ps -o pid,rss,vsz,comm -p $(pidof named)
# → PID   RSS    VSZ    COMMAND
# → 1234  256M   1.2G   named

# BIND: проверка количества файловых дескрипторов
ls /proc/$(pidof named)/fd | wc -l
cat /proc/$(pidof named)/limits | grep "open files"

# Unbound: статистика
unbound-control stats_noreset | grep -E "mem|queries|cache"

# CoreDNS: метрики через Prometheus
curl -s http://localhost:9153/metrics | grep -E "coredns_dns_requests_total|coredns_panicked"
```

## Практические сценарии

### Сценарий 1: BIND — клиенты получают SERVFAIL

**Диагностика:**

```bash
# 1. Проверка конфигурации
named-checkconf /etc/bind/named.conf
# → Если есть ошибки — исправить и перезапустить

# 2. Проверка зоны
named-checkzone example.com /etc/bind/zones/example.com.zone
# → Если zone file has errors — исправить

# 3. Проверка логов на ошибки
journalctl -u named --since "10 minutes ago" | grep -i "error\|fail\|panic"

# 4. Проверка DNSSEC (если зона подписана)
dig @127.0.0.1 example.com +dnssec +short
dig @127.0.0.1 example.com DNSKEY +dnssec

# 5. Проверка рекурсии
dig @127.0.0.1 google.com +trace +short

# 6. Проверка forwarded-запросов
rndc status | grep "recursive queries"

# 7. Сброс кэша резолвера и перезагрузка конфига (если изменения в named.conf)
rndc flush && rndc reconfig && rndc status
# → flush: success; reconfig: success; status shows updated config
```

**Решение:** Если ошибка в синтаксисе — исправить файл и выполнить `rndc reload`. Если DNSSEC — проверить ключи и DS-записи. Если forwarder недоступен — проверить сетевую связность.

### Сценарий 2: BIND — высокая латентность ответов

**Диагностика:**

```bash
# 1. Замер времени отклика
time dig @127.0.0.1 example.com +stats
# → Query time: 150 msec (норма < 5 мс для локального сервера)

# 2. Проверка CPU
top -bn1 -p $(pidof named) | tail -1
# → %Cpu(s): 85.0 us — перегрузка

# 3. Проверка размера кэша
rndc status | grep "cache size"
# → cache size: 2048 MB (если много — возможна фрагментация)

# 4. Проверка concurrent queries
rndc recursing
# → Если запросов слишком много — проблема с производительностью

# 5. Проверка network latency до forwarder
dig @<forwarder_ip> example.com +stats
# → Если через forwarder быстрее — проблема в рекурсии
```

**Решение:** Увеличить `max-cache-size`, оптимизировать `fetches-per-zone`, проверить `recursive-clients` лимит.

### Сценарий 3: Unbound — кэш возвращаает stale-данные

**Диагностика:**

```bash
# 1. Проверка кэша
unbound-control stats_noreset | grep -E "num\.queries|num\.cachehits|num\.cachemiss"

# 2. Очистка кэша
sudo unbound-control flush_zone .
# → Flush of . done.

# 3. Проверка prefetch
grep -i "prefetch" /etc/unbound/unbound.conf
# → prefetch: yes (должно быть включено для автоматического обновления)

# 4. Проверка TTL
dig @127.0.0.1 example.com +noall +answer
# → example.com.  3499  IN  A  93.184.216.34
# (TTL уменьшается с каждым запросом из кэша)

# 5. Принудительный обход кэша
dig @127.0.0.1 example.com +cd +short
# → Если ответ изменился — проблема в кэше
```

### Сценарий 4: CoreDNS — CrashLoopBackOff

**Диагностика:**

```bash
# 1. Проверка логов
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=100
# → Ищем: panic, fatal, loop detected, error

# 2. Проверка Corefile
kubectl -n kube-system get configmap coredns -o yaml | yq '.data.Corefile'
# → Ищем синтаксические ошибки

# 3. Проверка ресурсов
kubectl top pod -n kube-system -l k8s-app=kube-dns
# → CPU/Memory превышают limits → OOM

# 4. Проверка конфликта с systemd-resolved
kubectl logs -n kube-system -l k8s-app=kube-dns | grep -i "loop\|forward"
# → Если forward . /etc/resolv.conf указывает на 127.0.0.53 — петля

# 5. Проверка upstream DNS
kubectl exec -it <coredns_pod> -- dig @127.0.0.1 google.com +short
# → Если не работает — проблема с forward плагином
```

**Решение:** Исправить Corefile, исправить `--resolv-conf` в kubelet, увеличить лимиты памяти.

### Сценарий 5: BIND — зоны не синхронизируются (Master-Slave)

**Диагностика:**

```bash
# 1. Проверка serial на Master
dig @master example.com SOA +short
# → ns1.example.com. admin.example.com. 2023091501 ...

# 2. Проверка serial на Slave
dig @slave example.com SOA +short
# → Если serial меньше — трансфер не прошёл

# 3. Проверка journal-файлов
ls -la /var/cache/bind/example.com.zone.jnl
# → Если .jnl есть — изменения не записаны в зону

# 4. Проверка доступности трансфера
dig @master example.com AXFR +noall +answer
# → Если пусто — проблема с allow-transfer или TSIG

# 5. Проверка логов Slave
journalctl -u named --since "1 hour ago" | grep -i "transfer\|ixfr\|axfr"
# → Ищем ошибки трансфера

# 6. Принудительная синхронизация
sudo rndc reload example.com
```

### Сценарий 6: BIND — переполнение таблицы conntrack

**Диагностика:**

```bash
# 1. Проверка заполнения conntrack
sysctl net.netfilter.nf_conntrack_count
sysctl net.netfilter.nf_conntrack_max
# → count близок к max = проблема

# 2. Проверка дропов
dmesg | grep -i "nf_conntrack: table full"

# 3. Проверка UDP-соединений
ss -unp | grep :53 | wc -l
# → Если очень много — проблема

# 4. Мониторинг в реальном времени
watch -n1 "sysctl net.netfilter.nf_conntrack_count"
```

**Решение:** Увеличить `net.netfilter.nf_conntrack_max`, использовать DNS over TCP, настроить `single-request-reopen` на glibc-клиентах (musl/Alpine игнорирует эту опцию).

### Сценарий 7: Unbound — DNSSEC SERVFAIL для легитимных доменов

**Диагностика:**

```bash
# 1. Проверка с отключённой валидацией
dig @127.0.0.1 example.com +cd +short
# → Если работает с +cd — проблема в DNSSEC

# 2. Проверка цепочки DNSSEC
dig @127.0.0.1 example.com +dnssec +multiline
# → Ищем RRSIG, DNSKEY, DS записи

# 3. Проверкаtrust anchor
unbound-control list_stubs | grep "."
# → Должен содержать корневой trust anchor

# 4. Проверка системных часов
date && timedatectl
# → Неправильные часы = просроченные RRSIG

# 5. Проверка ключей
dig . DNSKEY +dnssec +short | head -5
# → Если нет корневых ключей — trust anchor повреждён
```

### Сценарий 8: CoreDNS — Slow DNS (>50ms p99)

**Диагностика:**

```bash
# 1. Замер latency из пода
kubectl exec <pod> -- time nslookup kubernetes.default.svc.cluster.local
# → real 0m0.050s (норма < 5мс)

# 2. Проверка метрик CoreDNS
kubectl exec -it <coredns_pod> -- wget -qO- http://localhost:9153/metrics | \
  grep coredns_forward_request_duration_seconds
# → Смотрим p99

# 3. Проверка NodeLocal DNSCache
kubectl get daemonset -n kube-system node-local-dns
# → Если не установлен — это причина высокой латентности

# 4. Проверка conntrack
kubectl exec <pod> -- ss -unp | grep :53
# → Много UNCONN записей = conntrack race

# 5. Проверка负载
kubectl top pod -n kube-system -l k8s-app=kube-dns
# → Если CPU high — масштабировать CoreDNS
```

## Best Practices

### По мониторингу серверов

1. **Настройте statistics channel** для BIND (`statistics-channels` в named.conf) и метрики для CoreDNS (`prometheus` плагин).
2. **Мониторьте RCODE-распределение** — рост SERVFAIL или REFUSED указывает на проблемы.
3. **Отслеживайте cache hit ratio** — если ниже 80%, проверьте размер кэша и уникальность имён.
4. **Контролируйте recursive-clients** — при достижении лимита новые запросы отклоняются.

### По логированию

1. **Включайте querylog** только при диагностике — постоянное логирование нагружает диск.
2. **Настройте разделение логов** по категориям (queries, security, network).
3. **Используйте `journalctl -u named -f`** для мониторинга в реальном времени.
4. **Для CoreDNS** настройте плагин `log` и `errors` для записи ошибок.

### По отказоустойчивости

1. **Минимум 2 DNS-сервера** (master + slave) в разных физических расположениях.
2. **Регулярно проверяйте трансфер зон** — `dig @slave example.com SOA` должен показывать актуальный serial.
3. **Тестируйте failover** — остановите master и убедитесь, что slave отвечает.

## Дополнительная информация

- [BIND: Диагностика и устранение неисправностей](../../../../Linux/Networking/Services/BIND/troubleshooting.md) — глубокое погружение в BIND-specific проблемы.
- [BIND: Master сервер](../../../../Linux/Networking/Services/BIND/master_server_local_zone.md) — настройка первичного сервера.
- [BIND: Slave сервер](../../../../Linux/Networking/Services/BIND/slave_server_configuration.md) — вторичный сервер и трансферы.
- [BIND: Высокая доступность](../../../../Linux/Networking/Services/BIND/high-availability-cluster.md) — Anycast и кластеризация.
- [Unbound — рекурсивный резолвер](../../../../Networking/Protocols/DNS/unbound_resolver.md) — настройка и диагностика Unbound.
- [Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md) — Prometheus, Grafana, алерты.
- [Тестирование производительности DNS](../../../../Networking/Protocols/DNS/dns_performance_testing.md) — бенчмаркинг dnsperf/dnspyre.
- [Петли перенаправления DNS](../../../../Networking/Protocols/DNS/dns_forwarding_loops.md) — диагностика петель в BIND/Unbound/CoreDNS.
- [Базовая диагностика DNS](./basic_diagnostics.md) — клиентская диагностика.
- [Производительность DNS-резолвинга](./dns_resolution_performance.md) — оптимизация клиента.
