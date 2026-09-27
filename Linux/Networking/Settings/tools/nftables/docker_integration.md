# nftables — интеграция с Docker

## Определения

**Docker firewall backend** — механизм, который Docker использует для управления сетевой фильтрацией контейнеров. Начиная с Docker 29.0+ поддерживается нативный бэкенд `nftables`, работающий напрямую через `libnftnl` без слоев совместимости iptables.

**Цепочка DOCKER-USER** — зарезервированная цепочка в iptables-режиме Docker, обрабатываемая до автоматических правил Docker. В nftables-режиме отсутствует — пользовательские правила размещаются в собственных таблицах с приоритетом выше Docker.

**Inter-Container Communication (ICC)** — параметр демона Docker, определяющий, могут ли контейнеры в пределах одной bridge-сети взаимодействовать напрямую. По умолчанию `true`.

**Микросегментация контейнеров** — изоляция трафика между отдельными контейнерами или группами контейнеров на уровне файрвола, предотвращающая lateral movement внутри container-хоста.

**Docker Compose** — инструмент для описания и запуска мультиконтейнерных приложений. Создает изолированные bridge-сети для каждого проекта, к которым применяются правила ICC и фильтрации.

## Основные концепции

### Архитектура сетевого стека Docker

Docker реализует сетевую изоляцию контейнеров через следующие механизмы:

1. **Bridge-сети** — виртуальные коммутаторы L2-уровня (`docker0`, `br-<id>`), к которым подключаются контейнеры.
2. ** DNAT/SNAT** — проброс портов хоста на контейнеры через NAT-таблицы.
3. **Фильтрация** — ограничение трафика между контейнерами и между контейнерами и внешним миром.

Порядок обработки пакета в iptables-режиме (Docker < 29.0):

```
Входящий пакет
  → PREROUTING (DNAT для проброса портов)
  → FORWARD
    → DOCKER-USER (пользовательские правила)
    → DOCKER-ISOLATION-STAGE-1/2 (изоляция между сетями)
    → DOCKER (разрешение доступа к опубликованным портам)
  → POSTROUTING (SNAT/MASQUERADE)
```

В nftables-режиме (Docker 29.0+) Docker создаёт собственные таблицы `ip docker-bridges` и `ip6 docker-bridges` с цепочками, обрабатывающими тот же pipeline.

### Сравнение iptables vs nftables бэкендов Docker

| Критерий | iptables (Docker < 29) | nftables (Docker 29+) |
|:---|:---|:---|
| **Механизм** | `iptables-nft` (shim) или `iptables-legacy` | Прямой вызов `libnftnl` |
| **Пользовательские правила** | Цепочка `DOCKER-USER` | Своя таблица `nftables` с приоритетом выше |
| **Производительность** | Линейный поиск правил $O(n)$ | Хэш-таблицы $O(1)$ для sets |
| **Атомарность** | Правила добавляются по одному | Атомарная загрузка через `nft -f` |
| **IPv6** | Требует `ip6tables` отдельно | Единая таблица `inet` |
| **Видимость** | `iptables -L` + `nft list ruleset` | Только `nft list ruleset` |
| **Сосуществование** | Конфликт с нативными nftables-таблицами | Полная интеграция |

### Определение активного бэкенда

```bash
# Проверка текущего бэкенда Docker
docker info | grep -i "iptables\|nftables\|firewall"
# → Firewall Backend: nftables
# или
# → iptables: true

# Просмотр созданных Docker таблиц
sudo nft list ruleset | grep -E "table (ip|ip6) docker"
# → table ip docker-bridges { ... }
# → table ip6 docker-bridges { ... }
```

### Приоритеты цепочек в nftables-режиме

При фильтрации трафика Docker важно учитывать приоритеты:

| Компонент | Приоритет | Описание |
|:---|:---|:---|
| Пользовательская таблица | `-10` (рекомендуется) | Обрабатывается раньше правил Docker |
| `docker-bridges` (forward) | `0` | Стандартная фильтрация Docker |
| `docker-bridges` (nat) | `-100` (prerouting) / `100` (postrouting) | NAT-трансляции |

**Правило:** создавайте свою таблицу с `hook forward priority -10`, чтобы фильтрация работала до DNAT и правил Docker.

## Предварительные требования

### Программные требования

| Компонент | Версия / Требование |
|:---|:---|
| **Docker Engine** | 29.0+ (для native nftables) |
| **Ядро Linux** | 5.3+ (bridge conntrack), 5.15+ рекомендуется |
| **nftables** | 1.0.0+ |
| **iproute2** | 5.x+ |
| **Права** | root (sudo) |

### Проверка окружения

```bash
# Версия Docker
docker --version
# → Docker version 29.0.3, build 2bf7420

# Проверка модулей ядра
lsmod | grep -E 'br_netfilter|nf_conntrack|bridge'
# → bridge                 327680  1 br_netfilter
# → nf_conntrack          163840  4 br_netfilter,nf_nat,overlay

# Проверка bridge-nf-call (для iptables-режима)
sysctl net.bridge.bridge-nf-call-iptables
# → net.bridge.bridge-nf-call-iptables = 1
```

## Практические сценарии

### 1. Переход на Native nftables (Docker 29.0+)

**Задача:** Включить нативный nftables-бэкенд и убрать зависимость от iptables.

```bash
# /etc/docker/daemon.json
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "firewall-backend": "nftables",
  "icc": false,
  "userland-proxy": false
}
EOF

# Перезапуск Docker
sudo systemctl restart docker

# Проверка
docker info | grep -i firewall
# → Firewall Backend: nftables

# Просмотр таблиц
sudo nft list ruleset | grep docker
# → table ip docker-bridges { ... }
```

**Валидация:**
```bash
# Проверка, что DOCKER-USER отсутствует
iptables -L DOCKER-USER -v -n 2>&1
# → iptables: No chain/target/match by that name.

# Проверка nftables-таблиц
sudo nft list tables
# → table ip docker-bridges
# → table ip6 docker-bridges
```

### 2. Фильтрация трафика к контейнерам (nftables-режим)

**Задача:** Разрешить доступ к порту 8080 контейнера только с доверенного IP.

```bash
# Создание пользовательской таблицы
sudo nft add table inet my_docker_filter

# Цепочка с приоритетом выше Docker (forward hook, priority -10)
sudo nft add chain inet my_docker_filter container_filter \
  '{ type filter hook forward priority -10; policy accept; }'

# Правило: разрешить только доверенному IP
sudo nft add rule inet my_docker_filter container_filter \
  ip saddr 10.0.0.0/8 tcp dport 8080 accept

# Правило: запретить все остальное к порту 8080
sudo nft add rule inet my_docker_filter container_filter \
  tcp dport 8080 drop
```

**Сохранение для персистентности:**
```bash
sudo nft list ruleset | sudo tee /etc/nftables.conf
sudo systemctl enable --now nftables
```

### 3. Микросегментация контейнеров

**Задача:** Изолировать контейнеры друг от друга, разрешив доступ только к определенным портам.

```bash
#!/usr/sbin/nft -f
flush ruleset

# Таблица для фильтрации Docker-трафика
table inet docker_filter {
    # Набор разрешенных пар: source_container . dest_port
    set allowed_access {
        type ipv4_addr . inet_service
        flags interval
        elements = {
            # web -> api: только порт 3000
            172.18.0.2 . 3000,
            # api -> db: только порт 5432
            172.18.0.3 . 5432,
            # api -> redis: только порт 6379
            172.18.0.3 . 6379
        }
    }

    chain forward {
        type filter hook forward priority -10; policy drop;

        # Established/related
        ct state established,related accept

        # Loopback (межконтейнерный в пределах одного хоста)
        iifname "docker*" accept

        # Проверка по набору разрешений
        ip saddr . tcp dport @allowed_access accept

        # Логирование заблокированного трафика
        log prefix "DOCKER_BLOCK: " limit rate 5/minute
    }
}
```

### 4. Изоляция контейнеров от внешних сетей

**Задача:** Разрешить контейнерам общение между собой, запретить доступ в интернет.

```bash
# Создание изолированной сети
docker network create --internal app-isolated

# Запуск контейнеров
docker run -d --network app-isolated --name web nginx
docker run -d --network app-isolated --name api my-api

# Проверка изоляции
docker exec api curl -s --max-time 3 https://example.com
# → timeout (внешний трафик заблокирован)
```

**Альтернатива через nftables (без `--internal`):**
```bash
table inet docker_filter {
    chain forward {
        type filter hook forward priority -10; policy accept;

        # Запретить исходящий трафик из Docker в интернет
        iifname "docker*" oifname != "docker*" drop

        # Разрешить межконтейнерный трафик
        iifname "docker*" oifname "docker*" accept
    }
}
```

### 5. Фильтрация по Docker-сетям в nftables

Docker создаёт bridge-сети с именами `br-<hash>`. Для фильтрации по конкретной сети используйте метки или IP-подсети:

```bash
table inet docker_filter {
    # Определение подсетей Docker-сетей
    set docker_networks {
        type ipv4_addr
        flags interval
        elements = {
            172.18.0.0/16,  # network: app-net
            172.19.0.0/16   # network: db-net
        }
    }

    chain forward {
        type filter hook forward priority -10; policy drop;

        ct state established,related accept

        # Разрешить трафик только между Docker-сетями
        ip saddr @docker_networks ip daddr @docker_networks accept

        # Разрешить DNS из контейнеров
        ip saddr @docker_networks udp dport 53 accept
        ip saddr @docker_networks tcp dport 53 accept

        # Запретить всё остальное
        log prefix "DOCKER_NET_BLOCK: "
    }
}
```

### 6. docker-compose + nftables

При использовании Docker Compose каждому проекту создаётся отдельная bridge-сеть `<project>_default`. Для фильтрации:

```bash
# Просмотр сетей Docker Compose
docker network ls | grep compose
# → NETWORK ID     NAME                DRIVER
# → abc123         myproject_default   bridge

# Определение IP-подсети сети
docker network inspect myproject_default | jq '.[0].IPAM.Config'
# → [{ "Subnet": "172.20.0.0/16", "Gateway": "172.20.0.1" }]
```

**Правило nftables для конкретного Docker Compose проекта:**
```bash
table inet compose_filter {
    chain forward {
        type filter hook forward priority -10; policy drop;

        ct state established,related accept

        # Разрешить трафик из сети myproject_default
        ip saddr 172.20.0.0/16 accept

        # Запретить доступ из интернета к myproject
        ip daddr 172.20.0.0/16 drop
    }
}
```

### 7. Защита Docker Daemon (Управление портом 2376)

```bash
table inet docker_daemon {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept
        tcp dport 22 accept

        # Docker API — только из management-сети
        tcp dport 2376 ip saddr 10.0.0.0/8 accept

        # Docker socket — только локально
        unix stream /var/run/docker.sock accept

        log prefix "DOCKER_DAEMON_BLOCK: "
    }
}
```

### 8. Логирование Docker-трафика

```bash
table inet docker_logging {
    chain forward {
        type filter hook forward priority -5; policy accept;

        # Логирование нового трафика к контейнерам
        iifname != "docker*" oifname "docker*" ct state new \
          log prefix "DOCKER_INBOUND: " limit rate 10/minute

        # Логирование исходящего трафика из контейнеров
        iifname "docker*" oifname != "docker*" \
          log prefix "DOCKER_OUTBOUND: " limit rate 10/minute
    }
}
```

## Валидация результатов

### Проверка правил

```bash
# Просмотр всех Docker-таблиц
sudo nft list ruleset | grep -A 20 "table.*docker"

# Просмотр конкретной цепочки
sudo nft list chain inet docker_filter forward

# Проверка счетчиков
sudo nft list chain inet docker_filter forward
# → ct state established,related accept # packets 15420 bytes 9872000
# → ip saddr . tcp dport @allowed_access accept # packets 320 bytes 48000
```

### Проверка контейнеров

```bash
# Проверка доступности порта контейнера
docker ps --format "table {{.Names}}\t{{.Ports}}"

# Тестирование фильтрации
nc -zv 172.18.0.2 8080
# → Connection succeeded (доверенный IP)

nc -zv 172.18.0.2 8080 с другого IP
# → Connection timed out (blocked)
```

### Проверка изоляции

```bash
# Контейнер не должен достучаться до внешнего IP
docker exec api ping -c 1 -W 2 8.8.8.8
# → ping: sendmsg: Operation not permitted

# Контейнер может общаться с другим контейнером в той же сети
docker exec api ping -c 1 172.18.0.2
# → 64 bytes from 172.18.0.2: icmp_seq=1 ttl=64 time=0.089 ms
```

## Диагностика и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
|:---|:---|:---|:---|
| **Docker не создает nftables-таблицы** | `nft list ruleset` пуст после restart | `docker info \| grep firewall` | Установите `firewall-backend: nftables` в daemon.json |
| **Контейнер не виден извне** | Порт не открыт | `nft list ruleset \| grep dnat` | Проверьте `-p` флаг при `docker run` |
| **DOCKER-USER отсутствует** | `iptables -L DOCKER-USER` → error | Docker 29+ с nftables backend | Используйте собственную таблицу nftables с priority -10 |
| **ICC блокирует трафик** | Контейнеры не общаются | `docker inspect <net> \| jq '.[0].Options'` | Проверьте `icc` параметр сети |
| **Docker перезаписывает правила** | Правила пропадают после `docker network create` | `docker events \| grep network` | Используйте `nft -f` для атомарной загрузки вместо `nft add` |
| **Conntrack переполнен** | `dmesg` показывает `table full` | `conntrack -S \| grep drop` | Увеличьте `nf_conntrack_max`, добавьте `notrack` для UDP |
| **Контейнер не может в интернет** | DNS не работает | `docker exec <c> nslookup example.com` | Проверьте `udp dport 53 accept` в вашей таблице |
| **Docker и nftables конфликтуют** | Дублирование правил | `nft list ruleset \| grep managed` | Удалите legacy iptables-таблицы: `iptables -F` |

## Краевые случаи и ограничения

1. **Rootless Docker** — в режиме Rootless Docker не имеет прав на модификацию системного файервола. Сетевой стек реализуется через `pasta` (Podman 5+) или `rootlesskit`. Фильтрация через nftables недоступна.

2. **Docker Desktop** — Docker Desktop использует собственный виртуальный сетевой стек (VPNKit, VZ framework) и не управляет системным nftables.

3. ** Overlay-сети** — при использовании overlay-сетей (Swarm, Kubernetes) трафик инкапсулируется в UDP (VXLAN). Фильтрация внутренних контейнеров требует проверки `outer UDP 4789` + внутренних IP.

4. **Macvlan-сети** — контейнеры с macvlan получают MAC-адреса из пула хоста. Bridge-фильтрация не работает; используйте `netdev` или `ip` семейства.

5. **IPv6 и Docker** — Docker по умолчанию не создает IPv6-сети. Для dual-stack потребуется `--ipv6` флаг и настройка `ip6tables`.

## Best Practices

1. **Всегда используйте `firewall-backend: nftables`** на Docker 29+ — это убирает зависимость от iptables и обеспечивает $O(1)$ поиск.

2. **Отключайте ICC** (`"icc": false`) в production — это основа микросегментации.

3. **Создавайте пользовательскую таблицу** с `priority -10` вместо `DOCKER-USER` — это совместимо с обоими бэкендами.

4. **Используйте `--internal` сети** для баз данных и критичных сервисов — это двойная изоляция (bridge + nftables).

5. **Сохраняйте правила в `/etc/nftables.conf`** и используйте `systemctl enable nftables` — Docker не персистит ваши правила.

6. **Версионируйте конфигурации** — храните nftables-правила для Docker в Git.

7. **Используйте sets** для IP-адресов контейнеров — это ускоряет фильтрацию и упрощает обновление.

8. **Тестируйте изоляцию** — после применения правил проверяйте доступность портов с внешних хостов и между контейнерами.

## См. также

- **[Интеграция Docker с iptables и nftables](../../../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — подробный разбор бэкендов и цепочек.
- **[Политики сетевой фильтрации Docker](../../../../../../Docker/Docker_network/docker_network_policies.md)** — ICC, DOCKER-USER, --internal сети.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — приоритеты и хуки.
- **[nftables — сегментирование сети](./network_segmentation.md)** — L2/L3 изоляция.
- **[nftables — практические сценарии](./practical_scenarios.md)** — NAT, flowtables, rate limiting.
