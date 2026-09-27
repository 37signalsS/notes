# Диагностика DNS: Обзор

## Определения

**DNS (Domain Name System)** — распределённая система преобразования доменных имён в IP-адреса и обратно. Теория и описание протокола представлены в разделе [Протокол DNS](../../../../Networking/Protocols/DNS/dns.md).

**Диагностика DNS** — процесс выявления и устранения сбоев в цепочке разрешения имён. Она охватывает проверку доступности транспорта (UDP/TCP/HTTPS/TLS), корректности логики системного резолвера и целостности данных (DNSSEC).

## Базовые концепции

### Архитектура разрешения имён в Linux

Диагностика строится на понимании трёх уровней взаимодействия:

1.  **Системный резолвер (NSS/libc):** Механизм, который используют прикладные программы. Порядок опроса источников определяется в `/etc/nsswitch.conf`. Основные источники: `files` (`/etc/hosts`), `resolve` (`systemd-resolved`) или `dns`.
2.  **Служба кэширования и управления (systemd-resolved):** Современный стандарт в Linux. Управляет динамическими конфигурациями, кэшем и поддерживает современные протоколы (DoT). Работает как заглушечный резолвер (stub resolver) на `127.0.0.53:53`.
3.  **Прямой опрос DNS-серверов:** Использование утилит для отправки сырых запросов в обход системных механизмов. Позволяет изолировать проблемы инфраструктуры от проблем конфигурации ОС.

**Важно:** В системах, где используется musl libc (Alpine Linux), NSS отсутствует. Разрешение имен происходит напрямую через `/etc/resolv.conf` и DNS-серверы, что упрощает, но изменяет логику диагностики.

### Таксономия сбоев DNS

Для систематизации проблем удобно классифицировать их по источнику:

| Категория | Характеристика | Типичные симптомы |
| :--- | :--- | :--- |
| **L3-транспорт** | Нет связности с DNS-сервером (UDP/53, TCP/53, 853, 443). | Таймауты, `dig +tcp` зависает, `ping` к серверу не проходит. |
| **L7-протокол** | Сервер отвечает, но с ошибкой (SERVFAIL, FORMERR). | `dig` возвращает не `NOERROR`, ответы обрезаны (`TC`). |
| **Конфигурация NSS** | `nsswitch.conf` или `/etc/hosts` переопределяют ожидаемое поведение. | `getent` возвращает другой результат, чем `dig`. |
| **Локальный кэш** | Устаревшие или повреждённые данные в `systemd-resolved`/`nscd`. | `dig @8.8.8.8` возвращает свежий IP, а `getent` — старый. |
| **Внешняя инфраструктура** | Проблемы на стороне upstream-серверов, форвардеров или авторитетных NS. | `dig @<upstream>` работает, а локальный резолвер — нет. |
| **DNSSEC** | Ошибки валидации подписей или отсутствие доверия к ключам. | `SERVFAIL` при включённом DNSSEC, исчезает при `+cd`. |

### Уровни диагностики

| Уровень | Объект проверки | Инструменты |
| :--- | :--- | :--- |
| **Связность (Connectivity)** | Доступность порта 53 (UDP/TCP) или 443/853 для шифрованных протоколов. | `ping`, `nc`, `nmap` |
| **Логика (Logic)** | Порядок разрешения в NSS, корректность `/etc/hosts`, поиск в кэше (`systemd-resolved`, `nscd`). | `getent`, `resolvectl query`, `nscd -g` |
| **Интеграция (Integration)** | Взаимодействие с внешними серверами, прохождение рекурсии. | `dig +trace`, `nslookup` |
| **Целостность (Integrity)** | Валидация подписей DNSSEC, проверка цепочки доверия. | `delv`, `dig +dnssec` |

### Ключевые инструменты

| Инструмент | Назначение | Особенности |
| :--- | :--- | :--- |
| **dig** | Детальный анализ | Основной инструмент инженера. См. [Инструмент dig](./dig_tool.md). |
| **resolvectl** | Работа с systemd | Просмотр состояния `resolved`, очистка кэша, статистика. |
| **getent hosts** | Проверка NSS | Показывает итоговый результат резолвинга «глазами системы». |
| **delv** | Проверка DNSSEC | Автоматическая валидация цепочки доверия. |
| **tcpdump / tshark** | Анализ трафика | Декодирование DNS-пакетов при подозрении на повреждение данных или фильтрацию. |

### Кэширование на разных уровнях

В Linux данные могут кэшироваться на нескольких уровнях одновременно. При устаревших или неверных ответах очистку нужно выполнять на всех уровнях:

```bash
# 1. systemd-resolved (основной кэш на большинстве современных дистрибутивов)
resolvectl flush-caches
resolvectl statistics

# 2. nscd (Name Service Cache Daemon) — если установлен
sudo nscd -i hosts

# 3. Локальный резолвер (BIND/unbound)
sudo rndc flush          # BIND
sudo unbound-control flush_zone .  # unbound

# 4. Браузеры (Chrome/Firefox) — кэш HOSTS на уровне приложения
# Chrome: chrome://net-internals/#dns
# Firefox: about:networking#dns
```

**Важно:** Отрицательное кэширование (RFC 2308) сохраняет ответы `NXDOMAIN` в кэше на время, указанное в поле `MINIMUM` записи SOA. При несуществующих доменах это предотвращает «шторм» запросов, но мешает быстрому повторному тестированию.

### Диагностика через systemd-resolved

`systemd-resolved` является центральным узлом диагностики в большинстве современных дистрибутивов.

```bash
# Просмотр активных DNS-серверов для каждого интерфейса
resolvectl status

# Проверка того, как имя разрешается через службу (с указанием интерфейса)
resolvectl query example.com

# Сброс кэша и просмотр статистики (помогает выявить переполнение кэша)
resolvectl flush-caches
resolvectl statistics

# Включение временного режима отладки (вывод в journalctl)
resolvectl log-level debug
# После завершения: resolvectl log-level info
```

**Дополнительно:** `resolvectl` показывает, какой именно интерфейс и сервер использовался для разрешения. Это критично при диагностике Split-horizon DNS или VPN-туннелей.

## Практические сценарии

### Сценарий 1: Конфликт источников и устаревший кэш

Если `dig` возвращает корректный IP, а приложения видят старый адрес, проблема локализована в NSS или локальном кэше.
**Диагностика:**
1. Проверить `/etc/hosts` на предмет статических записей.
2. Использовать `getent hosts <name>` для проверки итогового результата через NSS.
3. Проверить статус [nscd](../../../Networking/Services/nscd.md). Если он запущен, сбросить кэш: `sudo nscd -i hosts`.
4. Сбросить кэш `systemd-resolved`: `resolvectl flush-caches`.

### Сценарий 2: Неисправность рекурсии

Запрос к локальному резолверу возвращает `SERVFAIL`, но запрос к публичному серверу (`dig @8.8.8.8`) работает успешно.
**Диагностика:**
1. Выполнить `dig <name> +trace` для пошагового прохождения от корня (`.`) до авторитетного сервера.
2. Проверить поддержку больших UDP-пакетов (EDNS) и MTU, так как ответы DNSSEC могут быть обрезаны.

### Сценарий 3: Локальные протоколы (mDNS / LLMNR)

В офисных или домашних сетях имена хостов могут разрешаться через `Avahi` (mDNS) или `systemd-resolved` (LLMNR) без участия классического DNS-сервера.
**Проверка:**
```bash
# Проверка разрешения через mDNS
resolvectl query hostname.local
```

### Сценарий 4: Диагностика шифрованных протоколов (DoH / DoT)

Если в системе настроен DNS over TLS, блокировка порта 853 или проблемы с сертификатом сервера приведут к отказу всего резолвинга.
**Проверка:**
```bash
# Проверка связности DoT
openssl s_client -connect 1.1.1.1:853
```

### Сценарий 5: Пакетная проверка работоспособности DNS

Для мониторинга доступности нескольких DNS-серверов или списка доменов используйте простой bash-скрипт:

```bash
#!/bin/bash
# dns_healthcheck.sh — проверка доступности DNS-серверов
SERVERS=("8.8.8.8" "1.1.1.1" "9.9.9.9")
DOMAINS=("google.com" "cloudflare.com" "example.com")

for server in "${SERVERS[@]}"; do
    for domain in "${DOMAINS[@]}"; do
        if dig +short +timeout=2 +tries=1 @"$server" "$domain" A | grep -qE '^[0-9]+\.'; then
            echo "OK: $server -> $domain"
        else
            echo "FAIL: $server -> $domain"
        fi
    done
done
```

**Запуск:** `bash dns_healthcheck.sh | grep FAIL`

Для интеграции в мониторинг добавьте отправку алерта (email, Slack, Telegram) при обнаружении `FAIL`.

### Сценарий 6: Проверка работы форвардера

Если локальный резолвер должен пересылать запросы на внешний сервер, убедитесь, что он действительно делает это, а не обрабатывает запросы самостоятельно или возвращает устаревшие данные из кэша:

```bash
# 1. Спросите локальный резолвер
dig @127.0.0.53 example.com

# 2. Спросите внешний сервер напрямую
dig @8.8.8.8 example.com

# 3. Если ответы совпадают — возможно, локальный сервер просто кэширует данные.
#    Принудительно обойдите кэш:
dig @127.0.0.53 example.com +cd

# 4. Проверьте конфигурацию форвардера (BIND)
cat /etc/bind/named.conf.options | grep forwarder
```

### Сценарий 7: Диагностика Split-horizon DNS

В корпоративных сетях внутренний и внешний запросы к одному домену могут возвращать разные IP. Для проверки:

```bash
# Внутренний запрос (через локальный резолвер)
dig @10.0.0.1 internal.corp.example.com

# Внешний запрос (через публичный резолвер)
dig @8.8.8.8 internal.corp.example.com

# Если внешний резолвер возвращает NXDOMAIN, а внутренний — IP,
# значит, домен существует только внутри корпоративной сети.
```

### Сценарий 8: Анализ DNS-трафика через tcpdump

Когда вывод утилит не даёт явной картины, посмотрите на сами пакеты:

```bash
# Захват DNS-запросов и ответов на интерфейсе eth0
sudo tcpdump -i eth0 -n port 53 -vv

# Фильтр по конкретному домену
sudo tcpdump -i eth0 -n port 53 | grep example.com

# Захват DoH (порт 443) или DoT (порт 853)
sudo tcpdump -i eth0 -n port 443 or port 853 -vv
```

**Интерпретация:** Ищите флаг `TC` (truncated) в DNS-заголовке — он указывает, что ответ не влез в UDP и требует TCP. Смотрите на RCODE в ответе. Для декодирования бинарного содержимого используйте `tshark -d udp.port==53,dns`.

### Сценарий 9: Пост-изменённая проверка (Smoke Test)

После изменения DNS-записей (переезд на новый IP, смена NS-серверов) выполните минимальный набор проверок:

```bash
# 1. Проверьте серию зоны на новом authoritative сервере
dig @ns1.example.com example.com SOA
# → Убедитесь, что серийный номер увеличился

# 2. Проверьте новую запись напрямую у authoritative сервера
dig @ns1.example.com example.com A

# 3. Проверьте распространение через несколько независимых резолверов
for resolver in 8.8.8.8 1.1.1.1 9.9.9.9; do
    echo "=== $resolver ==="
    dig @"$resolver" example.com A +short
done

# 4. Проверьте обратное разрешение (PTR) для нового IP
dig -x <new_ip_address>
```

### Сценарий 10: Обнаружение проблем с MTU и фрагментацией

Большие DNS-ответы (DNSSEC, TXT-записи с длинными данными) могут превышать MTU и фрагментироваться:

```bash
# Принудительно используйте TCP для исключения UDP-проблем
dig example.com +tcp

# Проверьте, не блокируется ли фрагментация на сетевом пути
# Если +tcp работает, а UDP — нет, проблема на уровне firewall или MTU.
```

## Дополнительная информация

### Клиентская диагностика (в этой директории)

- **[Базовая диагностика DNS](./basic_diagnostics.md)** — пошаговый план поиска неисправностей.
- **[Конфигурация DNS-клиента](./configuration.md)** — файлы `resolv.conf`, `nsswitch.conf`, `systemd-resolved`.
- **[Порядок разрешения имён](./name_resolution.md)** — NSS, glibc vs musl, `getaddrinfo()`.
- **[Инструмент dig](./dig_tool.md)** — детальный анализ DNS-пакетов.
- **[Производительность DNS-резолвинга](./dns_resolution_performance.md)** — измерение латентности и оптимизация.
- **[Диагностика DNS в контейнерах](./container_diagnostics.md)** — Docker, Kubernetes, Podman.
- **[Диагностика DNS-серверов](./dns_server_diagnostics.md)** — BIND, Unbound, CoreDNS с серверной стороны.
- **[Диагностика безопасности DNS](./dns_security_diagnostics.md)** — DNSSEC, DoH/DoT, DDoS-защита.
- **[DNS в CI/CD](./dns_ci_cd_integration.md)** — автоматическая верификация и smoke-тесты.

### DNS-серверы и протоколы (в других разделах)

- **[Протокол DNS](../../../../Networking/Protocols/DNS/dns.md)** — общая теория, типы записей, RCODE.
- **[Типы DNS-записей](../../../../Networking/Protocols/DNS/dns_records.md)** — справочник A, AAAA, CNAME, MX, SRV, TXT, SVCB.
- **[Формат DNS-сообщения](../../../../Networking/Protocols/DNS/dns_message_format.md)** — структура заголовка, флаги, EDNS0.
- **[Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md)** — теория DNSSEC, DoH, DoT, DANE, атаки.
- **[Продвинутые сценарии DNS](../../../../Networking/Protocols/DNS/dns_advanced.md)** — Anycast, GeoDNS, ECS, RPZ, Split-horizon.
- **[Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md)** — Prometheus, Grafana, алерты.
- **[Тестирование производительности DNS](../../../../Networking/Protocols/DNS/dns_performance_testing.md)** — бенчмаркинг dnsperf/dnspyre.
- **[DNS-зоны](../../../../Networking/Protocols/DNS/dns_zones.md)** — создание, трансфер, динамические обновления.
- **[Миграция DNS](../../../../Networking/Protocols/DNS/dns_migration.md)** — AXFR/IXFR, смена провайдеров.
- **[Петли перенаправления DNS](../../../../Networking/Protocols/DNS/dns_forwarding_loops.md)** — диагностика петель BIND/Unbound/CoreDNS.
- **[Балансировка нагрузки DNS](../../../../Networking/Protocols/DNS/dns_load_balancing.md)** — Round-Robin, Weighted, GSLB.
- **[Рекурсивный резолвер Unbound](../../../../Networking/Protocols/DNS/unbound_resolver.md)** — настройка и диагностика Unbound.
- **[dnsmasq](../../../../Networking/Protocols/DNS/dnsmasq.md)** — лёгкий DNS/DHCP-сервер.

### DNS-сервер BIND (детальная документация)

- **[BIND: Обзор](../../../../Linux/Networking/Services/BIND/overview.md)** — архитектура и основные концепции.
- **[BIND: Установка](../../../../Linux/Networking/Services/BIND/installation.md)** — установка и начальная настройка.
- **[BIND: Master сервер](../../../../Linux/Networking/Services/BIND/master_server_local_zone.md)** — авторитативный сервер.
- **[BIND: Slave сервер](../../../../Linux/Networking/Services/BIND/slave_server_configuration.md)** — вторичный сервер и трансферы.
- **[BIND: Перенаправляющий сервер](../../../../Linux/Networking/Services/BIND/forwarding_server.md)** — `forward only`/`forward first`.
- **[BIND: Расширенные возможности](../../../../Linux/Networking/Services/BIND/advanced_topics.md)** — Views, ACL, RPZ, Catalog Zones.
- **[BIND: Высокая доступность](../../../../Linux/Networking/Services/BIND/high-availability-cluster.md)** — Anycast, кластеризация.
- **[BIND: DoH/DoT сервер](../../../../Linux/Networking/Services/BIND/dot-doh-server.md)** — настройка шифрованного сервера.
- **[BIND: Автоматизация (IaC)]../../../../Linux/Networking/Services/BIND/automation-iac.md)** — Ansible для BIND.
- **[BIND: Управление ключами TSIG](../../../../Linux/Networking/Services/BIND/tsig-key-management.md)** — аутентификация трансферов.
- **[BIND: Логирование и мониторинг](../../../../Linux/Networking/Services/BIND/logging-and-monitoring.md)** — настройка логов и метрик.
- **[BIND: Обратные зоны](../../../../Linux/Networking/Services/BIND/reverse_zone_configuration.md)** — PTR-записи.
- **[BIND: Диагностика](../../../../Linux/Networking/Services/BIND/troubleshooting.md)** — пошаговый разбор ошибок.
- **[BIND: Реагирование на инциденты](../../../../Linux/Networking/Services/BIND/incident-response.md)** — действия при сбоях.

### Автоматизация и CI/CD

- **[DNS Automation: PowerDNS, Route53, CloudFlare](../../../../Ansible/ansible_dns_automation.md)** — автоматизация DNS через Ansible.
- **[DNS в Kubernetes](../../../../Kubernetes/Networking/dns_deep_dive.md)** — CoreDNS, NodeLocal DNSCache, `dnsPolicy`.
- **[Diagnosing DNS in Containers](./container_diagnostics.md)** — Docker, Kubernetes, containerd.
- **[Решение проблем с DNS в Docker](../../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md)** — Docker-специфичные проблемы.
