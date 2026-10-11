# Методология диагностики сетевых проблем Docker (Decision Tree)

**Актуально для:** Docker Engine 29.x

## Определения

- **Decision tree (дерево решений)** — пошаговый алгоритм диагностики: от симптома к причине через последовательность проверок, каждая из которых отсекает класс проблем.
- **Слой диагностики** — уровень стека, на котором проверяется гипотеза: приложение → DNS → IP → порт → файрвол/маршрутизация → IPAM → MTU → conntrack → внешние факторы.
- **`getent hosts`** — проверка разрешения имени тем же путём, что и приложение (через NSS и `/etc/hosts`), в отличие от `dig`/`nslookup`, которые обращаются к DNS напрямую.
- **`nicolaka/netshoot`** — образ с набором сетевых утилит (`tcpdump`, `mtr`, `nmap`, `iperf3`, `ss`, `dig`), запускаемый в netns приложения.
- **IPAM** — подсистема управления адресами (IP Address Management): выделение подсетей и адресов сетям и контейнерам. Перекрытие подсетей Docker с внешней инфраструктурой — классическая причина «чёрной» маршрутизации без ошибок при создании сети.
- **`docker-proxy`** — userspace-процесс, переносящий трафик опубликованного порта для обращений с самого хоста на `127.0.0.1`; внешний трафик идёт по DNAT в ядре и прокси не затрагивает.
- **Hairpin NAT** — обращение к собственному опубликованному порту хоста (с хоста или из контейнера); требует MASQUERADE/`route_localnet`, иначе ответ уходит мимо клиента.

## Основные концепции

### Принцип: определить слой, а не гадать

Сетевой запрос проходит четыре уровня (см. [обзор сетевой модели](../docker_network.md)): файрвол/NAT → опубликованные порты → endpoint (veth) → sandbox (netns). Проблема — в одном из них. Диагностика начинается с определения, **какой** уровень не работает, а не с проверки приложения. Каждая проверка ниже отсекает целый класс проблем.

### Порядок проверок (от дешёвой к дорогой)

```
Симптом: «не работает»
        │
        ▼
[1] Контейнер запущен?            docker ps / docker inspect .State.Status
        │ да
        ▼
[2] В какой сети контейнер?       docker inspect .HostConfig.NetworkMode
        │
        ▼
[3] Резолвится ли имя?            getent hosts <name>  (путь приложения)
        │                          dig +short @127.0.0.11 <name>  (прямой DNS)
        ▼
[4] Доступен ли IP?               ping <ip>  (ICMP)
        │ нет → [4а] Перекрываются ли подсети?
        │         docker network inspect <net> --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}'
        ▼
[5] Открыт ли порт?               nc -zv <ip> <port> / ss -tulpn
        │
        ▼
[6] Файрвол/маршрутизация?        sysctl net.ipv4.ip_forward
        │                          iptables -S DOCKER-USER; iptables -t raw -S PREROUTING
        ▼
[7] MTU-проблема?                 ping -M do -s 1472 <ip>
        │
        ▼
[8] Conntrack исчерпан?           sysctl net.netfilter.nf_conntrack_count
        │
        ▼
[9] Внешний фактор?               upstream DNS, VPN, физическая сеть
```

Ключевое правило: **проверяйте тем же путём, что и приложение.** `getent hosts` (NSS + `/etc/hosts`) — путь приложения; `dig` — прямой DNS. Расхождение результатов — сам по себе диагностический сигнал (запись в `/etc/hosts`, а не в DNS).

**Инструменты в минимальных образах.** `getent`, `nc`, `ping`, `ss` — утилиты glibc/busybox; в distroless, scratch и slim-образах их нет, и `docker exec` выполнять нечего. Диагностику ведите из `nicolaka/netshoot` в netns приложения (сценарий 6) — это работает без shell в целевом образе.

## Предварительные условия

- Docker Engine 29.x: `docker version --format '{{.Server.Version}}'`.
- Root/sudo на хосте для `iptables` и `sysctl`; в rootless-режиме демон не управляет файрволом хоста.
- Доступ к демону и его сетевому стеку (в Docker Desktop сеть живёт в ВМ — см. «Ограничения»).

## Практические сценарии

### Сценарий 1: Контейнер не резолвит имя соседа

```bash
# [2] Сеть контейнера
docker inspect app --format '{{.HostConfig.NetworkMode}}'
# → app-net   (пользовательская — есть встроенный DNS)
# → bridge    (дефолтная — DNS НЕТ, только IP)

# [3] Резолв тем путём, что и приложение
docker exec app getent hosts db
# → 172.18.0.3   db        — OK
# → (пусто, exit 2)        — имя не резолвится

# [3а] Прямой DNS (обходит /etc/hosts)
docker exec app dig +short @127.0.0.11 db
# → 172.18.0.3

# Расхождение getent и dig → запись в /etc/hosts, не в DNS
docker exec app cat /etc/hosts
```

Если сеть `bridge` (дефолтная) — встроенного DNS нет. Решение: пользовательская сеть. Если сеть пользовательская, но имя не резолвится — проверьте, что контейнеры в **одной** сети и имя задано явно (`--name`/`--network-alias`), а не сгенерировано.

### Сценарий 2: Имя резолвится, но соединение не устанавливается

```bash
# [4] IP доступен?
docker exec app ping -c 2 172.18.0.3
# → 0% packet loss   — IP доступен
# → 100% loss        — проблема маршрутизации/изоляции

# [5] Порт открыт?
docker exec app nc -zv 172.18.0.3 5432
# → open   — порт доступен
# → refused/timed out — приложение не слушает или фильтрует

# [5а] Кто слушает порт (внутри целевого)
docker exec db ss -tulpn
# → LISTEN 0 511 0.0.0.0:5432  0.0.0.0:*  users:(("postgres",pid=1,fd=5))

# [5б] ICC не отключён для сети?
docker network inspect app-net --format '{{json .Options}}'
# → {"com.docker.network.bridge.enable_icc":"false"}   — прямой доступ внутри сети заблокирован
```

Если `ping` не проходит — проверьте, что контейнеры в одной сети (`docker network inspect <net> --format '{{range .Containers}}{{.Name}}{{end}}'`) и что ICC не отключён (`-o com.docker.network.bridge.enable_icc=false` блокирует прямой доступ между контейнерами внутри сети; это полное замыкание, а не микросегментация — см. [Политики](../docker_network_policies.md)).

### Сценарий 3: Порт опубликован, но недоступен снаружи

```bash
# [2] Порт действительно опубликован?
docker inspect app --format '{{json .NetworkSettings.Ports}}'
# → {"8080/tcp":[{"HostIp":"","HostPort":"8080"}]}   — опубликован
# → {}                                                — не опубликован (использован -P?)

# Быстрая проверка привязки
docker port app
# → 8080/tcp -> 0.0.0.0:8080   — все интерфейсы
# → 8080/tcp -> 127.0.0.1:8080 — только loopback

# [6] Файрвол: DOCKER-USER
sudo iptables -S DOCKER-USER
# → -N DOCKER-USER
# → -A DOCKER-USER -j DROP   — блокирует весь трафик

# [6а] Direct routing блокируется в raw (Docker 28.2+)
sudo iptables -t raw -S PREROUTING
# → -A PREROUTING ! -i docker0 * -d 172.18.0.2 -j DROP

# [6б] UFW не защищает опубликованные порты (DNAT до filter)
sudo ufw status
# → 8080 DENY   — бесполезно для docker run -p 8080:80

# [6в] Доступ с самого хоста: localhost работает, а внешний IP — нет (или наоборот)
curl -sS -m 3 http://127.0.0.1:8080/ ; curl -sS -m 3 http://<host-ip>:8080/
ps -C docker-proxy -o args= | grep 8080
# → пусто — docker-proxy умер: внешний доступ живёт (DNAT в ядре), а localhost отвалился
#   Восстановление: docker restart app (демон не перезапускает прокси самостоятельно)

# userland-proxy=false: loopback работает через route_localnet (только IPv4)
sysctl -a 2>/dev/null | grep route_localnet
# → net.ipv4.conf.br-xxxx.route_localnet = 1   — OK
#   ::1 при userland-proxy=false не работает в принципе: если резолвер вернёт ::1
#   первым, клиент молча таймаутит
```

Если доступен с хоста, но не извне — проверяйте `DOCKER-USER` и привязку (`-p 127.0.0.1:8080:80` ограничивает loopback'ом). Если прямой доступ к IP контейнера не работает — это `raw` PREROUTING (Docker 28.2+), `DOCKER-USER` его не отменит.

### Сценарий 4: Пинги проходят, но HTTP обрывается

```bash
# [7] MTU-проблема (типично для VPN/VXLAN/overlay)
docker exec app ping -M do -s 1472 8.8.8.8
# → Frag needed and DF set   — MTU хоста/туннеля < 1500

# Определение рабочего MTU
for s in 1472 1452 1400 1372; do
  ping -M do -s $s -c 1 8.8.8.8 >/dev/null 2>&1 && echo "MTU $((s+28)) OK" && break
done
# → MTU 1450 OK

# Решение: MTU сети или демона
docker network create -o com.docker.network.driver.mtu=1450 app-net
# или в daemon.json: {"mtu": 1450}

# Проверка применённого значения
docker network inspect app-net --format '{{json .Options}}'
# → {"com.docker.network.driver.mtu":"1450"}
```

### Сценарий 5: Периодические обрывы при большом числе соединений

```bash
# [8] Conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → count=262144 max=262144   — таблица полна

dmesg | grep conntrack
# → nf_conntrack: table full, dropping packet

# Немедленное облегчение
sudo sysctl -w net.netfilter.nf_conntrack_max=524288

# Решение (персистентное)
echo "net.netfilter.nf_conntrack_max=524288" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### Сценарий 6: Захват трафика в netns приложения

```bash
# Диагностический контейнер в netns приложения
docker run --rm -it --network container:app nicolaka/netshoot

# Внутри:
ss -tulpn          # кто слушает (PID не виден без --pid container:)
tcpdump -i eth0 -nn port 80   # захват трафика
mtr 8.8.8.8        # трассировка
iperf3 -c <server> # замер throughput
```

`ss -p` не показывает владельца порта, потому что PID namespace не разделяется — добавьте `--pid container:app --cap-add SYS_PTRACE --security-opt seccomp=unconfined`.

### Сценарий 7: Нет выхода в интернет из контейнера (egress)

```bash
# [3] DNS наружу резолвится?
docker exec app getent hosts google.com
# → адрес   — DNS есть, проблема в маршрутизации
# → (пусто) — проблема в DNS (см. dns_resolution_issues.md)

# [6] Маршрутизация на хосте
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1   — OK
# → 0                          — egress не работает: sudo sysctl -w net.ipv4.ip_forward=1

# Маскарадинг на POSTROUTING
sudo iptables -t nat -S POSTROUTING | grep MASQUERADE
# → -A POSTROUTING -s 172.18.0.0/16 ! -o br-xxxx -j MASQUERADE   — OK

# Сеть internal?
docker network inspect app-net --format '{{.Internal}}'
# → true   — маршрута по умолчанию нет по дизайну (см. docker_network_policies.md)

# Маршрут по умолчанию внутри контейнера
docker exec app ip route
# → default via 172.18.0.1 dev eth0   — OK
# → (пусто)                           — шлюз не назначен
```

Если `ip_forward=1`, MASQUERADE есть, сеть не internal, а интернета нет — проверяйте upstream-файрвол хоста и фильтрацию по протоколу (ICMP может проходить, а TCP — нет; проверяйте именно тот протокол, что использует приложение). Детальный разбор уровней egress-контроля — [Egress-политики](../docker_network_egress.md).

### Сценарий 8: Контейнер не достучится до сервиса на хосте

```bash
# Имя хоста резолвится?
docker exec app getent hosts host.docker.internal
# → 172.18.0.1 host.docker.internal   — OK (задано через host-gateway)
# → (пусто)                            — на Linux имя не задано по умолчанию

# Решение (Engine 20.10+): шлюз сети под именем хоста
docker run --add-host=host.docker.internal:host-gateway <image>

# Сервис на хосте слушает не тот интерфейс
ss -tlnp | grep :8080
# → LISTEN ... 127.0.0.1:8080   — контейнер не достанет: нужен 0.0.0.0
```

`host.docker.internal` на Docker Desktop доступен автоматически; на Linux — только через `host-gateway` (Engine 20.10+). Полный разбор — [Алиасы хоста в контейнере](../../Docker_troubleshooting/host_aliases_in_container.md).

### Сценарий 9: Подсети Docker перекрываются с инфраструктурой (IPAM)

```bash
# Подсети всех сетей
for n in $(docker network ls -q); do
  docker network inspect $n --format '{{.Name}}: {{range .IPAM.Config}}{{.Subnet}} {{end}}'
done
# → bridge: 172.17.0.0/16
# → app-net: 172.18.0.0/16

# Перекрытие с маршрутами хоста / корпоративной сетью
ip route | grep 172.17
# → 172.17.0.0/16 via 10.0.0.1 ...   — конфликт: трафик уходит в корпоративную
#                                        сеть, а не в docker0
```

Docker выбирает подсети автоматически и не знает о внешней инфраструктуре: если корпоративная сеть использует тот же диапазон (типично `172.17.0.0/16`), контейнеры теряют связь с ней или с другими хостами — при этом `docker network create` не выдаёт ошибки, потому что перекрытие внешнее. Явно заданные `--subnet` IPAM проверяет и откажет (`Pool overlaps with other one on this address space`), но автопул — нет. Решение — пул по умолчанию в `daemon.json`:

```json
{"default-address-pools": [{"base": "172.31.0.0/16", "size": 24}]}
```

Перекрытие двух Docker-сетей на одном демоне невозможно создать через default IPAM; если контейнер подключён к двум сетям с одинаковой подсетью (сторонний IPAM/плагин), маршрутизация становится неоднозначной — проверяйте `docker exec <c> ip route`. Планирование адресации для multi-host — [Multihost-сети](../docker_network_multihost.md).

## Устранение неисправностей

### Сводная таблица «симптом → слой → команда»

| Симптом | Слой | Первая команда |
| :--- | :--- | :--- |
| Имя не резолвится | DNS | `docker exec <c> getent hosts <name>` |
| Имя резолвится, соединения нет | IP/порт | `docker exec <c> nc -zv <ip> <port>` |
| Нет интернета из контейнера | маршрутизация | `sysctl net.ipv4.ip_forward` |
| Порт опубликован, снаружи недоступен | файрвол | `sudo iptables -S DOCKER-USER` |
| `localhost:порт` не отвечает, а извне — да | docker-proxy | `ps -C docker-proxy -o args=` |
| Контейнер не видит сервис на хосте | адресация | `docker exec <c> getent hosts host.docker.internal` |
| Связь с частью инфраструктуры потеряна | IPAM | `docker network inspect <net> --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'` |
| Пинги есть, HTTP обрывается | MTU | `ping -M do -s 1472 <ip>` |
| Периодические обрывы, много соединений | conntrack | `sysctl net.netfilter.nf_conntrack_count` |
| Всё работало, перестало после обновления | версия Engine | `docker version`; см. [DNS](../dns_and_service_discovery.md) |
| Sidecar `running`, но сети нет | жизненный цикл | `readlink /proc/self/ns/net` у обоих |

### Типовые ловушки

- **`dig` вместо `getent`** — `dig` обходит `/etc/hosts` и NSS; расхождение с `getent` означает, что имя резолвится через `/etc/hosts`.
- **`DOCKER-USER` для direct routing** — блокировка в `raw` PREROUTING (Docker 28.2+) срабатывает раньше `filter`; правило в `DOCKER-USER` не может её отменить.
- **UFW для опубликованных портов** — DNAT в `nat` обходит `INPUT`/`OUTPUT` UFW; фильтруйте в `DOCKER-USER`.
- **Проверка с хоста вместо из контейнера** — с хоста доступен адрес контейнера напрямую, извне — только опубликованный порт; разные пути, разные результаты.
- **Ожидание round-robin от DNS** — резолвер перемешивает адреса случайно, балансировка — на клиенте.
- **`docker-proxy` умер** — демон не перезапускает прокси самостоятельно: `localhost:порт` отваливается, а внешний доступ (DNAT) живёт. Восстановление — `docker restart <app>`.
- **`userland-proxy=false` и IPv6** — loopback-доступ к опубликованному порту работает только по IPv4 (`route_localnet`); если резолвер вернёт `::1` первым, клиент молча таймаутит.
- **Автопул IPAM** — Docker не знает о корпоративных подсетях; перекрытие с внешней инфраструктурой даёт «чёрную» маршрутизацию без ошибок при создании сети.
- **Проверка egress через ping** — ICMP может проходить, а TCP — нет (фильтр по протоколу); проверяйте именно тот протокол, который использует приложение (`nc -zv`, `curl`).

## Валидация

```bash
# 1. Демон отвечает, версия в scope
docker version --format '{{.Server.Version}}'
# → 29.8.2

# 2. Инструменты доступны в целевом образе (или ведите диагностику из netshoot)
docker exec app sh -c 'command -v getent nc ss'
# → /usr/bin/getent /usr/bin/nc /usr/bin/ss
# → (пусто) — минимальный образ

# 3. Сводная таблица применима к симптому
docker inspect app --format '{{.HostConfig.NetworkMode}} {{json .NetworkSettings.Ports}}'
# → app-net {"8080/tcp":[{"HostIp":"","HostPort":"8080"}]}

# 4. Цепочка DOCKER-USER существует и читаема
sudo iptables -S DOCKER-USER
# → -N DOCKER-USER
```

## Рекомендации

- **Начинайте с `[2]` (сеть контейнера)** — половина проблем с DNS и связностью — контейнер в дефолтной сети `bridge` вместо пользовательской.
- **Проверяйте путём приложения** — `getent hosts`, а не `dig`; расхождение — сигнал к проверке `/etc/hosts`.
- **Идите по слоям в порядке** — DNS → IP → порт → файрвол/маршрутизация → IPAM → MTU → conntrack; не перескакивайте.
- **Используйте netshoot** для захвата трафика и `ss` в netns приложения — это быстрее, чем отладка вслепую.
- **Снимайте baseline перед изменением правил** — `iptables-save`, `docker network ls`, `docker info` до правки.
- **Откатите изменения после диагностики** — удалите правило: `sudo iptables -D DOCKER-USER <правило>` (или `sudo iptables -F DOCKER-USER`); conntrack: удалите строку из `/etc/sysctl.conf` и `sudo sysctl -p`; MTU: опция задаётся при создании сети — пересоздайте сеть. Правила `DOCKER-USER` живут только в памяти ядра и не переживают перезапуск демона без сервиса персистентности (см. [Политики](../docker_network_policies.md)).
- **Документируйте инцидент** — симптом, слой, причина, решение; это превращает разовую диагностику в runbook.

## Дополнительная информация

### Смежные темы

- [Обзор сетевой модели](../docker_network.md) — четыре уровня стека, packet flow.
- [Устранение проблем сетевой связности](../../Docker_troubleshooting/network_connectivity_issues.md) — conntrack, MTU, netshoot (SSoT по симптомам).
- [Решение проблем с DNS](./dns_resolution_issues.md) — резолвер, ndots, systemd-resolved.
- [Интеграция с iptables/nftables](./iptables_integration.md) — цепочки, UFW.
- [Политики сетевой фильтрации](../docker_network_policies.md) — `DOCKER-USER`, `raw` PREROUTING, ICC.
- [Egress-политики](../docker_network_egress.md) — уровни контроля исходящего трафика.
- [Режим сети `container:`](../container_network.md) — диагностика в чужом netns.
- [Сетевая наблюдаемость](../docker_network_observability.md) — метрики, дропы, retransmits.
- [Алиасы хоста в контейнере](../../Docker_troubleshooting/host_aliases_in_container.md) — `host-gateway`, `host.docker.internal` (SSoT).
- [Конфликты портов](../../Docker_troubleshooting/port_conflicts.md) — бинд интерфейсов, ephemeral-порты.
- [Multihost-сети](../docker_network_multihost.md) — планирование IP-адресации.
- [iperf3](../../../Linux/Diagnostics/Networking/iperf3.md) — замер throughput.

### Ограничения

- Дерево покрывает типовые симптомы; редкие случаи (SELinux/AppArmor, специфика overlay-сетей и VXLAN) требуют отдельной диагностики.
- Команды `iptables` требуют root; в rootless-режиме демон не управляет файрволом хоста.
- В Docker Desktop (macOS/Windows) сеть живёт в ВМ: `nsenter` и `/var/run/docker/netns/` с хоста недоступны — используйте `docker exec`.
