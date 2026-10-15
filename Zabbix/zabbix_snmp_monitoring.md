# Zabbix — мониторинг через SNMP

**Актуально для:** Zabbix 7.0 LTS / 7.4

## Определения

* **SNMP-интерфейс хоста (SNMP interface)** — отдельный сетевой реквизит хоста (IP/DNS + порт 161), используемый только для SNMP-проверок. Хост может иметь несколько интерфейсов разных типов (agent, SNMP, IPMI, JMX) одновременно.
* **SNMP agent item** — тип элемента данных, значение которого запрашивается у SNMP-устройства. Ключ элемента свободный (имя), а OID задаётся в отдельном поле **SNMP OID**.
* **`get[OID]`** — формат поля SNMP OID для получения одного или нескольких конкретных объектов (GetRequest). Выполняется асинхронно.
* **`walk[OID]`** — формат для обхода поддерева OID (GetNext/GetBulk). Выполняется асинхронно, эффективен как master-элемент для LLD.
* **SNMP trapper** — процесс Zabbix, принимающий SNMP-трапы из временного файла, который пишет сторонний демон (snmptrapd).
* **SNMPTT** — внешний переводчик трапов, форматирующий ловушки в файл для SNMP trapper.
* **Динамический индекс (dynamic index)** — числовой суффикс OID, идентифицирующий строку таблицы (например, номер интерфейса `ifIndex`). Может меняться при переконфигурации оборудования.

Теорию протокола (версии, PDU, SMI, Trap vs Inform), настройку `snmpd` и утилиты `snmpwalk`/`snmptrapd` см. в [SNMP — протокол сетевого управления](../Networking/Protocols/snmp_overview.md). Мониторинг через Prometheus `snmp_exporter` — там же.

## Основные концепции

### Асинхронные SNMP-поллеры

Начиная с Zabbix 7.0 процессы SNMP-опроса асинхронные: один `snmp poller` обслуживает до `MaxConcurrentChecksPerPoller` (по умолчанию 1000) параллельных проверок, не блокируясь на ожидании ответа. Количество воркеров задаёт `StartSNMPPollers`. Это позволяет опрашивать сотни коммутаторов без пропорционального роста числа процессов.

Ключи `get[]` и `walk[]` исполняются асинхронно и не подпадают под per-interface `Use combined requests` — рекомендуется переводить проверки на них.

### Форматы поля SNMP OID

| Формат | Назначение | Пример |
|---|---|---|
| `OID` (числовой или MIB) | Одиночное значение | `.1.3.6.1.2.1.1.3.0` или `sysUpTime.0` |
| `get[OID1,OID2,...]` | Несколько конкретных объектов | `get[1.3.6.1.2.1.2.2.1.10.1]` |
| `walk[OID1,OID2,...]` | Обход поддерева | `walk[ifDescr]`, `walk[1.3.6.1.2.1.2.2.1.2]` |

Бульк-запросы (GetBulkRequest) применяются для SNMPv2/v3; для SNMPv1 используется GetNext. Размер бульк-пакета задаёт **max repetition value** (по умолчанию 10); при слишком большом значении возможен таймаут проверки.

### SNMP-трапы

Zabbix не принимает трапы напрямую. Схема:

```
Устройство --(trap UDP/162)--> snmptrapd --(запись в файл)--> SNMPTT --> SNMPTrapperFile --> Zabbix SNMP trapper
```

Сервер (или прокси) читает файл, указанный в `SNMPTrapperFile`, и формирует события/значения. Включается параметром `StartSNMPTrapper`.

## Практические сценарии

### Предварительные требования

* В системе установлен пакет `snmp` (net-snmp) — для диагностики и приёма трапов.
* На сервере в `zabbix_server.conf` добавлены параметры SNMP (см. ниже).
* Для сетевого устройства известны `community` (v1/v2c) или учётные данные v3.

### Шаг 1. Добавление SNMP-интерфейса хоста

`Data collection → Hosts → <host> → Interfaces → Add → SNMP`:

* IP address / DNS name устройства;
* Port по умолчанию `161`;
* Для SNMPv3 — `Context name`, `Security name`, уровень безопасности (`noAuthNoPriv` / `authNoPriv` / `authPriv`), протоколы аутентификации и шифрования (`Authentication protocol`, `Privacy protocol`), пароли.

Пароли SNMPv3 в шаблоне задаются макросами `{$SNMP_COMMUNITY}`, а для v3 — `{$SNMPV3_USER}`, `{$SNMPV3_AUTHPASS}`, `{$SNMPV3_PRIVPASS}` и т.п. (набор зависит от шаблона).

### Шаг 2. Создание элемента данных

`Data collection → Hosts → <host> → Items → Create item`:

* **Type:** `SNMP agent`;
* **Key:** осмысленное имя, например `net.if.in`;
* **Host interface:** созданный SNMP-интерфейс;
* **SNMP OID:** `.1.3.6.1.2.1.2.2.1.10.<index>` или `get[...]`/`walk[...]`;
* **Type of information:** `Numeric (unsigned)`/`Numeric (float)`;
* **Update interval**, **History storage period**.

> Важно: счётчики интерфейсов (`ifInOctets`, `ifHCInOctets`) накапливаются. Для получения скорости нужно добавить шаг предобработки **Change per second**. Без него график будет монотонно растущим.

### Шаг 3. Предобработка SNMP

`Preprocessing` элемента данных:

* **Change per second** — превращает накопительный счётчик в скорость (байт/с, пакетов/с).
* **SNMP walk to JSON** — преобразует результат `walk[]` в JSON-массив с макросами `{#SNMPINDEX}`, `{#SNMPVALUE}` и разобранными OID-компонентами.
* **SNMP walk value** — извлекает значение конкретного OID из результата master-walk (для dependent-элементов).

### Шаг 4. LLD через walk (рекомендуемый подход)

Вместо опроса каждого интерфейса по отдельности создаётся один master-элемент, обходящий таблицу:

1. Master item типа `SNMP agent`, поле OID = `walk[1.3.6.1.2.1.31.1.1.1.1]` (ifName), интервал опроса LLD.
2. Discovery rule типа `Dependent item`, Master item = этот walk-элемент.
3. Предобработка `SNMP walk to JSON` с параметрами (префикс OID для `{#SNMPINDEX}`).
4. Item prototype типа `Dependent item` с предобработкой `SNMP walk value` и OID вида `1.3.6.1.2.1.31.1.1.1.6.{#SNMPINDEX}`.

Итог: **один** walk-запрос за цикл вместо отдельного GET на каждый интерфейс. Это снижает нагрузку на устройство и на сервер.

### Шаг 5. Приём SNMP-трапов

`/etc/snmp/snmptrapd.conf` (на сервере/прокси или отдельном хосте):

```ini
disableAuthorization yes
authCommunity log,execute,net public
outputOption Q
outputOption f /var/log/snmptrap/snmptrap.log
traphandle default /usr/sbin/snmptthandler
```

`/etc/snmp/snmptt.ini`: указать `snmptt_conf_files`, формат вывода (`date_time_format` ISO). В `zabbix_server.conf`:

```ini
StartSNMPTrapper=1
SNMPTrapperFile=/var/log/snmptrap/snmptrap.log
```

Элементы данных принимают трапы через тип `SNMP trap` (значение — текст трапа), а фильтрация выполняется по содержимому.

## Операции и команды

```bash
# Доступность устройства по SNMPv2c из командной строки
snmpwalk -v2c -c public 192.168.1.1 sysUpTime
# → DISMAN-EVENT-MIB::sysUpTimeInstance = Timeticks: (123456) 1:02:00:56.00

# Обход таблицы интерфейсов (то, что делает walk[])
snmpwalk -v2c -c public 192.168.1.1 ifDescr
# → IF-MIB::ifDescr.1 = STRING: eth0
# → IF-MIB::ifDescr.2 = STRING: eth1

# SNMPv3 (authPriv)
snmpwalk -v3 -l authPriv -u zbx -a SHA -A authpass -x AES -X privpass 192.168.1.1 ifDescr

# Проверка SNMP-элемента из интерфейса: кнопка "Test" в форме item
# (SNMP-проверки исполняются Server/Proxy, zabbix_get здесь не применим)

# Тест приёма трапов
snmptrap -v2c -c public 127.0.0.1 '' 1.3.6.1.4.1.8072.2.3.0.1
# → в Zabbix появляется событие/значение SNMP trap
```

| Внутренняя метрика | Назначение |
|---|---|
| `zabbix[process,snmp poller,avg,busy]` | средняя занятость SNMP-поллеров, % |
| `zabbix[process,snmp trapper,avg,busy]` | занятость trapper |
| `zabbix[queue]` | общая очередь опроса |

Runtime control: `zabbix_server -R snmp_cache_reload` — перезагрузить кэш SNMP (после смены учётных записей SNMPv3 или при аномалиях с `engineBoots`/`engineID`).

## Устранение неисправностей

### Элемент в статусе Unsupported

* Неверный OID или `community`/SNMPv3-креды.
* Устройство/poller недоступны: `snmpwalk` из командной строки тоже не отвечает.
* Для v3 — несовпадение движка (engineID): помогает `snmp_cache_reload`, корректная настройка `engineID`/`engineBoots`.
* Ошибка `SNMP response from host ... does not contain all of the requested variable bindings` — устройство не поддерживает `Use combined requests`. Решение: перевести элементы на `get[]`/`walk[]` (асинхронные) или отключить combined requests для интерфейса.

### Таймауты при массовом опросе

* Уменьшить **max repetition value** (по умолчанию 10) и увеличить `Timeout` для walk-элементов.
* Увеличить `StartSNMPPollers`.
* Разнести интервалы опроса больших таблиц (не гнать LLD и счётчики в один момент).

### Трапы не появляются

* `StartSNMPTrapper` = 0 (по умолчанию выключен).
* `SNMPTrapperFile` не совпадает с реальным путём, куда пишет snmptrapd; файл должен существовать и быть доступен пользователю `zabbix`.
* snmptt/snmptrapd не запущены или фильтруют трап.

### Динамические индексы «поехали»

* Строите элементы на фиксированных индексах — при переконфигурации устройства индексы меняются и данные пишутся не туда. Решение — LLD на базе `walk[]` с извлечением `{#SNMPINDEX}`.

## Лучшие практики

* **Используйте `get[]`/`walk[]` и асинхронные поллеры** — рекомендованный на 7.0+ способ. Отказывайтесь от legacy-ключей с `Use combined requests`.
* **Один walk + dependent items** вместо множества отдельных GET — снижает трафик и нагрузку на устройство.
* **SNMPv3 с authPriv** для прода; `community` v2c — только в доверенной изолированной сети.
* **Шаблоны вместо ручных элементов** — для вендоров поддерживайте шаблоны; кликабельные OID берите из MIB с подтверждением через `snmpwalk`.
* **Мониторьте здоровье самого SNMP-контура**: занятость поллеров, очередь, `snmp_cache_reload` при подозрениях.
* **Изолируйте управляющий трафик** в отдельный network segment, ограничьте доступ к порту 161.
* **Для трапов** держите snmptrapd+SNMPTT на отдельном хосте или прокси, чтобы падение приёма ловушек не затрагивало основной опрос.

## Дополнительная информация

### См. также

* [SNMP — протокол сетевого управления](../Networking/Protocols/snmp_overview.md) — теория протокола, `snmpd`, `snmp_exporter`.
* [Низкоуровневое обнаружение (LLD)](./low_level_discovery.md) — механика discovery и прототипов.
* [Мониторинг сетевого оборудования](./zabbix_network_devices.md) — стандартизированные шаблоны для коммутаторов, маршрутизаторов и firewall.
* [Элементы данных](./zabbix_items.md) — типы, предобработка, calculated.
* [Мониторинг IPMI](./zabbix_ipmi_monitoring.md) — аппаратный мониторинг серверов.
* [IPMI/BMC в Linux](../Linux/Diagnostics/Hardware/ipmi_bmc.md) — `ipmitool` и BMC.

### Источники

* Zabbix documentation: [SNMP agent](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/snmp), [Discovery of SNMP OIDs](https://www.zabbix.com/documentation/current/en/manual/discovery/low_level_discovery/examples/snmp_oids_walk), [SNMP traps](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/snmptrap).
