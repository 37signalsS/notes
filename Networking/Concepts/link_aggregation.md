# Агрегация каналов (Link Aggregation)

## Определения

**Агрегация каналов** (также известная как `Link Aggregation`, `Port Channel`, `EtherChannel`) — это технология, позволяющая объединить несколько физических сетевых интерфейсов в один логический. В Linux для этого используется модуль ядра **`bonding`** (рекомендуемый) и модуль **`teaming`** (deprecated в RHEL 9+).

Основные цели агрегации:

1. **Отказоустойчивость (Fault Tolerance):** Если один из физических каналов выходит из строя, трафик автоматически перенаправляется через оставшиеся рабочие каналы, обеспечивая непрерывность соединения.
2. **Увеличение пропускной способности (Bandwidth Aggregation):** Суммирование пропускной способности нескольких каналов для увеличения общей скорости передачи данных. **Важно:** это увеличивает *пропускную способность*, но не *скорость* одного соединения. Скорость одного потока (например, скачивания одного файла) будет ограничена скоростью одного физического канала.

## Основные концепции

### Bonding vs. Teaming

- **Bonding:** Стандартный модуль ядра Linux. Поддерживает множество режимов работы. **Рекомендуемый способ** в современных дистрибутивах (RHEL 9+, Fedora, Debian/Ubuntu).
- **Teaming:** Реализация в пользовательском пространстве через `teamd` и `teamdctl`. Предлагает те же режимы, называемые "runners". **Deprecated в RHEL 9**, не рекомендуется для новых конфигураций.

### Режимы работы (Runners)

Режим определяет, как трафик распределяется между объединенными интерфейсами.

- `round_robin` (в bonding `mode=0`):
  - **Принцип:** Пакеты поочередно отправляются через каждый интерфейс в группе.
  - **Преимущества:** Обеспечивает балансировку нагрузки.
  - **Недостатки:** Может приводить к нарушению порядка доставки пакетов.

- `active_backup` (в bonding `mode=1`):
  - **Принцип:** Один интерфейс активен, остальные находятся в режиме ожидания. Если активный интерфейс падает, один из резервных занимает его место.
  - **Преимущества:** Идеально для простой отказоустойчивости. Не требует настройки коммутатора.
  - **Недостатки:** Не увеличивает пропускную способность.

- `xor` (в bonding `mode=2`):
  - **Принцип:** Выбор интерфейса для отправки пакета осуществляется на основе XOR-операции над MAC-адресами отправителя и получателя.

- `broadcast` (в bonding `mode=3`):
  - **Принцип:** Все пакеты отправляются через все интерфейсы в группе.
  - **Преимущества:** Максимальная отказоустойчивость.
  - **Недостатки:** Непрактично.

- `lacp` (в bonding `mode=4`, 802.3ad):
  - **Принцип:** Динамическая агрегация каналов по протоколу LACP (Link Aggregation Control Protocol).
  - **Преимущества:** Отраслевой стандарт, обеспечивает балансировку нагрузки и отказоустойчивость.
  - **Требование:** **Обязательна поддержка и настройка на сетевом коммутаторе.** Не будет работать с неуправляемыми ("тупыми") свитчами.

- `loadbalance` (`balance-tlb` и `balance-alb` в bonding):
  - **Принцип:** Адаптивная балансировка нагрузки. Исходящий трафик распределяется в зависимости от текущей нагрузки.
  - **Требование:** Не требует специальной настройки коммутатора.

## Практические сценарии

> **Важно:** `teaming` deprecated в RHEL 9+. Для новых конфигураций используйте `bonding`. Примеры ниже приведены для legacy-систем и ознакомления.

### Настройка Teaming с помощью `nmcli`

#### Сценарий 1: Режим `active_backup` для отказоустойчивости

Этот режим не требует настройки на коммутаторе.

```bash
# 1. Посмотреть текущие соединения и устройства
nmcli connection show
nmcli device status

# 2. Удалить существующие профили для физических интерфейсов (например, enp0s3 и enp0s8)
nmcli connection delete "Wired connection 1"
nmcli connection delete "Wired connection 2"

# 3. Создать логический team-интерфейс
# con-name - имя профиля, ifname - имя интерфейса, config - конфигурация team в JSON
nmcli connection add type team con-name my-team-0 ifname team0 config '{"runner": {"name": "active_backup"}}'

# 4. Назначить IP-адрес team-интерфейсу
nmcli connection modify my-team-0 ipv4.addresses 192.168.1.10/24
nmcli connection modify my-team-0 ipv4.method manual

# 5. Добавить физические интерфейсы ("порты") в team
nmcli connection add type team-slave con-name team0-port1 ifname enp0s3 master team0
nmcli connection add type team-slave con-name team0-port2 ifname enp0s8 master team0

# 6. Активировать соединение
nmcli connection up my-team-0

# 7. Проверить состояние
teamdctl team0 state
```

#### Сценарий 2: Режим `lacp` для увеличения пропускной способности

Этот режим требует, чтобы на коммутаторе порты были объединены в LACP-группу (Port Channel).

```bash
# Создание team-интерфейса с runner'ом lacp
nmcli connection add type team con-name my-team-1 ifname team1 config '{"runner": {"name": "lacp"}}'

# Дальнейшие шаги аналогичны (назначение IP, добавление slave-интерфейсов)
nmcli connection modify my-team-1 ipv4.addresses 192.168.2.10/24 ipv4.method manual
nmcli connection add type team-slave con-name team1-port1 ifname enp0s9 master team1
nmcli connection add type team-slave con-name team1-port2 ifname enp0s10 master team1
nmcli connection up my-team-1
```

### Настройка VLAN поверх агрегированного интерфейса

Сначала создается `team`, а затем на его основе создается `vlan`.

```bash
# 1. Создать team-интерфейс (как в примерах выше, но без IP-адреса)
nmcli connection add type team con-name my-team-0 ifname team0 config '{"runner": {"name": "active_backup"}}'
nmcli connection add type team-slave con-name team0-port1 ifname enp0s3 master team0
nmcli connection add type team-slave con-name team0-port2 ifname enp0s8 master team0
nmcli connection up my-team-0

# 2. Создать VLAN-интерфейс поверх team0
# dev - родительский интерфейс, id - номер VLAN
nmcli connection add type vlan con-name vlan10 ifname team0.10 dev team0 id 10

# 3. Назначить IP-адрес VLAN-интерфейсу
nmcli connection modify vlan10 ipv4.addresses 10.0.10.10/24 ipv4.method manual
nmcli connection up vlan10
```

## Дополнительная информация

### Связанные технологии

- **[VLAN](../Concepts/vlan_l2_switching/definitions_and_concepts.md):** VLAN можно настраивать поверх агрегированных интерфейсов.
- **[QoS](./qos.md):** Агрегация может использоваться для увеличения пропускной способности для критического трафика.
- **[Netplan bonding](../../Linux/Networking/Settings/Persistent_Network/ubuntu_netplan.md):** Настройка bonding через Netplan (Ubuntu/Debian).

### Сравнение bonding и teaming

| Характеристика | bonding | teaming |
|----------------|---------|---------|
| **Реализация** | В ядре Linux | Пользовательское пространство (`teamd`) |
| **Производительность** | Высокая | Высокая |
| **Гибкость настройки** | Стандартная | Расширенная через JSON |
| **Статус** | **Рекомендуемый** | **Deprecated (RHEL 9+)** |

Для настройки `bonding` через `nmcli` и конфигурационные файлы см. **[Persistent Network Configuration](../../Linux/Networking/Settings/Persistent_Network/index.md)**.
