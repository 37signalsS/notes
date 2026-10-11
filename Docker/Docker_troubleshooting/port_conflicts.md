# Конфликты портов и публикация портов (Port Conflicts)

**Актуально для:** Docker Engine 20.10+ (`host-gateway`); 28.0+ (network isolation); rootless — ограничение привилегированных портов

## Определения

**«port is already allocated»** — ошибка демона при попытке забиндить хост-порт, который уже занят другим контейнером или процессом хоста. В Compose та же ошибка выглядит как `Binding for 0.0.0.0:8080 failed: port is already allocated`.

**Published port** — маппинг хост-порта на порт контейнера (`-p [host_ip:]host_port:container_port[/proto]`). По умолчанию биндится на `0.0.0.0` (все интерфейсы хоста).

**EXPOSE ≠ публикация** — `EXPOSE` в Dockerfile и `expose` в Compose лишь документируют порт и открывают его **между контейнерами одной сети**; хост-порт при этом не создаётся. Публикация на хост — только `-p`/`--publish`/`-P` или `ports` в Compose.

**Userland proxy** — процесс `docker-proxy`, который демон запускает для каждого published port при `"userland-proxy": true` (дефолт). Обеспечивает доступ к контейнеру с самого хоста по `localhost`. При `"userland-proxy": false` используется только DNAT в iptables (см. **[Performance Tuning](../Docker_performance_tuning.md)**).

**Ephemeral ports** — диапазон исходящих портов хоста (`net.ipv4.ip_local_port_range`, дефолт `32768 60999`). Исходящие соединения **всех** контейнеров идут с хостовых ephemeral-портов — при высокой нагрузке диапазон исчерпывается (TIME_WAIT).

## Основные концепции

### Кто и как занимает порт

| Источник | Механизм | Диагностика |
| :--- | :--- | :--- |
| Другой running-контейнер | `docker-proxy` / DNAT на хост-порт | `docker ps --format 'table {{.Names}}\t{{.Ports}}'` |
| Процесс хоста (nginx, systemd-юнит) | обычный bind | `ss -tlnp`, `lsof -i :PORT` |
| Остановленный контейнер | **не держит порт** (порт освобождается при stop) | `docker ps` (без `-a`) |
| Второй демон (rootless + rootful) | разные демоны биндят один порт | `docker context ls`, `ps aux \| grep dockerd` |

**Важно:** `docker ps -a` показывает колонку PORTS и для stopped-контейнеров, но порт занимает только **running**-контейнер.

### Семантика привязки

```bash
-p 8080:80            # 0.0.0.0:8080 → 80 (все интерфейсы, включая внешние)
-p 127.0.0.1:8080:80  # только loopback хоста (безопасно: недоступен из LAN)
-p ::1:8080:80        # IPv6 loopback
-p 8080:80/udp        # протокол (по умолчанию tcp)
-P                      # случайный хост-порт на каждый EXPOSE
```

В режиме `--network host` флаги `-p`/`-P` игнорируются с предупреждением `WARNING: Published ports are discarded when using host network mode` — приложение слушает порты хоста напрямую (и конфликтует с процессами хоста обычным `bind`, ошибка прилетит от самого приложения, не от демона).

**Коллизия биндингов на одном порту:** бинд `0.0.0.0:8080` покрывает loopback — поэтому после `-p 127.0.0.1:8080:80` запуск с `-p 8080:80` (и наоборот, если первым был wildcard) падает с тем же `port is already allocated`, хотя «интерфейсы разные». Разные IP-адреса хоста (`-p 192.168.1.5:8080:80` и `-p 127.0.0.1:8080:80`) — конфликт не дают.

### Ephemeral-порты и исходящие соединения

Контейнер не имеет собственного сетевого стека для исходящих соединений: NAT маскарадит их под хостовый IP и ephemeral-порт. Симптом исчерпания: новые исходящие соединения из контейнеров падают с `cannot assign requested address`, при этом `ss -s` показывает десятки тысяч `TIME_WAIT`.

## Практические сценарии

### Сценарий 1: «port is already allocated»

```bash
docker run -p 8080:80 nginx
# → Error response from daemon: driver failed programming external
#   connectivity on endpoint ...: Bind for 0.0.0.0:8080 failed:
#   port is already allocated

# 1. Кто держит порт
sudo ss -tlnp | grep :8080
# → LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("docker-proxy",pid=1234,...))

# 2. Если docker-proxy — какой контейнер
docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep 8080
# → web   0.0.0.0:8080->80/tcp

# 3. Если процесс хоста
sudo lsof -i :8080
# → nginx   5678 root  6u  IPv4 ... TCP *:8080 (LISTEN)

# 4. Маппинги конкретного контейнера (обязательно для -P: хост-порт случайный)
docker port web
# → 80/tcp -> 0.0.0.0:32768

# 5. Коллизия интерфейсов: wildcard-бинд конфликтует с loopback-биндом
docker run -d --name web2 -p 8080:80 nginx
# → Error response from daemon: ... Bind for 0.0.0.0:8080 failed:
#   port is already allocated   ← хотя первый контейнер биндил 127.0.0.1
```

**Решение:** остановить конфликтующий контейнер (`docker stop web`), освободить порт процесса (`sudo systemctl stop nginx`) или сменить маппинг (`-p 8081:80`).

### Сценарий 2: Порт опубликован, но недоступен извне

```bash
# 1. На каком интерфейсе бинд
ss -tlnp | grep :8080
# → 127.0.0.1:8080   ← доступен только с самого хоста!

# 2. Правильный маппинг для доступа из LAN
docker run -p 0.0.0.0:8080:80 nginx     # или просто -p 8080:80

# 3. Firewall хоста
sudo iptables -L -n -v | grep -i drop
sudo ufw status

# 4. Docker 28+: неопубликованные порты DROP-аются для трафика
#    извне (LAN) — но с самого хоста по container IP доступны.
#    Вернуть старое поведение (без фильтрации портов при
#    direct-routing): сеть с gateway_mode=nat-unprotected.
#    Опция "ip-forward-no-drop": true в /etc/docker/daemon.json
#    лишь возвращает политику FORWARD в ACCEPT — DROP для
#    неопубликованных портов она НЕ отменяет
#    (детали — см. network_connectivity_issues.md)
```

**Диагностика «с хоста работает, из сети нет»:** `curl localhost:8080` на хосте vs `curl <host-ip>:8080` извне. Разница указывает на бинд к `127.0.0.1` или firewall.

**Как Docker обходит firewall (важно для SRE):** трафик к published-портам идёт через таблицу `nat` (DNAT) и **минует** цепочки `INPUT`/`OUTPUT` ufw — правила ufw на порт не действуют в обе стороны (документация Docker, «Packet filtering and firewalls»). С firewalld наоборот: dockerd создаёт зону `docker` с `target=ACCEPT` и вставляет в неё все bridge-интерфейсы, поэтому правила firewalld на эти интерфейсы перестают работать. Для честной фильтрации published-портов фильтруйте в `FORWARD`-цепочке или на границе сети, а не через ufw INPUT.

### Сценарий 3: Безопасная привязка к loopback

Для сервисов, которые не должны быть доступны из сети (админки, отладочные порты, БД):

```bash
docker run -p 127.0.0.1:8080:80 nginx
# → ss -tlnp | grep 8080
# → LISTEN 0 511 127.0.0.1:8080 0.0.0.0:* users:(("docker-proxy",...))

# Доступ только с хоста:
curl localhost:8080
# → <html>...
```

В Compose:

```yaml
services:
  adminer:
    image: adminer
    ports:
      - "127.0.0.1:8080:8080"   # только loopback
```

### Сценарий 4: Исчерпание ephemeral-портов

**Симптом:** контейнеры не могут открывать новые исходящие соединения; `curl` из контейнера падает с `cannot assign requested address`.

```bash
# 1. Сводка TCP-состояний
ss -s
# → Total: 12345 (kernel 0) TCP: 8901 (estab 1234, closed 5678, orphaned 0,
#    timewait 7890, ...)   ← много timewait

# 2. Текущий диапазон
cat /proc/sys/net/ipv4/ip_local_port_range
# → 32768 60999

# 3. Расширение диапазона и reuse TIME_WAIT
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
sudo sysctl -w net.ipv4.tcp_tw_reuse=1
# → (постоянно: /etc/sysctl.d/99-docker-ports.conf)

# 4. Порты, зарезервированные вне диапазона (systemd, БД)
cat /proc/sys/net/ipv4/ip_local_reserved_ports
# → 25000,25001   ← эти порты исключены из ephemeral-диапазона
```

Теория TIME_WAIT и exhaustion — **[Transport layer](../../Networking/OSI_TCP_IP_Model/transport_layer.md)**; общая диагностика — **[Network troubleshooting flowchart](../../Networking/OSI_TCP_IP_Model/network_troubleshooting_flowchart.md)**.

### Сценарий 5: Rootless — привилегированные порты

В rootless-режиме `docker run -p 80:80` падает (детали — **[docker_daemon_failures.md](./docker_daemon_failures.md)**, Сценарий 6):

```bash
docker run -p 80:80 nginx:alpine
# → Error response from daemon: ... cannot expose privileged port 80,
#   you might need to add "net.ipv4.ip_unprivileged_port_start=0"
#   (currently 1024) to /etc/sysctl.conf, or set CAP_NET_BIND_SERVICE
#   on rootlesskit binary, or choose a larger port number (>= 1024)
```

Решения: маппинг на порт ≥ 1024 (рекомендуется), `net.ipv4.ip_unprivileged_port_start=0` в sysctl, или `sudo setcap cap_net_bind_service=ep $(which rootlesskit)` + `systemctl --user restart docker`.

### Сценарий 6: Compose — порт занят старым стеком

```bash
docker compose up
# → Error response from daemon: driver failed programming external
#   connectivity ... Bind for 0.0.0.0:8080 failed: port is already allocated

# Старый контейнер от предыдущего compose up
docker compose down          # снять текущий стек
docker compose ps -a         # найти остатки
docker rm -f <old-container> # удалить вручную, если compose не видит
```

**Причина:** предыдущий стек не снят (`docker compose down` не выполнен), либо контейнер создан вне Compose с тем же портом. В Compose можно зафиксировать интерфейс и протокол развёрнутым синтаксисом:

```yaml
services:
  web:
    ports:
      - target: 80
        published: 8080
        protocol: tcp
        mode: host   # host — единственный режим для bridge-сетей
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `port is already allocated` | Порт занят контейнером или процессом хоста | `ss -tlnp`, `docker ps --format '{{.Ports}}'`; освободить или сменить порт |
| `port is already allocated` при «другом» интерфейсе | Wildcard-бинд `0.0.0.0` покрывает `127.0.0.1` | Биндить на разные конкретные IP или менять порт |
| `Binding for 0.0.0.0:8080 failed` (Compose) | То же, в Compose-стеке | `docker compose down`; удалить остатки контейнеров |
| Порт опубликован, но недоступен из LAN | Бинд к `127.0.0.1`, firewall или Docker 28 isolation | `-p 0.0.0.0:8080:80`; `iptables`/`ufw`; проверка из сети |
| Правила ufw «не работают» на published-портах | Docker DNAT-маршрутизация минует `INPUT`/`OUTPUT` ufw | Фильтровать в `FORWARD` или на границе сети |
| `WARNING: Published ports are discarded...` | `-p` в `--network host` | Убрать `-p`; приложение слушает порт хоста напрямую |
| `cannot assign requested address` из контейнера | Исчерпание ephemeral-портов | `ss -s`; расширить `ip_local_port_range`, `tcp_tw_reuse=1` |
| `cannot expose privileged port` (rootless) | Порт < 1024 в rootless | Порт ≥ 1024; `ip_unprivileged_port_start=0`; `setcap` на `rootlesskit` |
| Доступ с хоста по `localhost` не работает при `userland-proxy: false` | Только DNAT; loopback-хоста не проксируется | Включить `userland-proxy: true` или обращаться по IP bridge (`172.17.0.1`) |
| `EXPOSE`/`expose` не даёт доступа с хоста | Это документация, не публикация | Добавить `-p`/`ports` |

## Валидация

```bash
# 1. Порт забинден на нужном интерфейсе
sudo ss -tlnp | grep :8080
# → LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("docker-proxy",...))

# 2. Сервис отвечает снаружи
curl -s -o /dev/null -w '%{http_code}' http://$(hostname -I | awk '{print $1}'):8080
# → 200

# 3. Loopback-маппинг недоступен извне
curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://<host-ip>:8080
# → 000 (таймаут) — ожидаемо для 127.0.0.1-бинда

# 4. Ephemeral-диапазон достаточен
ss -s | grep timewait
# → timewait 12 (не десятки тысяч)
```

## Лучшие практики

1. **Явно указывайте интерфейс**: `-p 127.0.0.1:8080:80` для внутренних сервисов — не расширяйте поверхность атаки случайно.
2. **Проверяйте `ss -tlnp` до `docker run`** при «port is already allocated» — быстрее, чем гадать.
3. **Фиксируйте хост-порты в Compose** — случайные порты (`-P`) ломают firewall-правила и алерты.
4. **Мониторьте TIME_WAIT** на хостах с исходящей нагрузкой (прокси, API-шлюзы): алерт на `ss -s` timewait > 20000.
5. **`userland-proxy: false`** для production-хостов с высокой нагрузкой (меньше процессов, ниже latency) — но помните про loopback-хоста (см. таблицу выше).
6. **Docker 28+**: неопубликованные порты недоступны извне по умолчанию — публикуйте явно через `-p` (см. **[network_connectivity_issues.md](./network_connectivity_issues.md)**).
7. **Не полагайтесь на ufw для published-портов** — DNAT-минование `INPUT`-цепочки значит, что «закрыть порт в ufw» не закроет опубликованный порт; фильтруйте в `FORWARD` или на границе сети.
8. **`EXPOSE` — не публикация**: он не открывает хост-порт; в security-ревью проверяйте именно `ports`/`-p`.

## Дополнительная информация

### См. также

- **[Диагностика сетевой связности](./network_connectivity_issues.md)** — iptables, MTU, conntrack, Docker 28 isolation.
- **[Диагностика демона](./docker_daemon_failures.md)** — rootless и привилегированные порты.
- **[Docker: Оптимизация производительности](../Docker_performance_tuning.md)** — `userland-proxy`, TCP-буферы.
- **[Transport layer (TIME_WAIT)](../../Networking/OSI_TCP_IP_Model/transport_layer.md)** — теория исчерпания портов.
- **[Сетевой драйвер host](../Docker_network/drivers/host.md)** — режим без маппинга портов.

**Глубокое изучение:**
- **[docker run — publishing ports (документация)](https://docs.docker.com/reference/cli/docker/container/run/#publish)** — семантика `-p`.
- **[Docker 28 network isolation](../Docker_network/docker_network_policies.md)** — политики фильтрации.
