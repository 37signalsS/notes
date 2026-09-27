# Диагностика IPv6 в Linux

## Определения

**Диагностика IPv6** — комплекс мероприятий по выявлению и устранению проблем сетевой связности, включающий проверку состояния стека, корректности адресации, механизмов обнаружения соседей (NDP) и многоадресной рассылки (MLD).

**Neighbor Discovery Protocol (NDP)** — ключевой протокол (RFC 4861), заменяющий ARP. Отвечает за разрешение адресов, обнаружение маршрутизаторов и проверку уникальности адресов (DAD).

**Duplicate Address Detection (DAD)** — механизм проверки того, что выбранный IPv6-адрес не используется другим узлом в том же сегменте сети.

**Multicast Listener Discovery (MLD)** — протокол (RFC 2710 / MLDv2 RFC 3810), аналог IGMP для IPv6. Управляет членством в multicast-группах; без корректной работы MLD маршрутизаторы не будут перенаправлять multicast-трафик на интерфейс.

**Neighbor Unreachability Detection (NUD)** — механизм отслеживания состояния доступности соседа после разрешения адреса. Переводит запись через состояния REACHABLE → STALE → DELAY → PROBE → FAILED / INCOMPLETE.

**Path MTU Discovery (PMTUD)** — механизм автоматического определения максимального размера передаваемого пакета. В IPv6 является обязательным: маршрутизаторы не фрагментируют пакеты в транзите, а только генерируют ICMPv6 Type 2 (Packet Too Big).

## Основные концепции

### Состояние стека и параметры ядра (sysctl)

В Linux параметры IPv6 настраиваются для каждого интерфейса отдельно (`all`, `default`, `<ifname>`).

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **`disable_ipv6`** | `0` / `1` | Полное включение/отключение стека на интерфейсе. |
| **`accept_ra`** | `0` / `1` / `2` | Прием Router Advertisements (RA). `2` — принимать даже при включенном forwarding. |
| **`autoconf`** | `0` / `1` | Использование SLAAC для генерации адреса. |
| **`use_tempaddr`** | `0` / `2` | Использование временных (Privacy) адресов. |
| **`accept_ra_defrtr`** | `0` / `1` | Прием информации о Default Router из RA. |
| **`accept_ra_pinfo`** | `0` / `1` | Прием параметров сети (DNS, домен) из RA (RFC 6106). |
| **`forwarding`** | `0` / `1` | Включение forwarding для маршрутизации. |
| **`accept_redirects`** | `0` / `1` | Прием ICMPv6 Redirect. `0` — рекомендуется для security. |
| **`retrans`** | мс | Таймаут повторной отправки Neighbor Solicitation (по умолчанию 1000 мс). |
| **`base_reachable_time`** | мс | Базовое время удержания записи в состоянии REACHABLE. |
| **`gc_stale_time`** | с | Время, после которого STALE-запись удаляется GC (по умолчанию 60 с). |

### Особенности Link-Local адресов

Для диагностики адресов `fe80::/10` **обязательно** указывать идентификатор интерфейса (Scope ID) через символ `%` (например, `fe80::1%eth0`). Без этого ядро не сможет определить выходной интерфейс, так как Link-Local префикс не уникален в рамках всей системы.

### NUD (Neighbor Unreachability Detection)

После успешного разрешения адреса (NS/NA обмен) ядро отслеживает состояние доступности соседа через конечный автомат:

| Состояние | Значение |
| :--- | :--- |
| **INCOMPLETE** | Ожидание ответа на NS (запрос отправлен, ответа нет). |
| **REACHABLE** | Получен положительный отклик недавно (в пределах `base_reachable_time`). |
| **STALE** | Запись существует, но превышено время REACHABLE. При отправке трафика запрашивается подтверждение. |
| **DELAY** | Трафик был отправлен, ожидается подтверждение в течение 5 секунд. |
| **PROBE** | Идет активная отправка NS для подтверждения доступности. |
| **FAILED** | Не получен ответ после нескольких попыток NS. |

### Критичность ICMPv6 для функциональности IPv6

В отличие от IPv4, где блокировка ICMP часто лишь снижает удобство, в IPv6 полная блокировка ICMPv6 делает узел неработоспособным:
- **NDP (Types 133–137):** разрешение адресов, обнаружение маршрутизаторов, DAD, Redirect.
- **MLD (Types 130–132):** управление multicast-группами.
- **Packet Too Big (Type 2):** обязателен для PMTUD. Без него TCP-сессии с большими пакетами зависнут.
- **Destination Unreachable (Type 1):** информирует о недоступности порта/сети.
- **Echo Request/Reply (Types 128/129):** мониторинг доступности.

## Практические сценарии

### 1. Проверка состояния адресов и DAD

При назначении адреса он проходит стадию проверки на дубликаты.

```bash
# Просмотр адресов с флагами состояния
ip -6 addr show

# Результаты DAD:
# tentative -> проверка идет (адрес еще не активен)
# dadfailed -> адрес занят другим устройством (критическая ошибка)
# <пусто>   -> адрес успешно подтвержден и активен

# Проверка глобального включения стека
cat /proc/net/if_inet6
# Если файл пуст — стек отключен глобально (GRUB или sysctl)

# Просмотр только глобальных адресов
ip -6 addr show scope global

# Проверка параметров DAD и NDP
sysctl net.ipv6.conf.eth0.retrans
sysctl net.ipv6.conf.eth0.accept_ra
sysctl net.ipv6.conf.eth0.disable_ipv6
```

### 2. Анализ соседей и NDP

Если `ping6` не проходит в локальной сети, проверьте таблицу соседей (аналог ARP-таблицы).

```bash
# Просмотр кэша соседей
ip -6 neigh show

# Состояния:
# REACHABLE -> связь подтверждена недавно
# STALE     -> запись есть, но требует подтверждения при отправке
# FAILED    -> сосед не ответил на запросы (NS)
# INCOMPLETE -> запрос отправлен, ответа нет

# Детальный просмотр NDP с расширенной информацией
ip -6 -d neigh show

# Фильтрация по состоянию
ip -6 neigh show nud reachable
ip -6 neigh show nud stale
ip -6 neigh show nud failed

# Очистка кэша соседей (для сброса проблемных записей)
sudo ip -6 neigh flush dev eth0

# Мониторинг событий NDP в реальном времени
ip -6 monitor neigh

# Проверка конкретного соседа
ip -6 neigh show 2001:db8::1
```

Для активной проверки NDP используйте инструменты из пакета `ndisc6`:
```bash
# Ручной запрос MAC-адреса по IPv6 (Neighbor Solicitation)
ndisc6 2001:db8::1 eth0

# Ручной запрос с таймаутом (для тестирования firewall)
ndisc6 -1 2001:db8::1 eth0
# → Должен получить Advertisement

# Поиск маршрутизаторов в сети (Router Solicitation)
rdisc6 eth0

# Активный Router Solicitation с таймаутом
rdisc6 -1 eth0
```

### 3. Диагностика сокетов и портов (ss)

Для анализа того, какие сервисы слушают IPv6 и в каком состоянии находятся соединения:

```bash
# Просмотр всех TCP IPv6 сокетов в состоянии прослушивания
ss -6 -lnt

# Проверка установленных соединений с указанием процессов
sudo ss -6 -atp

# Все TCP/UDP сокеты (включая неслушающие)
ss -6 -t -a
ss -6 -u -a

# Внутренняя информация о соединениях (PMTUD, MSS, TCP info)
ss -6 -i

# Проверка конкретного порта
ss -6 -ant | grep :443
```

### 4. Глубокий анализ через системные счетчики

Счетчики в `/proc/net/snmp6` и `nstat` позволяют увидеть ошибки на уровне протокола (например, отброшенные пакеты из-за ошибок в заголовках).

```bash
# Просмотр статистики ошибок ICMPv6
cat /proc/net/snmp6 | grep -i icmp6

# Ищем специфические ошибки:
# Icmp6InErrors          -> ошибки во входящих ICMPv6
# Icmp6InMsgs            -> всего получено сообщений
# Icmp6InPktTooBigs      -> Packet Too Big (индикатор PMTUD проблем)
# Icmp6InNeighborSolicits -> входящие NS (базовый уровень)
# Icmp6InNeighborAdverts -> входящие NA

# Расширенная статистика через nstat (более подробная)
nstat -az | grep -E 'Icmp6|Icmp'
# или для IPv6-специфичных счетчиков:
nstat -az | grep -E 'Ip6|Icmp6'

# Мониторинг в реальном времени (каждые 1 сек, 60 раз)
nstat -az -y second -c 60 | grep -E 'Icmp6:'

# Просмотр сырых сокетных таблиц (для отладки conntrack/firewall)
cat /proc/net/tcp6
cat /proc/net/udp6

# Проверка состояния conntrack для IPv6
sudo conntrack -L -f ipv6
sudo conntrack -L -f ipv6 | grep -i drop
```

### 5. Глубокий анализ трафика (tcpdump)

Фильтрация по типам сообщений ICMPv6 позволяет быстро найти причину отказа SLAAC или NDP.

```bash
# Перехват только Neighbor Solicitation/Advertisement
sudo tcpdump -i eth0 -n "icmp6 && (ip6[40] == 135 || ip6[40] == 136)"

# Перехват Router Advertisements (RA)
sudo tcpdump -i eth0 -vvn "icmp6 && ip6[40] == 134"

# Перехват MLD (Multicast Listener Discovery)
sudo tcpdump -i eth0 -n "icmp6 && (ip6[40] == 130 || ip6[40] == 131 || ip6[40] == 132)"

# Перехват Packet Too Big (Type 2) — критично для PMTUD
sudo tcpdump -i eth0 'icmp6[0] == 2' -nn

# Весь трафик ICMPv6 (ошибки, пинги, NDP)
sudo tcpdump -i eth0 -n icmp6

# Перехват всего IPv6-трафика по EtherType
sudo tcpdump -i eth0 -n ether proto 0x86DD

# DAD-пробы (Neighbor Solicitation с src ::)
sudo tcpdump -ni eth0 'ip6 proto 58 && ip6[40] == 135 && ip6 src ::'

# Поиск ICMPv6 Redirect (потенциальный MITM)
sudo tcpdump -i eth0 -nn 'icmp6[0] == 137'
```

### 6. Мониторинг групп рассылки (MLD)

IPv6 сильно зависит от мультикаста. Если NDP или SLAAC не работают, проверьте членство в группах.

```bash
# Просмотр групп, в которых состоит интерфейс
ip -6 maddr show

# Просмотр групп для конкретного интерфейса
ip -6 maddr show dev eth0

# Проверка прохождения мультикаст-трафика (ping всех узлов сегмента)
ping6 -c 2 ff02::1%eth0

# Привязка ping к интерфейсу (для Link-Local)
ping6 -I eth0 -c 2 ff02::1%eth0
```

### 7. Маршрутизация и политики

```bash
# Просмотр IPv6-маршрутов
ip -6 route show

# Полная таблица маршрутов (включая кастомные таблицы)
ip -6 route show table all

# Поиск маршрута для конкретного адреса (FIB lookup)
ip -6 route get 2001:db8::1

# Просмотр политик маршрутизации (policy routing)
ip -6 rule show

# Просмотр меток адресов (адресные приоритеты)
ip -6 addrlabel show
```

### 8. Трассировка и Path MTU

```bash
# Трассировка с обнаружением MTU на пути
tracepath6 -n google.com

# Проверка PMTUD вручную (DF-бит аналог для IPv6)
# Указываем размер пейлоада 1432 (1500 MTU - 40 IPv6 header - 8 ICMPv6)
ping6 -M do -s 1432 2001:db8::1

# Проверка конкретного размера пакета
ping6 -s 1400 -c 3 2001:db8::1
```

## Таблица устранения неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Address family not supported` | IPv6 отключен в ядре или через GRUB | Проверить параметры загрузки и `sysctl` |
| Адрес висит в `tentative` | Проблема с ответом на DAD или петля L2 | Проверить `tcpdump`, исключить петли в коммутаторах |
| `Network is unreachable` | Нет маршрута по умолчанию (Default GW) | Проверить прием RA (`accept_ra`) или настройки статики |
| `Permission denied` | Блокировка в `nftables` / `ip6tables` | См. **[Firewall для IPv6](./firewall.md)** |
| Пинг проходит, TCP виснет | Проблема с **Path MTU** (PMTUD) | Проверить прохождение ICMPv6 Type 2. Уменьшить MTU или настроить MSS Clamping. |
| Адрес в статусе `dadfailed` | Конфликт IP в сети | Изменить статический IP или проверить настройки DHCPv6/SLAAC. |
| NDP в статусе `FAILED` / `INCOMPLETE` | Сосед не отвечает на NS, L2-проблема или firewall | Проверить физику, VLAN, `tcpdump icmp6`, убедиться что NDP не блокируется. |
| RA не приходят | `accept_ra=0`, RA Guard, блокировка multicast | `rdisc6 -1 eth0` (активный RS), проверить порт коммутатора (trusted для RA). |
| SLAAC не работает | `accept_ra=0`, `autoconf=0`, неверный префикс, multicast-блокировка | `rdisc6 eth0`, `sysctl net.ipv6.conf.all.accept_ra`, `ip -6 maddr show`. |
| `ping6` к Link-Local не работает | Отсутствует Scope ID (`%eth0`) | Всегда указывать интерфейс для `fe80::/10`. |
| ICMPv6 Packet Too Big не проходят | Блокировка Type 2 в файрволе | `tcpdump 'icmp6[0] == 2'`, настроить `nftables`/`ip6tables`. |
| `conntrack: table full, dropping packet` | Переполнение conntrack-таблицы | Увеличить `net.netfilter.nf_conntrack_max`, проверить `conntrack -L -f ipv6`. |
| Статическая запись теряется | GC удаляет запись, не хватает `gc_thresh3` | Увеличить `gc_thresh3` или использовать `nud permanent`. |
| `ndisc6` не получает Advertisement | NDP/ICMPv6 заблокирован файрволом | `tcpdump icmp6`, проверить `nft list ruleset | grep nd-neighbor`. |

## Дополнительная информация

### Лучшие практики

1. **Статические NDP для критичных хостов:** Шлюзы, DNS, базы данных — добавляйте через `sudo ip -6 neigh add ... nud permanent`, чтобы предотвратить потерю при GC.
2. **Мониторинг NDP:** Используйте `ip -6 monitor neigh` для отслеживания переходов состояний в production.
3. **Расширенная статистика:** `nstat -az | grep -E 'Icmp6|Icmp'` дает больше метрик, чем `/proc/net/snmp6`.
4. **ICMPv6 должен быть разрешен:** Полная блокировка ICMPv6 делает сеть неработоспособной (NDP, PMTUD, MLD).
5. **Privacy Extensions:** Включайте `use_tempaddr=2` на клиентских устройствах для защиты от трекинга.
6. **MSS Clamping для туннелей:** Настройте `tcp option maxseg size set 1400` для трафика через туннели с MTU < 1500.
7. **`accept_ra` на серверах:** Для статики используйте `accept_ra=0`. Для клиентов — `accept_ra=1`. `accept_ra=2` — только для маршрутизаторов.
8. **PMTUD testing:** Регулярно проверяйте прохождение ICMPv6 Type 2 через весь путь (включая hardware firewall и Security Groups).
9. **Link-Local scoping:** Всегда используйте `%iface` для `fe80::/10` в скриптах и командах.

### См. также

- **[Настройка адресов IPv6](./address_configuration.md)** — практические примеры настройки.
- **[Firewall для IPv6](./firewall.md)** — критические правила ICMPv6.
- **[ip neighbour](../../Tools/iproute2/ip_neighbour.md)** — подробное описание управления таблицей соседей.
- **[Мониторинг IPv6](./monitoring.md)** — Prometheus, Blackbox Exporter, alerting для IPv6.
