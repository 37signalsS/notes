# Устранение проблем сетевой связности Docker

## Определения

**Проблемы сетевой связности** — сбои, при которых контейнеры не могут взаимодействовать с хостом, другими контейнерами или внешними сетями. Причины чаще всего лежат на уровне конфигурации ядра Linux (маршрутизация, фильтрация), настроек файрвола (iptables/nftables) или сетевых лимитов.

**Network Isolation (Изоляция сети)** — механизм, предотвращающий нежелательный доступ к контейнерам. Docker 28.0 перестал полагаться на политику `FORWARD` хоста и добавил блокировку неопубликованных портов в цепочку `DOCKER`, а 28.2 перенёс её в `raw` PREROUTING по одному правилу на контейнер. Блокируется только трафик **извне хоста** к IP контейнера: обращения с самого хоста и между контейнерами одной bridge-сети по-прежнему разрешены. Правило в `DOCKER-USER` не может отменить этот DROP — он срабатывает раньше таблицы `filter`. Подробно: [Политики сетевой фильтрации Docker](../Docker_network/docker_network_policies.md).

## Основные концепции

### Ключевые компоненты системы

| Компонент | Назначение | Типичная проблема |
| :--- | :--- | :--- |
| **`iptables` / `nftables`** | Фильтрация и NAT трафика | Конфликты с `ufw`/`firewalld`, блокировка в `DOCKER-USER`. |
| **`net.ipv4.ip_forward`** | Маршрутизация пакетов | Отключенная маршрутизация блокирует выход из моста в интернет. |
| **`MTU`** | Макс. размер пакета | Фрагментация или дроп пакетов в VPN/VXLAN туннелях. |
| **`conntrack`** | Отслеживание соединений | Исчерпание таблицы соединений при высокой нагрузке (PPS). |
| **Embedded DNS (`127.0.0.11`)** | Внутренний резолвер | Проблемы с `ndots`, конфликты с `systemd-resolved`. |

### Новое в Docker 28+ (Network Isolation)
С версии 28.0 Docker по умолчанию **сбрасывает (DROP)** входящий трафик на любые порты контейнера, которые не были явно опубликованы через `-p` или `--publish`. 
- **Цель:** Предотвращение несанкционированного доступа из локальной сети хоста к внутренним портам приложения.
- **Управление:** Если требуется старое поведение (полная доступность IP контейнера внутри сети), используйте флаг `--ip-forward-no-drop` в `daemon.json`.

---

## Быстрая диагностика по симптомам

| Симптом | Вероятная причина | Инструмент проверки |
| :--- | :--- | :--- |
| **Нет связи с внешним миром** | `ip_forward` отключен | `sysctl net.ipv4.ip_forward` |
| **DNS-имена не резолвятся** | Конфликт резолверов | `nslookup google.com` внутри контейнера |
| **TCP-сессии виснут (SSH, TLS)** | Несоответствие MTU | `ping -s 1472 -M do 8.8.8.8` |
| **Случайные обрывы соединений** | Лимит conntrack | `dmesg | grep conntrack` |
| **Порт проброшен, но связи нет** | Блокировка в iptables | `iptables -S DOCKER-USER` |

---

## Практические сценарии

### Сценарий 1: Исчерпание таблицы соединений (Conntrack)

**Симптомы:** Контейнеры работают, но периодически теряют связь или возвращают ошибки таймаута при большом количестве мелких запросов.

**Диагностика:**
```bash
# Проверка текущего заполнения и лимита
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# В логах ядра видны ошибки:
dmesg | grep "nf_conntrack: table full"
```

**Решение:** Увеличьте лимиты в `/etc/sysctl.conf`:
```bash
echo "net.netfilter.nf_conntrack_max=524288" >> /etc/sysctl.conf
sysctl -p
```

### Сценарий 2: Конфликт MTU в туннелях (VPN/Cloud)

**Симптомы:** Пинги проходят, но передача данных (HTTP GET, git clone) обрывается после установления соединения.

**Диагностика:**
```bash
# Тест максимального размера пакета без фрагментации
docker exec -it app ping -M do -s 1472 8.8.8.8
# Если "Frag needed and DF set", значит MTU хоста (VPN) меньше 1500.
```

**Решение:** Настройте MTU глобально в `daemon.json`:
```json
{
  "mtu": 1450
}
```
Или укажите его при создании конкретной сети:
```bash
docker network create -d bridge -o "com.docker.network.driver.mtu"="1450" my_net
```

### Сценарий 3: Блокировка в Docker 28+ (Network Isolation)

**Симптомы:** Вы можете достучаться до контейнера по его внутреннему IP с самого хоста, но другой сервер в той же локальной сети не может этого сделать, даже если маршруты прописаны.

**Решение:** Используйте цепочку **`DOCKER-USER`** (она является единственным SSoT для кастомных правил).
```bash
# Разрешить трафик с конкретного интерфейса хоста к сети Docker
iptables -I DOCKER-USER -i eth1 -o docker0 -j ACCEPT
```

### Сценарий 4: Диагностика через eBPF (Inspektor Gadget)

**Задача:** Увидеть, на каком этапе сбрасывается пакет, не используя тяжелый `tcpdump`.

**Использование инструмента `ig`:**
```bash
# Отслеживание TCP-соединений в реальном времени (connect/accept/close)
sudo ig trace tcp -c my_app

# Отслеживание сброшенных ядром пакетов (Drop) с указанием причины
sudo ig trace tcpdrop
```

### Сценарий 5: Порт опубликован, но недоступен снаружи

**Симптом:** `docker ps` показывает `0.0.0.0:8080->80/tcp`, но `curl <host-ip>:8080` не отвечает, при этом с самого хоста `curl localhost:8080` работает.

**Диагностика:**

```bash
# 1. На каком интерфейсе забинден порт
sudo ss -tlnp | grep :8080
# → LISTEN 0 511 127.0.0.1:8080 0.0.0.0:* users:(("docker-proxy",...))
#   ↑ бинд к loopback — из сети недоступен

# 2. Приложение слушает внутри контейнера
docker exec my-app ss -tlnp
# → LISTEN 0 511 0.0.0.0:8080 ...   ← должно быть 0.0.0.0, не 127.0.0.1

# 3. Firewall хоста
sudo iptables -L -n -v | grep -i drop
sudo ufw status
```

**Решение:** маппинг на все интерфейсы (`-p 8080:80` или явно `-p 0.0.0.0:8080:80`); для внутренних сервисов — наоборот, `-p 127.0.0.1:8080:80`. Полный разбор — **[Конфликты портов](./port_conflicts.md)**.

### Сценарий 6: Bridge vs host network mode

**Симптом:** контейнер не виден в сети, либо порты ведут себя не так, как ожидалось.

| Режим | Сетевой стек | Порты | Когда использовать |
| :--- | :--- | :--- | :--- |
| **bridge** (дефолт) | Отдельный namespace, NAT через `docker0` | Требуется `-p` для доступа извне | Обычные сервисы, изоляция |
| **host** | Общий стек с хостом | `-p` игнорируется (`WARNING: Published ports are discarded`), приложение слушает порт хоста напрямую | Максимальная производительность, нет NAT-overhead |
| **none** | Только loopback внутри контейнера | Нет сети | Batch-задачи без сети |
| **container:<id>** | Общий namespace с другим контейнером | Общие порты | Sidecar (см. **[debugging_distroless.md](./debugging_distroless.md)**) |

**Диагностика:**

```bash
# Режим контейнера
docker inspect my-app --format '{{.HostConfig.NetworkMode}}'
# → bridge

# В host-режиме приложение слушает порт хоста напрямую
docker run --network host nginx
ss -tlnp | grep :80
# → LISTEN ... nginx   ← не docker-proxy
```

**Нюанс bridge:** с самого хоста доступ к контейнеру по его IP (`172.17.0.x`) работает напрямую; извне — только через опубликованные порты (а в Docker 28+ неопубликованные порты DROP-аются для внешнего трафика, см. выше).

### Сценарий 7: IPv6 и dual-stack

**Симптом:** контейнер резолвирует только IPv4, приложение предпочитает IPv6 и таймаутит, или `curl` внутри контейнера падает с `Network is unreachable` для IPv6-адресов.

**Диагностика:**

```bash
# IPv6 включён для Docker?
docker network inspect bridge --format '{{(index .Options "com.docker.network.enable-ipv6")}}'
# → (пусто = выключен)

# Внутри контейнера
docker exec my-app ip -6 addr
# → (пусто = нет IPv6 в контейнере)
```

**Решение** — включить IPv6 в `daemon.json` (требуется явно, документация Docker):

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "2001:db8:1::/64"
}
```

```bash
sudo systemctl restart docker
docker network create --ipv6 my-net
```

**Нюанс:** без включённого IPv6 в Docker приложения, делающие `getaddrinfo` с приоритетом IPv6, могут получать таймауты — либо включайте IPv6, либо заставляйте приложение предпочитать IPv4 (`RES_OPTIONS="single-request"` в glibc-образах; musl шлёт A/AAAA параллельно — см. **[alpine_glibc_compatibility.md](./alpine_glibc_compatibility.md)**).

---

## Инструменты диагностики (Toolbox)

Для глубокого анализа используйте образ **`nicolaka/netshoot`**, который содержит все необходимые утилиты (`tcpdump`, `mtr`, `nmap`, `iperf3`).

```bash
# Подключение к сетевому пространству имен целевого контейнера
docker run --rm -it --net container:<id> nicolaka/netshoot

# Внутри netshoot:
# Просмотр всех открытых портов и соединений
ss -tapn

# Трассировка с учетом MTU
mtr -T -P 80 google.com
```

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `docker exec <c> ss -tlnp` | Что слушает внутри контейнера | `docker exec my-app ss -tlnp` |
| `docker port <c>` | Опубликованные порты контейнера | `docker port my-app` |
| `docker inspect --format '{{.HostConfig.NetworkMode}}'` | Сетевой режим | `docker inspect my-app --format '{{.HostConfig.NetworkMode}}'` |
| `docker network inspect <net>` | Конфигурация сети | `docker network inspect bridge` |
| `docker network create --ipv6 <net>` | Сеть с IPv6 | `docker network create --ipv6 my-net` |
| `sysctl net.ipv4.ip_forward` | Маршрутизация на хосте | `sysctl net.ipv4.ip_forward` |
| `sysctl net.netfilter.nf_conntrack_count` | Заполнение conntrack | `sysctl net.netfilter.nf_conntrack_max` |
| `sudo ig trace tcp -c <c>` | TCP-события (eBPF) | `sudo ig trace tcp -c my-app` |
| `sudo ig trace tcpdrop` | Дропы пакетов ядром | `sudo ig trace tcpdrop` |

## Лучшие практики

1. **Проверяйте бинд порта перед firewall-правилами** — `ss -tlnp` на хосте отличает проблему маппинга (`127.0.0.1` vs `0.0.0.0`) от проблемы firewall (см. **[port_conflicts.md](./port_conflicts.md)**).
2. **Явно публикуйте порты в Docker 28+** — неопубликованные порты недоступны извне по умолчанию (network isolation).
3. **`start_period` и `retries` в healthcheck** — чтобы сетевой сбой при старте не приводил к ложному `unhealthy` (см. **[docker_autoheal.md](./docker_autoheal.md)**).
4. **MTU в туннелях** — при VPN/VXLAN задавайте MTU в `daemon.json` или опцией сети, иначе «пинги проходят, а HTTP обрывается».
5. **conntrack на высоконагруженных хостах** — алерт на `nf_conntrack_count / nf_conntrack_max > 80%`.
6. **Sidecar `nicolaka/netshoot`** — универсальный диагностический контейнер для любой Engine (не требует shell в целевом образе).

## Дополнительная информация

### Чеклист проверки при сбое
1.  **IP Forwarding:** `sysctl net.ipv4.ip_forward` должен быть `1`.
2.  **Chain Policy:** `iptables -L FORWARD` часто имеет `DROP`. Убедитесь, что правила Docker стоят в начале.
3.  **Bridge IP:** Интерфейс `docker0` должен иметь назначенный IP-адрес.
4.  **Local DNS:** Внутри контейнера `cat /etc/resolv.conf` должен указывать на `127.0.0.11`.

### См. также
- **[Интеграция с iptables](../Docker_network/troubleshooting/iptables_integration.md)** — детальный разбор цепочек и UFW.
- **[Решение проблем с DNS](../Docker_network/troubleshooting/dns_resolution_issues.md)** — глубокая диагностика резолва.
- **[Обзор сетевых моделей Docker](../Docker_network/docker_network.md)** — архитектура и драйверы.
- **[Диагностика через Docker Events](./debugging_with_docker_events.md)** — отслеживание сетевых событий.
- **[Конфликты портов](./port_conflicts.md)** — «port is already allocated», бинд интерфейсов, ephemeral-порты.
- **[Зависшие контейнеры](./hung_containers.md)** — когда сеть в порядке, но сервис не отвечает.
- **[Методология диагностики](./troubleshooting_methodology.md)** — decision tree по симптомам.

**Глубокое изучение:**
- **[iperf3](../../Linux/Diagnostics/Networking/iperf3.md)** — benchmarking. В Docker: `docker run --network=host networkstatic/iperf3 -s` (сервер) и `docker run networkstatic/iperf3 -c <host>` (клиент) для замера throughput между контейнерами/хостами.
- **[tcpdump](../../Linux/Diagnostics/Networking/tcpdump.md)** — захват пакетов. В Docker: `nsenter -t $(docker inspect -f '{{.State.Pid}}' <container>) -n tcpdump -i eth0` для захвата трафика контейнера без `--privileged`.
- **[netshoot](../../Kubernetes/Troubleshooting/troubleshooting_overview.md)** — диагностический toolkit. В Docker: `docker run --rm --net container:<target> nicolaka/netshoot` для диагностики сети целевого контейнера.
