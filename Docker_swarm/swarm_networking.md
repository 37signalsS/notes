# Docker Swarm: сетевое взаимодействие

**Актуально для:** Docker Swarm 29.x

## Определения

**Overlay Network (Оверлейная сеть)** — виртуальная сеть уровня L2, созданная поверх физической инфраструктуры с использованием инкапсуляции VXLAN. Это стандартный способ взаимодействия сервисов на разных узлах. Подробнее о механизме VXLAN и VTEP см. **[Сетевой драйвер overlay (SSoT)](../Docker/Docker_network/drivers/overlay.md)**.

**Ingress Network (Входящая сеть)** — специальная системная оверлейная сеть (по умолчанию `ingress`), управляющая входящим трафиком. Она обеспечивает работу Routing Mesh.

**Routing Mesh (Сетчатая маршрутизация)** — механизм Swarm, позволяющий любому узлу кластера принимать трафик на опубликованный порт сервиса и перенаправлять его к активной реплике, независимо от того, запущена ли она на этом узле.

**Virtual IP (VIP)** — единый IP-адрес сервиса в оверлейной сети. Запросы к VIP балансируются между всеми репликами сервиса на уровне ядра Linux (IPVS).

**DNSRR (DNS Round-Robin)** — альтернативный режим балансировки, при котором встроенный DNS-сервер возвращает список IP-адресов всех задач (tasks) сервиса по его имени. Подробнее о механизме DNS и приоритете поиска см. **[DNS и Service Discovery в Docker](../Docker/Docker_network/dns_and_service_discovery.md)**.

**docker_gwbridge** — локальный мост на каждом узле, обеспечивающий контейнерам в оверлейных сетях выход во внешнюю сеть (NAT для исходящего трафика). Также используется для связи с сервисами в сети `ingress`.

**Attachable Network (Подключаемая сеть)** — overlay сеть с флагом `--attachable`, к которой могут подключаться не только сервисы Swarm, но и отдельные контейнеры. Используется для отладки, одноразовых задач или гибридных нагрузок.

**Internal Network (Внутренняя сеть)** — overlay сеть с флагом `--internal`, которая не имеет маршрута во внешние сети. Контейнеры в такой сети могут общаться только между собой. Используется для изолированных backend-компонентов (базы данных, кэш).

**Data Path Address (Адрес плоскости данных)** — отдельный IP-адрес узла, используемый для VXLAN-трафика (плоскость данных), чтобы отделить его от адреса управления (Raft/gossip). Настраивается через `docker swarm init --data-path-addr`.

## Базовые концепции

### Архитектура сетевого стека Swarm

Swarm наследует Container Network Model (CNM) от Docker Engine и расширяет его уровнем кластерного планирования:

1. **Уровень Engine:** Docker Daemon управляет локальными драйверами сетей (bridge, host, overlay) на каждом узле независимо. CNM состоит из Sandbox (сетевое пространство имён), Endpoint (виртуальный интерфейс veth) и Network (коммутатор).
2. **Уровень Orchestrator:** SwarmKit координирует создание overlay-сетей, распределение эндпоинтов между узлами и поддержку состояния сетей через gossip-протокол.
3. **Уровень Network Driver:** Драйвер `overlay` реализует инкапсуляцию VXLAN между узлами.

### Routing Mesh и IPVS

Когда вы публикуете порт сервиса (например, `--publish 80:80`), Swarm использует **IPVS (IP Virtual Server)** внутри пространства имен `ingress_sbox` для балансировки трафика.

1. Запрос поступает на опубликованный порт любого узла кластера.
2. Routing Mesh перехватывает трафик и направляет его в сеть `ingress`.
3. IPVS выбирает доступную реплику сервиса (алгоритм Round-Robin по умолчанию) и пересылает пакет.

**Ограничение:** Routing Mesh выполняет SNAT (Source NAT), из-за чего приложение видит IP-адрес моста `docker_gwbridge` вместо реального IP клиента. Для сохранения IP используйте режим `mode: host` (минуя Routing Mesh) или Ingress-контроллеры (например, Traefik). Подробнее о маршрутизации L7 см. **[Ingress-контроллер Traefik в Swarm](./swarm_ingress_traefik.md)**.

### Обнаружение сервисов (Service Discovery)

Swarm предоставляет встроенный DNS-резолвер по адресу `127.0.0.11`. В пользовательских сетях (overlay, bridge) Docker автоматически настраивает `/etc/resolv.conf` внутри контейнера.

#### Режимы Endpoint Mode

| Режим | Как работает | Применение |
|:---|:---|:---|
| **VIP** (дефолт) | Один виртуальный IP на сервис. Балансировка прозрачна для клиента. | Стандартные HTTP-сервисы, базы данных. |
| **DNSRR** | DNS возвращает список IP всех контейнеров. Клиент сам выбирает IP. | Внешние балансировщики (Nginx/Traefik), gRPC с клиентской балансировкой. |

Подробнее о приоритете поиска, опциях `ndots` и IPv6 AAAA записях см. **[DNS и Service Discovery в Docker](../Docker/Docker_network/dns_and_service_discovery.md)**.

### docker_gwbridge

`docker_gwbridge` создаётся автоматически на каждом узле при подключении к overlay-сетям. Он выполняет две функции:
1. **NAT для исходящего трафика:** контейнеры в overlay-сетях выходят во внешнюю сеть через IP узла.
2. **Мост для сети ingress:** обеспечивает доступ к опубликованным портам сервисов.

При проблемах с выходом в интернет из overlay-контейнеров проверяйте состояние моста:
```bash
docker network inspect docker_gwbridge
# → убедитесь, что subnet не конфликтует с внутренними подсетями
```

### Безопасность и изоляция

1. **Изоляция сетей:** Контейнеры могут общаться только если они находятся в одной и той же оверлейной сети. Используйте `internal: true` для backend-сетей без выхода наружу.
2. **Шифрование (IPsec):** Опция `--opt encrypted` включает шифрование трафика между узлами. В 2026 году накладные расходы составляют менее 5% благодаря аппаратным инструкциям AES-NI. **Ограничение:** шифрование не поддерживается на Windows-узлах.
3. **Secure by Default (начиная с Docker 28.0):** Обращения извне узла к IP-адресам контейнеров на неопубликованные порты отбрасываются — сначала правилом в цепочке `DOCKER`, с 28.2 перенесённым в `raw` PREROUTING. Обращения с самого узла и между сервисами одной overlay-сети по-прежнему разрешены. Учтите, что оверлейные правила не мигрированы на nftables: бэкенд `firewall-backend: nftables` нельзя включить при активном Swarm.
4. **IPv6 Dual-Stack (стабилен с Docker 27.x):** Поддержка IPv6 в Swarm позволяет назначать глобальные IPv6 адреса сервисам. При использовании `gateway_mode_ipv6=routed` трафик маршрутизируется напрямую без NAT66.

## Практические сценарии

### Предварительные требования

- **Docker Engine:** 29.x на всех менеджерах и рабочих узлах.
- **Открытые порты:** между всеми узлами должны быть открыты 2377/TCP (управление), 7946/TCP+UDP (gossip), 4789/UDP (VXLAN). При шифровании — protocol 50 (ESP).
- **Сетевая связность:** узлы должны иметь доступ друг к другу по L3 (роутинг между подсетями).
- **VXLAN Offloading (рекомендуется):** для снижения нагрузки на CPU включите `tx-udp-tnl-segmentation` на сетевых интерфейсах: `ethtool -K eth0 tx-udp-tnl-segmentation on`.
- **Метаданные:** для топологии на узлы должны быть назначены labels (`docker node update --label-add rack=rack-3 <node>`).

### Создание overlay-сети с шифрованием и оптимизацией MTU

VXLAN добавляет 50 байт оверхеда. При стандартном физическом MTU 1500 используйте MTU 1450 для overlay-сети.

```bash
docker network create \
  --driver overlay \
  --opt com.docker.network.driver.mtu=1450 \
  --opt encrypted \
  --attachable \
  backend-net
```

**Валидация:**
```bash
docker network ls --filter driver=overlay
# → NAME        DRIVER   SCOPE
# → backend-net overlay  swarm

docker network inspect backend-net
# → Ищите "MTU": 1450 и "Options": {"encrypted": "true"}
```

### Публикация портов в режиме Host

Если приложению критично видеть реальный IP-адрес клиента (например, для логирования или систем защиты от DDoS), порт публикуется в обход Routing Mesh:

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - target: 80
        published: 80
        mode: host # Порт открывается только на тех узлах, где запущен контейнер
    deploy:
      mode: global # Рекомендуется для host-портов, чтобы занять порт на всех узлах
```

**Валидация:**
```bash
docker service ps nginx --no-trunc
# → убедитесь, что задача запущена на ожидаемых узлах

ss -tlnp | grep :80
# → порт слушается непосредственно на интерфейсе узла, без 127.0.0.1
```

### Разделение трафика управления и данных

Для стабильности крупных кластеров рекомендуется разделить интерфейсы для управления (Raft/gossip) и данных (VXLAN):

```bash
docker swarm init \
  --advertise-addr 10.0.1.10 \ # IP для менеджеров и gossip
  --data-path-addr 10.0.5.10   # Отдельный IP для VXLAN-трафика
```

**Валидация:**
```bash
docker node inspect self --format '{{ .ManagerStatus.Addr }}'
# → 10.0.1.10:2377

# На узле проверьте маршруты VXLAN:
ip route show table 0 | grep 10.0.5.10
# → via 10.0.5.10 dev eth0
```

### Attachable и Internal сети

**Attachable overlay-сеть** позволяет подключать к ней отдельные контейнеры (не сервисы) для отладки или запуска одноразовых задач:

```bash
docker network create --driver overlay --attachable debug-net

# Подключение standalone-контейнера:
docker run --rm -it --network debug-net alpine sh
```

**Internal overlay-сеть** не имеет маршрута наружу. Используйте её для изоляции баз данных и внутренних сервисов:

```yaml
services:
  db:
    image: postgres:17-alpine
    networks:
      - backend-internal

networks:
  backend-internal:
    driver: overlay
    internal: true
```

**Валидация:**
```bash
docker run --rm --network debug-net alpine nslookup db
# → должно резолвить имя сервиса db

# Для internal-сети:
docker run --rm --network backend-internal alpine wget -O- http://db:5432
# → соединение внутри кластера пройдёт
docker run --rm --network backend-internal alpine wget -O- http://example.com
# → таймаут (нет маршрута в интернет)
```

### DNSRR для gRPC и внешних балансировщиков

Для сервисов, за которыми стоит внешний балансировщик (Nginx/Traefik) или для gRPC с клиентской балансировкой, используйте DNSRR:

```yaml
services:
  api:
    image: my-api:v1
    deploy:
      replicas: 3
    dnsrr: true # Вместо VIP возвращаем список IP задач
```

**Валидация:**
```bash
docker run --rm --network backend-net alpine nslookup api
# → возвращаются IP-адреса всех реплик, а не один VIP
```

## Обслуживание и мониторинг

### Очистка неиспользуемых сетей

Overlay-сети не удаляются автоматически при удалении стека. Используйте prune с осторожностью:

```bash
# На менеджере: удаление конкретной неиспользуемой сети
docker network rm <network-name>

# Локальная очистка на узле (удаляет локальные bridge-сети)
docker network prune

# Глобальная очистка (включает overlay)
docker network prune --filter "until=24h"
```

**Валидация:**
```bash
docker network ls --filter driver=overlay
# → проверьте отсутствие неиспользуемых сетей
```

## Операции и команды

| Операция | Локальная сеть | Overlay сеть |
|:---|:---|:---|
| **Создание** | `docker network create --driver bridge <name>` | `docker network create --driver overlay [--attachable] [--internal] [--opt encrypted] <name>` |
| **Список** | `docker network ls` | `docker network ls --filter driver=overlay` |
| **Инспекция** | `docker network inspect <name>` | `docker network inspect <name>` |
| **Удаление** | `docker network rm <name>` | `docker network rm <name>` (только если нет сервисов) |
| **Очистка** | `docker network prune` (на узле) | `docker network prune` (на узле; overlay удаляются только если не используются) |
| **Подключение сервиса** | `docker network connect <name> <container>` | `docker service update --network-add <name> <service>` |
| **Отключение сервиса** | `docker network disconnect <name> <container>` | `docker service update --network-rm <name> <service>` |
| **Публикация порта** | `-p 80:80` | `--publish 80:80` или `mode: host` |
| **Валидация связности** | `docker run --rm <image> ping <target>` | `docker service ps <service>` + `docker exec <task> ping <target>` |

## Устранение неполадок

### Требуемые порты (Firewall)

Убедитесь, что между всеми узлами открыты:
- **2377/TCP**: Управление кластером.
- **7946/TCP+UDP**: Gossip-протокол (Service Discovery).
- **4789/UDP**: VXLAN трафик. При конфликтах измените порт через `--data-path-port`.
- **Protocol 50 (ESP)**: Если включено шифрование `--opt encrypted`.

### Проверка связности и IPVS

Если трафик не доходит до сервиса:
1. Проверьте статус IPVS на узле (требуется `ipvsadm`):
   ```bash
   nsenter --net=/var/run/docker/netns/ingress_sbox ipvsadm -Ln
   ```
2. Проверьте MTU: если `ping` проходит, а `curl` зависает — установите MTU 1450.
3. Логи встроенного DNS: контейнеры должны успешно резолвить имена через `127.0.0.11`.
4. Для rootless Docker: убедитесь, что используется `pasta`/`passt` (рекомендуется с Docker 28.x), а не `slirp4netns`.

### Windows-узлы

- Шифрование `--opt encrypted` не поддерживается на Windows до версии Server 2025.
- Overlay-сети работают, но с ограничениями производительности.

### Превышение количества сетей

При большом количестве overlay-сетей (>500) протокол gossip создаёт значительную нагрузку на Control Plane. Рекомендуется группировать сервисы в общие сети.

## Лучшие практики

1. **MTU:** Используйте MTU 1450 для overlay-сетей при стандартном физическом MTU 1500. При Jumbo Frames (9000) overlay может использовать 1500 или выше.
2. **VXLAN Offloading:** Включайте `tx-udp-tnl-segmentation` на сетевых картах для снижения нагрузки на CPU.
3. **Изоляция:** Не используйте одну сеть для всего кластера. Разделяйте фронтенд, бэкенд и базы данных. Используйте `internal: true` для backend-сетей.
4. **Attachable:** Используйте `--attachable` только для отладочных сетей. В production предпочитайте сервисы Swarm.
5. **Пропускная способность:** Routing Mesh создаёт дополнительный "прыжок" (hop) в сети. Для высоконагруженных систем рассмотрите `host` режим или прямую маршрутизацию.
6. **Data Path Address:** для кластеров больше 10 узлов настраивайте `--data-path-addr` для отделения VXLAN-трафика от gossip.
7. **Шифрование:** используйте `--opt encrypted` для чувствительных данных. Проверяйте совместимость с Windows-узлами.

## Дополнительная информация

### Смотрите также

- **[Сетевой драйвер overlay (SSoT)](../Docker/Docker_network/drivers/overlay.md)** — глубокие детали VXLAN, VTEP и производительности.
- **[Docker: Обзор сетевых моделей](../Docker/Docker_network/docker_network.md)** — сравнение bridge, host, overlay, macvlan.
- **[DNS и Service Discovery](../Docker/Docker_network/dns_and_service_discovery.md)** — механизм 127.0.0.11, ndots, IPv6.
- **[Ingress-контроллер Traefik в Swarm](./swarm_ingress_traefik.md)** — маршрутизация L7 и сохранение IP клиента.
- **[Основные концепции Docker Swarm](./swarm_core_concepts.md)** — архитектура узлов и сервисов.
- **[Диагностика сетевых проблем](../Docker/Docker_troubleshooting/network_connectivity_issues.md)** — общие методы отладки (conntrack, MTU, iptables).
