# Egress control в Docker (управление исходящим трафиком)

**Актуально для:** Docker Engine 29.x

## Определения

- **Egress control** — управление исходящим трафиком контейнеров: куда контейнер может обращаться, с какого адреса он выходит и через какой путь.
- **Egress allowlist** — политика, разрешающая исходящий трафик только к перечисленным адресам/подсетям; всё остальное блокируется.
- **Egress gateway (прокси)** — выделенный контейнер/сервис, через который весь исходящий трафик проходит централизованно (HTTP-прокси, TLS-inspection, аудит).
- **Fixed SNAT IP** — фиксированный исходящий адрес для всей сети (`com.docker.network.host_ipv4`, IPv6 — `com.docker.network.host_ipv6`, Docker ≥ 25), чтобы внешние сервисы могли allowlist'ить один IP.
- **MASQUERADE vs SNAT** — MASQUERADE динамически подставляет адрес исходящего интерфейса (дефолт Docker); SNAT (`host_ipv4`/`host_ipv6`) подставляет фиксированный адрес. Разница критична на хостах с несколькими интерфейсами или динамическими адресами.
- **Gateway mode** — режим внешней связности bridge-сети (`com.docker.network.bridge.gateway_mode_ipv4/ipv6`): `nat` (дефолт), `routed` (egress без NAT, с адреса контейнера), `nat-unprotected`, `isolated` (только с `--internal`). Полная механика — SSoT в [Обзоре сетевой модели](./docker_network.md).
- **`--internal`** — флаг сети, отключающий маршрут во внешние сети: контейнеры общаются только внутри сети (DNS внутри работает, внешний — нет).
- **`DOCKER-USER`** — цепочка iptables, единственное место для пользовательских правил фильтрации; базовые egress-правила описаны в [Политиках сетевой фильтрации](./docker_network_policies.md). В nftables-бэкенде (Docker 29) цепочки нет — правила переносятся в собственную таблицу nftables (см. [Политики, сценарий 6](./docker_network_policies.md)).

## Основные концепции

### Три уровня egress control

| Уровень | Механизм | Гранулярность |
| :--- | :--- | :--- |
| **Сеть** | `--internal`, gateway modes | вся сеть целиком |
| **Хост (фильтрация)** | `DOCKER-USER` (iptables/nftables) | по подсети, адресу, порту назначения |
| **Приложение** | egress-прокси, SDK, allowlist в коде | по URL/домену, с аудитом |

Docker не имеет объекта «сетевая политика» уровня Kubernetes: egress control собирается из этих трёх уровней. Выбор уровня определяется требованием: изоляция целой сети — уровень сети; точечные запреты — `DOCKER-USER`; аудит и TLS-inspection — egress-прокси.

### Что Docker контролирует нативно

- **`--internal`** — полная изоляция от внешних сетей (нет маршрута по умолчанию). Внутренние имена резолвятся, внешние — `SERVFAIL` (замысел, не поломка).
- **Gateway mode `isolated`** — убирает адрес шлюза с моста, закрывая связность хост↔контейнер через адрес моста (только с `--internal`; режим появился в 28.0).
- **Gateway mode `routed`** — egress без NAT: исходящие пакеты сохраняют адрес контейнера. Требует маршрута обратно к подсети сети, иначе ответы теряются; применяется для маршрутизируемых IPv6-префиксов (примеры — в [Обзоре сетевой модели](./docker_network.md)).
- **`DOCKER-USER`** — точечные правила: разрешить/запретить egress по адресу назначения, порту, подсети.
- **`com.docker.network.host_ipv4`** (Docker ≥ 20.10) и **`com.docker.network.host_ipv6`** (Docker ≥ 25) — фиксированный SNAT-адрес для исходящих пакетов сети; действуют только при `com.docker.network.bridge.enable_ip_masquerade=true` (дефолт).

### Когда egress-прокси оправдан

`DOCKER-USER` фильтрует по IP/порту, но не по домену и не может аудировать TLS-трафик. Egress-прокси (Squid, Envoy, mitmproxy) оправдан, когда требуется:

- allowlist по доменам (не IP);
- аудит/логирование исходящих запросов;
- TLS-inspection (в корпоративных средах);
- централизованный выход с фиксированным IP для внешних API.

## Предварительные условия

- **Доступ root/sudo** — правила `iptables`/`nftables` и `sysctl` меняются на хосте, не внутри контейнера (контейнер по умолчанию без `NET_ADMIN`).
- **Версии Engine**: `com.docker.network.host_ipv4` — ≥ 20.10; `com.docker.network.host_ipv6` — ≥ 25; gateway modes `nat-unprotected` и `isolated` — ≥ 28.0 (`routed` опция принималась и ранее, но поведение применяется с 28.0).
- **Активный бэкенд файрвола** — `docker info --format '{{.FirewallBackend.Driver}}'`. В режиме `nftables` (Docker 29) цепочки `DOCKER-USER` не существует: правила переносятся в собственную таблицу nftables (процедура — в [Политиках, сценарий 6](./docker_network_policies.md)).
- **Ядро с `ipset`** — требование только Docker **28.0.0** для правил port publishing и изоляции сетей; начиная с 28.0.1 зависимость от модулей `ip_set`/`netfilter_xt_set` убрана (moby#49530). Правила в iptables-таблице `raw` (с 28.0.x) требуют `CONFIG_IP_NF_RAW`.
- **Диагностические утилиты** — `iptables`/`nft` на хосте; `getent`/`nc`/`ip` внутри контейнера (в минимальных образах `distroless`/`scratch`/`slim` их нет — ведите диагностику из `netshoot`).

## Практические сценарии

### Сценарий 1: Полная изоляция egress (безопасная БД)

```bash
# Сеть без выхода наружу
docker network create --internal --subnet 172.30.5.0/24 db-net
docker run -d --name pg --network db-net postgres:17-alpine

# Валидация: внешний DNS не резолвится (SERVFAIL — замысел)
docker exec pg nslookup example.com
# → ** server can't find example.com: SERVFAIL

# Валидация: нет маршрута по умолчанию
docker exec pg ip route
# → 172.30.5.0/24 dev eth0 scope link src 172.30.5.2
#   (default route отсутствует)
```

Контейнеру, которому нужен и внутренний доступ, и внешний — подключите вторую сеть (см. сценарий 3).

### Сценарий 2: Egress allowlist по адресу назначения

Базовое правило — в [Политиках](./docker_network_policies.md) (шаблон «заблокировать egress контейнеру»). Здесь — allowlist конкретных внешних адресов:

```bash
# Контейнер в app-net (172.30.6.0/24) может выходить только к двум внешним адресам
# Правила добавляются через -A (append): порядок в листинге = порядок в цепочке
sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# Разрешить DNS (нужен для резолва внешних имён)
sudo iptables -A DOCKER-USER -s 172.30.6.0/24 -p udp --dport 53 -j ACCEPT
sudo iptables -A DOCKER-USER -s 172.30.6.0/24 -p tcp --dport 53 -j ACCEPT

# Разрешить конкретные внешние адреса
sudo iptables -A DOCKER-USER -s 172.30.6.0/24 -d 203.0.113.10 -j ACCEPT
sudo iptables -A DOCKER-USER -s 172.30.6.0/24 -d 198.51.100.20 -j ACCEPT

# Всё остальное — запретить
sudo iptables -A DOCKER-USER -s 172.30.6.0/24 ! -d 172.30.6.0/24 -j DROP

# Валидация
docker exec app ping -c 2 203.0.113.10
# → 2 packets transmitted, 2 received
docker exec app ping -c 2 1.1.1.1
# → 100% packet loss
```

Порядок правил критичен: `RELATED,ESTABLISHED` первым, иначе `DROP` разорвёт установленные соединения. Не используйте `-I` для нескольких правил подряд: `-I` вставляет каждое правило в начало цепочки, итоговый порядок получается обратным, и `DROP` окажется первым — заблокировав всё, включая DNS и установленные соединения. Проверить фактический порядок: `sudo iptables -L DOCKER-USER -v -n --line-numbers`.

### Сценарий 3: Две сети — внутренняя + с выходом

```bash
# Внутренняя сеть (без выхода) и сеть с выходом
docker network create --internal --subnet 172.30.5.0/24 db-net
docker network create --subnet 172.30.6.0/24 app-net

# БД — только во внутренней сети
docker run -d --name pg --network db-net postgres:17-alpine

# Приложение — в обеих: видит БД и выходит наружу
docker run -d --name app --network app-net my-app
docker network connect db-net app

# Валидация: app пингует БД и внешний мир, БД — только внутреннее
docker exec app ping -c 1 172.30.5.2   # → OK (БД)
docker exec app ping -c 1 1.1.1.1        # → OK (внешний)
docker exec pg ping -c 1 1.1.1.1         # → Network unreachable
```

### Сценарий 4: Фиксированный исходящий IP (SNAT)

Внешний API allowlist'ит IP. Вся сеть выходит с одного адреса:

```bash
# Сеть с фиксированным SNAT-адресом
docker network create \
  --subnet 172.30.7.0/24 \
  -o com.docker.network.host_ipv4=203.0.113.100 \
  -o com.docker.network.bridge.enable_ip_masquerade=true \
  egress-net

# IPv6-аналог (Docker ≥ 25): фиксированный SNAT-адрес для IPv6-egress
docker network create --ipv6 --subnet fd00:1234::/64 \
  -o com.docker.network.host_ipv6=2001:db8:1::100 \
  -o com.docker.network.bridge.enable_ip_masquerade=true \
  egress-net6

# Валидация: исходящий адрес — фиксированный
docker run --rm --network egress-net alpine:3 \
  sh -c 'wget -qO- https://ifconfig.me'
# → 203.0.113.100

# Демон создаёт правило SNAT в POSTROUTING вместо MASQUERADE
sudo iptables -t nat -S POSTROUTING | grep 172.30.7.0
# → -A POSTROUTING -s 172.30.7.0/24 ! -o br-xxxx -j SNAT --to-source 203.0.113.100
```

Требуется `enable_ip_masquerade=true` (дефолт) и маршрут до `203.0.113.100` — адрес должен принадлежать хосту или маршрутизироваться на него. Не правьте правило SNAT вручную: демон пересоздаёт правила сети (см. [Граничные случаи](#граничные-случаи)).

### Сценарий 5: Egress через HTTP-прокси

Централизованный выход с аудитом и allowlist'ом по доменам:

```yaml
# docker-compose.yml
services:
  # Egress-прокси (Squid) — единственный выход наружу
  egress-proxy:
    image: ubuntu/squid:6.6-24.04_beta
    ports:
      - "3128:3128"
    volumes:
      - ./squid.conf:/etc/squid/squid.conf:ro
    networks:
      - egress
      - internal

  # Приложение без прямого выхода: только в internal
  app:
    image: my-app:latest
    environment:
      HTTP_PROXY: "http://egress-proxy:3128"
      HTTPS_PROXY: "http://egress-proxy:3128"
      NO_PROXY: "localhost,127.0.0.1,.internal"
    networks:
      - internal

networks:
  egress: {}      # прокси имеет выход
  internal:
    internal: true # приложение — без прямого выхода
```

```bash
# squid.conf — allowlist доменов
acl allowed dstdomain .api.example.com .cdn.example.com
http_access allow allowed
http_access deny all
```

Приложение физически не имеет маршрута наружу (`internal: true`), весь egress — через прокси, который логирует и фильтрует по домену.

Образ `ubuntu/squid` поддерживается Canonical (Verified Publisher); суффикс `_beta` в тегах — channel-имя Canonical, не признак незрелости. Предыдущий в этом файле `sameersbn/squid:3.5.27` не обновляется с 2019 года (Squid 3.5 EOL). Конфиг монтируется в `/etc/squid/squid.conf`, логи — `/var/log/squid`, init-процесс — Pebble.

### Сценарий 6: Контроль DNS-egress

```bash
# Контейнер в --internal-сети не резолвит внешние имена (SERVFAIL).
# Если внешний DNS нужен — отдельная сеть с явным --dns:
docker network create --subnet 172.30.8.0/24 dns-net
docker run -d --name app --network dns-net \
  --dns 10.0.0.10 --dns-search company.local my-app

# Валидация
docker exec app cat /etc/resolv.conf
# → nameserver 10.0.0.10
# → search company.local
```

В режимах `host` и `container:<id>` флаги `--dns`/`--dns-search` отклоняются (`conflicting options: dns and the network mode`).

## Граничные случаи

- **DNS-утечка из `--internal`-сети (CVE-2024-29018).** На Docker < 25.0.5 запросы встроенного резолвера могли уходить на внешний DNS, если DNS хоста слушал на loopback (systemd `127.0.0.53`) — эксфильтрация через DNS-запросы несмотря на `--internal`. Исправлено в 25.0.5; проверьте версию: `docker version --format '{{.Server.Version}}'`. Механика уязвимости — в [Сетевой безопасности](../Docker_security/network_security.md).
- **Демон пересоздаёт правила NAT.** Удаление или замена правила MASQUERADE/SNAT в `POSTROUTING` вручную не работает: демон восстанавливает свои правила (moby/moby#30053). Кастомный SNAT задавайте опцией `host_ipv4`/`host_ipv6` при создании сети, а не правкой iptables.
- **`routed`-сеть без обратного маршрута.** Egress с адреса контейнера работает, только если инфраструктура маршрутизирует ответы обратно к подсети сети; иначе соединения устанавливаются, а ответы теряются (симптом — `ping` проходит, HTTP-таймауты).
- **`DOCKER-USER` не видит трафик с самого хоста.** Цепочка находится в `FORWARD`: обращения хоста к контейнеру и от него идут через `OUTPUT`/`INPUT` или `docker-proxy`. Фильтруйте их отдельно.
- **nftables-бэкенд (Docker 29).** Цепочки `DOCKER-USER` не существует; правила живут в собственной таблице nftables с приоритетом выше таблиц Docker. Переход и откат — в [Политиках, сценарий 6](./docker_network_policies.md).

## Устранение неисправностей

| Симптом | Причина | Диагностика |
| :--- | :--- | :--- |
| `SERVFAIL` на внешнее имя в `--internal` | проксирование отключено намеренно | `docker network inspect <net> --format '{{.Internal}}'` |
| Egress не блокируется правилом | правило ниже `RELATED,ESTABLISHED` или неверная подсеть | `iptables -L DOCKER-USER -v -n --line-numbers` |
| Фиксированный SNAT не работает | `enable_ip_masquerade=false` или нет маршрута | `docker network inspect <net> --format '{{json .Options}}'` |
| Прокси недоступен из контейнера | прокси в другой сети или `internal` без маршрута | `docker exec app getent hosts egress-proxy` |
| Правила пропали после перезапуска демона | `DOCKER-USER` в памяти ядра | сервис персистентности (см. [Политики](./docker_network_policies.md)) |
| Ingress-трафик не фильтруется | `DOCKER-USER` видит только `FORWARD` | фильтровать в `OUTPUT`/`INPUT` или на маршруте |
| Правила есть, но egress не фильтруется | активен nftables-бэкенд: цепочки `DOCKER-USER` не существует | `docker info --format '{{.FirewallBackend.Driver}}'` |
| `routed`-сеть: соединения устанавливаются, ответы теряются | нет маршрута обратно к подсети сети | `ip route get <ip-контейнера>` с удалённого хоста |
| Фиксированный SNAT «слетает» после пересоздания сети | правило SNAT пересоздаётся демоном из опции сети | `docker network inspect <net> --format '{{json .Options}}'` |

## Валидация

```bash
# 1. Активный бэкенд файрвола (определяет, где живут правила)
docker info --format '{{.FirewallBackend.Driver}}'
# → iptables

# 2. Правило NAT для сети: MASQUERADE (динамический адрес) или SNAT (фиксированный)
sudo iptables -t nat -S POSTROUTING | grep -E 'MASQUERADE|SNAT'
# → -A POSTROUTING -s 172.30.6.0/24 ! -o br-xxxx -j MASQUERADE
# → -A POSTROUTING -s 172.30.7.0/24 ! -o br-yyyy -j SNAT --to-source 203.0.113.100

# 3. Порядок правил в DOCKER-USER: ESTABLISHED первым, DROP последним
sudo iptables -L DOCKER-USER -v -n --line-numbers
# → 1    ACCEPT     all  --  ... ctstate RELATED,ESTABLISHED
# → ...
# → 6    DROP       all  --  172.30.6.0/24  !172.30.6.0/24

# 4. Исходящий адрес контейнера — фактический, не задуманный
docker run --rm --network egress-net alpine:3 sh -c 'wget -qO- https://ifconfig.me'
# → 203.0.113.100

# 5. Изоляция: в --internal-сети нет маршрута по умолчанию
docker exec pg ip route
# → 172.30.5.0/24 dev eth0 scope link src 172.30.5.2   (default route отсутствует)
```

## Рекомендации

- **Изолируйте stateful-компоненты** через `--internal` — БД и очереди не должны иметь произвольного egress.
- **Разделяйте сети по назначению** — внутренняя (данные) и внешняя (выход) сети на одном контейнере дают точный контроль без правил на каждый порт.
- **Используйте `DOCKER-USER` для точечных запретов** — по адресу/подсети назначения; базовые шаблоны — в [Политиках](./docker_network_policies.md).
- **Egress-прокси — когда нужен allowlist по домену или аудит** — `DOCKER-USER` не видит домены и TLS-SNI без дополнительных инструментов.
- **Фиксируйте исходящий IP** (`com.docker.network.host_ipv4`) для интеграции с внешними allowlist'ами.
- **Персистентируйте правила** сервисом после старта Docker — иначе перезапуск демона их сотрёт.
- **Тестируйте egress-политику** — проверяйте и разрешённые, и запрещённые направления изнутри контейнера.
- **Откатите изменения при демонтаже.** Удалите свои правила (`sudo iptables -D DOCKER-USER <номер>` по строкам из `iptables -L DOCKER-USER --line-numbers`; `sudo iptables -F DOCKER-USER` осторожно — флуш удалит и чужие правила), остановите прокси (`docker compose down`), удалите сети (`docker network rm db-net app-net egress-net`), уберите `HTTP_PROXY`/`HTTPS_PROXY` из окружения приложений.

## Дополнительная информация

### Смежные темы

- [Политики сетевой фильтрации](./docker_network_policies.md) — ICC, `--internal`, `DOCKER-USER`, шаблоны egress-правил (SSoT по правилам).
- [Обзор сетевой модели](./docker_network.md) — gateway modes, `--internal`, SNAT.
- [Сетевая безопасность](../Docker_security/network_security.md) — модель угроз сети, CVE-2024-29018 (DNS-утечка из internal-сетей).
- [Интеграция с iptables/nftables](./troubleshooting/iptables_integration.md) — цепочки, персистентность.
- [DNS и Service Discovery](./dns_and_service_discovery.md) — DNS в `--internal`-сетях, `--dns`.
- [Многохостовые сети без Swarm](./docker_network_multihost.md) — VPN-мост и egress через туннель.
- [WireGuard](../../Vpn/wireguard.md) — шифрованный egress-канал.
- [NetworkPolicy: паттерны egress](../../Kubernetes/Networking/Network/NetworkPolicy/egress_patterns.md) — модель Kubernetes (для сравнения, не для Docker).

### Ограничения

- Docker не имеет объекта «сетевая политика»: egress control собирается из `--internal`, `DOCKER-USER` и прокси.
- `DOCKER-USER` фильтрует по IP/порту, не по домену; доменный allowlist требует egress-прокси.
- Правила `DOCKER-USER` не переживают перезапуск демона без сервиса персистентности.
- В nftables-бэкенде (Docker 29) `DOCKER-USER` отсутствует — фильтрация через собственную таблицу nftables.
- Демон пересоздаёт правила NAT при пересоздании сети; ручные правки `POSTROUTING` не переживают её.
