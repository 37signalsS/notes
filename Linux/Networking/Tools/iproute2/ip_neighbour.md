# ip neighbour: Управление ARP/NDP-таблицей

## Определения

**ARP (Address Resolution Protocol)** — протокол для определения MAC-адреса по известному IP-адресу в локальной сети (IPv4).

**NDP (Neighbor Discovery Protocol)** — аналог ARP для IPv6, использует ICMPv6-сообщения.

**`ip neighbour`** — команда `iproute2` для управления кэшем ARP (IPv4) и таблицей соседей NDP (IPv6).

## Базовые концепции

### Статусы записей

| Статус | Описание |
|--------|----------|
| **REACHABLE** | Подтверждённая запись: MAC-адрес известен, соединение активно |
| **STALE** | Устаревшая запись: MAC известен, но требует подтверждения при следующем использовании |
| **DELAY** | Задержка: запись в состоянии STALE, ожидается подтверждение перед переводом в PROBE |
| **PROBE** | Проверка: отправляются ARP/NDP-запросы для подтверждения записи |
| **INCOMPLETE** | В процессе разрешения: отправлен запрос, ожидается ответ |
| **PERMANENT** | Статическая запись: не истекает, не удаляется автоматически |
| **NOARP** | Запись без проверки: используется для интерфейсов, не требующих ARP |

### Время жизни записей

* **gc_stale_time** (по умолчанию 60 с) — время до перевода из REACHABLE в STALE
* **delay_first_probe_time** (по умолчанию 5 с) — задержка перед отправкой ARP/NDP-запроса

## Практические сценарии

### Просмотр ARP-таблицы

```bash
# Все записи
ip neighbour show

# Только IPv4
ip -4 neighbour show

# Только IPv6
ip -6 neighbour show

# По конкретному интерфейсу
ip neighbour show dev eth0

# В JSON-формате (для скриптов)
ip -j neighbour show
```

### Фильтрация по статусу

```bash
# Только подтверждённые записи
ip neighbour show nud reachable

# Только устаревшие
ip neighbour show nud stale

# Все активные (reachable + delay + probe)
ip neighbour show nud all
```

> **nud** = "neighbor unreachability detection"

### Добавление статической записи

```bash
# Статическая запись (не истекает)
sudo ip neighbour add 192.168.1.50 lladdr 00:11:22:33:44:55 dev eth0 nud permanent

# Временная запись с явным указанием статуса
sudo ip neighbour add 192.168.1.51 lladdr aa:bb:cc:dd:ee:ff dev eth0 nud reachable
```

### Удаление записей

```bash
# Удалить конкретную запись
sudo ip neighbour del 192.168.1.50 dev eth0

# Очистить всю таблицу для интерфейса
sudo ip neighbour flush dev eth0

# Очистить только устаревшие записи
sudo ip neighbour flush dev eth0 nud stale
```

### Принудительное обновление

```bash
# Отправить ARP/NDP-запрос для обновления записи
sudo ip neighbour change 192.168.1.50 dev eth0 nud probe
```

### Отладка проблем

```bash
# Проверить, разрешается ли IP
ip neighbour get 192.168.1.50

# Мониторинг изменений в реальном времени
watch -n 1 'ip neighbour show dev eth0'

# Статистика ARP (счетчики ядра)
cat /proc/net/stat/arp_cache
```

## Дополнительная информация

### Связанные темы

* **[ARP](../../../../Networking/Protocols/arp.md)** — детально о протоколе ARP
* **[IPv6](../../Settings/ipv6_configuration/firewall.md)** — настройка IPv6, NDP
* **[Сетевая диагностика](../../network_diagnostics_tools.md)** — инструменты отладки сети

### Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| Запись в **INCOMPLETE** | Нет ответа на ARP/NDP | Проверить доступность узла, кабель, VLAN |
| Запись в **STALE** | Истёк gc_stale_time | Нормально, обновится при использовании |
| Дубликаты IP | Конфликт адресов | Проверить `arping`, найти дубликат |
| Переполнение таблицы | Слишком много соседей | Увеличить `gc_thresh` через `sysctl` |
