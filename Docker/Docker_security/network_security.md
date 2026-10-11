# Сетевая безопасность Docker

**Актуально для:** Docker Engine 29.x. Сетевая теория (bridge/overlay/macvlan, ICC, DOCKER-USER, gateway mode, direct routing) — SSoT в [docker_network_policies.md](../Docker_network/docker_network_policies.md); egress-контроль — в [docker_network_egress.md](../Docker_network/docker_network_egress.md). Данный файл — security-разрез: угрозы, CVE и конфигурации защиты сети контейнеров.

## Определения

**ICC (Inter-Container Communication)** — флаг демона, разрешающий прямое общение контейнеров внутри одной bridge-сети. По умолчанию `true`: любой контейнер в bridge-сети достигает любого другого по IP.

**DOCKER-USER** — цепочка iptables, которую Docker обрабатывает **после** своих правил и которая сохраняется при перезапуске демона. Единственная надёжная точка для пользовательских firewall-правил Docker.

**Internal network** — bridge-сеть без шлюза наружу (`docker network create --internal`): контейнеры общаются только друг с другом.

**Host network** (`--network=host`) — контейнер разделяет сетевой namespace хоста: все порты, все интерфейсы, без сетевой изоляции.

**DNS-forwarder Docker** — встроенный DNS-прокси демона (127.0.0.11), резолвит имена контейнеров и пересылает остальные запросы на DNS хоста.

## Базовые концепции

### Модель угроз сети контейнеров

| Угроза | Вектор | Последствия |
| :--- | :--- | :--- |
| Lateral movement | ICC=true, общая bridge-сеть | Скомпрометированный контейнер атакует соседние |
| Эксфильтрация данных | Открытый egress | Данные утекают через DNS/HTTP из контейнера |
| Обход изоляции | `--network=host` | Контейнер видит все порты хоста; доступ к API containerd-shim (CVE-2020-15257) |
| Эксфильтрация из «изолированной» сети | DNS-forwarder (CVE-2024-29018) | Запросы уходят на внешний DNS, несмотря на `--internal` |
| Spoofing трафика хоста | IPv6 RA (CVE-2020-13401) | Контейнер перенаправляет IPv6-трафик хоста |
| Атака на управляющую плоскость | `/var/run/docker.sock` в контейнере | Полный контроль хоста (не сеть, но частый вектор) |

### Почему iptables в контейнере не работает

Контейнер по умолчанию не имеет `NET_ADMIN` и `NET_RAW` — правила iptables внутри контейнера неприменимы. Сетевая фильтрация выполняется **на хосте**: цепочки DOCKER, DOCKER-ISOLATION-STAGE-1/2, DOCKER-USER. Поэтому все security-политики конфигурируются на хосте или через daemon.json, а не внутри контейнера.

## Практические сценарии

### Сценарий 1: запрет межконтейнерного трафика

**Глобально (все сети):**

```json
// /etc/docker/daemon.json
{ "icc": false }
```

```bash
sudo systemctl restart docker
# Проверка: контейнеры в одной bridge-сети не пингуют друг друга по IP
```

**Точечно (одна сеть, сохраняя ICC):** отдельная bridge-сеть + правила DOCKER-USER по интерфейсу. Полная механика цепочек — в [docker_network_policies.md](../Docker_network/docker_network_policies.md).

**Правило по умолчанию для всех сетей (whitelist-подход):**

```bash
# Запретить весь трафик между контейнерами разных сетей
sudo iptables -I DOCKER-USER -i docker0 ! -o docker0 -j DROP
```

### Сценарий 2: egress-контроль

Docker не имеет встроенного egress-файрвола. Три уровня решения:

1. **`--internal`** — сеть без шлюза: контейнеры не имеют маршрута наружу.
2. **iptables в DOCKER-USER** — фильтрация по IP/порту назначения.
3. **HTTP-прокси (Squid)** — L7-whitelist доменов для контейнеров, которым нужен интернет.

Пошаговые конфиги и примеры — в [docker_network_egress.md](../Docker_network/docker_network_egress.md).

### Сценарий 3: защита от CVE-2024-29018 (DNS-эксфильтрация из internal-сети)

**Уязвимость:** Docker DNS-forwarder пересылал запросы на внешние DNS для контейнера, подключённого только к `--internal` сети, если DNS хоста слушал на loopback (systemd `127.0.0.53`). Данные уходили наружу через DNS-запросы.

**Исправление:** Docker ≥ 25.0.5 — запросы не пересылаются на внешние серверы для internal-сетей.

**Проверка:**

```bash
docker version --format '{{.Server.Version}}'
# → 29.8.1 (>= 25.0.5 — защищён)
```

**Вывод для архитектуры:** `--internal` — не гарантия отсутствия исходящего трафика на непропатченных версиях; для строгой изоляции комбинируйте с DOCKER-USER.

### Сценарий 4: защита от CVE-2020-13401 (IPv6 RA spoofing)

**Уязвимость:** в конфигурации по умолчанию контейнер с `CAP_NET_RAW` мог отправлять поддельные IPv6 Router Advertisements, перенастраивая маршрутизацию хоста. Затронуты Docker 18.09.1, 19.03.0; исправлено в 19.03.14 (отключение RA).

**Митигация:** обновить Docker; для контейнеров без необходимости IPv6 — `--sysctl net.ipv6.conf.all.disable_ipv6=1` или отключить IPv6 в демоне.

### Сценарий 5: почему `--network=host` — отдельный риск

Контейнер в host-сети:
- видит и может связываться со всеми портами хоста (включая локальные API);
- на containerd < 1.3.9 / 1.4.0–1.4.2 с UID 0 имеет доступ к абстрактному сокету shim'а (CVE-2020-15257) — запуск процессов с повышенными правами;
- обходит все сетевые политики Docker.

**Правило:** `--network=host` только для системных компонентов (мониторинг, VPN), никогда для недоверенных образов. Обход CVE-2020-15257 без патча — AppArmor `deny unix addr=@**`.

### Сценарий 6: шифрование трафика между хостами (overlay)

Overlay-сети Swarm поддерживают шифрование:

```bash
docker network create --driver overlay --opt encrypted app-net
# → трафик между узлами шифруется (IPsec-подобный, через VXLAN)
```

Для bridge-сетей на одном хосте шифрование не требуется (локальный трафик); для межхостового — overlay `--opt encrypted` или сетевой стек (WireGuard, Cilium).

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Правила iptables исчезают после рестарта Docker | Правила добавлены в цепочки DOCKER* напрямую | Добавлять только в DOCKER-USER — Docker перезаписывает свои цепочки при старте |
| Контейнер в internal-сети имеет интернет | Старая версия Docker (CVE-2024-29018) или DNS хоста на loopback | Обновить Docker ≥ 25.0.5; проверить `docker network inspect <net>` (наличие шлюза) |
| ICC=false не блокирует трафик | Контейнеры в одной user-defined bridge-сети (ICC применяется к docker0 и user-defined) | Проверить `docker network inspect`; использовать DOCKER-USER для явного запрета |
| Контейнер не резолвит имена | DNS-forwarder отключён или `--dns` указан неверно | `docker run --dns 8.8.8.8`; проверить `/etc/resolv.conf` в контейнере |
| Подозрение на эксфильтрацию через DNS | Аномальный объём UDP/53 от контейнера | `tcpdump -i docker0 port 53`; ограничить egress через DOCKER-USER; мониторинг — [runtime_monitoring.md](./runtime_monitoring.md) |

## Лучшие практики

1. **`icc: false` по умолчанию** в daemon.json; разрешайте общение явно через общие сети.
2. **Все пользовательские правила — в DOCKER-USER.** Это единственная цепочка, переживающая рестарт демона.
3. **`--internal` для бэкендов**, которым не нужен интернет (БД, очереди), с учётом CVE-2024-29018 на старых версиях.
4. **Никогда `--network=host` для недоверенных образов** — снимает сетевую изоляцию и экспонирует API shim'а (CVE-2020-15257).
5. **Egress — белый список.** Docker не фильтрует исходящий трафик: прокси или DOCKER-USER правила обязательны для compliance (PCI DSS req. 1).
6. **Шифруйте межхостовой трафик** (`--opt encrypted` для overlay).
7. **Мониторьте сетевые аномалии** через Falco/Tetragon — правила в [runtime_monitoring.md](./runtime_monitoring.md).

## Дополнительная информация

**Связанные документы:**

- [Политики Docker-сетей](../Docker_network/docker_network_policies.md) — SSoT: ICC, DOCKER-USER, gateway mode, direct routing, raw PREROUTING.
- [Egress-контроль](../Docker_network/docker_network_egress.md) — SSoT: прокси, DNS-egress, iptables-конфиги.
- [Docker Networking: вопросы на собеседованиях](../Docker_network/docker_network_interview_qa.md) — Q&A по сетевой модели.
- [CVE побегов из контейнеров](./container_escape_cves.md) — CVE-2020-15257, CVE-2024-29018, CVE-2020-13401.
- [Укрепление хоста и демона](./host_daemon_hardening.md) — сетевая конфигурация демона.
- [docker-socket-proxy](../Docker_compose/docker_compose_security.md) — защита управляющего API.

**Внешние ресурсы:**

- [Docker network security](https://docs.docker.com/network/) — официальная документация.
- [Docker Security Advisories](https://docs.docker.com/security/security-announcements) — бюллетени (CVE-2024-29018, CVE-2020-13401).

**Инструменты:** `iptables` (DOCKER-USER), `tcpdump` (диагностика), Falco/Tetragon (мониторинг), Squid (L7-egress).
