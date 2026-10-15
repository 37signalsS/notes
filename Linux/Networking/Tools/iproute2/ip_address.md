# ip address: Управление IP-адресами

## Определения

* **`ip address`** (синонимы: `ip addr`, `ip a`) — специализированный объект утилиты `ip` из пакета `iproute2`, предназначенный для управления адресами протоколов IPv4 и IPv6 на сетевых интерфейсах. Предоставляет полный контроль над назначением, удалением, модификацией и 조회ой IP-адресов на любом интерфейсе Linux.
* **Основной адрес (Primary Address)** — первый адрес, назначенный в конкретной подсети на интерфейсе. Он служит адресом источника (`Source IP`) по умолчанию для исходящих пакетов, генерируемых самим хостом. При удалении основного адреса могут удаляться и все вторичные адреса той же подсети.
* **Вторичный адрес (Secondary Address)** — дополнительные адреса в той же подсети. В Linux они логически привязаны к основному адресу. Удаление основного адреса приводит к удалению всех вторичных адресов, если не включен параметр `promote_secondaries`.
* **Область видимости (Scope)** — атрибут, определяющий логический радиус действия адреса (например, только внутри хоста или во всей глобальной сети). Scope влияет на то, как ядро использует адрес для маршрутизации и выбора исходного IP.
* **`ip addr replace`** — атомарная операция замены адреса: если адрес уже существует, он обновляется; если нет — создается. Позволяет избежать ошибки `File exists` при повторном применении конфигурации.
* **`ip addr flush`** — удаление всех адресов на указанном интерфейсе. Операция необратима и требует осторожности: при удалении основного адреса может быть потерян маршрут по умолчанию.

> **Важно:** Все изменения, внесенные через `ip address`, применяются немедленно в ядре, но являются **временными**. Они будут утеряны после перезагрузки. Для постоянной настройки используйте системные конфигураторы (systemd-networkd, Netplan, NetworkManager).

## Предпосылки

### Требования

* **Пакет `iproute2`**: Установлен в системе (включает утилиту `ip`).
    ```bash
    # Debian/Ubuntu
    sudo apt install iproute2

    # RHEL/CentOS/Rocky
    sudo dnf install iproute
    ```
* **Права root**: Все команды `ip address` (кроме `ip address show`) требуют привилегий суперпользователя (`sudo`).
* **Сетевой интерфейс**: Интерфейс должен находиться в состоянии `UP` для назначения адресов.
    ```bash
    # Проверка состояния интерфейса
    ip link show dev eth0
    # → state UP или state DOWN

    # Поднятие интерфейса
    sudo ip link set eth0 up
    ```

### Проверка текущего состояния

```bash
# Просмотр всех адресов на всех интерфейсах
ip address show

# Краткий вывод для быстрой проверки
ip -br address show
# →输出: iface  state  ip/prefix  ...

# Просмотр только IPv4 адресов
ip -4 address show

# Просмотр только IPv6 адресов
ip -6 address show
```

## Основные концепции

### Структура вывода ip addr show

Каждый интерфейс в выводе `ip addr show` содержит:

```
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 52:54:00:12:34:56 brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 2001:db8::1/64 scope global dynamic noprefixroute
       valid_lft 2591999sec preferred_lft 604799sec
    inet6 fe80::5054:ff:fe12:3456/64 scope link
       valid_lft forever preferred_lft forever
```

| Поле | Описание |
| :--- | :--- |
| **inet** | IPv4-адрес с маской (CIDR). |
| **inet6** | IPv6-адрес с префиксом. |
| **brd** | Широковещательный адрес (Broadcast). |
| **scope** | Область видимости: `global`, `link`, `host`. |
| **valid_lft** | Время жизни адреса (_Valid Lifetime). `forever` — статический адрес. |
| **preferred_lft** | Время предпочтительности (Preferred Lifetime). После истечения адрес становится `deprecated`. |
| **dynamic** | Адрес получен автоматически (DHCP/SLAAC). |
| **noprefixroute** | Ядро не создает маршрут для префикса этого адреса. |
| **temporary** | Временный адрес (IPv6 Privacy Extensions). |
| **deprecated** | Адрес валиден для приема, но не для новых соединений. |

### Классификация областей видимости (Scope)

| Область | Техническое описание | Примеры использования |
| :--- | :--- | :--- |
| **global** | Глобально маршрутизируемый адрес, доступный за пределами локального сегмента. | Публичные IP, RFC1918 в маршрутизируемых сетях. |
| **link** | Адрес валиден только в пределах данного L2-домена. | IPv6 Link-Local `fe80::/10`, адреса Loopback. |
| **host** | Адрес ограничен пределами самого хоста. | Интерфейс `lo` (`127.0.0.1/8`). |

**Важно:** Scope определяет, будет ли ядро использовать адрес как источник при маршрутизации. Адрес `scope link` не будет использоваться для маршрутизации за пределами локального сегмента.

### Атрибуты и флаги адресов

| Флаг | Описание | Когда использовать |
| :--- | :--- | :--- |
| **dynamic** | Адрес получен автоматически (DHCP или SLAAC). | Стандартное поведение для DHCP-клиентов. |
| **permanent** | Адрес настроен вручную (статически). | Статическая конфигурация серверов. |
| **deprecated** | Адрес валиден для приема трафика, но его использование для новых исходящих соединений не рекомендуется. | Перенумерация IPv6, вывод адреса из эксплуатации. |
| **tentative** | (IPv6) Адрес находится в процессе проверки на уникальность (DAD — Duplicate Address Detection). | Назначение нового IPv6-адреса. |
| **dadfailed** | (IPv6) Обнаружен дубликат адреса, проверка уникальности не пройдена. | Конфликт IPv6-адресов в сети. |
| **nodad** | (IPv6) Отключает проверку дубликатов. Критично для Anycast или ускорения настройки. | Anycast-адреса, критичные сервисы. |
| **mngtmpaddr** | (IPv6) Указывает ядру генерировать временные адреса на основе префикса этого адреса (RFC 4941 Privacy Extensions). | Защита от отслеживания. |
| **noprefixroute** | Запрещает ядру автоматически создавать маршрут в таблицу маршрутизации для префикса этого адреса. | Ручное управление маршрутами, VRF. |
| **home** | (IPv6) Помечает адрес как "Home Address" для Mobile IPv6. | Мобильные устройства. |
| **stable-privacy** | (IPv6) Стабильный приватный адрес (RFC 7217). | Современные реализации Privacy Extensions. |
| **optimistic** | (IPv6) Оптимистичный DAD (RFC 4429) — позволяет использовать адрес до завершения проверки DAD. | Ускорение сетевой связности. |

### Управление временем жизни (Lifetimes)

Для динамических сред и IPv6 критически важны параметры времени жизни:

* **valid_lft** (Valid Lifetime) — общее время (в секундах), в течение которого адрес считается валидным. По истечении этого времени адрес удаляется. `forever` означает бессрочный адрес.
* **preferred_lft** (Preferred Lifetime) — время, в течение которого адрес считается предпочтительным. После его истечения адрес переходит в состояние `deprecated`. Новые соединения не будут использовать этот адрес как источник.

```bash
# Просмотр времени жизни
ip -6 addr show dev eth0
# → valid_lft 2591999sec preferred_lft 604799sec

# Назначение адреса с ограниченным временем жизни
sudo ip address add 172.16.0.5/24 dev eth0 valid_lft 3600 preferred_lft 1800
# → Адрес будет удален через 1 час, deprecated через 30 минут
```

### Механизм выбора исходного IP (Source IP Selection)

Ядро Linux выбирает исходный IP-адрес на основе:

1. **Explicit bind():** Приложение явно указало адрес через `bind()`.
2. **Routing table match:** Адрес назначения совпадает с подсетью одного из интерфейсов.
3. **Scope:** Ядро предпочитает адреса `scope global` над `scope link`.
4. **Address label (addrlabel):** Правила приоритета для выбора исходного адреса (настраиваются через `ip addrlabel`).

```bash
# Просмотр правил addrlabel
ip addrlabel show

# Добавление правила addrlabel (предпочтение префикса 2001:db8::/32)
sudo ip addrlabel add prefix 2001:db8::/32 label 100 dev eth0

# Удаление правила
sudo ip addrlabel del prefix 2001:db8::/32 label 100
```

### Взаимодействие с VRF (Virtual Routing and Forwarding)

При использовании VRF адреса назначаются на интерфейсы, которые затем привязываются к VRF-мастеру. Это позволяет изолировать адресные пространства на одном хосте.

```bash
# Просмотр адресов в контексте конкретного VRF
ip address show vrf vrf-mgmt

# Назначение адреса на интерфейс, привязанный к VRF
sudo ip address add 10.0.0.1/24 dev eth0 vrf vrf-mgmt
```

### promote_secondaries

Параметр sysctl, определяющий поведение при удалении основного адреса:

* **`promote_secondaries=0`** (по умолчанию в большинстве дистрибутивов): При удалении основного адреса все вторичные адреса той же подсети также удаляются.
* **`promote_secondaries=1`**: При удалении основного адреса первый вторичный адрес той же подсети становится основным.

```bash
# Просмотр текущего значения
sysctl net.ipv4.conf.all.promote_secondaries
# → net.ipv4.conf.all.promote_secondaries = 0

# Включение (рекомендуется для серверов)
sudo sysctl -w net.ipv4.conf.all.promote_secondaries=1
sudo sysctl -w net.ipv4.conf.eth0.promote_secondaries=1

# Постоянная запись
echo "net.ipv4.conf.all.promote_secondaries=1" | sudo tee -a /etc/sysctl.d/99-promote-secondaries.conf
echo "net.ipv4.conf.eth0.promote_secondaries=1" | sudo tee -a /etc/sysctl.d/99-promote-secondaries.conf
```

## Практические сценарии

### Оперативный просмотр и диагностика

```bash
# Вывод всех адресов на всех интерфейсах (подробно)
ip address show

# Краткий (однострочный) вывод для быстрой проверки
ip -br address show
# → lo  UNKNOWN  127.0.0.1/8 ::1/128
# → eth0 UP  192.168.1.100/24 2001:db8::1/64 fe80::.../64

# Добавление и мгновенная проверка результата
ip addr add 10.0.0.5/24 dev eth0 && ip addr show dev eth0
# → 3: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
# →     inet 10.0.0.5/24 scope global eth0

# Фильтрация по протоколу
ip -4 address show
ip -6 address show

# Вывод в формате JSON для автоматизации (скрипты, мониторинг)
ip -j -p address show eth0
# → {"ifindex":2,"ifname":"eth0","state":"UP","addr_info":[...]}

# Просмотр адресов конкретного интерфейса
ip address show dev eth0

# Просмотр только глобальных адресов (без link-local)
ip address show scope global

# Просмотр только link-local адресов
ip address show scope link

# Просмотр адресов с фильтрацией по подсети
ip address show | grep "inet 192.168"
```

**Машиночитаемый дамп интерфейсов с фильтрацией через jq:**

```bash
# Вывести поднятые линки и их локальные IP через jq
ip -j a | jq -r '.[] | select(.operstate=="UP") | .ifname + " " + (.addr_info[]?.local // "-")'
```

### Назначение и модификация адресов

```bash
# Добавление статического IPv4 адреса с указанием широковещательного адреса
sudo ip address add 192.168.1.100/24 brd + dev eth0

# Добавление IPv6 глобального адреса
sudo ip -6 address add 2001:db8::1/64 dev eth0

# Добавление IPv6 Link-Local адреса (обычно назначается автоматически)
sudo ip -6 address add fe80::1/64 dev eth0 nodad

# Настройка Anycast адреса (IPv6)
# Используется nodad для предотвращения конфликтов при назначении одного IP на несколько хостов
sudo ip -6 address add 2001:db8:ffff::1/128 dev eth0 nodad anycast

# Добавление адреса с меткой (alias) для совместимости со старым ifconfig
sudo ip address add 10.0.0.1/24 dev eth0 label eth0:mgmt

# Ограничение времени жизни адреса (например, для временного доступа)
sudo ip address add 172.16.0.5/24 dev eth0 valid_lft 3600 preferred_lft 1800

# Атомарная замена адреса (не выдаст ошибку "File exists")
sudo ip address replace 192.168.1.100/24 dev eth0
```

### Работа с вторичными адресами

Вторичные адреса используются для:
- Размещения нескольких подсетей на одном интерфейсе
- Настройки виртуальных хостов
- Миграции между подсетями без даунтайма

```bash
# Добавление основного адреса
sudo ip address add 192.168.1.100/24 dev eth0

# Добавление вторичного адреса в той же подсети
sudo ip address add 192.168.1.101/24 dev eth0 secondary

# Добавление вторичного адреса в другой подсети
sudo ip address add 10.0.0.100/24 dev eth0 secondary

# Просмотр всех адресов с указанием типа (primary/secondary)
ip address show dev eth0 | grep -E "(inet |secondary)"

# Удаление только вторичного адреса
sudo ip address del 192.168.1.101/24 dev eth0
```

### Удаление и очистка интерфейсов

```bash
# Удаление конкретного адреса
sudo ip address del 192.168.1.100/24 dev eth0

# Полная очистка (удаление) всех адресов на интерфейсе
sudo ip address flush dev eth0

# Удаление всех IPv4 адресов на интерфейсе
sudo ip -4 address flush dev eth0

# Удаление всех IPv6 адресов на интерфейсе
sudo ip -6 address flush dev eth0

# Удаление всех адресов с определенным scope
sudo ip address flush dev eth0 scope global
```

**Внимание:** При удалении основного адреса, полученного по DHCP, ядро может также удалить маршрут по умолчанию, привязанный к этому адресу, что приведет к потере сетевой связности. Всегда проверяйте маршрут после `ip addr del`:

```bash
# Проверка маршрута после удаления адреса
ip route get 8.8.8.8
# → Если нет маршрута — потеря связности
```

### Механизмы приватности (IPv6 Privacy Extensions)

Используются для предотвращения отслеживания хоста по его статическому IPv6-адресу. Ядро генерирует временные адреса, которые周期ически меняются.

```bash
# Включение генерации временных адресов через sysctl
sudo sysctl -w net.ipv6.conf.all.use_tempaddr=2
sudo sysctl -w net.ipv6.conf.default.use_tempaddr=2

# Значения:
# 0 — отключено (по умолчанию в старых дистрибутивах)
# 1 — включено, но не отключает статические адреса
# 2 — включено, статические адреса также могут использовать temporary

# Проверка наличия временных адресов (флаг 'temporary' в выводе)
ip -6 address show eth0 | grep temporary
# → inet6 2001:db8::a:b:c:d/64 scope global temporary dynamic
```

### Сохранение и восстановление состояния

```bash
# Сохранение текущих адресов в файл (экспериментальная функция)
ip address save > addresses.state

# Восстановление адресов из файла
sudo ip address restore < addresses.state

# Сохранение только для определенного интерфейса
ip address show dev eth0 > eth0_addresses.state
```

### Назначение адресов на виртуальные интерфейсы

```bash
# VLAN-интерфейс
sudo ip address add 192.168.10.1/24 dev eth0.10
sudo ip address add 192.168.20.1/24 dev eth0.20

# Bridge-интерфейс
sudo ip address add 10.0.0.1/24 dev br0

# Bond-интерфейс
sudo ip address add 192.168.1.100/24 dev bond0

# Туннельный интерфейс (GRE)
sudo ip address add 10.0.0.1/30 dev gre1

# MACVLAN-интерфейс
sudo ip address add 192.168.1.201/24 dev macv-eth0
```

## Диагностика и мониторинг

### Проверка конфигурации после изменений

```bash
# Проверка назначения адреса
ip address show dev eth0 | grep "inet 192.168.1.100"
# → inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0

# Проверка состояния интерфейса
ip link show dev eth0 | grep state
# → state UP

# Проверка маршрута по умолчанию
ip route show default
# → default via 192.168.1.1 dev eth0

# Проверка связности
ping -c 3 192.168.1.1
# → 3 packets transmitted, 3 received, 0% packet loss
```

### Мониторинг изменений в реальном времени

```bash
# Мониторинг событий netlink (изменения адресов, интерфейсов)
sudo ip monitor address

# Мониторинг всех сетевых событий
sudo ip monitor all

# Мониторинг конкретного интерфейса
sudo ip monitor address dev eth0
```

### Просмотр статистики адресов

```bash
# Статистика пакетов для всех интерфейсов
ip -s address show

# Статистика для конкретного интерфейса
ip -s address show dev eth0
# → RX: bytes, packets, errors, dropped, overrun, mcast
# → TX: bytes, packets, errors, dropped, aborted, carrier
```

## Траблшутинг

### Проблема: "RTNETLINK answers: File exists"

**Причина:** Адрес уже назначен интерфейсу.

**Решение:**
```bash
# Просмотр текущих адресов
ip address show dev eth0 | grep "inet 192.168.1.100"
# → Если адрес есть — это нормально (для идемпотентных скриптов)

# Использование атомарной замены
sudo ip address replace 192.168.1.100/24 dev eth0

# Или удаление перед добавлением
sudo ip address del 192.168.1.100/24 dev eth0
sudo ip address add 192.168.1.100/24 dev eth0
```

### Проблема: "RTNETLINK answers: Cannot assign requested address"

**Причины:**
1. Интерфейс выключен (состояние `DOWN`).
2. Адрес уже используется другим интерфейсом (в той же L2-сегменте).
3. Нарушены правила адресации (например, `127.x.x.x` на внешнем интерфейсе).

**Решение:**
```bash
# Проверка состояния интерфейса
ip link show dev eth0
# → state DOWN → нужен ip link set eth0 up

# Включение интерфейса
sudo ip link set eth0 up

# Проверка, не занят ли адрес
ip address show | grep "192.168.1.100"
# → Если занят — удалите или используйте другой адрес

# Проверка scope
ip address show | grep "192.168.1.100" | awk '{print $7}'
# → Если scope неверный (например, link вместо global)
```

### Проблема: Сеть пропала после `ip addr del`

**Причина:** Удален основной адрес (Primary) и связанный шлюз по умолчанию.

**Решение:**
```bash
# 1. Проверка наличия маршрута по умолчанию
ip route show default
# → Пусто — маршрут потерян

# 2. Включение promote_secondaries (для предотвращения в будущем)
sudo sysctl -w net.ipv4.conf.all.promote_secondaries=1

# 3. Восстановление маршрута
sudo ip route add default via 192.168.1.1 dev eth0

# 4. Восстановление адреса
sudo ip address add 192.168.1.100/24 dev eth0
```

### Проблема: IPv6-адрес в состоянии `tentative`

**Причина:** Идет проверка на уникальность (DAD — Duplicate Address Detection). Это нормальное поведение, занимает 1-2 секунды.

**Решение:**
```bash
# Ожидание завершения DAD (обычно 1-2 секунды)
sleep 2
ip -6 address show dev eth0 | grep tentative
# → Если нет вывода — проверка завершена

# Отключение DAD (ускорение, но повышает риск конфликтов)
sudo ip -6 address add 2001:db8::1/64 dev eth0 nodad

# Проверка конфликтов (dadfailed)
ip -6 address show dev eth0 | grep dadfailed
# → Если есть — конфликт IPv6-адресов в сети
```

### Проблема: Не удается назначить IPv6-адрес

**Причины:**
1. Интерфейс выключен (состояние `DOWN`).
2. IPv6 отключен на интерфейсе.
3. Неверный формат адреса.

**Решение:**
```bash
# Проверка состояния интерфейса
ip link show dev eth0 | grep -i "state\|ipv6"

# Включение IPv6 на интерфейсе
sudo sysctl -w net.ipv6.conf.eth0.disable_ipv6=0

# Проверка, что IPv6 включен
cat /proc/sys/net/ipv6/conf/eth0/disable_ipv6
# → 0 = включен, 1 = отключен
```

### Проблема: Высокое потребление CPU при большом количестве адресов

**Причина:** Ядро обрабатывает ARP/NDP-запросы для каждого адреса.

**Решение:**
```bash
# Уменьшение частоты ARP-кеша
sudo sysctl -w net.ipv4.neigh.eth0.gc_stale_time=120

# Проверка ARP-таблицы
ip neigh show dev eth0 | wc -l
# → Если >1000 — рассмотрите агрегацию адресов или VLAN
```

### Проблема: Конфликт DAD (Duplicate Address Detection)

**Причина:** Два устройства в одной сети используют одинаковый IPv6-адрес.

**Диагностика:**
```bash
# Просмотр адресов с флагом dadfailed
ip -6 address show | grep dadfailed
# → inet6 2001:db8::1/64 scope global dadfailed

# Просмотр邻居 (neighbor) с конфликтами
ip -6 neigh show | grep FAILED
# → 2001:db8::1 dev eth0 FAILED
```

**Решение:**
```bash
# 1. Определение конфликтного адреса
ip -6 address show | grep dadfailed

# 2. Удаление конфликтного адреса
sudo ip -6 address del 2001:db8::1/64 dev eth0

# 3. Назначение нового уникального адреса
sudo ip -6 address add 2001:db8::2/64 dev eth0

# 4. Или использование stable-privacy адресов (RFC 7217)
sudo sysctl -w net.ipv6.conf.eth0.addr_gen_mode=2
```

## Оптимизация и лучшие практики

### Рекомендации для серверов

```bash
# 1. Включение promote_secondaries (обязательно для серверов)
sudo sysctl -w net.ipv4.conf.all.promote_secondaries=1
sudo sysctl -w net.ipv4.conf.default.promote_secondaries=1

# 2. Отключение IPv6 Privacy Extensions на серверах (стабильные адреса)
sudo sysctl -w net.ipv6.conf.all.use_tempaddr=0
sudo sysctl -w net.ipv6.conf.default.use_tempaddr=0

# 3. Включение IPv6 для серверов
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0
sudo sysctl -w net.ipv6.conf.default.disable_ipv6=0

# 4. Настройка ICMP-ответов (для мониторинга)
sudo sysctl -w net.ipv4.icmp_echo_ignore_all=0
sudo sysctl -w net.ipv6.icmp.echo_ignore_all=0
```

### Рекомендации для клиентских машин

```bash
# 1. Включение IPv6 Privacy Extensions
sudo sysctl -w net.ipv6.conf.all.use_tempaddr=2
sudo sysctl -w net.ipv6.conf.default.use_tempaddr=2

# 2. Ускорение DAD (Optimistic DAD)
sudo sysctl -w net.ipv6.conf.all.optimistic_dad=1

# 3. Отключение ICMP-ответов (защита от сканирования)
sudo sysctl -w net.ipv4.icmp_echo_ignore_all=1
```

## Очистка среды

**Важно:** Всегда проверяйте результаты изменений и сохраняйте возможность отката.

```bash
# Сохранение текущего состояния перед изменениями
ip address save > /tmp/ip_address_backup_$(date +%Y%m%d).state

# Удаление временных адресов
sudo ip address del 172.16.0.5/24 dev eth0

# Полная очистка интерфейса (ОСТОРОЖНО!)
sudo ip address flush dev eth0

# Восстановление из резервной копии
sudo ip address restore < /tmp/ip_address_backup_20260911.state

# Проверка восстановления
ip address show dev eth0
```

## Связанные темы

* **[ip link](./ip_link.md)** — управление состоянием и параметрами уровней L1/L2.
* **[ip route](./ip_route.md)** — управление таблицами маршрутизации.
* **[ip neighbour](./ip_neighbour.md)** — управление ARP/NDP-таблицами (кэш соседей).
* **[Сетевые интерфейсы Linux](../../Concepts/linux_network_interfaces.md)** — глубокий разбор типов (Bridge, Bond, VLAN).
* **[Постоянная настройка сети](../../Settings/Persistent_Network/index.md)** — методы сохранения конфигурации в различных дистрибутивах.
* **[Выбор исходного IP](../../SystemAdministration/routing.md#выбор-исходного-ip-source-ip-selection)** — детализированный алгоритм выбора `Source IP` ядром.
* **[IPv6 Address Configuration](../../Settings/ipv6_configuration/address_configuration.md)** — подробное руководство по настройке IPv6-адресов.
