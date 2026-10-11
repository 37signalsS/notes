# Управление сетями Docker: CLI-справочник

**Актуально для:** Docker Engine 29.x

---

## Определения

- **`docker network`**: Набор команд CLI (Command Line Interface) для управления жизненным циклом сетей Docker.
- **Сеть (Network)**: Виртуальный коммутатор, обеспечивающий связь между контейнерами (endpoints) внутри одного или нескольких хостов.
- **Драйвер сети (Network Driver)**: Плагин, реализующий сетевую логику (`bridge`, `host`, `overlay`, `macvlan`, `ipvlan`, `none`).
- **IPAM (IP Address Management)**: Система управления адресным пространством (подсети, шлюзы, диапазоны IP, резервные адреса).
- **Config-only Network**: Сеть, содержащая только параметры конфигурации (IPAM, опции драйвера) без создания самой сети данных. Используется в Docker Swarm и для macvlan/ipvlan на многохостовых конфигурациях.
- **Scope**: Атрибут сети, определяющий её видимость: `local` (один хост) или `swarm` (кластер Swarm). Задаётся флагом `--scope`.
- **Network Namespace**: Изолированное сетевое окружение (интерфейсы, таблицы маршрутизации, правила фильтрации), реализуемое ядром Linux для каждого контейнера.
- **Endpoint (Конечная точка)**: Виртуальный интерфейс (обычно veth-пара), соединяющий Network Namespace контейнера с сетью. Один эндпоинт принадлежит ровно одной сети.

## Основные концепции

### Архитектура CLI и принцип работы

Docker Networking использует архитектуру клиент-сервер: CLI передаёт запросы демону (`dockerd`), который взаимодействует с сетевым драйвером и модулями ядра Linux (`netlink`, `iptables`/`nftables`, `bridge`).

Жизненный цикл команды:
1. Парсинг аргументов и валидация флагов.
2. Вызов соответствующего API-метода (`NetworkCreate`, `NetworkConnect`, `NetworkInspect` и т.д.).
3. Демон применяет изменения: создаёт bridge-интерфейс, выделяет IP через IPAM, обновляет iptables/nftables.
4. CLI возвращает результат (ID сети, JSON-описание, количество удалённых объектов).

### Группы команд

| Группа | Команды | Назначение |
| :--- | :--- | :--- |
| **Инспекция** | `ls`, `inspect` | Просмотр списка сетей и детальной информации |
| **Жизненный цикл** | `create`, `rm` | Создание и удаление сетей |
| **Подключение** | `connect`, `disconnect` | Управление подключением контейнеров к сетям |

### Фильтры (`--filter`)

Фильтры поддерживаются в командах `ls` и `prune`. Несколько фильтров с разными ключами объединяются по логике **AND**, с одинаковыми — по **OR**.

| Ключ | Пример | Значения / Описание |
| :--- | :--- | :--- |
| `driver` | `--filter driver=bridge` | Тип драйвера (`bridge`, `overlay`, `macvlan`, `ipvlan`, `host`, `none`) |
| `type` | `--filter type=custom` | `custom` (пользовательские) или `builtin` (предустановленные: `bridge`, `host`, `none`) |
| `scope` | `--filter scope=swarm` | `local` или `swarm` |
| `name` | `--filter name=prod-*` | Имя сети (поддерживает частичное совпадение) |
| `label` | `--filter label=env=prod` | Метки. Поддерживаются `label=`, `label!=`, `label==`, `label!= =` |
| `id` | `--filter id=abc123` | ID сети (полное или частичное совпадение) |
| `until` | `--filter until=24h` | Сети, созданные раньше указанного момента (`5m`, `24h`, `2026-10-01T00:00:00Z`) |
| `dangling` | `--filter dangling=true` | Сети без подключённых контейнеров |

### Форматирование вывода (`--format`)

Docker CLI поддерживает Go-шаблоны для форматирования. Доступные плейсхолдеры для `docker network inspect`:

- `.Id` — полный ID сети
- `.Name` — имя сети
- `.Driver` — драйвер
- `.Scope` — область видимости (`local` / `swarm`)
- `.IPAM` — конфигурация IPAM (сеть, шлюз, диапазон)
- `.Containers` — карта подключённых контейнеров
- `.Options` — пользовательские опции драйвера
- `.Labels` — метки сети

### Поддерживаемые флаги создания сети (Docker Engine 29.x)

| Флаг | Назначение | Примечание |
| :--- | :--- | :--- |
| `-d`, `--driver` | Драйвер сети | По умолчанию `bridge` |
| `--subnet` | Подсеть в CIDR | Можно указать несколько через `--ipv4`/`--ipv6` |
| `--gateway` | Шлюз для подсети | |
| `--ip-range` | Диапазон выдаваемых IP | Внутри указанной подсети |
| `--aux-address` | Резервные IP | Формат: `--aux-address="name=IP"` |
| `--ipv4` | Включить IPv4 | По умолчанию `true` |
| `--ipv6` | Включить IPv6 | По умолчанию `false` |
| `--internal` | Блокировать выход в интернет | Только связь между контейнерами внутри сети |
| `--attachable` | Разрешить ручное подключение | Требуется для `overlay` с не-Swarm контейнерами |
| `--ingress` | Создать ingress-сеть Swarm | Только для `overlay` |
| `--scope` | Область видимости | `local` (по умолчанию) или `swarm` |
| `--config-only` | Создать только конфигурацию | Без данных-planes |
| `--config-from` | Скопировать конфигурацию | Имя config-only сети |
| `--label` | Метка сети | Можно указать несколько |
| `-o`, `--opt` | Опция драйвера | Например: `com.docker.network.bridge.enable_icc=false` |
| `--ipam-driver` | Драйвер IPAM | По умолчанию `default` |
| `--ipam-opt` | Опция IPAM драйвера | |

## Практические сценарии

### Сценарий 1: Создание кастомной bridge-сети с валидацией

Создаём изолированную сеть с фиксированной подсетью, проверяем результат.

```bash
# Создание сети
docker network create \
  --driver bridge \
  --subnet 10.30.0.0/24 \
  --gateway 10.30.0.1 \
  --opt com.docker.network.bridge.enable_icc=false \
  --label env=production \
  prod-backend

# → вывод ID созданной сети (например: 8a9b3c7d5e1f2a3b4c5d6e7f)

# Валидация: проверяем параметры
docker network inspect prod-backend -f '{{.Driver}} {{.Scope}} {{.IPAM.Config}}'
# → bridge local [{Gateway:10.30.0.1 Subnet:10.30.0.0/24}]

# Валидация: проверяем опции
docker network inspect prod-backend -f '{{index .Options "com.docker.network.bridge.enable_icc"}}'
# → false

# Валидация: проверяем метки
docker network inspect prod-backend -f '{{json .Labels}}' | jq .
# → {"env":"production"}
```

### Сценарий 2: Многосетевое подключение контейнера с проверкой

Запускаем контейнер в одной сети, подключаем к второй с алиасами и статическим IP.

```bash
# Создаём две сети
docker network create frontend-net
docker network create backend-net

# Запускаем контейнер в frontend
docker run -d --name my-app --network frontend-net nginx:alpine

# Подключаем к backend со статическим IP и алиасами
docker network connect \
  --ip 10.40.0.20 \
  --alias api \
  --alias app-internal \
  backend-net my-app

# Проверка: контейнер виден в обеих сетях
docker network inspect frontend-net -f '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}'
# → my-app

docker network inspect backend-net -f '{{range .Containers}}{{.Name}} -> {{.IPv4Address}}{{"\n"}}{{end}}'
# → my-app -> 10.40.0.20/24

# Проверка изнутри контейнера
docker exec my-app sh -c "ip route | grep 10.40"
# → 10.40.0.0/24 via 10.40.0.1 dev eth1

# Проверка алиаса (DNS)
docker exec my-app getent hosts api
# → 10.40.0.20 api
```

### Сценарий 3: Config-only сеть для macvlan в Swarm

Создаём config-only сеть для многохостовой конфигурации macvlan. Используется при развёртывании Swarm-сервисов.

```bash
# На каждом хосте создаётся config-only сеть с локальными параметрами
# Хост 1:
docker network create \
  --config-only \
  --subnet 192.168.100.0/24 \
  --gateway 192.168.100.1 \
  -o parent=eth0 \
  mv-config

# Хост 2:
docker network create \
  --config-only \
  --subnet 192.168.200.0/24 \
  --gateway 192.168.200.1 \
  -o parent=eth0 \
  mv-config

# Создаём рабочую swarm-сеть, копируя конфигурацию
docker network create \
  -d macvlan \
  --scope swarm \
  --config-from mv-config \
  --attachable \
  swarm-macvlan

# Проверка scope
docker network inspect swarm-macvlan -f '{{.Scope}}'
# → swarm
```

### Сценарий 4: Инспекция и отладка (Go Templates + jq)

Используем `inspect` с шаблонами и `jq` для аудита сетевой конфигурации.

```bash
# Список всех контейнеров в сети с IP и алиасами
docker network inspect prod-net -f '{{range .Containers}}{{.Name}} {{.IPv4Address}} {{range .Aliases}}{{.}} {{end}}{{"\n"}}{{end}}'
# → web-1 172.20.0.5 web-1 web.internal
# → api-1 172.20.0.6 api-1 api.internal

# Проверка конкретных опций драйвера
docker network inspect bridge -f '{{index .Options "com.docker.network.bridge.name"}}'
# → docker0

# Фильтрация по label через jq
docker network ls --filter label=env=production --format json | jq -r '.[].Name'
# → prod-backend
# → prod-frontend

# Проверка, что сеть не имеет подключённых контейнеров (dangling)
docker network ls --filter dangling=true --format "{{.Name}}"
# → old-test-net
# → temp-net
```

### Сценарий 5: Массовые операции и очистка

Удаление и prune сетей с валидацией перед действием.

```bash
# Просмотр сетей, удаляемых prune (dry-run через filter)
docker network ls --filter label=project=old-app --filter dangling=true --format "{{.Name}}"
# → old-app-frontend
# → old-app-backend

# Удаление конкретных сетей (множественный аргумент)
docker network rm old-app-frontend old-app-backend
# → old-app-frontend
# → old-app-backend

# Принудительная очистка всех неиспользуемых сетей старше 24 часов
docker network prune -f --filter "until=24h"
# → Deleted Networks:
# → temp-net-1
# → temp-net-2

# Валидация: убедимся, что prune не задел активные сети
docker network ls --filter label=project=prod --filter dangling=true
# → (пусто, если все prod-сети имеют контейнеры)
```

### Сценарий 6: IPv6 Routed Mode (v28+)

Включение routed mode для IPv6 без NAT66. Работает на Docker Engine 28.x и 29.x.

```bash
# Создание сети с IPv6 routed mode
docker network create -d bridge \
  --ipv6 \
  --subnet fd00:dead:beef::/64 \
  -o com.docker.network.bridge.gateway_mode_ipv6=routed \
  ipv6-routed-net

# Проверка режима
docker network inspect ipv6-routed-net -f '{{index .Options "com.docker.network.bridge.gateway_mode_ipv6"}}'
# → routed

# Запуск контейнера с IPv6
docker run -d --name ipv6-test --network ipv6-routed-net nginx:alpine

# Проверка IPv6 адреса внутри контейнера
docker exec ipv6-test ip -6 addr show eth0
# → inet6 fd00:dead:beef::2/64 scope global
```

## Устранение неисправностей

### Типичные ошибки CLI и их решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Error response from daemon: network ... not found` | Сеть удалена или опечатка в имени | Проверьте имя: `docker network ls --filter name=<prefix>` |
| `Error response from daemon: network ... is in use` | К сети подключены контейнеры | Отключите контейнеры: `docker network disconnect <network> <container>` или используйте `disconnect -f` |
| `Error response from daemon: invalid subnet` | Пересечение с существующей сетью или неверный CIDR | Проверьте существующие подсети: `docker network inspect <network> -f '{{.IPAM.Config}}'` |
| `Error response from daemon: only one of --config-from or --config-only is allowed` | Указаны оба флага одновременно | Используйте только один из флагов в зависимости от операции |
| `Error response from daemon: scope can only be used with Swarm mode` | Флаг `--scope swarm` при неактивированном Swarm | Активируйте Swarm: `docker swarm init` или используйте `scope=local` |
| `Error response from daemon: driver ... not found` | Драйвер не установлен или недоступен | Проверьте плагины: `docker info | grep -i "plugins.*network"` |
| `Error response from daemon: network-scoped alias is already in use` | Алиас занят в целевой сети | Выберите другой алиас или очистите существующий: `docker network disconnect <net> <container>` |
| `Error: network-scoped alias ... does not match the current network` | При подключении указан IP, но алиас из другой сети | Укажите `--alias` только для целевой сети |

### Диагностика подключённых контейнеров

```bash
# Быстрый список контейнеров в сети
docker network inspect <network> --format '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}'

# Проверка IP и MAC всех эндпоинтов
docker network inspect <network> --format '{{range .Containers}}{{.Name}}: {{.IPv4Address}} / {{.MacAddress}}{{"\n"}}{{end}}'

# Проверка, что контейнер подключён к ожидаемым сетям
docker inspect <container> --format '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{"\n"}}{{end}}'
```

### Валидация после создания сети

```bash
# 1. Сеть появилась в списке
docker network ls --filter name=<network-name>

# 2. Параметры IPAM соответствуют ожиданиям
docker network inspect <network> --format '{{json .IPAM.Config}}' | jq .

# 3. Драйвер и опции корректны
docker network inspect <network> --format 'Driver: {{.Driver}}{{"\n"}}Options: {{json .Options}}' | jq .

# 4. Метки применены
docker network inspect <network> --format '{{json .Labels}}' | jq .

# 5. Для overlay: проверить参与 nodes
docker network inspect <network> --format '{{range .Peers}}{{.Name}} {{.IP}}{{"\n"}}{{end}}'
```

## Рекомендации

### Безопасность и изоляция

- **Используйте пользовательские сети** вместо дефолтного `bridge`. Дефолтный `bridge` не поддерживает автоматическое DNS-резолвинг по именам контейнеров.
- **Отключайте ICC** в продакшне на уровне отдельных сетей: `-o com.docker.network.bridge.enable_icc=false`. Глобальное отключение через `daemon.json` рекомендуется только если все приложения готовы к работе с опубликованными портами.
- **Изолируйте базы данных** через `--internal`. Это предотвращает утечку данных наружу при компрометации контейнера.
- **Используйте метки (`--label`)** для всех сетей. Это упрощает аудит (`docker network ls --filter label=env=prod`) и автоматическую очистку.
- **Не публикуйте порты без необходимости**. Если сервис доступен только внутри сети, не используйте `-p`.

### Производительность

- **Для высоконагруженных сервисов** на одном хосте рассмотрите драйвер `host` (`--network host`). Это убирает NAT и мост из пути пакета, снижая задержку.
- **Для overlay-сетей** в Swarm используйте `--attachable` только если нужен доступ из не-Swarm контейнеров. Каждый attachable контейнер увеличивает нагрузку на VXLAN.
- **Настраивайте MTU** при использовании VPN-туннелей или VXLAN. Стандартный MTU 1500 работает только на "чистых" физических сетях без инкапсуляции.

### Управление жизненным циклом

- **Проверяйте параметры после создания** через `docker network inspect`. Это позволяет отловить опечатки в CIDR или незаданные опции до запуска контейнеров.
- **Используйте `docker network prune` с фильтрами**, а не без фильтров. Без фильтров prune удалит все неиспользуемые сети, включая те, что были созданы скриптами развёртывания.
- **Не храните критичные данные в контейнерах**, подключённых к `--internal` сетям, без backup. При удалении сети все подключённые контейнеры отключаются, и если они зависят от этой сети для связи — могут потерять доступ к зависимостям.
- **Используйте `--config-from`** для macvlan/ipvlan в Swarm вместо дублирования параметров IPAM на каждом узле.

### Отладка

- **Используйте Go-шаблоны** вместо `grep` на полном JSON. Шаблоны работают быстрее и дают структурированный вывод.
- **Для сложных запросов** используйте `--format json` + `jq`. Это позволяет фильтровать, сортировать и группировать данные.
- **Проверяйте DNS внутри контейнера** через `nslookup` или `getent hosts`, если контейнер не может разрешить имена других контейнеров в той же сети.
- **Для захвата трафика** на bridge-интерфейсе используйте `nsenter` или `--net=host`, чтобы избежать проблем с правами доступа к network namespace.

## Особенности и ограничения

### Драйверы

- **`host`**: Флаги `--ip` и `--alias` игнорируются, так как контейнер использует сетевой стек хоста напрямую. Контейнер не может быть подключён к другим сетям одновременно.
- **`none`**: Полностью отключает сеть. После запуска контейнера с `--network none` его можно подключить к другим сетям через `docker network connect`.
- **`overlay`**: Требует активированного Swarm-режима (`docker swarm init` или `docker swarm join`). Без Swarm создание overlay-сети завершится ошибкой.
- **`macvlan` / `ipvlan`**: Требуют предварительного создания интерфейса на хосте (`ip link add`) и настройки promiscuous mode на физическом интерфейсе (для macvlan). В Swarm используйте config-only сети.

### Переименование и удаление

- Docker CLI **не поддерживает** команду `rename` для сетей. Для изменения имени необходимо удалить сеть (`docker network rm`) и создать новую с нужным именем.
- Удаление сети (`docker network rm`) возможно только если к ней **не подключены контейнеры**. Принудительное отключение: `docker network disconnect -f <network> <container>`.

### Конфликты и пересечения

- Docker проверяет пересечение подсетей **только внутри своего демона**. Он не знает о внешних маршрутах хоста, существующих VLAN или маршрутах, добавленных вручную. Это может привести к потере связи при совпадении CIDR с корпоративной сетью.
- При использовании `--config-from` убедитесь, что целевая сеть существует и имеет тип `config-only`. Попытка использовать обычную сеть как источник конфигурации приведёт к ошибке.

### Имена сетей

- Имя сети может содержать только буквы (a-z, A-Z), цифры (0-9), знаки подчёркивания (`_`), точки (`.`) и дефисы (`-`).
- Имена чувствительны к регистру.
- Длина имени: от 1 до 63 символа.

## Дополнительная информация

### Связь с другими компонентами

- **iptables/nftables**: Docker автоматически управляет правилами фильтрации и NAT. Для кастомных правил используйте цепочку `DOCKER-USER` (iptables) или пользовательские таблицы (nftables). Детали: [Сетевые политики Docker](./docker_network_policies.md)
- **DNS**: Встроенный DNS-сервер (`127.0.0.11`) обеспечивает service discovery по именам контейнеров. Детали: [DNS и Service Discovery](./dns_and_service_discovery.md)
- **Swarm**: Для кластерного режима используется overlay-сети и Routing Mesh. Детали: [Docker Swarm: Сетевое взаимодействие](../../Docker_swarm/swarm_networking.md)
- **События Docker**: поток событий жизненного цикла сетей в реальном времени (`docker events --filter type=network --filter event=connect`). Детали: [Отладка с помощью Docker Events](../Docker_troubleshooting/debugging_with_docker_events.md)

### Смотрите также

- [Обзор сетевых моделей Docker (SSoT)](./docker_network.md) — CNM, драйверы, Service Discovery
- [Сетевой драйвер bridge](./drivers/bridge.md) — архитектура, packet flow, veth-пары
- [Сетевой драйвер overlay](./drivers/overlay.md) — VXLAN, Routing Mesh, Swarm
- [Сетевой драйвер macvlan](./drivers/macvlan.md) — L2-изоляция, promiscuous mode
- [Сетевой драйвер ipvlan](./drivers/ipvlan.md) — L3-альтернатива macvlan
- [Сетевой драйвер host](./drivers/host.md) — производительность, ограничения
- [Сетевые политики Docker](./docker_network_policies.md) — ICC, DOCKER-USER, nftables
- [Диагностика сетевых проблем](../Docker_troubleshooting/network_connectivity_issues.md) — MTU, conntrack, iptables
- [Интеграция с iptables](./troubleshooting/iptables_integration.md) — автоматические правила Docker
- [Устранение проблем с DNS](../Docker_network/troubleshooting/dns_resolution_issues.md) — 127.0.0.11, ndots, systemd-resolved
- [Методология диагностики (decision tree)](./troubleshooting/decision_tree.md) — пошаговый алгоритм от симптома к слою
- [Вопросы на собеседованиях](./docker_network_interview_qa.md) — типичные вопросы DevOps/SRE
- [Сетевая наблюдаемость](./docker_network_observability.md) — per-container network I/O, дропы, алерты
- [IPAM и планирование ёмкости](./docker_network_ipam_scale.md) — default-address-pools, шардирование
- [libnetwork и плагины драйверов](./docker_network_plugins.md) — CNM, remote driver, CNM vs CNI
- [Многохостовые сети без Swarm](./docker_network_multihost.md) — macvlan multi-host, VXLAN, VPN-мост
- [Traffic shaping](./docker_network_traffic_shaping.md) — ограничение полосы через tc на veth
- [Egress control](./docker_network_egress.md) — управление исходящим трафиком, allowlist, egress-прокси
