# Zabbix — элементы данных и предобработка

**Актуально для:** Zabbix 7.0 LTS / 7.4

## Определения

* **Элемент данных (Item)** — минимальная единица сбора: один ключ, тип сбора, интервал и тип значения. Хранит один временной ряд.
* **Тип элемента (Item type)** — механизм сбора: агент, SNMP, IPMI, JMX, HTTP-агент, траппер, вычисляемый и т. д.
* **Вычисляемый элемент (Calculated item)** — значение рассчитывается самой не из сбора, а по формуле из данных других элементов.
* **Zabbix aggregate** — элемент, агрегирующий данные других хостов группы (`grpavg`, `grpsum`, `grpmax`, `grpmin`, `grpcount`).
* **Зависимый элемент (Dependent item)** — получает значение из master-элемента через предобработку, не выполняя отдельного сбора.
* **Master item** — элемент, собирающий «сырые» данные (часто JSON), из которого извлекают значения зависимые элементы.
* **Предобработка (Preprocessing)** — упорядоченный список шагов преобразования полученного значения перед записью в БД.
* **Value mapping** — таблица соответствия числового значения текстовой метке (например, `1 → up`, `2 → down`).

## Основные концепции

### Типы элементов

| Тип | Модель | Типовой пример |
|---|---|---|
| `Zabbix agent` | Pull/Push | `system.cpu.load[all,avg1]` |
| `Zabbix agent (active)` | Push | активные проверки, `log[]` |
| `SNMP agent` | Pull | OID/`walk[]` (см. [SNMP](./zabbix_snmp_monitoring.md)) |
| `IPMI agent` | Pull | датчики BMC (см. [IPMI](./zabbix_ipmi_monitoring.md)) |
| `JMX agent` | Pull | heap JVM (см. [JMX](./zabbix_jmx_monitoring.md)) |
| `Simple check` | Pull | `net.tcp.service[tcp,,80]`, ICMP-ping |
| `SSH agent` / `Telnet agent` | Pull | выполнение команд на устройстве |
| `External check` | Pull (server) | скрипт на сервере/прокси |
| `Trapper` | Push | данные от `zabbix_sender`/`history.push` |
| `Zabbix internal` | — | самодиагностика сервера |
| `Calculated` | — | формула по другим элементам |
| `Dependent item` | — | извлечение из master |
| `HTTP agent` | Pull | REST/JSON API |
| `Browser` (7.0+) | Pull | синтетика через браузер |
| `Zabbix aggregate` | — | агрегация по группе хостов |
| `Database monitor` | Pull | ODBC-запрос |

Ключ элемента — строка с параметрами в квадратных скобках. Для «повторяющихся» ключей одинаковый ключ возвращает одно значение; параметры позволяют различать объекты (`net.if.in[eth0]`).

### Типы значений и связи

* Типы информации: `Numeric (unsigned)`, `Numeric (float)`, `Character`, `Text`, `Log`.
* **Master/dependent:** один запрос к БД/API/SNMP возвращает JSON (master), значения извлекаются dependent-элементами через JSONPath. Это главный способ снизить число обращений к целевой системе — подробнее в [мониторинге БД](./zabbix_database_monitoring.md) и [лучших практиках](./zabbix_best_practices.md).
* **История/тренды:** `History storage period` хранит исходные значения, тренды — часовые агрегаты (см. [концепции](./definitions_and_concepts.md)).

### Вычисляемые элементы

Ключ вычисляемого элемента — произвольное имя, а формула задаётся в поле **Formula**. В формуле доступны функции, читающие тайп-серию других элементов:

```
last("net.if.in[eth0]")
avg("system.cpu.load[all,avg1]",10m)
sum("net.if.in[eth0]",1h)
max("vm.memory.size[available]",5m)
```

Формула может строиться из нескольких элементов, например «свободно памяти в процентах»:

```
100 * last("vm.memory.size[available]") / last("vm.memory.size[total]")
```

Функции вычисляемых элементов отличаются от функций триггеров: они оперируют историей и не имеют доступа к состоянию события.

### Агрегированные проверки

Элемент типа `Zabbix aggregate` считает статистику по **группе хостов**:

```
grpsum["Linux servers","net.if.in[eth0]","last",0]
grpavg["Web servers","system.cpu.load[all,avg1]","avg",10m]
grpmax["Databases","vfs.fs.size[/,pfree]","last",0]
```

Синтаксис: `grp<func>[<host group>,<item key>,<function>,<param>]`. Типовое применение — «средняя загрузка по пулу web-серверов», «суммарный трафик кластера».

### Value mapping

Числовому значению сопоставляется текст. Классический случай — статусы SNMP-интерфейса:

| Значение | Представление |
|---|---|
| 1 | up |
| 2 | down |
| 3 | testing |

В элементе выбирается поле `Show value` → нужная таблица. Таблица отображается в истории, на графиках и в триггерах.

### Предобработка

Шаги выполняются по порядку на сервере/прокси:

* **Change per second** — производная накопительных счётчиков;
* **JSONPath** — извлечение из JSON (master → dependent);
* **Regular expression** — парсинг текста (до 9 групп `\1`…`\9`);
* **JavaScript** — произвольное преобразование (JSON, вычисления);
* **SNMP walk to JSON / SNMP walk value** — разбор `walk[]` (см. [SNMP](./zabbix_snmp_monitoring.md));
* **Throttling** — не сохранять чаще, чем раз в интервал;
* **Discard unchanged (with heartbeat)** — не писать повторяющиеся значения (экономия места);
* **Custom on fail** — поведение при ошибке шага (выбросить/подставить значение/ошибку).

## Практические сценарии

### Сценарий 1. Calculated item: память в процентах

`Data collection → Items → Create item`:

* **Type:** `Calculated`;
* **Key:** `vm.memory.used.pct`;
* **Formula:** `100 * (last("vm.memory.size[total]") - last("vm.memory.size[available]")) / last("vm.memory.size[total]")`;
* **Type of information:** `Numeric (float)`.

### Сценарий 2. Aggregate: суммарный трафик кластера

* **Type:** `Zabbix aggregate`;
* **Key:** `web.cluster.traffic`;
* **Aggregate function / group / item:** `grpsum["Web servers","net.if.in[eth0]","last",0]`.

### Сценарий 3. Value mapping для статуса

1. `Administration → Value mapping → Create` с таблицей `1→up, 2→down`.
2. В SNMP-элементе `net.if.status[ifOperStatus]` выбрать `Show value` = созданная таблица.
3. В истории и на графике вместо чисел отображается `up`/`down`.

### Сценарий 4. Master + dependent с Discard unchanged

Master:

* **Key:** `db.stats`, **Type:** `Zabbix agent (active)` → возвращает JSON.

Dependent-прототипы:

* **Type:** `Dependent item`, **Master item:** `db.stats`;
* Предобработка `JSONPath` `$.active`;
* Предобработка `Discard unchanged with heartbeat: 1h` — повторяющиеся значения не пишутся.

### Проверка

```bash
# Тест вычисляемого/агрегированного элемента — кнопкой "Test" в форме item
# Для JSONPath удобно проверить реальный JSON master-элемента:
zabbix_get -s 127.0.0.1 -k 'db.stats'
# → {"active":5,"idle":3,"total":1200}
```

## Операции и команды

| Задача | Действие |
|---|---|
| Создать элемент | `Data collection → Hosts/Templates → Items → Create item` |
| Значение-таблица | `Administration → Value mapping` |
| Тест элемента | кнопка `Test` (для серверных типов) или `zabbix_get` (для агентских) |
| Массовое обновление | `Mass update` для группы элементов |
| Тип элемента для push | `Trapper` + `zabbix_sender` (см. [установка](./installation.md)) |

```bash
# Проверка ключа на агенте
zabbix_agent2 -t 'system.cpu.load[all,avg1]'
# → system.cpu.load[all,avg1]   [f|0.42]
```

## Устранение неисправностей

### Calculated item возвращает ошибку

* Синтаксическая ошибка формулы или несуществующий ключ в кавычках.
* Указан элемент без истории (например, только тренды) — функция не находит данных.
* Функции триггеров использованы в вычисляемом элементе (они несовместимы).

### Dependent item Unsupported

* Неверный JSONPath относительно структуры master-значения.
* Master-элемент не собрал данные (тогда dependent тоже пуст).
* Master возвращает не JSON, а текст.

### Aggregate item пуст

* Группа хостов не существует или в ней нет элементов с указанным ключом.
* Неверный порядок/регистр параметров `grp<func>`.
* Периоды: `last`/`avg` требуют наличия данных у хотя бы одного хоста группы.

### Value mapping не отображается

* Таблица не выбрана в поле `Show value` элемента.
* Для триггера значение и так текстовое — mapping применяется к числовым.

### Значения «скачут»/дублируются

* Лишние срабатывания при накопительных счётчиках — добавьте `Change per second`.
* Дублирование редких значений — `Discard unchanged`.
* Слишком частый сбор тяжёлого ключа — `Throttling`.

## Лучшие практики

* **Используйте master/dependent и `Discard unchanged`** для снижения нагрузки и объёма БД.
* **Calculated — для производных метрик**, которые нельзя получить напрямую (проценты, отношения), а не для простого копирования.
* **Aggregate — для пулов и кластеров**, где нужна сводка по группе хостов.
* **Value mapping** — обязателен для статусных элементов (SNMP, службы, state-датчики): читаемость истории и триггеров.
* **Не плодите элементы на каждую метрику**, если их можно извлечь из одного master JSON.
* **Проверяйте предобработку на реальном значении** (кнопка Test) до сохранения.
* **Помните про типы значений:** строку в числовой элемент не записать — несоответствие делает элемент Unsupported.

## Дополнительная информация

### См. также

* [Определения и основные концепции](./definitions_and_concepts.md) — модель данных, история и тренды.
* [Мониторинг баз данных](./zabbix_database_monitoring.md) — master/dependent на практике, ODBC.
* [Лучшие практики настройки](./zabbix_best_practices.md) — master/dependent, теги, триггеры.
* [Мониторинг через SNMP](./zabbix_snmp_monitoring.md) — `walk[]`, предобработка SNMP.
* [Плагины Zabbix Agent 2](./zabbix_agent_plugins.md) — ключи элементов от плагинов (docker, mysql, redis и др.).
* [Макросы](./zabbix_macros.md) — пользовательские, контекстные и секретные макросы в элементах данных.
* [Установка и настройка](./installation.md) — trapper и `zabbix_sender`.

### Источники

* Zabbix documentation: [Items](https://www.zabbix.com/documentation/current/en/manual/config/items/item), [Item types](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes), [Calculated items](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/calculated), [Aggregate items](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/aggregate), [Value mapping](https://www.zabbix.com/documentation/current/en/manual/config/items/mapping), [Preprocessing](https://www.zabbix.com/documentation/current/en/manual/config/items/preprocessing).
