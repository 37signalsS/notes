# libnetwork и плагины сетевых драйверов Docker

**Актуально для:** Docker Engine 29.x (актуальный релиз — 29.8.x, сентябрь 2026)

## Определения

- **libnetwork** — библиотека на Go (проект moby/libnetwork), реализующая сетевой стек Docker внутри `dockerd`. Именно она, а не containerd, создаёт network namespace, veth-пары, мосты и правила NAT. Containerd управляет образами и жизненным циклом контейнеров; сеть — зона ответственности `dockerd` + libnetwork.
- **CNM (Container Network Model)** — модель данных libnetwork: три сущности — **Sandbox** (сетевое окружение контейнера), **Endpoint** (привязка sandbox к сети), **Network** (набор эндпоинтов). Все драйверы — встроенные и сторонние — оперируют этими сущностями.
- **Встроенный драйвер (built-in)** — драйвер, скомпилированный в `dockerd`: `bridge`, `host`, `overlay`, `macvlan`, `ipvlan`, `null` (`none`). Не требует установки.
- **Удалённый драйвер (remote network driver)** — сторонний плагин, реализующий интерфейс NetworkDriver и общающийся с `dockerd` через HTTP/JSON-RPC (POST-запросы вида `/NetworkDriver.CreateNetwork`) поверх Unix-сокета. Создаёт сети через `docker network create -d <имя-плагина>`.
- **CNI (Container Network Interface)** — стандарт CNCF: плагин вызывается runtime (containerd, CRI-O) как отдельный процесс с JSON-конфигурацией (`ADD`/`DEL`). Модель Kubernetes, не Docker.
- **Network driver plugin** — процесс, регистрирующийся в Docker через Unix-сокет в `/run/docker/plugins/` (или `.spec`/`.json`-файл с URL) и обрабатывающий вызовы `CreateNetwork`, `CreateEndpoint`, `Join` и т.д.
- **Remote IPAM driver** — плагин управления адресами, подключаемый через `--ipam-driver <имя>` при создании сети; реализует эндпоинты `IpamDriver.RequestPool` / `RequestAddress` / `ReleaseAddress`. Встроенный IPAM-драйвер (`default`) покрывает большинство случаев.

## Основные концепции

### Где живёт сеть в архитектуре Docker

```
docker CLI
    │
    ▼
dockerd (демон)
    │
    ├── libnetwork ── CNM: Sandbox / Endpoint / Network
    │       │
    │       ├── встроенные драйверы (bridge, host, overlay, macvlan, ipvlan, null)
    │       │
│       └── HTTP/JSON ──► удалённый драйвер (плагин)
│                     └── реализует NetworkDriver API
    │
    └── containerd ── образы, snapshot-слои, жизненный цикл контейнеров (сеть НЕ его зона)
```

Практическое следствие: сетевая конфигурация применяется `dockerd`, поэтому изменения сетей требуют доступа к демону (сокет `/var/run/docker.sock`), а не к containerd.

### CNM vs CNI — ключевое различие

| Свойство | CNM (Docker) | CNI (Kubernetes) |
| :--- | :--- | :--- |
| Кто вызывает плагин | `dockerd` (через HTTP/JSON-RPC, долгоживущий) | runtime (exec процесса с JSON) |
| Модель данных | Sandbox / Endpoint / Network | нет модели — плагин получает конфиг |
| Управление состоянием | демон хранит состояние сетей | состояние в etcd / API-сервере |
| Применение | Docker Engine, Swarm | Kubernetes, containerd, CRI-O |
| Расширение | remote network driver plugin | CNI plugin (бинарник) |

Docker не использует CNI: libnetwork реализует собственную модель. Плагины CNI (Calico, Cilium, Flannel) не подключаются к Docker напрямую — они работают с Kubernetes/containerd.

### Как работает удалённый драйвер

1. Плагин создаёт Unix-сокет в `/run/docker/plugins/<name>.sock` (или `.spec`/`.json`-файл в `/etc/docker/plugins/` / `/usr/lib/docker/plugins/` с URL вида `unix:///other.sock` или `tcp://host:8080` — для плагина на другом хосте).
2. `dockerd` обнаруживает плагин **по имени при первом обращении** (не при старте демона): сканирует каталоги, выполняет handshake `POST /Plugin.Activate`, плагин отвечает манифестом `{"Implements": ["NetworkDriver"]}`.
3. `docker network create -d <имя>` создаёт сеть через плагин; `docker network inspect` показывает драйвер и его опции.
4. Плагин отвечает за реальную сетевую логику (VXLAN, BGP, политики) — Docker только передаёт вызовы (`CreateNetwork`, `CreateEndpoint`, `Join`, `DeleteNetwork` и т.д.).

Проверка доступных плагинов:

```bash
docker info --format '{{json .Plugins}}'
# → {"Network":["bridge","host","overlay","macvlan","ipvlan","null","<сторонние>"],...}

# Или
docker info | grep -i "plugins.*network"
```

Плагины могут использовать socket-активацию systemd: демон запускает плагин при первом обращении к сокету (официальные helpers поддерживают это нативно).

### Remote IPAM-драйверы

Помимо драйвера сети, подключаемым может быть и драйвер управления адресами:

```bash
# Сеть со сторонним IPAM (при условии, что плагин зарегистрирован)
docker network create -d <net-driver> --ipam-driver <ipam-driver> \
  --subnet 10.20.0.0/16 --gateway 10.20.0.1 ipam-net
```

Встроенный IPAM (`default`) выделяет адреса из `--subnet`, поддерживает `--ip-range`, `--aux-address`. Сторонний IPAM оправдан, когда адресация интегрирована с внешней системой (IPAM предприятия, DHCP-интеграция). Драйвер сети и IPAM-драйвер выбираются независимо.

### Когда нужен сторонний драйвер

| Потребность | Встроенное решение | Сторонний драйвер |
| :--- | :--- | :--- |
| Связь на одном хосте | `bridge` | не нужен |
| Много хостов + Swarm | `overlay` | не нужен |
| L2 без NAT | `macvlan`/`ipvlan` | не нужен |
| Шифрование overlay без Swarm | нет | Weave Net (шифрование, DNS) |
| Сетевые политики L3/L4 | только `DOCKER-USER` вручную | Calico for Docker (distributed firewall) |
| BGP-маршрутизация | нет | Calico (BGP) |

Сторонние драйверы оправданы, когда встроенные не покрывают требование (политики, шифрование вне Swarm, BGP). Для большинства deployment встроенных драйверов достаточно.

## Предварительные условия

- **Docker Engine 29.x**; для сценариев 2–3 — установленный и работающий плагин (процесс на хосте или managed-плагин).
- **Права root** — чтение `/run/docker/plugins/`, `ss -xlpn`, journalctl.
- **Плагин зарегистрирован** — сокет в `/run/docker/plugins/` или `.spec`/`.json` в `/etc/docker/plugins/`; проверка: `docker info --format '{{json .Plugins}}'`.
- **Для rootless** — пути плагинов другие (`$XDG_CONFIG_HOME/docker/plugins`); плагины, требующие `CAP_SYS_ADMIN` или host network, несовместимы.

## Практические сценарии

### Сценарий 1: Проверка, какой драйвер обслуживает сеть

```bash
# Драйвер и scope каждой сети
docker network ls --format 'table {{.Name}}\t{{.Driver}}\t{{.Scope}}'
# → NAME        DRIVER  SCOPE
# → bridge      bridge  local
# → host        host    local
# → app-net     bridge  local
# → swarm-net   overlay swarm

# Опции драйвера и IPAM
docker network inspect app-net \
  --format 'driver={{.Driver}} ipam={{.IPAM.Driver}} options={{json .Options}}'
# → driver=bridge ipam=default options={}
```

### Сценарий 2: Создание сети через удалённый драйвер

> **Статус примера (Weave Net):** компания Weaveworks прекратила деятельность, репозиторий `weaveworks/weave` архивирован 20 июня 2024 (только чтение), документация docs.weave.works недоступна. Плагин не развивается и не рекомендуется для новых внедрений — проверяйте активные форки или альтернативы. Подробно: [многохостовые сети](./docker_network_multihost.md).

```bash
# Плагин должен быть установлен и зарегистрирован (пример — weave)
docker network create -d weave --name weave-net
# → 8a9b3c7d5e1f...

# Проверка: драйвер — сторонний
docker network inspect weave-net --format '{{.Driver}}'
# → weave

# Удаление
docker network rm weave-net
```

Если плагин не зарегистрирован, создание завершится ошибкой:

```bash
docker network create -d weave net-x
# → Error response from daemon: network driver not found: weave
```

### Сценарий 3: Отладка взаимодействия с плагином

```bash
# Логи демона при создании сети через плагин
sudo journalctl -u docker -f &
docker network create -d <plugin> test-net
# → в логах: вызовы NetworkDriver.CreateNetwork, CreateEndpoint

# Сокет плагина существует
ls -l /run/docker/plugins/
# → srw-rw-rw- 1 root root 0 ... weave.sock

# Плагин отвечает
sudo ss -xlpn | grep docker/plugins
# → LISTEN 0 128 /run/docker/plugins/weave.sock ...

# Handshake: демон активирует плагин при первом обращении по имени
# (в логах демона — вызовы Plugin.Activate, NetworkDriver.GetCapabilities)
docker network ls --format '{{.Name}} {{.Driver}}' | grep weave
# → weave-net weave
```

### Сценарий 4: Выбор между встроенным и сторонним

Решаюющие вопросы:

1. **Нужны ли политики между контейнерами?** Встроенное: разделение по сетям + `DOCKER-USER`. Стороннее: Calico for Docker — распределённый файрвол с селекторами.
2. **Нужно ли шифрование между хостами без Swarm?** Встроенное `overlay` требует Swarm; `encrypted` — опция overlay в Swarm. Weave Net шифрует вне Swarm.
3. **Нужна ли BGP-маршрутизация?** Только сторонний драйвер (Calico).
4. **Есть ли Swarm?** Если да — `overlay` покрывает большинство случаев, сторонний драйвер редко нужен.

## Устранение неисправностей

| Симптом | Причина | Диагностика |
| :--- | :--- | :--- |
| `network driver not found` | плагин не установлен/не зарегистрирован | `docker info --format '{{json .Plugins}}'`; `ls /run/docker/plugins/` |
| Сеть создана, но контейнеры не видят друг друга | плагин не реализует connectivity корректно | `docker exec <c> ping <ip>`; логи плагина |
| `docker network rm` зависает | плагин не отвечает на DELETE | `sudo ss -xlpn \| grep docker/plugins`; перезапуск плагина |
| Плагин работал, перестал после обновления Docker | несовместимость версии протокола плагина | версия плагина против версии Engine; changelog плагина |
| `dockerd` не видит сокет плагина | неверные права на сокет | `ls -l /run/docker/plugins/` — сокет должен быть доступен `dockerd` |
| Плагин не найден после установки | сокет лежит не в `/run/docker/plugins/`, а `.spec`/`.json` — не в `/etc/docker/plugins/` или `/usr/lib/docker/plugins/` | `ls /run/docker/plugins/ /etc/docker/plugins/`; демон ищет по имени при первом обращении |
| Плагин не найден в rootless-режиме | пути другие: `$XDG_CONFIG_HOME/docker/plugins` | `docker info` — проверьте режим демона; см. [volume drivers](../Docker_fs/volume_drivers.md) |
| `network driver not found` при управляемом плагине | managed-плагин (`docker plugin install`) не включён на этом узле | `docker plugin ls` — ENABLED=false; `docker plugin enable <name>` |

## Рекомендации

- **Начинайте со встроенных драйверов** — они покрывают большинство deployment; сторонний плагин добавляет зависимость и поверхность атаки.
- **Проверяйте статус плагина перед внедрением** — сторонние драйверы (Weave, Calico for Docker) имеют собственный жизненный цикл; убедитесь в актуальности и поддержке под вашу версию Engine.
- **Держите плагин под контролем версий** — конфигурация плагина и его версия должны воспроизводиться на всех узлах.
- **Не смешивайте CNM и CNI** — плагины CNI (Calico, Cilium, Flannel) не подключаются к Docker; для Docker нужны remote network drivers.
- **Мониторьте плагин как часть Docker** — недоступность плагина ломает создание сетей и подключение контейнеров; алерт на отсутствие сокета в `/run/docker/plugins/`.
- **Документируйте выбор драйвера** — в инвентаризации хоста фиксируйте, какие сети обслуживаются сторонним драйвером, чтобы при инциденте знать, где искать проблему.

## Дополнительная информация

### Смежные темы

- [Обзор сетевой модели Docker](./docker_network.md) — CNM: Sandbox, Endpoint, Network.
- [Многохостовые сети](./docker_network_multihost.md) — overlay, Weave Net (статус EOL), сторонние драйверы в Swarm.
- [Драйверы томов](../Docker_fs/volume_drivers.md) — managed-плагины (`docker plugin install`) и rootless-ограничения.
- [Обзор Docker](../docker_overview.md) — роли `dockerd`, containerd, libnetwork.
- [Сравнение Podman и Docker](../../Podman/podman_vs_docker.md) — libnetwork против Netavark/aardvark-dns.
- [Драйвер overlay](./drivers/overlay.md) — встроенный многохостовый драйвер (Swarm).
- [Политики сетевой фильтрации](./docker_network_policies.md) — встроенная фильтрация без плагинов.
- [CNI и kube-proxy](../../Kubernetes/Networking/Network/cni_kube_proxy_roles.md) — модель CNI (для сравнения, не для Docker).
- [Контейнерный Networking через призму OSI](../../Networking/OSI_TCP_IP_Model/container_networking.md) — сравнение CNI-плагинов.

### Ограничения

- Список конкретных сторонних драйверов и их статус поддержки меняется; перед внедрением проверяйте актуальность плагина под вашу версию Engine.
- Удалённые драйверы — экспериментальная по зрелости область: поведение при обновлении Engine и совместимость протокола плагина нужно проверять в staging.
- Детали интерфейса NetworkDriver (точные методы, версии API) выходят за рамку этой заметки и описаны в исходниках moby/libnetwork.
- Протокол плагинов — HTTP/JSON-RPC поверх сокета (не gRPC): handshake `/Plugin.Activate`, эндпоинты `/NetworkDriver.*`; спецификация — docs.docker.com/engine/extend/plugin_api.
- В rootless-режиме пути плагинов другие (`$XDG_CONFIG_HOME/docker/plugins`), а плагины, требующие `CAP_SYS_ADMIN` или host network, несовместимы.
