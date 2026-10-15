# Zabbix — мониторинг сетевого оборудования

**Актуально для:** Zabbix 7.0 LTS / 7.4

Документ описывает стандартизированные шаблоны Zabbix для сетевого оборудования (коммутаторы, маршрутизаторы, firewall, storage, беспроводное оборудование) и практику их применения. Механика опроса по SNMP (OID, версии, LLD по SNMP) описана в **[Zabbix — мониторинг по SNMP](./zabbix_snmp_monitoring.md)**; масштабное снятие опроса с сервера — в **[Zabbix — прокси](./zabbix_proxy.md)**.

---

## Определения

* **Chassis** — шасси устройства: питание, вентиляторы, температура, CPU/память, инвентарь (серийный номер, модель, прошивка).
* **Network interface** — сетевой интерфейс устройства (порт); мониторится отдельно от шасси.
* **Standardized template** — поставляемый Zabbix шаблон для семейства устройств (например, `Cisco IOS SNMP`, `Huawei VRP by SNMP`).
* **Model (модель шаблона)** — из двух моделей строятся шаблоны: для самого устройства (chassis) и для интерфейса.
* **Certified** — тег шаблона: покрыты все три категории (Fault + Performance + Inventory).
* **IF-MIB / EtherLike-MIB** — стандартные MIB для мониторинга интерфейсов (статус, трафик, duplex).
* **`@Network interfaces for discovery`** — глобальное регулярное выражение, фильтрующее интерфейсы при LLD.

---

## Основные концепции

### Две модели шаблонов

Для сетевого оборудования Zabbix использует **две модели**:

1. **Модель устройства (chassis)** — сам девайс: питание, вентиляторы, температура, общий статус, CPU/память, инвентарь (серийный номер, модель, версия прошивки).
2. **Модель интерфейса** — сетевые порты: статус (link), загрузка трафика, duplex (для Ethernet).

Шаблон семейства устройств обычно сочетает обе модели, поэтому на одном устройстве получаются и метрики шасси, и метрики интерфейсов.

### Что покрывают шаблоны

Шаблоны покрывают (там, где устройство отдаёт данные):

* **Chassis fault monitoring** — питание (БП), вентиляторы, температура, общий статус;
* **Chassis performance monitoring** — CPU и память;
* **Chassis inventory collection** — серийный номер, имя модели, версия прошивки;
* **Network interface monitoring** по IF-MIB и EtherLike-MIB — статус интерфейса, загрузка трафика, duplex для Ethernet.

### Тег сертификации

| Тег | Значение |
|---|---|
| `Performance` | MIB семейства отдают CPU и память |
| `Fault` | MIB семейства отдают хотя бы один датчик температуры |
| `Inventory` | MIB семейства отдают хотя бы серийный номер и имя модели |
| `Certified` | покрыты все три категории выше |

### Принципы дизайна шаблонов

Из официальной документации:

* **Макросы пользователя** используются везде, где возможно, — триггеры настраиваются без правки шаблона.
* **Low-level discovery** применяется максимально широко, чтобы минимизировать число неподдерживаемых элементов.
* **Все шаблоны зависят от `Template ICMP Ping`** — доступность устройства проверяется ещё и по ICMP.
* **Элементы не используют MIB-файлы** — в элементах и LLD применяются SNMP OID напрямую. Поэтому загружать MIB в Zabbix для работы шаблонов не требуется.
* **Loopback-интерфейсы отфильтровываются** при обнаружении, а также интерфейсы с `ifAdminStatus = down(2)`.
* **64-битные счётчики** берутся из `IF-MIB::ifXTable`, где это поддержано; иначе используются 32-битные счётчики.

Для корректной фильтрации интерфейсов рекомендуется обновить глобальное регулярное выражение `@Network interfaces for discovery`:

```text
Result is FALSE: ^Software Loopback Interface
Result is FALSE: ^(In)?[lL]oop[bB]ack[0-9._]*$
Result is FALSE: ^NULL[0-9.]*$
Result is FALSE: ^[lL]o[0-9.]*$
Result is FALSE: ^[sS]ystem$
Result is FALSE: ^Nu[0-9.]*$
```

Управление триггером линка для конкретного интерфейса — через макрос с контекстом. Триггер имеет вид:

```text
{$IFCONTROL:"{#IFNAME}"}=1 and last(/<Template>/net.if.status[ifOperStatus.{#SNMPINDEX}])=2 and (last(...,#1)<>last(...,#2))
```

Чтобы отключить мониторинг линка для интерфейса `Gi0/0`, задают макрос `{$IFCONTROL:"Gi0/0"}` = `0`. Чтобы включить триггеры только для избранных интерфейсов (например, аплинков), меняют логику макроса на обратную.

### Доступные семейства устройств

Список семейств (фрагмент; в поставке Zabbix их больше — единый источник — страница документации «Standardized templates for network devices»):

| Шаблон | Вендор | Семейство |
|---|---|---|
| `Cisco IOS SNMP` | Cisco | IOS-коммутаторы и маршрутизаторы |
| `Cisco Catalyst 3750<device model> SNMP` | Cisco | Catalyst 3750 |
| `Juniper SNMP`, `Juniper MX SNMP` | Juniper | EX, MX |
| `Huawei VRP by SNMP` | Huawei | VRP (AR/S-серия и др.) |
| `Huawei OceanStor 5300 V5 by SNMP`, `Huawei OceanStor Dorado by SNMP` | Huawei | СХД OceanStor |
| `FortiGate by SNMP` | Fortinet | FortiGate |
| `Check Point Next Generation Firewall by SNMP` | Check Point | NGFW |
| `Stormshield SNS by SNMP` | Stormshield | SNS firewall |
| `Aruba CX 8300s by SNMP` | HPE Aruba | CX 8300 |
| `HP Comware HH3C SNMP`, `HP Enterprise Switch SNMP` | HPE | Comware, ProCurve |
| `Dell Force S-Series SNMP` | Dell | Force10 S-Series |
| `Brocade FC SNMP`, `Brocade_Foundry ...` | Brocade | FC, Foundry |
| `MikroTik SNMP` и серия `MikroTik <модель> SNMP` | MikroTik | RouterBOARD, CCR/CRS/CSS и др. |
| `Netgear Fastpath SNMP` | Netgear | Fastpath |
| `TP-LINK SNMP` | TP-LINK | Коммутаторы |
| `Ubiquiti AirOS SNMP` | Ubiquiti | AirOS |
| `Ciena 3906 by SNMP` | Ciena | 3906 |
| `Vyatta Virtual Router by SNMP` | Vyatta | Virtual Router |
| `QTech QSW SNMP` | QTech | QSW |
| `Extreme Exos SNMP` | Extreme | EXOS |
| `Alcatel Timetra TiMOS SNMP` | Nokia/Alcatel | TiMOS |
| `Mellanox SNMP`, `Intel_Qlogic Infiniband SNMP` | Mellanox/Intel | Infiniband |

Если шаблона нет в установке — его нужно предварительно импортировать (Data collection → Templates → Import).

---

## Практические сценарии

### Предварительные требования

* На устройстве **включён и настроен SNMP** (v2c community или v3 с аутентификацией/шифрованием); см. **[Zabbix — мониторинг по SNMP](./zabbix_snmp_monitoring.md)**.
* Zabbix server/proxy имеет сетевую доступность до устройства по UDP/161.
* Для большого парка устройств опрос выносится на **Zabbix proxy** — см. **[Zabbix — прокси](./zabbix_proxy.md)**.

### Сценарий 1. Подключение коммутатора/маршрутизатора

1. Включить SNMP на устройстве (пример для Cisco IOS):

   ```
   snmp-server community <COMMUNITY> ro
   snmp-server sysname <HOSTNAME>
   ```

2. В Zabbix: Data collection → Hosts → Create host.
   * **Interfaces**: добавить интерфейс типа **SNMP** (IP:порт 161), указать `{$SNMP_COMMUNITY}` или SNMPv3-креды.
   * **Monitored by**: выбрать proxy, если устройство за прокси.
3. **Templates** → привязать шаблон семейства, например `Cisco IOS SNMP` или `Huawei VRP by SNMP`.
4. Дать LLD-правилам время отработать (обычно 1 час по умолчанию, настраивается макросом).
5. Проверить: Monitoring → Latest data — появились метрики шасси и интерфейсов.

### Сценарий 2. Настройка фильтрации интерфейсов

1. Administration → General → Regular expressions → `@Network interfaces for discovery` — добавить шаблоны из раздела выше.
2. Для интерфейса, который не нужно мониторить, задать макрос `{$IFCONTROL:"<IFNAME>"}` = `0` на хосте.

### Валидация

```bash
# Проверить доступность SNMP и системный OID
snmpget -v2c -c <COMMUNITY> <HOST> 1.3.6.1.2.1.1.5.0
# → SNMPv2-MIB::sysName.0 = STRING: <HOSTNAME>

# Проверить таблицу интерфейсов (LLD-источник)
snmpwalk -v2c -c <COMMUNITY> <HOST> 1.3.6.1.2.1.2.2.1.2
# → SNMPv2-MIB::ifDescr.1 = ... (список интерфейсов)

# Проверить из Zabbix (если доступен zabbix_get на прокси/сервере)
zabbix_get -s <HOST> -k "net.if.discovery"
# → JSON с интерфейсами
```

В UI: Latest data по хосту должен содержать элементы net.if.* и элементы шасси; ничего (или минимум) в состоянии «Unsupported».

---

## Операции и команды

```bash
# Список OID системной группы (sysDescr, sysName, sysUpTime)
snmpwalk -v2c -c <COMMUNITY> <HOST> 1.3.6.1.2.1.1
# → system.sysDescr.0, system.sysName.0, system.sysUpTime.0, ...

# Проверка 64-битных счётчиков ifXTable
snmpwalk -v2c -c <COMMUNITY> <HOST> 1.3.6.1.2.1.31.1.1.1.6
# → ifHCInOctets.<idx> (счётчики в байтах)

# Проверка кастомного LLD-правила из шаблона (пример интерфейсов)
zabbix_get -s <HOST> -k "net.if.discovery"
```

| Что проверить | Команда |
|---|---|
| Доступность SNMP | `snmpget -v2c -c <COMMUNITY> <HOST> 1.3.6.1.2.1.1.1.0` |
| Список интерфейсов | `snmpwalk ... 1.3.6.1.2.1.2.2.1.2` |
| 64-bit счётчики | `snmpwalk ... 1.3.6.1.2.1.31.1.1.1.6` |
| LLD из Zabbix | `zabbix_get -s <HOST> -k "net.if.discovery"` |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Хост недоступен по SNMP | Не включён SNMP / ACL / неверный community | Проверить `snmpget`, ACL и community |
| Интерфейсы не обнаруживаются | Неверный `@Network interfaces for discovery` | Обновить глобальное регулярное выражение |
| Метрики интерфейса неполные | `ifAdminStatus = down(2)` или loopback | Снять фильтр / задать контекст макроса |
| Трафик считается неверно | Устройство не отдаёт 64-bit счётчики | Шаблон откатывается на 32-bit; учесть переполнение |
| Нет метрик шасси (CPU/память) | MIB/прошивка устройства не отдаёт OID | Проверить поддержку OID на устройстве, обновить прошивку |
| Значения инвентаря пусты | Устройство не отдаёт ENTITY-MIB / серийник | Проверить OID `ENTITY-MIB` вручную |
| Триггер линка «flapping» | Кратковременные переключения порта | Использовать макрос `{$IFCONTROL}` и/или гистерезис |

---

## Лучшие практики

* **Использовать стандартные шаблоны** вместо самописных OID — они поддерживаются и обновляются с выходом новых версий Zabbix.
* **Выносить опрос сетевого оборудования на proxy**, размещённый ближе к устройствам, чтобы не тянуть SNMP через WAN.
* **Обновлять глобальное выражение `@Network interfaces for discovery`** при импорте новых шаблонов — иначе появятся лишние интерфейсы.
* **Проверять 64-bit счётчики**: на старых устройствах 32-bit переполняются за минуты на высоких скоростях и дают ложные графики.
* **Не включать триггер линка на всех портах доступа** — шум от подключений рабочих станций; ограничивать аплинками через `{$IFCONTROL}`.
* **Использовать SNMPv3** там, где позволяет оборудование, вместо community v2c.
* **Проверять теги шаблона** (`Certified`/`Fault`/`Performance`/`Inventory`) — что именно покрывается на конкретном устройстве, чтобы не ждать отсутствующих метрик.

---

## Дополнительная информация

### См. также

* [Zabbix — мониторинг по SNMP](./zabbix_snmp_monitoring.md) — OID, версии SNMP, LLD по SNMP (базовая механика).
* [Zabbix — прокси](./zabbix_proxy.md) — распределённый опрос широкого парка устройств.
* [Zabbix — элементы данных (items)](./zabbix_items.md) — настройка элементов и LLD-правил.
* [Zabbix — low-level discovery](./low_level_discovery.md) — механика LLD.
* [Zabbix — инвентаризация и отчётность](./zabbix_inventory_and_reporting.md) — сбор инвентаря с сетевых устройств.

### Источники и ссылки

* Zabbix documentation: [Standardized templates for network devices](https://www.zabbix.com/documentation/7.0/en/manual/config/templates_out_of_the_box/network_devices)
* Zabbix documentation: [SNMP agent](https://www.zabbix.com/documentation/7.0/en/manual/config/items/itemtypes/snmp)
* Zabbix documentation: [Quickstart — Monitor a network switch or router](https://www.zabbix.com/documentation/7.0/en/manual/quickstart/monitor_switch)
