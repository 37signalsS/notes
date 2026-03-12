# iproute2: Обзор

## Определения

**`iproute2`** — набор современных утилит командной строки для управления сетью в ядре Linux. Заменяет устаревшие инструменты (`ifconfig`, `route`, `arp`, `ipxconf`).

**Объект** — центральное понятие `iproute2`. Команда `ip` работает с объектами: `link`, `address`, `route`, `neighbour`, `netns`, `tunnel`, `rule`.

## Базовые концепции

### Архитектура

* **Основная утилита:** `ip` (единый интерфейс ко всем объектам)
* **Дополнительные утилиты:** `ss`, `rtmon`, `nstat`, `lnstat`
* **Конфигурация:** `/etc/iproute2/` (таблицы маршрутизации, правила)
* **Временные настройки:** Все изменения через `ip` действуют до перезагрузки

> **Постоянная настройка:** См. [Постоянная настройка сети](../../Settings/persistent_network_configuration.md).

### Синтаксис команд

```bash
ip [опции] объект команда [аргументы]

# Примеры:
ip -br link show          # Краткий вывод интерфейсов
ip -j address show eth0   # JSON-вывод для скриптов
ip -s route show          # Статистика маршрутов
```

**Общие опции:**

| Опция | Описание |
|-------|----------|
| `-br` | Краткий вывод (brief) |
| `-j` | JSON-формат |
| `-s` | Статистика (можно `-s -s`) |
| `-d` | Детальная информация |
| `-4` / `-6` | Только IPv4 / IPv6 |

### Ключевые объекты

| Объект | Команда | Описание |
|--------|---------|----------|
| **link** | `ip l` | Сетевые интерфейсы (state, MTU, MAC) | [`ip link`](./ip_link.md) |
| **address** | `ip a` | IP-адреса на интерфейсах | [`ip address`](./ip_address.md) |
| **route** | `ip r` | Таблица маршрутизации | [`ip route`](./ip_route.md) |
| **neighbour** | `ip n` | ARP/NDP-таблица | [`ip neighbour`](./ip_neighbour.md) |
| **rule** | `ip rule` | Policy-Based Routing | [PBR](../../Policy_Based_Routing/index.md) |
| **netns** | `ip netns` | Сетевые namespace | [`ip netns`](./ip_netns.md) |
| **tunnel** | `ip tunnel` | Туннели (GRE, IPIP, SIT, VXLAN) | [`ip tunnel`](./ip_tunnel.md) |
| **monitor** | `ip monitor` | Мониторинг событий | — |

### Управление трафиком (tc)

**`tc`** — утилита `iproute2` для QoS (Quality of Service).

| Компонент | Описание |
|-----------|----------|
| **qdisc** | Дисциплина очереди (FQ, HTB, netem) | [`tc`](./tc.md) |
| **class** | Классы трафика (HTB) | [`tc`](./tc.md) |
| **filter** | Фильтрация и маркировка | [`tc`](./tc.md) |
| **netem** | Эмуляция проблем сети | [`tc netem`](./tc_netem.md) |

## Практические сценарии

### Быстрая диагностика

```bash
# Проверить интерфейсы и адреса
ip -br a

# Проверить маршрут до хоста
ip route get 8.8.8.8

# Проверить ARP-кэш
ip neighbour show

# Мониторинг изменений в реальном времени
ip monitor
```

### Скрипты и автоматизация

```bash
# JSON-вывод для парсинга
ip -j link show | jq '.[] | select(.ifname == "eth0")'

# Получить только IP-адрес
ip -j address show eth0 | jq '.[0].addr_info[0].local'
```

### Policy-Based Routing (PBR)

```bash
# Показать правила
ip rule show

# Добавить правило для таблицы 100
ip rule add from 192.168.1.0/24 table 100

# Показать таблицу
ip route show table 100
```

> **Подробно:** [Policy-Based Routing](../../Policy_Based_Routing/index.md)

## Дополнительная информация

### Связанные темы

* **[Постоянная настройка сети](../../Settings/persistent_network_configuration.md)** — сохранение настроек
* **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_tuning_overview.md)** — tuning TCP-стека, QoS
* **[Network namespaces](../../../../Linux/Core/namespaces.md)** — изоляция сети
* **[Сетевая диагностика](../../network_diagnostics_tools.md)** — инструменты отладки

### Установка

| Дистрибутив | Пакет |
|-------------|-------|
| Debian/Ubuntu | `iproute2` |
| RHEL/CentOS | `iproute` |
| Alpine | `iproute2` |
| Arch | `iproute2` |

### Версия и проверка

```bash
# Проверить версию
ip -V

# Обновление базы данных маршрутов
sudo ip route flush cache  # Только для кэшированных маршрутов
```
