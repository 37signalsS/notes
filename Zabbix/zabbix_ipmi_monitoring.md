# Zabbix — мониторинг IPMI (аппаратное обеспечение серверов)

**Актуально для:** Zabbix 7.0 LTS / 7.4

## Определения

* **IPMI (Intelligent Platform Management Interface)** — стандарт управления и мониторинга аппаратного обеспечения сервера через BMC, работающий независимо от ОС и процессора.
* **IPMI sensor** — датчик BMC: температура, вентилятор, напряжение, ток, питание, дискретные состояния (state). Имеет числовой **ID** и имя.
* **`ipmi.get`** — специальный ключ Zabbix (поддерживается с 5.0), возвращающий JSON со всеми датчиками BMC одним запросом. Используется как master-элемент для LLD.
* **IPMI-интерфейс хоста** — сетевой реквизит хоста (IP BMC + порт, по умолчанию **623/UDP**), используемый для IPMI-проверок.
* **Дискретный датчик (discrete sensor)** — датчик с состоянием (например, `OK`/`Critical`), а не с числовым значением.
* **Пороговый датчик (threshold sensor)** — числовой датчик с порогами (например, температура с `high`/`critical`).

Теорию BMC, `ipmitool`, SEL, SOL, Redfish и вендорные утилиты (racadm, ipmitool для iDRAC/iLO) см. в [Диагностика и управление через IPMI/BMC](../Linux/Diagnostics/Hardware/ipmi_bmc.md). Мониторинг через Prometheus `ipmi_exporter` — в [IPMI/BMC — мониторинг аппаратного обеспечения](../Prometheus/Exporters/ipmi_exporter.md).

## Основные концепции

### Роль Zabbix в IPMI-мониторинге

Zabbix Server или Proxy сам опрашивает BMC по сети (агент на хосте не нужен). Для этого:

* в `zabbix_server.conf`/`zabbix_proxy.conf` задаётся `StartIPMIPollers` (по умолчанию **0** — IPMI-опрос выключен);
* на хосте, где запущен Server/Proxy, должна быть установлена библиотека **OpenIPMI**;
* хост в Zabbix имеет интерфейс типа **IPMI** с адресом BMC и портом 623.

### Один запрос — все датчики

Ключевой паттерн (аналогично SNMP walk + dependent): элемент `ipmi.get` за один опрос получает JSON со всеми датчиками, а LLD и dependent-элементы разбирают его. Это снимает необходимость в отдельном запросе на каждый датчик и щадит BMC (IPMI-запросы медленные).

## Практические сценарии

### Предварительные требования

* BMC доступен по сети на порту 623 (обычно в изолированной management-сети).
* Установлена OpenIPMI:

```bash
# Debian/Ubuntu
sudo apt install openipmi libopenipmi0   # 7.0: libopenipmi0 может идти как зависимость
# RHEL/Rocky/Alma
sudo dnf install OpenIPMI OpenIPMI-libs
```

* В `zabbix_server.conf` включены IPMI-поллеры:

```ini
StartIPMIPollers=3
```

### Шаг 1. IPMI-интерфейс и учётные данные

`Data collection → Hosts → <server> → Interfaces → Add → IPMI`: адрес BMC (management IP) и порт `623`. Учётные данные задаются макросами `{$IPMI.USER}` и `{$IPMI.PASSWORD}` (значения из шаблона/хоста).

### Шаг 2. Ручной элемент по датчику

`Data collection → Items → Create item`:

* **Type:** `IPMI agent`;
* **Key:** осмысленное имя, например `ipmi.temp.cpu1`;
* **Host interface:** IPMI-интерфейс;
* **IPMI sensor:** ID или имя датчика, например `CPU1 Temp` или `sensor[CPU1 Temp]`.

Для дискретного датчика тип информации — `Text`; для числового датчика — `Numeric (float)`.

### Шаг 3. LLD по всем датчикам (рекомендуемый подход)

1. **Master item:** тип `IPMI agent`, ключ `ipmi.get`, тип информации `Text` (JSON может быть большим).
2. **Discovery rule:** тип `Dependent item`, Master item = `ipmi.get`. В «LLD macros» определить макросы через JSONPath (например, `{#SENSOR_ID}` из `$.[*].id`).
3. **Item prototype:** тип `Dependent item`, ключ `ipmi_sensor[{#SENSOR_ID}]`, предобработка JSONPath:

```
$.[?(@.id=='{#SENSOR_ID}')].value.first()
```

Для дискретных датчиков состояние извлекается из `.state.text`:

```
$.[?(@.id=='{#SENSOR_ID}')].state.text.first()
```

В результате на каждом цикле discovery создаются элементы по одному на датчик, значения извлекаются из единственного `ipmi.get`.

### Шаг 4. Официальный шаблон

Готовое решение — шаблон **Chassis by IPMI** (ранее `Template Server Chassis by IPMI`). Он использует `ipmi.get`, раздельные LLD-правила для дискретных и пороговых датчиков и триггеры по температурам/вентиляторам/питанию. Обязательные макросы — `{$IPMI.USER}`, `{$IPMI.PASSWORD}`.

### Шаг 5. Валидация

```bash
# BMC отвечает по IPMI (с хоста, где стоит ipmitool)
ipmitool -I lanplus -H 10.0.0.100 -U admin -P secret sensor list
# → CPU1 Temp  | 62.000 | degrees C | ok | ...
# → FAN1       | 7200.000 | RPM | ok | ...

# Один опрос даёт JSON всех датчиков (master item ipmi.get)
#   проверяется кнопкой "Test" в форме элемента данных
```

## Операции и команды

| Задача | Команда / параметр |
|---|---|
| Число IPMI-поллеров | `StartIPMIPollers` (server/proxy), по умолчанию 0 |
| Занятость IPMI-поллеров | `zabbix[process,ipmi poller,avg,busy]` |
| Тест BMC | `ipmitool -I lanplus -H <bmc> -U <user> -P <pass> sensor list` |
| Библиотека OpenIPMI | `ldconfig -p \| grep -i ipmi` |

```bash
# Проверка, что Zabbix видит BMC через интерфейс (кнопка Test в item)
# Для IPMI-проверок zabbix_get не применим — опрос идёт с Server/Proxy.

# Диагностика занятости IPMI-поллеров через внутренние метрики
# zabbix[process,ipmi poller,avg,busy]  → 0..100%
```

## Устранение неисправностей

### IPMI-элементы Unsupported / «Cannot connect to IPMI»

* `StartIPMIPollers=0` — IPMI-опрос выключен.
* Не установлена библиотека OpenIPMI.
* Неверные `{$IPMI.USER}`/`{$IPMI.PASSWORD}` или IPMI-интерфейс не привязан к хосту.
* BMC недоступен по сети: проверить через `ipmitool` вручную.

### Ошибки LLD «Cannot create trigger» для датчиков с пустым порогом

Известная проблема шаблона Chassis by IPMI: у некоторых датчиков порог пуст. Решение — фильтровать такие датчики макросом `{$IPMI.SENSOR_TYPE.NOT_MATCHES}` (`invalid`) или обновить шаблон.

### Высокая нагрузка на BMC

* Слишком частый `ipmi.get` — BMC медленный, большие интервалы (60–120 с) предпочтительнее.
* Много IPMI-поллеров не всегда помогает: узкое место — сам BMC.

### Значения не обновляются, хотя BMC доступен

* Закэшированный JSON `ipmi.get` не обновляется — проверьте интервал master-элемента.
* Проверьте, что discovery не потерял датчик (`Lost resources`), а предобработка JSONPath корректна.

## Лучшие практики

* **Один `ipmi.get` + LLD** вместо отдельных элементов на датчик — меньше запросов к BMC.
* **Изолированная management-сеть** для BMC; IPMI-трафик не должен идти через прод-сеть.
* **Длинные интервалы** (60–120 с): IPMI-запросы тяжёлые и медленные.
* **Используйте официальный шаблон Chassis by IPMI** — покрывает температурные/пороговые и дискретные датчики.
* **Дополняйте IPMI данным ОС** (`lm-sensors`, см. [аппаратный мониторинг](../Linux/Diagnostics/Hardware/hardware_monitoring.md)): IPMI видит BMC-датчики, hwmon — датчики ОС; вместе дают полную картину.
* **Мониторьте сами IPMI-поллеры** (`zabbix[process,ipmi poller,avg,busy]`).

## Дополнительная информация

### См. также

* [Диагностика и управление через IPMI/BMC](../Linux/Diagnostics/Hardware/ipmi_bmc.md) — `ipmitool`, SEL, SOL, Redfish.
* [IPMI/BMC — мониторинг аппаратного обеспечения](../Prometheus/Exporters/ipmi_exporter.md) — Prometheus-подход.
* [Аппаратный мониторинг: температура, вентиляторы, напряжение](../Linux/Diagnostics/Hardware/hardware_monitoring.md) — `lm-sensors`/hwmon.
* [Элементы данных](./zabbix_items.md) — типы элементов и предобработка.
* [Мониторинг через SNMP](./zabbix_snmp_monitoring.md) — безагентный мониторинг сетевого оборудования.

### Источники

* Zabbix documentation: [IPMI monitoring](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/ipmi), [Discovery of IPMI sensors](https://www.zabbix.com/documentation/current/en/manual/discovery/low_level_discovery/examples/ipmi_sensors), [IPMI template](https://www.zabbix.com/documentation/current/en/manual/config/templates_out_of_the_box/ipmi).
