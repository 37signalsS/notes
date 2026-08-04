# Управление сетями Docker: CLI-справочник

## Определения

- **`docker network`**: Набор команд CLI (Command Line Interface — интерфейс командной строки) для управления жизненным циклом сетей Docker.
- **Сеть (Network)**: Виртуальный коммутатор, обеспечивающий связь между контейнерами (endpoints).
- **Драйвер сети (Network Driver)**: Плагин, реализующий сетевую логику (`bridge`, `host`, `overlay`, `macvlan`, `ipvlan`, `none`).
- **IPAM (IP Address Management)**: Система управления адресным пространством (подсети, шлюзы, диапазоны IP).
- **Config-only Network**: Специальный тип сети в Docker Swarm, содержащий только параметры конфигурации без создания самой сети данных. Используется для разделения определений и реализации.

## Основные концепции

### Команды управления

| Команда | Назначение | Ключевые флаги / Фильтры |
| :--- | :--- | :--- |
| `ls` | Список сетей | `--filter` (`driver`, `type`, `name`, `scope`), `--format`, `--no-trunc` |
| `create` | Создание сети | `-d` (драйвер), `--subnet`, `--gateway`, `--internal`, `--attachable`, `--config-only` |
| `inspect` | Детальная информация | `--format` (Go-шаблоны), `-v` (verbose) |
| `connect` | Подключение контейнера | `--ip`, `--ip6`, `--alias`, `--link` (legacy) |
| `disconnect` | Отключение контейнера | `-f` (force — принудительно) |
| `rm` | Удаление сети | Удаляет только неиспользуемые сети |
| `prune` | Очистка системы | `--filter` (например, `until=24h`, `label=project=web`), `-f` |

### Расширенные опции создания (v27/v28+)

- **Управление IP (IPAM):**
  - `--subnet`: Определяет подсеть в формате CIDR.
  - `--gateway`: Указывает адрес шлюза.
  - `--ip-range`: Ограничивает диапазон выдаваемых IP-адресов внутри подсети.
  - `--aux-address`: Резервирует IP-адреса (например, `--aux-address="router=192.168.1.5"`).
- **Параметры драйвера (`-o, --opt`):**
  - `com.docker.network.bridge.name`: Кастомное имя интерфейса на хосте.
  - `com.docker.network.bridge.enable_icc`: Включение/выключение связи между контейнерами (Inter-Container Communication).
  - `com.docker.network.bridge.gateway_mode_ipv6=routed`: (v27+) Включает прямую маршрутизацию IPv6 без NAT.
- **Особенности Swarm/Overlay:**
  - `--attachable`: Позволяет подключать обычные контейнеры к `overlay`-сетям.
  - `--encrypted`: Включает шифрование трафика (IPsec) на уровне данных.

## Практические сценарии

### Продвинутая фильтрация и форматирование

**Поиск сетей, созданных более 24 часов назад:**

```bash
docker network ls --filter "until=24h"
```

**Вывод ID и драйвера в формате таблицы:**

```bash
docker network ls --format "table {{.ID}}\t{{.Driver}}\t{{.Name}}"
# → NETWORK ID     DRIVER    NAME
# → a1b2c3d4e5f6   bridge    bridge
```

### Сложное создание сети

**Создание bridge-сети с IPv6 Routed Mode (v28):**

```bash
docker network create -d bridge \
  --ipv6 --subnet=fd00::/64 \
  -o com.docker.network.bridge.gateway_mode_ipv6=routed \
  ipv6-routed-net
```

**Создание конфигурационной сети (Config-only) для Swarm:**

```bash
docker network create --config-only --subnet 10.20.0.0/24 my-config-net
# → Используется позже через --config-from при создании рабочей сети
```

### Инспекция и отладка (Go Templates)

**Получение списка всех контейнеров в сети (только имена и IP):**

```bash
docker network inspect prod-net -f '{{range .Containers}}{{.Name}} -> {{.IPv4Address}}{{println}}{{end}}'
# → my-web-app -> 172.18.0.2/16
# → my-db-app -> 172.18.0.3/16
```

**Проверка наличия специфических опций драйвера:**

```bash
docker network inspect bridge -f '{{index .Options "com.docker.network.bridge.name"}}'
# → docker0
```

### Массовые операции

**Удаление всех неиспользуемых сетей с меткой проекта:**

```bash
docker network prune -f --filter "label=project=dev-stack"
```

## Дополнительная информация

### Нюансы и ограничения

- **Принудительное отключение (`disconnect -f`)**: Рекомендуется при "зависании" контейнера в сети, когда демон не может корректно обновить правила iptables/nftables.
- **Ограничения драйверов**:
  - `host`: Флаги `--ip` или `--alias` игнорируются, так как контейнер использует стек хоста напрямую.
  - `none`: Невозможно подключить контейнер к любой другой сети.
- **Переименование**: Docker CLI не поддерживает команду `rename` для сетей. Для изменения имени необходимо удалить и пересоздать сеть.
- **Конфликты**: Docker проверяет пересечение подсетей только внутри своего демона. Он не знает о внешних маршрутах хоста, что может привести к потере связи с внешней сетью при совпадении CIDR.

**Смотрите также:**

- [Обзор сетевых моделей Docker (SSoT)](./docker_network.md)
- [Сетевой драйвер bridge (SSoT)](./drivers/bridge.md)
- [Сетевой драйвер overlay (SSoT)](./drivers/overlay.md)
- [Диагностика сетевых проблем](../Docker_troubleshooting/network_connectivity_issues.md)
