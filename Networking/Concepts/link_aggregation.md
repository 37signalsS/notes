# Агрегация каналов (Link Aggregation)

## Определения

**Агрегация каналов** (также известная как `Link Aggregation`, `Port Channel`, `EtherChannel`) — это технология, позволяющая объединить несколько физических сетевых интерфейсов в один логический. В Linux для этого используется модуль ядра **`bonding`** (рекомендуемый) и, ранее, модуль **`teaming`**.

Основные цели агрегации:

1.  **Отказоустойчивость (Fault Tolerance):** Если один из физических каналов выходит из строя, трафик автоматически перенаправляется через оставшиеся рабочие каналы, обеспечивая непрерывность соединения.
2.  **Увеличение пропускной способности (Bandwidth Aggregation):** Суммирование пропускной способности нескольких каналов для увеличения общей скорости передачи данных. **Важно:** это увеличивает *пропускную способность*, но не *скорость* одного соединения. Скорость одного потока (например, скачивания одного файла) будет ограничена скоростью одного физического канала.

## Основные концепции

### Bonding vs. Teaming

-   **Bonding:** Стандартный модуль ядра Linux. Поддерживает множество режимов работы. **Рекомендуемый способ** в современных дистрибутивах (RHEL 9+, Fedora, Debian/Ubuntu).
-   **Teaming:** Реализация в пользовательском пространстве через `teamd`. Предлагает те же режимы, называемые "runners". **Считается устаревшим в RHEL 9+** и не рекомендуется для новых конфигураций.

### Режимы работы Bonding

Режим определяет, как трафик распределяется между объединенными интерфейсами.

-   `mode=0` (`round-robin`):
    -   **Принцип:** Пакеты поочередно отправляются через каждый интерфейс в группе.
    -   **Преимущества:** Обеспечивает балансировку нагрузки.
    -   **Недостатки:** Может приводить к нарушению порядка доставки пакетов.
-   `mode=1` (`active-backup`):
    -   **Принцип:** Один интерфейс активен, остальные находятся в режиме ожидания. Если активный интерфейс падает, один из резервных занимает его место.
    -   **Преимущества:** Идеально для простой отказоустойчивости. Не требует настройки коммутатора.
    -   **Недостатки:** Не увеличивает пропускную способность.
-   `mode=2` (`balance-xor`):
    -   **Принцип:** Выбор интерфейса для отправки пакета осуществляется на основе XOR-операции над MAC-адресами отправителя и получателя.
-   `mode=3` (`broadcast`):
    -   **Принцип:** Все пакеты отправляются через все интерфейсы в группе.
    -   **Преимущества:** Максимальная отказоустойчивость.
    -   **Недостатки:** Непрактично.
-   `mode=4` (`802.3ad`, LACP):
    -   **Принцип:** Динамическая агрегация каналов по протоколу LACP (Link Aggregation Control Protocol).
    -   **Преимущества:** Отраслевой стандарт, обеспечивает балансировку нагрузки и отказоустойчивость.
    -   **Требование:** **Обязательна поддержка и настройка на сетевом коммутаторе.** Не будет работать с неуправляемыми коммутаторами.
-   `mode=5` (`balance-tlb`) и `mode=6` (`balance-alb`):
    -   **Принцип:** Адаптивная балансировка нагрузки. Исходящий трафик распределяется в зависимости от текущей нагрузки.
    -   **Требование:** Не требует специальной настройки коммутатора.

## Практические сценарии

### Настройка Bonding (рекомендуемый способ)

#### С помощью nmcli (Red Hat/Fedora/CentOS)

**Сценарий 1: Режим `active-backup` для отказоустойчивости**

Этот режим не требует настройки на коммутаторе.

```bash
# 1. Создать логический bond-интерфейс
nmcli connection add type bond con-name bond0 ifname bond0 mode active-backup

# 2. Назначить IP-адрес
nmcli connection modify bond0 ipv4.addresses 192.168.1.10/24
nmcli connection modify bond0 ipv4.method manual

# 3. Добавить физические интерфейсы ("порты") в bond
nmcli connection add type ethernet con-name bond0-port1 ifname enp0s3 master bond0
nmcli connection add type ethernet con-name bond0-port2 ifname enp0s8 master bond0

# 4. Активировать соединение
nmcli connection up bond0

# 5. Проверить состояние
cat /proc/net/bonding/bond0
```

**Сценарий 2: Режим `802.3ad` (LACP) для увеличения пропускной способности**

Этот режим требует, чтобы на коммутаторе порты были объединены в LACP-группу (Port Channel).

```bash
# Создание bond-интерфейса с режимом 802.3ad
nmcli connection add type bond con-name bond1 ifname bond1 mode 802.3ad

# Дальнейшие шаги аналогичны (назначение IP, добавление slave-интерфейсов)
nmcli connection modify bond1 ipv4.addresses 192.168.2.10/24 ipv4.method manual
nmcli connection add type ethernet con-name bond1-port1 ifname enp0s9 master bond1
nmcli connection add type ethernet con-name bond1-port2 ifname enp0s10 master bond1
nmcli connection up bond1
```

#### С помощью Netplan (Ubuntu/Debian)

Пример конфигурации в файле `/etc/netplan/01-netcfg.yaml`.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0f0:
      dhcp4: no
    enp3s0f1:
      dhcp4: no
  bonds:
    bond0:
      dhcp4: no
      interfaces: [enp3s0f0, enp3s0f1]
      parameters:
        mode: 802.3ad
        mii-monitor-interval: 1
      addresses: [10.10.10.2/24]
      routes:
        - to: default
          via: 10.10.10.1
```
Подробнее: **[Настройка Netplan](../../Linux/Networking/Settings/Persistent_Network/ubuntu_netplan.md)**.

### Настройка VLAN поверх Bond-интерфейса

Сначала создается `bond`, а затем на его основе — `vlan`.

```bash
# 1. Создать bond-интерфейс (как в примерах выше, но без IP-адреса)
nmcli connection add type bond con-name bond0 ifname bond0 mode active-backup
nmcli connection add type ethernet con-name bond0-port1 ifname enp0s3 master bond0
nmcli connection add type ethernet con-name bond0-port2 ifname enp0s8 master bond0
nmcli connection up bond0

# 2. Создать VLAN-интерфейс поверх bond0
# dev - родительский интерфейс, id - номер VLAN
nmcli connection add type vlan con-name vlan10 ifname bond0.10 dev bond0 id 10

# 3. Назначить IP-адрес VLAN-интерфейсу
nmcli connection modify vlan10 ipv4.addresses 10.0.10.10/24 ipv4.method manual
nmcli connection up vlan10
```

### Настройка Teaming (устаревший способ)

> **Важно:** `teaming` считается устаревшим в RHEL 9+. Примеры ниже приведены для legacy-систем и ознакомления. Для новых конфигураций используйте `bonding`.

#### Сценарий: Режим `active_backup`

```bash
# 1. Создать логический team-интерфейс
nmcli connection add type team con-name my-team-0 ifname team0 config '{"runner": {"name": "active_backup"}}'

# 2. Назначить IP-адрес
nmcli connection modify my-team-0 ipv4.addresses 192.168.1.10/24 ipv4.method manual

# 3. Добавить физические интерфейсы ("порты") в team
nmcli connection add type team-slave con-name team0-port1 ifname enp0s3 master team0
nmcli connection add type team-slave con-name team0-port2 ifname enp0s8 master team0

# 4. Активировать соединение
nmcli connection up my-team-0

# 5. Проверить состояние
teamdctl team0 state
```

## Дополнительная информация

### Связанные технологии

-   **[VLAN](./vlan_l2_switching/definitions_and_concepts.md):** VLAN можно настраивать поверх агрегированных интерфейсов.
-   **[QoS](./qos.md):** Агрегация может использоваться для увеличения пропускной способности для критического трафика.
-   **[Netplan bonding](../../Linux/Networking/Settings/Persistent_Network/ubuntu_netplan.md):** Настройка bonding через Netplan (Ubuntu/Debian).

### Сравнение bonding и teaming

| Характеристика      | bonding                               | teaming                               |
| ------------------- | ------------------------------------- | ------------------------------------- |
| **Реализация**      | В ядре Linux                          | Пользовательское пространство (`teamd`) |
| **Производительность** | Высокая                               | Высокая                               |
| **Гибкость настройки** | Стандартная                           | Расширенная через JSON                |
| **Статус**          | **Рекомендуемый**                     | **Устаревший (RHEL 9+)**              |

Для настройки `bonding` через конфигурационные файлы см. **[Persistent Network Configuration](../../Linux/Networking/Settings/Persistent_Network/index.md)**.
