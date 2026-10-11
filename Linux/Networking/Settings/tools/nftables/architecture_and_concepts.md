# nftables — архитектура и основные концепции

**Актуально для:** nftables 1.0+ / Linux kernel 5.15+ (базовые функции: 3.13+, flowtables: 5.3+, bridge conntrack: 5.3+)

## Определения

**nftables** — современная подсистема ядра Linux для фильтрации и классификации сетевых пакетов, заменяющая классический стек `iptables`. Она основана на специализированной **виртуальной машине (VM)**, которая выполняет байт-код непосредственно в пространстве ядра. Это позволяет минимизировать объем кода в ядре и перенести логику парсинга протоколов в пространство пользователя.

**Netfilter** — низкоуровневый фреймворк ядра Linux, предоставляющий набор хуков (hooks) в сетевом стеке. nftables является основным инструментом управления этими хуками в современных системах.

**Netlink API** — протокол взаимодействия между утилитой `nft` и ядром. В nftables он используется для передачи **атомарных транзакций**: либо весь набор изменений применяется успешно, либо состояние системы не меняется вовсе.

**Байт-код nftables** — набор инструкций для VM (например, «загрузить данные из пакета в регистр», «сравнить регистр с константой», «установить вердикт»). Это делает nftables независимым от конкретных протоколов на уровне ядра.

**Регистровая виртуальная машина (Register-based VM)** — архитектура nftables, в которой пакет последовательно обрабатывается набором инструкций, оперирующих регистрами. Данные из заголовков пакетов, метаинформации или счетчиков загружаются в регистры, над ними выполняются сравнения/математические операции, и на их основе принимается вердикт.

**Выражения (Expressions)** — атомарные инструкции VM, которые либо извлекают данные (`payload`, `meta`, `ct`), либо выполняют действия (`drop`, `accept`, `limit`, `counter`). Правило — это упорядоченный список выражений.

**Вердикт (Verdict)** — окончательное решение о судьбе пакета: `accept`, `drop`, `reject`. Некоторые выражения (`jump`, `goto`, `return`) управляют потоком выполнения, но не являются вердиктами в строгом смысле.

**Stateful objects** — объекты ядра, сохраняющие состояние между пакетами: встроенные счетчики (`counter`), квоты (`quota`), лимиты частоты (`limit`), именованные лимиты (`limit` с именем).

**Именованные лимиты (named limits)** — объекты, определяемые внутри таблицы, которые позволяют задать лимит частоты или объема один раз и повторно использовать его в нескольких правилах через ссылку по имени.

**Flowtable** — технология Fastpath в ядре Linux, позволяющая передавать пакеты установленных соединений напрямую между сетевыми интерфейсами, минуя классический стек Netfilter. Это снижает задержки и нагрузку на CPU, делая nftables пригодным для роли маршрутизатора на скоростях 10Gbps+.

**Sets (Наборы)** — именованные структуры данных в ядре (обычно хэш-таблицы), содержащие элементы (IP, порты, интерфейсы). Поддерживают автоматическое истечение (`timeout`) и динамическое пополнение. Обеспечивают поиск за время O(1) вместо линейного перебора правил.

**Maps (Карты)** — структуры «ключ-значение», где ключ сопоставляется с одним или несколькими значениями. В nftables могут использоваться для динамического выбора вердикта, NAT-преобразования или модификации заголовков.

**Verdict Maps (Карты вердиктов)** — специализированный тип map, где значением является вердикт (`accept`, `drop`, `jump`, `goto`). Позволяют заменить цепочку из десятков правил одним выражением.

**Payload expressions** — выражения для доступа к полям заголовков пакетов (L2–L4) по смещению. Пример: `ip saddr`, `tcp dport`, `icmp type`.

**Meta expressions** — выражения для доступа к метаданным пакета, которые не являются частью заголовка: интерфейсы входа/выхода (`iifname`, `oifname`), метки (`mark`), длина пакета, группа PID/UID создателя.

**CT expressions** — выражения для работы с подсистемой отслеживания соединений (`conntrack`). Доступ к состоянию (`ct state`), исходному/целевому адресу после NAT (`ct original saddr`), меткам и таймаутам.

**RT expressions** — выражения для работы с маршрутной информацией ядра: исходный/целевой адрес после принятия решения о маршрутизации (`rt saddr`, `rt daddr`), выходной интерфейс (`oif`).

**FIB expressions** — выражения для прямого запроса к таблице маршрутизации FIB (Forwarding Information Base). Позволяют проверять, является ли адрес локальным (`fib saddr type local`), широковещательным или удаленным, без выполнения реальной маршрутизации.

**nftrace** — механизм трассировки пакетов в nftables, позволяющий помечать пакеты для последующего анализа через `nft monitor trace`.

**notrack** — выражение, отключающее отслеживание соединения в conntrack для конкретного пакета. Используется для снижения нагрузки на таблицу conntrack при обработке высоконагруженного трафика, не требующего stateful-анализа (например, DNS-запросы к кэширующему серверу).

## Архитектура nftables

### Жизненный цикл пакета (Packet Path)

Пакет проходит через nftables в строго определенной последовательности, определяемой семейством таблицы и хуком:

1.  **Получение кадра (L2)** — для семейства `netdev` на хуке `ingress` или `egress`.
2.  **DSP (Decapsulation/Processing)** — удаление/добавление канальных заголовков.
3.  **Prerouting** — обработка до принятия решения о маршрутизации. Здесь работает NAT назначения (`dstnat`) и магия `raw`/`mangle`.
4.  **Маршрутизация (Routing decision)** — ядро выбирает выходной интерфейс.
5.  **Input / Forward / Output** — в зависимости от адресата пакета.
6.  **Postrouting** — обработка после маршрутизации, перед отправкой. Здесь работает NAT источника (`srcnat`).
7.  **Передача кадра (L2)** — инкапсуляция и отправка.

**Важно для DevOps/SRE:** Порядок обработки внутри одного хука определяется **приоритетом** (числовым значением) и **порядком следования цепочек** с одинаковым приоритетом. Пакет проходит через все цепочки хука, если не встретит вердикт `drop` или `accept`.

### Регистровая виртуальная машина

Вместо жестко зашитых в ядро модулей (как в `iptables`), nftables использует универсальную VM:

- **Регистры:** 16 регистров по 128 бит каждый. В них загружаются любые данные: IP-адреса, порты, метки, счетчики.
- **Инструкции:** каждая инструкция атомарна. Примеры: `load` (загрузка из payload в регистр), `cmp` (сравнение), `imm` (загрузка константы), `set` (запись в регистр), ` verdict` (вынесение решения).
- **Выполнение:** VM интерпретирует байт-код. JIT-компилятор (если доступен в ядре) преобразует байт-код в нативный машинный для ускорения.
- **Преимущество:** добавление нового поля протокола (например, нового типа IPv6-заголовка) не требует изменения ядра — достаточно обновить утилиту `nft`, которая сгенерирует правильный байт-код.

### Выражения (Expressions)

Все выражения делятся на категории:

| Категория | Описание | Примеры полей |
| :--- | :--- | :--- |
| **Payload** | Данные из заголовков пакетов (L2–L4) | `ether saddr`, `ip saddr`, `tcp dport`, `udp sport`, `icmp type` |
| **Meta** | Метаданные пакета, не входящие в заголовок | `iifname`, `oifname`, `mark`, `len`, `nfproto`, `protocol` |
| **CT (Conntrack)** | Состояние и атрибуты отслеживаемого соединения | `ct state`, `ct original saddr`, `ct mark`, `ct helper` |
| **RT (Routing)** | Информация о принятом решении маршрутизации | `rt saddr`, `rt daddr`, `oif`, `nexthop` |
| **FIB** | Прямой запрос к таблице маршрутизации FIB | `fib saddr type local`, `fib daddr iif lo` |
| **Rate limit / Quota** | Ограничение частоты и объема | `limit rate 10/second`, `quota over 100 mbytes` |
| **Counter** | Встроенный счетчик пакетов/байт | `counter` |
| **Notrack** | Отключение отслеживания соединения | `notrack` |
| **Log** | Логирование в journald | `log prefix "DROP: "` |

### Действия (Verdicts и управление потоком)

| Действие | Описание |
| :--- | :--- |
| `accept` | Разрешить прохождение пакета. Прекращает обработку в текущей таблице. |
| `drop` | Молча отбросить пакет. |
| `reject` | Отклонить пакет с отправкой уведомления (ICMP-сообщения). |
| `log` | Записать информацию о пакет в системный журнал. |
| `nftrace set 1` | Пометить пакет для трассировки (позволяет увидеть путь через цепочки). |
| `notrack` | Отключить отслеживание соединения в conntrack. |
| `jump <chain>` | Перейти в указанную цепочку и вернуться после её обработки. |
| `goto <chain>` | Перейти в указанную цепочку без возврата. |
| `return` | Вернуться из текущей цепочки в вызывающую (при `jump`). |

### Stateful objects

Объекты, которые создаются внутри таблицы и переиспользуются в правилах:

| Объект | Описание | Пример использования |
| :--- | :--- | :--- |
| `counter` | Встроенный счетчик пакетов и байт. | `counter packets 1542 bytes 98720` |
| `quota` | Ограничение общего объема трафика. | `quota over 100 mbytes drop` |
| `limit` | Ограничение частоты событий. | `limit rate 10/second burst 20 packets accept` |
| `limit` (named) | Именованный лимит, определяемый в таблице и используемый по ссылке в нескольких правилах. | `limit name ssh_limit 400/minute` в правиле: `tcp dport 22 limit name ssh_limit accept` |

### Именованные лимиты (Named Limits)

В nftables можно определять лимиты как именованные объекты внутри таблицы, а затем ссылаться на них в правилах по имени. Это позволяет повторно использовать одну и ту же политику ограничения частоты в нескольких правилах и изменять её в одном месте.

```bash
table inet filter {
    # Определение именованных лимитов
    limit ssh_limit {
        type packet
        rate 400 / minute
    }

    limit http_limit {
        type byte
        rate 1024 / second
        burst 2048
    }

    chain input {
        type filter hook input priority filter; policy drop;
        ct state established,related accept
        iif lo accept

        # Использование именованного лимита
        tcp dport 22 ct state new limit name ssh_limit accept
        tcp dport { 80, 443 } limit name http_limit accept

        drop
    }
}
```

**Преимущества:**
- Единое место управления политикой ограничения.
- Возможность применять одинаковый лимит к нескольким правилам без дублирования выражений `limit rate`.
- Поддержка комментариев к лимитам для документации.

### Наборы, карты и карты вердиктов

**Sets (Наборы):**
```bash
# Создание набора IPv4-адресов
set trusted_hosts {
    type ipv4_addr
    elements = { 192.168.1.0/24, 10.0.0.0/8 }
}
# Использование в правиле
ip saddr $trusted_hosts accept
```

**Dynamic sets с таймаутом (для блокировки брутфорса):**
```bash
set ssh_bruteforce {
    type ipv4_addr
    timeout 1h
}
tcp dport 22 ct state new update @ssh_bruteforce { ip saddr }
ip saddr @ssh_bruteforce drop
```

**Maps (Карты):**
```bash
# Карта: порт → вердикт
map port_policy {
    type inet_proto . inet_service : verdict
    elements = { tcp . 22 : accept, tcp . 80 : accept, udp . 53 : accept }
}
ip protocol . tcp dport @port_policy
```

**Verdict Maps (Карты вердиктов):**
```bash
# Карта вердиктов: IP-адрес → действие
map blackhole {
    type ipv4_addr : verdict
    elements = { 203.0.113.0/24 : drop }
}
ip daddr @blackhole
```

**Concatenations (Конкатенации):**
Позволяют использовать составные ключи (например, `ip saddr . tcp dport`) для маппинга на действие.

### Flowtables (Fastpath)

Flowtables позволяют обойти классический стек Netfilter для established-соединений:

```bash
table inet filter {
    flowtable ft_main {
        hook ingress priority 0; devices = { eth0, eth1 }
    }

    chain forward {
        type filter hook forward priority filter; policy accept;
        ip protocol tcp ct state established,related flow offload @ft_main
    }
}
```

**Когда использовать:**
- Маршрутизаторы и шлюзы с пропускной способностью >1 Gbps.
- Большое количество коротких TCP-соединений (HTTP-балансировщики, прокси).
- Системы, где задержки (latency) критичны.

**Ограничения:**
- Поддерживается только начиная с ядра 5.3+.
- Не работает с некоторыми выражениями (`log`, `quota`, `counter` внутри flowtable).
- Требует явного указания устройств (`devices = { eth0 }`).

### Семейства таблиц (Address Families)

| Семейство | Уровень OSI | Описание |
| :--- | :--- | :--- |
| **`inet`** | L3 (IPv4/v6) | Универсальное семейство для обработки обоих протоколов. Рекомендуется как стандарт. |
| **`ip`** / **`ip6`** | L3 | Специфичные таблицы для IPv4 или IPv6. |
| **`arp`** | L2/L3 | Фильтрация ARP-трафика. |
| **`bridge`** | L2 | Обработка кадров, проходящих через Linux Bridge. |
| **`netdev`** | L1/L2 | Работает на уровне сетевого драйвера. Поддерживает хуки `ingress` и `egress`. |

### Хуки (Hooks) и приоритеты

Приоритет определяет очередность обработки цепочек с одним и тем же хуком. Меньшее число означает более раннюю обработку.

| Семейство | Хук (Hook) | Описание | Приоритеты (стандартные) |
| :--- | :--- | :--- | :--- |
| `netdev` | `ingress` | Самая ранняя точка после получения кадра. | `filter` (0) |
| `ip/inet` | `prerouting` | До принятия решения о маршрутизации. | `raw` (-300), `mangle` (-150), `dstnat` (-100) |
| `ip/inet` | `input` | Пакет предназначен локальному хосту. | `filter` (0), `security` (50) |
| `ip/inet` | `forward` | Пакет проходит транзитом через хост. | `filter` (0) |
| `ip/inet` | `output` | Пакет создан локальным процессом. | `mangle` (-150), `filter` (0) |
| `ip/inet` | `postrouting` | После маршрутизации, перед отправкой. | `mangle` (-150), `srcnat` (100) |

### Основные действия (Verdicts)

| Действие | Описание |
| :--- | :--- |
| `accept` | Разрешить прохождение пакета. Прекращает обработку в текущей таблице. |
| `drop` | Молча отбросить пакет. |
| `reject` | Отклонить пакет с отправкой уведомления (ICMP-сообщения). |
| `log` | Записать информацию о пакете в системный журнал. |
| `jump <chain>` | Перейти в указанную цепочку и вернуться после её обработки. |
| `goto <chain>` | Перейти в указанную цепочку без возврата. |

## Основные концепции

### Ключевые архитектурные преимущества

- **Атомарность транзакций:** Обновление правил не приводит к кратковременным разрывам или неопределенным состояниям. Все изменения (добавление таблиц, удаление цепочек, вставка правил) выполняются как единая операция.
- **Регистровая виртуальная машина:** VM nftables оперирует набором регистров, в которые можно загружать любые данные из заголовков пакетов или метаданных (интерфейсы, метки).
- **Производительность O(1):** Использование именованных наборов (Sets) и карт (Maps) позволяет выполнять поиск по тысячам элементов (IP-адреса, порты) за константное время, в то время как `iptables` выполнял линейный перебор.
- **Унификация семейств:** Семейство `inet` позволяет писать общие правила для IPv4 и IPv6, избавляя от необходимости дублировать конфигурацию в `iptables` и `ip6tables`.
- **Flowtables (Fastpath):** Позволяет перенаправлять пакеты установленных соединений сразу после L2/L3 уровня, минуя классический стек Netfilter. Это критично для производительности маршрутизаторов и сопоставимо с аппаратным ускорением.

### Архитектурные компоненты

| Компонент | Описание |
| :--- | :--- |
| **Таблицы (tables)** | Контейнеры верхнего уровня. Не имеют предопределенного смысла, служат для группировки цепочек. |
| **Цепочки (chains)** | **Базовые** (Base chains) привязаны к хукам ядра. **Обычные** используются как подпрограммы (`jump`). |
| **Правила (rules)** | Набор выражений, выполняемых VM последовательно. |
| **Выражения (expressions)** | Инструкции для VM: селекторы данных (payload, meta, ct) и действия (verdicts). |
| **Состояния (Stateful objects)** | Объекты, сохраняющие состояние между пакетами: счетчики (`counter`), квоты, лимиты. |
| **Хэндлы (handles)** | Внутренние индексы правил, которые остаются неизменными при добавлении других правил в ту же цепочку. |

### Переменные и модульность

В отличие от `iptables`, nftables поддерживает нативные переменные и включение файлов, что позволяет строить иерархические конфигурации.

**Использование переменных (`define`):**
```bash
define ext_if = "eth0"
define trusted_hosts = { 192.168.1.10, 192.168.1.20 }

# Использование в правилах
nft add rule inet filter input iifname $ext_if ip saddr $trusted_hosts accept
```

**Включение файлов (`include`):**
```bash
# /etc/nftables.conf
include "/etc/nftables/vars.nft"
include "/etc/nftables/sets.nft"

table inet filter {
    include "/etc/nftables/input_chain.nft"
}
```

### Инструменты управления (CLI)

Утилита `nft` является единой точкой управления всеми семействами протоколов.

| Команда | Описание |
| :--- | :--- |
| `nft list ruleset` | Вывод всех текущих правил и таблиц |
| `nft list ruleset -a` | Вывод с хэндлами (уникальными идентификаторами правил) |
| `nft list ruleset -s` | Вывод в **stateless** формате (без счетчиков) — готовый к сохранению конфиг |
| `nft flush ruleset` | Полная очистка текущей конфигурации в памяти |
| `nft -c -f <файл>` | Проверка синтаксиса конфигурационного файла без применения |
| `nft -j list ruleset` | Экспорт конфигурации в формате **JSON** |
| `nft describe <объект>` | Получение подробной справки о полях и типах данных объекта |
| `nft monitor trace` | Просмотр трассировки помеченных пакетов |
| `nft monitor` | Отслеживание событий добавления/удаления правил в реальном времени |
| `nft list set <family> <table> <set> -s` | Вывод только определения набора без элементов. Ускоряет вывод для больших наборов и предотвращает падение по памяти (OOM). |
| `nft list ruleset > /etc/nftables.conf` | Экспорт текущей конфигурации в файл, который можно использовать как декларативный конфиг для `nft -f`. |

**Примечания по CLI:**
- Флаг `-s`/`--stateless` для `nft list ruleset` и `nft list set` выводит конфигурацию без значений счетчиков — именно этот формат предназначен для сохранения в `/etc/nftables.conf`.
- Флаг `-s`/`--stateless` для `nft list set` полезен при работе с наборами, содержащими тысячи элементов: вывод без элементов занимает существенно меньше памяти и времени.
- Выход `nft list ruleset` является валидным nftables-скриптом — его можно сохранить в `/etc/nftables.conf` и использовать для персистентности или восстановления конфигурации.
- Интерактивная консоль: `nft -i` позволяет работать без префикса `nft` перед каждой командой.

### Архитектурные различия бэкендов iptables

В современных дистрибутивах `iptables` может быть либо legacy-бинарником, работающим напрямую с Netfilter, либо shim-обёрткой над nftables. Это критически важно при миграции, так как правила, добавленные через `iptables-nft`, сосуществуют с нативными nftables-таблицами.

| Бэкенд | Путь | Характеристики |
| :--- | :--- | :--- |
| `iptables-legacy` | `/sbin/iptables-legacy` | Работает напрямую с Netfilter; несовместим с nftables. |
| `iptables-nft` | `/sbin/iptables-nft` | Транслирует в байт-код nftables; правила видны в `nft list ruleset`. |
| `nft` (native) | `/sbin/nft` | Нативный инструмент; атомарные транзакции через Netlink. |

**Определение активного бэкенда:**
```bash
update-alternatives --display iptables
# → iptables - auto mode
# →   link best version is /usr/sbin/iptables-nft
# →   link currently points to /usr/sbin/iptables-nft
```

### Инструменты миграции: iptables-translate

Для перевода правил из синтаксиса `iptables` в `nftables` используются утилиты из пакета `iptables-nft`:

| Утилита | Назначение |
| :--- | :--- |
| `iptables-translate` | Перевод одного правила из синтаксиса iptables в nftables |
| `ip6tables-translate` | То же для IPv6 |
| `iptables-restore-translate` | Перевод всего набора правил из формата `iptables-save` |
| `ip6tables-restore-translate` | То же для IPv6 |
| `iptables-translate -f <файл>` | Перевод правил из файла |

**Примеры:**
```bash
# Перевод одного правила
iptables-translate -A INPUT -p tcp --dport 22 -j ACCEPT
# → nft add rule ip filter INPUT tcp dport 22 accept

# Перевод всего набора (iptables-save формат)
iptables-save | iptables-restore-translate > /etc/nftables.conf
```

**Важные нюансы совместимости:**
- При использовании `iptables-nft` (режим совместимости) таблицы и цепочки создаются с именами, ожидаемыми iptables (`filter`, `INPUT`, `FORWARD`, `OUTPUT`).
- Если одновременно существуют нативные nftables-таблицы и таблицы, созданные через `iptables-nft`, на одном хуке могут возникнуть **конфликты приоритетов** (например, две цепочки `input` с приоритетом 0). nftables выводит предупреждение: `table has incompatible base chains`.
- Docker и другие инструменты, использующие iptables, будут создавать правила в таблицах `iptables-nft`, которые видны в `nft list ruleset`.
- **Рекомендация:** для новых развёртываний используйте нативный nftables синтаксис и семейство `inet`. При миграции либо полностью переведите конфигурацию на nftables, либо используйте только `iptables-nft` без смешивания с нативными таблицами.

## Практические сценарии

### Предварительные требования

#### Аппаратные требования

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| ** NIC** | 1 порт | 2+ порта для маршрутизации/NAT |
| ** CPU** | 2 ядра | 4+ ядер при нагрузке >1Gbps |
| ** RAM** | 512 MB | 2 GB+ для больших таблиц conntrack |

#### Программные требования

| Компонент | Версия / Требование |
| :--- | :--- |
| **Ядро Linux** | 5.3+ (нативный `bridge` conntrack), 5.15+ рекомендуется |
| **nftables** | 1.0.0+ |
| **iproute2** | 5.x+ |
| **conntrack-tools** | для диагностики (`conntrack`, `conntrackd`) |
| **Права** | root (sudo) |
| **Служба** | `nftables` (systemd) для персистентности |

#### Проверка окружения

```bash
# Версия ядра
uname -r
# → 5.15.0-78-generic

# Наличие nftables
which nft && nft --version
# → nft v1.0.9

# Проверка загруженных модулей ядра
lsmod | grep -E 'nf_conntrack|nf_defrag_ipv4|nf_nat'
# → nf_conntrack          163840  1 bridge
# → nf_nat                245760  1 nf_conntrack

# Размер таблицы conntrack
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144
```

### Синтаксис командной строки `nft`

Команды в nftables выполняются атомарно. Основной формат:
`nft <команда> <объект> <семейство> <таблица> <цепочка> <параметры>`

**Ключевые команды управления:**

```bash
# Создание таблицы
nft add table inet my_firewall

# Создание базовой цепочки (обязательно указывать hook и priority)
nft add chain inet my_firewall my_input { type filter hook input priority 0 \; policy drop \; }

# Вывод всей активной конфигурации
nft list ruleset
# → table inet my_firewall {
# →     chain my_input {
# →         type filter hook input priority filter; policy drop;
# →     }
# → }

# Очистка всех правил в памяти ядра
nft flush ruleset
```

### Работа с правилами и хэндлами

Каждое правило имеет уникальный идентификатор (handle), который необходим для удаления или вставки правил в конкретное место. В отличие от `iptables`, где правила нумеруются последовательно (1, 2, 3...), в nftables хэндлы **стабильны**: при удалении правила его хэндл не переиспользуется, а новые правила получают новые уникальные хэндлы. Это предотвращает случайное удаление не того правила при повторных операциях.

**Приоритеты цепочек:** Можно указывать как числовые значения, так и текстовые алиасы (например, `filter` = 0, `mangle` = -150, `dstnat` = -100, `srcnat` = 100). Текстовые алиасы повышают читаемость конфигурации. Для просмотра числовых значений используйте флаг `--numeric-priority` (или `-n`).

```bash
# Добавление правила
nft add rule inet my_firewall my_input tcp dport 22 accept

# Просмотр конфигурации с хэндлами
nft -a list ruleset
# → ... tcp dport 22 accept # handle 5

# Удаление правила по хэндлу
nft delete rule inet my_firewall my_input handle 5

# Вставка правила перед существующим (position = хэндл целевого правила)
nft insert rule inet my_firewall my_input position 6 tcp dport 80 accept

# Замена правила (handle сохраняется)
nft replace rule inet my_firewall my_input handle 4 tcp dport 8443 accept
```

**Важно:** Параметр `position` в командах `insert`/`add` принимает **хэндл**, а не порядковый номер правила. Это ключевое отличие от `iptables`.

### Базовый stateful-файрвол (инвентаризация для DevOps)

```bash
#!/usr/sbin/nft -f
# /etc/nftables.conf — базовая конфигурация

flush ruleset

table inet filter {
    # === INPUT chain ===
    chain input {
        type filter hook input priority filter; policy drop;
        ct state established,related accept
        ct state invalid drop
        iif lo accept
        ip protocol icmp icmp type echo-request limit rate 1/second accept
        tcp dport 22 accept
        drop
    }

    # === FORWARD chain ===
    chain forward {
        type filter hook forward priority filter; policy drop;
        ct state established,related accept
        ip saddr 192.168.1.0/24 oif eth1 accept
        drop
    }

    # === OUTPUT chain ===
    chain output {
        type filter hook output priority filter; policy accept;
    }
}
```

**Примечание:** Для production-сценариев с NAT, защитой от DoS, балансировкой и интеграцией с Docker используйте готовые шаблоны в **[nftables — практические сценарии](./practical_scenarios.md)**.

### Использование sets, maps и verdict maps

```bash
table inet filter {
    set trusted_hosts {
        type ipv4_addr
        elements = { 192.168.1.0/24, 10.0.0.0/8 }
    }

    set ssh_bruteforce {
        type ipv4_addr
        timeout 1h
    }

    map port_whitelist {
        type inet_service : verdict
        elements = { 22 : accept, 80 : accept, 443 : accept }
    }

    chain input {
        type filter hook input priority filter; policy drop;
        ct state established,related accept
        ip saddr $trusted_hosts accept
        tcp dport @port_whitelist
        tcp dport 22 ct state new update @ssh_bruteforce { ip saddr }
        ip saddr @ssh_bruteforce drop
        drop
    }
}
```

### Verdict Maps (vmap) для conntrack state

В nftables можно использовать **verdict maps (vmap)** для компактного описания действий на основе состояния соединения (`ct state`). Это позволяет заменить несколько правил одним выражением:

```bash
# Вместо трёх правил:
# ct state established,related accept
# ct state invalid drop
# ct state new accept

# Одно правило с vmap:
ct state vmap { established: accept, related: accept, invalid: drop, new: accept }
```

**Преимущества vmap:**
- Атомарность: все состояния обрабатываются в одном проходе VM.
- Читаемость: политика по состоянию соединения видна в одном месте.
- Производительность: один lookup вместо последовательной проверки нескольких правил.

### Использование flowtables

```bash
table inet filter {
    flowtable ft_ssh {
        hook ingress priority 0; devices = { eth0 }
    }

    chain forward {
        type filter hook forward priority filter; policy accept;
        ip protocol tcp ct state established,related flow offload @ft_ssh
    }
}
```

### Модульная конфигурация

```bash
# /etc/nftables.conf
#!/usr/sbin/nft -f

define ext_if = "eth0"
define lan_if = "eth1"

include "/etc/nftables/vars.nft"
include "/etc/nftables/sets.nft"

table inet filter {
    include "/etc/nftables/input_chain.nft"
    include "/etc/nftables/forward_chain.nft"
}
```

### Отладка и мониторинг

**Включение трассировки для конкретного правила:**
```bash
nft add rule inet filter input ip saddr 192.168.1.100 meta nftrace set 1
nft monitor trace
```

**Просмотр встроенных счетчиков:**
```bash
nft list ruleset -a
# → tcp dport 22 accept # handle 5 packets 1542 bytes 98720
```

**Мониторинг событий в реальном времени:**
```bash
nft monitor
# → add table inet filter
# → add chain inet filter input { ... }
```

### Персистентность через systemd

```bash
# Включение и запуск службы (Debian/Ubuntu/RHEL 9+)
systemctl enable --now nftables

# Проверка статуса
systemctl status nftables

# Применение конфигурации
nft -f /etc/nftables.conf
```

### Валидация конфигурации

```bash
# Проверка синтаксиса без применения
nft -c -f /etc/nftables.conf
# → (нет вывода — ошибок нет)

# Экспорт текущей конфигурации в JSON для аудита
nft -j list ruleset > /tmp/nftables_export.json
```

### Диагностика типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `nf_conntrack: table full` | Таблица conntrack переполнена | `sysctl -w net.netfilter.nf_conntrack_max=262144` |
| Пакеты не логируются | В ядре отключен netfilter logging | `dmesg \| grep -i nf`; проверьте `log` выражение |
| Правила не применяются | Ошибка синтаксиса в середине файла | `nft -c -f <файл>` для проверки |
| `iperf3` показывает 0 Mbps | Flowtable отбросил не-offload-able трафик | Уберите `flow offload` для TCP/UDP портов, не являющихся established |
| Docker bypass | Правила INPUT не затрагивают docker-интерфейс | Используйте семейство `inet` и проверьте `bridge-nf-call-iptables` |
| Время ожидания SSH при миграции | Правило `ct state invalid drop` отбрасывает первый пакет | Временно добавьте `accept` для SSH перед отладкой |
| `nft list ruleset` пустой | Неактивный бэкенд iptables (iptables-legacy) | Проверьте `update-alternatives --display iptables` |
| Утечка памяти в nft_monitor | Слишком частые изменения правил в production | Используйте атомарные загрузки через `nft -f`, а не инкрементальные `add rule` |

### Краевые случаи и ограничения

1.  **Атомарность:** При загрузке конфигурации через `nft -f` ошибка в середине файла не применяет ни одно изменение. Это защита, но требует тщательного тестирования перед деплоем.
2.  **IPv6 и ICMPv6:** Без разрешения ICMPv6 (Neighbor Discovery, Packet Too Big) работа IPv6 нарушается. Не блокируйте весь ICMPv6 без анализа.
3.  **Логирование `full`:** Выводит полный payload пакета в лог. На производительности сказывается сильно — используйте только для отладки на отдельных правилах.
4.  **Rate limit:** Применяется к самому выражению, а не к цепочке. Если нужно ограничить всю цепочку, используйте `limit` в каждом правиле или метер (`meter`).
5.  **Conntrack и NAT:** При изменении NAT-таблиц (`nat` family) conntrack не всегда корректно обновляет старые соединения. После изменения NAT-правил может потребоваться сброс conntrack: `conntrack -F`.
6.  **Notrack:** Использование `notrack` для всего трафика отключает stateful-инспекцию. Используйте только для защищенных сегментов или UDP-сервисов, не требующих отслеживания.
7.  **Flowtables и NAT:** Flowtables не поддерживают NAT. Для маршрутизаторов с NAT используйте классические цепочки.
8.  **Hairpin (NAT loopback):** Для доступа к сервису по внешнему IP из внутренней сети требуется дополнительная маршрутизация (`hairpin_nat`). В nftables реализуется через двойной NAT (`dnat` + `snat`) или через `redirect`.
9.  **MTU и фрагментация:** При изменении MTU на интерфейсе (например, для IPsec) убедитесь, что nftables не фрагментирует пакеты, нарушая MSS. Используйте `tcpmss` clamp в `mangle` таблице.
10. **Асимметричная маршрутизация:** При разном пути входа и выхода `conntrack` может терять пакеты. Используйте `notrack` или отключите conntrack для таких маршрутов.
11. **ALG helpers:** Некоторые приложения (FTP, SIP, H.323) требуют ALG (Application Layer Gateway) helpers в conntrack. В nftables управление через `ct helper` и `ct helper set`.
12. **Устаревшие модули:** Модули `nf_conntrack_amanda`, `nf_conntrack_ftp` и другие ALG могут быть собраны как модули или встроены в ядро. Проверьте `lsmod | grep conntrack`.
13. **Совместное использование бэкендов:** `iptables-nft` и `nft` (native) могут сосуществовать, но создавая таблицы в одном семействе, они могут конфликтовать. Используйте разные семейства или имена таблиц для изоляции.
14. **Статическая компиляция ядра:** Если nftables собран статически в ядре, модули `nf_tables` и `nf_conntrack` недоступны для выгрузки. Проверьте `grep NFTABLES /boot/config-$(uname -r)`.
15. **Производительность больших sets:** При количестве элементов >100k в `ip` семействе может наблюдаться фрагментация памяти. Используйте `type ipv4_addr . inet_service` для конкатенации или разделите на несколько сетов.

### Best Practices

1.  **Принцип Default Deny:** Устанавливайте политику `drop` для всех базовых цепочек (`input`, `forward`, `output`). Разрешайте явно.
2.  **Stateful Inspection на первом месте:** Размещайте `ct state established,related accept` в верхней части цепочки для минимизации нагрузки.
3.  **Используйте `inet` вместо дублирования `ip`/`ip6`:** Единая таблица `inet` упрощает поддержку и исключает рассинхронизацию правил.
4.  **Sets вместо больших списков:** Для >10 элементов используйте `set` или `map`. Это ускоряет обработку и упрощает обновление.
5.  **Атомарные загрузки:** Все изменения применяйте через `nft -f <файл>`, а не через отдельные `add rule` в production. Это исключает промежуточные неконсистентные состояния.
6.  **Именование:** Используйте осмысленные имена таблиц и цепочек: `inet filter`, `inet nat`, `bridge filter`. Избегайте generic-имен (`table1`, `chain_a`).
7.  **Логирование:** Логируйте только `drop` и аномалии (`invalid`). Избегайте логирования всего трафика (`log` на каждом правиле) — это создает огромные логи и нагрузку.
8.  **Персистентность:** Храните конфигурацию в `/etc/nftables.conf` и используйте systemd-службу `nftables`. Не полагайтесь на ручные `nft add rule` после reboot.
9.  **Версионирование:** Храните `nftables.conf` в git. Любые изменения проходят через code review.
10. **Ограничение conntrack:** Настройте `nf_conntrack_max`, `nf_conntrack_tcp_timeout_established` и другие параметры в `/etc/sysctl.d/99-nftables.conf` под нагрузку.
11. **Bogon filtering:** Блокируйте спуфинг-адреса (`0.0.0.0/8`, `127.0.0.0/8`, `224.0.0.0/3`) на внешних интерфейсах.
12. **Отключение ненужных helpers:** Удалите неиспользуемые ALG helpers (`conntrack -L` и `conntrack -D`).
13. **Тестирование:** Используйте `nft -c` и `nft monitor trace` перед деплоем. Проверяйте правила сканерами (`nmap`, `ss`).
14. **Изоляция broute vs filter:** Для Linux Bridge используйте семейство `bridge` для L2-фильтрации и `broute` для transparent-маршрутизации.
15. **Backup:** Экспортируйте текущие правила (`nft list ruleset > /root/nftables_backup_$(date +%F).nft`) перед каждым изменением.

### Очистка окружения

**Полное удаление nftables и возврат к iptables-legacy:**
```bash
# Остановка службы
systemctl stop nftables
systemctl disable nftables

# Очистка правил
nft flush ruleset

# Удаление правил iptables-nft (если активен)
iptables-nft -F
iptables-nft -X
ip6tables-nft -F
ip6tables-nft -X

# Переключение на iptables-legacy
update-alternatives --set iptables /usr/sbin/iptables-legacy
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy

# Удаление пакета (Debian/Ubuntu)
apt remove nftables

# Удаление пакета (RHEL/Fedora)
dnf remove nftables
```

## Дополнительная информация

### Важные замечания по эксплуатации

1.  **Чистый лист:** В отличие от `iptables`, nftables не имеет встроенных таблиц. Если вы не создали таблицу и цепочку для хука `input`, трафик будет проходить без ограничений.
2.  **Атомарные обновления:** Использование `nft -f <файл>` гарантирует, что правила будут применены либо все, либо ни одно. Это исключает ситуацию «заблокировал сам себя», если в середине файла была ошибка.
3.  **Приоритеты цепочек:** Если на одном хуке (например, `input`) висят две базовые цепочки с разными приоритетами, первой сработает та, у которой число меньше (например, -100 перед 0). Пакет проходит через ВСЕ цепочки хука, если только не встретит вердикт `drop`.
4.  **Сравнение с eBPF:** В то время как eBPF предоставляет максимальную гибкость, nftables оптимизирован специально для сетевой классификации и проще в управлении через декларативный синтаксис.
5.  **Сосуществование с Docker:** Docker автоматически добавляет правила в iptables/nftables для публикации портов. При использовании `iptables-nft` или `nft` эти правила видны в `nft list ruleset`. Для предотвращения bypass используйте семейство `inet` и проверяйте, что политика `FORWARD` не `accept` по умолчанию. Детали — в **[Docker — сеть](../../../../../Docker/Docker_network/docker_network.md)**.
6.  **Совместная работа с iptables-legacy:** Если система одновременно использует `iptables-legacy` и `nft`, правила из разных бэкендов не пересекаются. Убедитесь, что для одного семейства (`ip`) активен только один бэкенд.
7.  **Производительность JSON-экспорта:** `nft -j list ruleset` может быть медленным на конфигурациях с >10k правил. Используйте его только для аудита, а не в production-скриптах.

### DNS-over-HTTPS (DoH) и DNS-over-TLS (DoT) — фильтрация

Современные клиенты всё чаще используют шифрованные DNS-протоколы, что делает невозможной фильтрацию DNS-запросов по содержимому на уровне файрвола.

**Характеристики:**

| Протокол | Порт | Шифрование | Фильтрация в nftables |
|:---|:---|:---|:---|
| **DNS (обычный)** | 53 UDP/TCP | Нет | Полная (по домену, типу) |
| **DoT (DNS-over-TLS)** | 853 TCP | TLS 1.3 | Только по IP назначения |
| **DoH (DNS-over-HTTPS)** | 443 TCP | HTTPS (TLS) | Невозможна (маскируется под HTTPS) |

**Подходы к фильтрации:**

1. **Блокировка порта 853** — запрещает DoT, но не DoH:
```bash
table inet filter {
    chain output {
        type filter hook output priority 0; policy accept;

        # Блокировка DoT
        tcp dport 853 drop
    }
}
```

2. **Блокировка Known DoH-провайдеров по IP** — требует обновления sets:
```bash
table inet filter {
    set doh_providers {
        type ipv4_addr
        flags interval
        elements = {
            1.1.1.1,    # Cloudflare
            8.8.8.8,    # Google
            9.9.9.9     # Quad9
        }
    }

    chain output {
        type filter hook output priority 0; policy accept;

        # Блокировка DoH по IP (но не HTTPS в целом)
        ip daddr @doh_providers tcp dport 443 drop
    }
}
```

3. **Permissive-подход** — разрешить DoH только доверенным резолверам:
```bash
table inet filter {
    set trusted_doh {
        type ipv4_addr
        elements = { 10.0.0.53 }  # Корпоративный DoH-сервер
    }

    chain output {
        type filter hook output priority 0; policy drop;

        # Разрешить только доверенный DoH
        ip daddr @trusted_doh tcp dport 443 accept

        # Разрешить обычный DNS
        udp dport 53 accept
        tcp dport 53 accept
    }
}
```

**Рекомендация:** В корпоративных сетях настройте внутренний DoH-резолвер и блокируйте внешние DoH-провайдеры. Для публичных серверов фильтрация DoH невозможна без TLS inspection (MITM).

### VRF (Virtual Routing and Forwarding) и nftables

VRF — механизм изоляции таблиц маршрутизации в Linux, позволяющий одному хосту работать с несколькими независимыми сетевыми стеками. Каждый VRF имеет собственные интерфейсы, таблицы маршрутизации и параметры ядра.

**Архитектура:**

```
┌─────────────────────────────────────────┐
│              Linux Host                  │
│  ┌──────────────┐  ┌──────────────┐     │
│  │   VRF red    │  │   VRF blue   │     │
│  │  (table 10)  │  │  (table 20)  │     │
│  │  eth0, eth1  │  │  eth2, eth3  │     │
│  │  nftables:   │  │  nftables:   │     │
│  │  table vrf_red│  │  table vrf_blue│   │
│  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────┘
```

**Фильтрация VRF через nftables:**

```bash
# Привязка интерфейса к VRF
ip link add vrf-red type vrf table 10
ip link set eth0 master vrf-red

# Правило nftables для конкретного VRF
table inet vrf_filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Правила для VRF red (только SSH)
        iifname "eth0" tcp dport 22 accept

        # Правила для VRF blue (HTTP/HTTPS)
        iifname "eth2" tcp dport { 80, 443 } accept

        # Общие правила
        ct state established,related accept
        iif "lo" accept
    }
}
```

**Использование meta-iifname для VRF:**

```bash
table inet vrf_global {
    chain input {
        type filter hook input priority 0; policy drop;

        # Фильтрация по VRF через iifname
        iifname "vrf-red" jump input_vrf_red
        iifname "vrf-blue" jump input_vrf_blue
    }

    chain input_vrf_red {
        tcp dport 22 accept
        tcp dport 8080 accept
    }

    chain input_vrf_blue {
        tcp dport { 80, 443 } accept
    }
}
```

### MPTCP (Multipath TCP) — фильтрация

MPTCP (RFC 8684) позволяет устанавливать TCP-соединения через несколько сетевых путей одновременно. Используется для агрегации каналов и повышения отказоустойчивости.

**Характеристики:**

- Работает поверх стандартного TCP (совместимость с NAT и файрволами)
- Использует TCP Option (MP_CAPABLE, MP_JOIN, ADD_ADDR, etc.)
- Ядро Linux поддерживает MPTCP начиная с версии 5.6

**Фильтрация MPTCP в nftables:**

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept

        # Разрешить MPTCP (TCP с опциями MPTCP)
        # nftables не различает MPTCP и обычный TCP на уровне L4
        # Фильтрация возможна только по порту назначения
        tcp dport { 80, 443 } accept

        # Блокировка MPTCP (если не поддерживается)
        # На уровне ядра: sysctl -w net.mptcp.enabled=0
    }
}
```

**Важно:** nftables не различает MPTCP и обычный TCP на транспортном уровне. MPTCP-пакеты выглядят как обычные TCP-пакеты с дополнительными опциями. Фильтрация MPTCP возможна только через:
1. Блокировку на уровне ядра (`sysctl net.mptcp.enabled=0`)
2. Специализированные eBPF-программы для анализа TCP Options
3. Rate limiting для MPTCP-соединений

**Настройка MPTCP в Linux:**
```bash
# Включение MPTCP
sysctl -w net.mptcp.enabled=1

# Настройка天地 paths
sysctl -w net.mptcp.pm_type=0

# Просмотр MPTCP-соединений
ss -M
# → ESTAB  0  0  10.0.0.1:443  203.0.113.5:52182  mptcp:subflows=2
```

### См. также

-   **[nftables — практические сценарии](./practical_scenarios.md):** примеры NAT, защиты от DoS и балансировки нагрузки.
-   **[nftables — миграция и справочник синтаксиса](./migration_and_reference.md):** перевод правил с iptables и быстрый поиск по полям заголовков.
-   **[nftables — моделирование угроз](./threat_modeling.md):** проектирование цепочек на основе рисков.
-   **[nftables — мониторинг и алертинг](./monitoring_and_alerting.md):** Prometheus, nflog, Grafana.
-   **[nftables — настройка производительности](./performance_tuning.md):** 10G+, flowtable, XDP.
-   **[Межсетевые экраны: концепции](../../../../../Networking/Concepts/firewall_concepts.md):** теоретическая база Netfilter и модели OSI.
