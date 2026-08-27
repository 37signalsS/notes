# Агрегация каналов (Link Aggregation)

## Определения

**Агрегация каналов** (также известная как `Link Aggregation`, `Port Channel`, `EtherChannel`, `Bonding`) — это технология объединения нескольких физических сетевых интерфейсов в один логический. Это позволяет повысить отказоустойчивость и увеличить суммарную пропускную способность соединения.

В ОС Linux для реализации этой технологии используются два основных механизма:
1.  **Модуль ядра `bonding`:** Классическая и наиболее стабильная реализация. **Рекомендуется** для использования во всех современных системах (RHEL, Debian, Ubuntu).
2.  **Модуль `teaming`:** Архитектура с логикой в пользовательском пространстве (`teamd`). **Признана устаревшей (deprecated)** в RHEL 9 и **полностью удалена** в RHEL 10+. Использовать не рекомендуется.

### Архитектура Bonding

При создании bond-интерфейса происходит следующее:
- Создается виртуальный сетевой интерфейс (например, `bond0`), который виден ядру как обычное сетевое устройство.
- Физические интерфейсы (`eth0`, `eth1`) переводятся в режим `slave` (подчиненных) и теряют собственную сетевую идентичность.
- Весь трафик на уровне ядра проходит через `bond0`, а модуль `bonding` распределяет его по физическим интерфейсам согласно выбранному алгоритму.
- Bond-интерфейс использует MAC-адрес первого подчиненного интерфейса (или может быть задан вручную через `fail_over_mac`).

### Основные цели

*   **Отказоустойчивость (Fault Tolerance):** При выходе из строя одного физического линка трафик прозрачно переключается на оставшиеся. Время переключения зависит от метода мониторинга (miimon) и обычно составляет 100–300 мс.
*   **Увеличение пропускной способности (Bandwidth Aggregation):** Суммирование емкости каналов. Например, два 1 Гбит/с линка дают суммарно 2 Гбит/с для множественных потоков.
*   **Важное ограничение:** Агрегация увеличивает *общую* пропускную способность интерфейса, но не скорость *одиночного* TCP-соединения. Из-за алгоритмов хеширования один поток данных всегда ограничен скоростью одного физического порта (для предотвращения нарушения порядка следования пакетов).

## Базовые концепции

### Мониторинг состояния линков

Для определения работоспособности физических интерфейсов в `bonding` используются два метода:

1.  **MII мониторинг (Media Independent Interface):** Проверяет только состояние несущей (Link Carrier) через драйвер сетевой карты.
    *   **Плюс:** Работает мгновенно, не создает дополнительный трафик.
    *   **Минус:** Не обнаруживает проблемы за пределами первого коммутатора (например, если порт коммутатора «горит», но данные не проходят).
    *   **Параметр:** `miimon` (интервал в мс, рекомендуется 100 мс).
    *   **Дополнительные параметры:** `updelay` и `downdelay` — задержка перед переводом интерфейса в состояние up/down (рекомендуется равным `miimon` для синхронизации с коммутатором).

2.  **ARP мониторинг (Address Resolution Protocol):** Проверяет доступность конкретного IP-адреса (например, шлюза) через каждый интерфейс.
    *   **Плюс:** Проверяет реальную сквозную передачу данных.
    *   **Минус:** Создает дополнительный трафик; не совместим с режимом LACP (mode 4) в некоторых старых версиях ядра.
    *   **Параметры:** `arp_interval` (интервал в мс) и `arp_ip_target` (IP-адреса для проверки, минимум один, максимум 16).

> **Рекомендация:** Для режима LACP (mode 4) используйте MII мониторинг. LACP сам по себе контролирует состояние линков через LACPDU.

### Политики хеширования (Transmit Hash Policy)

Для режимов с балансировкой (`mode 2` и `mode 4`) параметр `xmit_hash_policy` определяет, как ядро распределяет пакеты по портам. Хеш вычисляется на основе заголовков пакетов и определяет, через какой slave-интерфейс будет отправлен пакет:

*   **layer2 (по умолчанию):** Хеш на основе MAC-адресов (src MAC XOR dst MAC). Весь трафик между двумя хостами всегда идет через один порт. Подходит, если весь трафик идет через один шлюз.
*   **layer2+3:** Комбинация MAC и IP (src MAC XOR dst MAC XOR src IP XOR dst IP). Лучшее распределение для трафика, уходящего за пределы подсети (через маршрутизатор).
*   **layer3+4:** IP-адреса + TCP/UDP порты (src IP XOR dst IP XOR (src_port << 16) | dst_port). Самое равномерное распределение, разные сессии между одними и теми же узлами могут идти через разные линки. **Рекомендуется** для серверов с множественными соединениями.
*   **encap2+3 / encap3+4:** Расширенные политики для анализа инкапсулированного трафика (например, внутри VXLAN или GRE). Используют внутренние MAC/IP-адреса для хеширования.

### Режимы работы Bonding

| Режим | Название | Описание | Требование к коммутатору | Балансировка TX | Балансировка RX |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **mode=0** | `balance-rr` | Round-robin. Пакеты отправляются по очереди. | Static Trunk (EtherChannel) | Да | Нет |
| **mode=1** | `active-backup` | Один активный, остальные в резерве. | Не требуется | Нет | Нет |
| **mode=2** | `balance-xor` | Статическая балансировка на основе хеша. | Static Trunk (EtherChannel) | Да | Нет |
| **mode=3** | `broadcast` | Дублирование всех пакетов на все порты. | Static Trunk | Да (дублирование) | Да (дублирование) |
| **mode=4** | `802.3ad` (LACP) | Динамическая агрегация по протоколу LACP. | **Поддержка LACP (IEEE 802.3ad)** | Да | Нет |
| **mode=5** | `balance-tlb` | Адаптивная балансировка исходящего трафика. | Не требуется | Да | Нет |
| **mode=6** | `balance-alb` | Адаптивная балансировка входящего и исходящего. | Не требуется | Да | Да (через ARP) |

> **Внимание:** Режим `mode=0` может приводить к `TCP Out-of-Order` (нарушение порядка пакетов), что резко снижает скорость TCP. В 2026 году стандартом де-факто является `mode=4` (LACP).

### Протокол LACP (802.3ad) — Подробности

**LACP (Link Aggregation Control Protocol)** — протокол канального уровня (L2), определенный в стандарте IEEE 802.3ad (позже включен в 802.1AX). Позволяет автоматически согласовывать агрегацию между двумя устройствами.

#### Компоненты LACP

*   **LACPDU (LACP Data Units):** Служебные пакеты для обмена информацией между сервером (Actor) и коммутатором (Partner). Содержат:
    - Приоритет системы и устройства
    - Ключ агрегации
    - Состояние порта (Active, Timeout, Aggregation, Synchronization, Collecting, Distributing, Defaulted, Expired)
    - Таймеры

#### Состояния LACP-порта

| Состояние | Описание |
| :--- | :--- |
| **Activity** | Порт активно участвует в LACP (отправляет LACPDU) |
| **Timeout** | Использует короткий таймаут (3 сек при `fast`) |
| **Aggregation** | Порт может быть агрегирован |
| **Synchronization** | Порт синхронизирован с партнером, готов передавать данные |
| **Collecting** | Порт принимает трафик |
| **Distributing** | Порт отправляет трафик |
| **Defaulted** | Использует настройки по умолчанию (партнер не ответил) |
| **Expired** | Таймаут ожидания ответа от партнера |

#### Тонкие настройки LACP

*   **LACP Rate:**
    *   `slow` (по умолчанию): Обмен раз в 30 секунд. Таймаут партнера — 90 секунд.
    *   `fast`: Обмен каждую секунду. Позволяет быстрее обнаружить падение линка (таймаут 3 сек вместо 90 сек). **Рекомендуется** для production-сред.
*   **ad_select:** Выбор активного агрегатора:
    *   `stable` (по умолчанию): Не менять группу линков без необходимости.
    *   `bandwidth`: Выбирать агрегатор с максимальной пропускной способностью.
    *   `count`: Выбирать агрегатор с максимальным числом портов.
*   **min_links:** Минимальное количество активных линков для поднятия bond-интерфейса (по умолчанию 0).

### Технологии Multi-Chassis (MLAG / vPC)

Обычный LACP работает только с одним логическим коммутатором. Для отказоустойчивости на уровне *железа* (при подключении сервера к двум физическим свитчам) используются:

*   **vPC (Virtual Port Channel):** Решение от Cisco Nexus. Два коммутатора объединяются в пару через vPC peer-link и peer-keepalive link.
*   **MLAG (Multi-Chassis Link Aggregation):** Открытый стандарт (Arista, Mellanox, Juniper). Аналогичная концепция, но реализованная по-разному у разных вендоров.
*   **MC-LAG (Multi-Chassis Link Aggregation Group):** Общий термин для подобных технологий.

Это позволяет объединить порты с разных физических коммутаторов в одну логическую группу LACP, обеспечивая отказоустойчивость на уровне коммутаторов.

## Практические сценарии

### Настройка через NetworkManager (nmcli)

**Предварительные требования:**
- Установленный NetworkManager: `systemctl status NetworkManager`
- Два физических интерфейса (`eth1`, `eth2`)
- Коммутатор с поддержкой LACP (IEEE 802.3ad) для mode 4

**Сценарий: LACP (mode 4) с хешированием layer3+4 и быстрыми LACPDU.**

```bash
# 1. Создание bond-интерфейса
nmcli connection add type bond con-name bond0 ifname bond0 \
  mode 802.3ad \
  bond.options "miimon=100,xmit_hash_policy=layer3+4,lacp_rate=fast"

# 2. Добавление физических портов
nmcli connection add type ethernet con-name bond0-p1 ifname eth1 master bond0
nmcli connection add type ethernet con-name bond0-p2 ifname eth2 master bond0

# 3. Настройка IP и запуск
nmcli connection modify bond0 ipv4.addresses 10.0.0.50/24 ipv4.method manual
nmcli connection up bond0
```

**Валидация:**
```bash
# Проверка состояния bond
nmcli connection show bond0 | grep -E "GENERAL.STATE|IP4.ADDRESS"
# → GENERAL.STATE: активировано
# → IP4.ADDRESS[1]: 10.0.0.50/24

# Проверка статуса через /proc
cat /proc/net/bonding/bond0
# → Bonding Mode: IEEE 802.3ad Dynamic link aggregation
# → MII Status: up
# → Number of active slaves: 2
```

---

### Настройка через systemd-networkd

**Предварительные требования:**
- Служба `systemd-networkd` запущена: `systemctl enable --now systemd-networkd`
- Два физических интерфейса (например, `enp1s0`, `enp2s0`)

**Сценарий: LACP-агрегат со статическим IP.**

```ini
# /etc/systemd/network/10-bond0.netdev
[NetDev]
Name=bond0
Kind=bond

[Bond]
Mode=802.3ad
MIIMonitorSec=100ms
LACPTransmitRate=fast
TransmitHashPolicy=layer3+4
```

```ini
# /etc/systemd/network/20-bond0-slave.network
[Match]
Name=enp1s0 enp2s0

[Network]
Bond=bond0
```

```ini
# /etc/systemd/network/30-bond0.network
[Match]
Name=bond0

[Network]
Address=192.168.1.10/24
Gateway=192.168.1.1
DNS=8.8.8.8
```

**Применение:**
```bash
# Перезапуск службы
sudo systemctl restart systemd-networkd

# Проверка статуса
networkctl status bond0
# → Link File: /usr/lib/systemd/network/99-default.link
# → Network File: /etc/systemd/network/30-bond0.network
# → State: routable (configured)
# → Address: 192.168.1.10
```

---

### Настройка через Netplan (Ubuntu)

**Предварительные требования:**
- Ubuntu 18.04+ или Debian 12+
- Два физических интерфейса (например, `enp3s0`, `enp3s1`)

Конфигурация в `/etc/netplan/00-installer-config.yaml`:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0: {}
    enp3s1: {}
  bonds:
    bond0:
      interfaces: [enp3s0, enp3s1]
      addresses: [192.168.1.10/24]
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
      parameters:
        mode: 802.3ad
        mii-monitor-interval: 100
        transmit-hash-policy: layer3+4
        lacp-rate: fast
```

**Применение:**
```bash
sudo netplan apply

# Проверка
sudo netplan status bond0
```

---

### Сценарий Active-Backup (без коммутатора)

**Предварительные требования:**
- Два физических интерфейса
- **Не требует** поддержки коммутатора (режим active-backup)

**Применение:** Идеально для серверов с двумя провайдерами или для простого резервирования без настройки LACP на коммутаторе.

**Через nmcli:**
```bash
# Создание bond в режиме active-backup
nmcli connection add type bond con-name bond0 ifname bond0 \
  mode active-backup \
  bond.options "miimon=100,primary=eth1"

# Добавление портов
nmcli connection add type ethernet ifname eth1 master bond0
nmcli connection add type ethernet ifname eth2 master bond0

# Настройка IP
nmcli connection modify bond0 ipv4.addresses 10.0.0.50/24 ipv4.method manual
nmcli connection up bond0
```

**Через systemd-networkd:**
```ini
# /etc/systemd/network/10-bond0.netdev
[NetDev]
Name=bond0
Kind=bond

[Bond]
Mode=active-backup
MIIMonitorSec=100ms
PrimaryReselectPolicy=always
```

**Валидация отказоустойчивости:**
```bash
# Определение активного интерфейса
cat /proc/net/bonding/bond0 | grep "Currently Active Slave"
# → Currently Active Slave: eth1

# Имитация обрыва линка
sudo ip link set eth1 down

# Проверка переключения (должно быть < 300 мс)
cat /proc/net/bonding/bond0 | grep "Currently Active Slave"
# → Currently Active Slave: eth2

# Восстановление
sudo ip link set eth1 up
```

---

### Bonding + Bridge (для виртуализации)

**Предварительные требования:**
- Два физических интерфейса для bond
- Планируется использование KVM/LXD/Docker

**Применение:** Создание моста поверх bond для обеспечения отказоустойчивой сети для виртуальных машин.

**Через Netplan:**
```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp1s0: {}
    enp2s0: {}
  bonds:
    bond0:
      interfaces: [enp1s0, enp2s0]
      parameters:
        mode: 802.3ad
        mii-monitor-interval: 100
        transmit-hash-policy: layer3+4
  bridges:
    br0:
      interfaces: [bond0]
      addresses: [192.168.1.10/24]
      routes:
        - to: default
          via: 192.168.1.1
```

**Через nmcli:**
```bash
# Создание bond
nmcli connection add type bond con-name bond0 ifname bond0 \
  mode 802.3ad \
  bond.options "miimon=100,xmit_hash_policy=layer3+4"

# Добавление портов
nmcli connection add type ethernet ifname enp1s0 master bond0
nmcli connection add type ethernet ifname enp2s0 master bond0

# Создание моста поверх bond
nmcli connection add type bridge con-name br0 ifname br0
nmcli connection modify br0 ipv4.addresses 192.168.1.10/24 ipv4.method manual

# Добавление bond в мост
nmcli connection add type bridge-port ifname bond0 master br0

# Запуск
nmcli connection up bond0
nmcli connection up br0
```

**Валидация:**
```bash
# Проверка моста
bridge link show
# → 3: bond0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master br0

# Проверка bond в мосту
cat /proc/net/bonding/bond0 | grep "MII Status"
# → MII Status: up
```

---

### Временная настройка через iproute2

**Применение:** Быстрая настройка без перезагрузки (не сохраняется после перезагрузки).

```bash
# Загрузка модуля bonding
sudo modprobe bonding

# Создание bond-интерфейса
sudo ip link add name bond0 type bond mode 802.3ad

# Настройка параметров (через sysfs)
echo 100 > /sys/class/net/bond0/bonding/miimon
echo layer3+4 > /sys/class/net/bond0/bonding/xmit_hash_policy

# Добавление физических интерфейсов
sudo ip link set eth1 down
sudo ip link set eth2 down
sudo ip link set eth1 master bond0
sudo ip link set eth2 master bond0

# Настройка IP и поднятие
sudo ip addr add 10.0.0.50/24 dev bond0
sudo ip link set bond0 up
```

---

## Валидация и диагностика

### Основные команды диагностики

| Задача | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| Статус bond | `cat /proc/net/bonding/bond0` | MII Status: up, Active slaves: 2 |
| Список bond-интерфейсов | `ip -d link show type bond` | bond0 с деталями |
| Статистика по slave | `ip -s link show eth1` | RX/TX пакеты |
| Проверка LACP | `cat /proc/net/bonding/bond0 \| grep "LACPDU"` | Ненулевые счетчики |
| Проверка в мосту | `bridge link show` | bond0 master br0 |

### Проверка состояния через /proc

```bash
# Полный статус bond
cat /proc/net/bonding/bond0
```

**Ключевые показатели:**
*   **Bonding Mode:** Должен соответствовать настроенному (например, `IEEE 802.3ad Dynamic link aggregation`).
*   **MII Status:** Должен быть `up`. Если `down`, линк физически мертв.
*   **Active Slaves / Currently Active Slave:** Количество активных линков.
*   **Partner Mac Address:** В режиме LACP должен быть виден MAC-адрес коммутатора. Если там `00:00:00:00:00:00`, значит LACP не согласован (проблема в настройках коммутатора).
*   **LACPDU Statistics:** Проверьте счетчики входящих/исходящих LACPDU — они должны расти.

### Мониторинг статистики

```bash
# Статистика по каждому slave
for slave in eth1 eth2; do
  echo "=== $slave ==="
  ip -s link show $slave | grep -A1 "RX:\|TX:"
done

# Мониторинг в реальном времени
watch -n 1 'cat /proc/net/bonding/bond0 | grep -E "MII|Active|LACPDU"'
```

### Проверка балансировки трафика

```bash
# Включение отладки (если нужно)
echo 1 > /sys/class/net/bond0/bonding/debug

# Проверка распределения (через ethtool)
ethtool -S eth1 | grep rx_packets
ethtool -S eth2 | grep rx_packets
```

---

## Устранение неполадок

### Проблема: LACP не поднимается (Partner MAC = 00:00:00:00:00:00)

**Причины:**
- На коммутаторе не настроен LACP
- Несовпадение ключей агрегации
- Блокировка LACPDU файрволом

**Диагностика:**
```bash
# Проверка статуса LACP
cat /proc/net/bonding/bond0 | grep -A5 "802.3ad"
# → Partner Mac Address: 00:00:00:00:00:00  ← Проблема!

# Проверка через ethtool
ethtool -S bond0 | grep lacp
```

**Решение:**
1. Убедитесь, что на коммутаторе настроен LACP:
   ```cisco
   ! Cisco IOS
   interface Port-channel1
    switchport mode trunk
   interface GigabitEthernet0/1
    channel-group 1 mode active
   interface GigabitEthernet0/2
    channel-group 1 mode active
   ```
2. Проверьте, что порты на коммутаторе в одной группе.
3. Убедитесь, что между сервером и коммутатором нет файрвола, блокирующего LACPDU (Ethertype 0x8809).

### Проблема: Failover не работает

**Причины:**
- Не настроен `miimon` или `arp_interval`
- Слишком большая задержка `downdelay`

**Диагностика:**
```bash
# Проверка настроек мониторинга
cat /proc/net/bonding/bond0 | grep -E "MII Polling|ARP Interval|Up Delay|Down Delay"
# → MII Polling Interval (ms): 0  ← Проблема!
```

**Решение:**
```bash
# Установка miimon
echo 100 > /sys/class/net/bond0/bonding/miimon

# Или через nmcli
nmcli connection modify bond0 bond.options "miimon=100,downdelay=200,updelay=200"
```

### Проблема: MAC Flapping на коммутаторе

**Причины:**
- Режим balance-rr (mode 0) отправляет пакеты с одного MAC через разные порты
- Неправильная настройка хеширования

**Решение:**
```bash
# Переключение на mode 4 (LACP) с правильным hash policy
nmcli connection modify bond0 bond.options "mode=802.3ad,xmit_hash_policy=layer2+3"
```

### Проблема: Низкая пропускная способность

**Диагностика:**
```bash
# Проверка, какой slave используется
cat /proc/net/bonding/bond0 | grep "Currently Active Slave"

# Проверка скорости каждого линка
ethtool eth1 | grep Speed
ethtool eth2 | grep Speed
```

**Возможные причины и решения:**
- Один поток ограничен скоростью одного порта — это нормально для bonding
- Для лучшего распределения используйте `xmit_hash_policy=layer3+4`
- Проверьте, что все линки одной скорости (например, оба 1 Гбит/с)

### Проблема: MTU не применяется

**Решение:**
```bash
# Установка MTU на bond и всех slaves
sudo ip link set bond0 mtu 9000
sudo ip link set eth1 mtu 9000
sudo ip link set eth2 mtu 9000
```

---

## Дополнительная информация

### Тонкая настройка (Bonding Options)

*   **`primary` / `primary_reselect`:** Для режима `active-backup`. Позволяет жестко закрепить приоритетный интерфейс (например, самый быстрый). `primary_reselect` определяет, когда происходит возврат на основной интерфейс (`always`, `better`, `failure`).
*   **`all_slaves_active`:** Если `1`, то в режиме `active-backup` все подчиненные интерфейсы будут принимать трафик (полезно для некоторых систем мониторинга).
*   **`resend_igmp`:** Количество IGMP-запросов после смены активного линка. Критично для работы **Multicast** трафика.
*   **`fail_over_mac`:** Политика MAC-адреса в режиме active-backup:
    *   `none` (по умолчанию) — MAC не меняется
    *   `active` — используется MAC активного интерфейса
    *   `follow` — MAC переключается на активный slave
*   **`num_grat_arp` / `num_unsol_na`:** Количество gratuitous ARP при переключении — помогает обновить ARP-таблицы соседей.
*   **`min_links`:** Минимальное количество активных линков для работы bond (0 по умолчанию).

### Сравнение инструментов управления

| Инструмент | Плюсы | Минусы | Рекомендация |
| :--- | :--- | :--- | :--- |
| **NetworkManager** | GUI, интеграция с desktop, nmcli | Требует установленный NM | Рабочие станции, серверы с NM |
| **systemd-networkd** | Легковесный, встроен в systemd | Текстовые конфиги | Серверы, контейнеры, minimal-системы |
| **Netplan** | YAML, простой синтаксис | Требует генерации конфиг | Ubuntu 18.04+ |
| **ifupdown2** | Совместимость с interfaces | Устаревает | Debian/Ubuntu legacy |
| **iproute2 (ручная)** | Гибкость, отладка | Не персистентна | Тестирование, отладка |

### Связанные технологии

*   **[VLAN в Linux](../Protocols/VLAN/vlan_linux_diagnostics.md):** Создание тегированных интерфейсов (bond0.100) поверх агрегата.
*   **[Linux Bridge](../../Linux/Networking/Concepts/linux_bridge.md):** Добавление `bond0` в мост для виртуализации (KVM/LXD).
*   **[Оптимизация TCP](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md):** Настройка параметров стека для работы с толстыми каналами.
*   **[L2 Switching и VLAN](../vlan_l2_switching/practical_scenarios.md):** Сценарий Bonding + VLAN с полной конфигурацией.

### Сравнение технологий агрегации

| Характеристика | Bonding | Teaming (teamd) |
| :--- | :--- | :--- |
| **Реализация** | Ядро Linux (Kernel space) | Пользовательское пространство (User space) |
| **Статус (2026)** | **Стандарт (SSoT)** | **Удалено (Deprecated/Removed)** |
| **Управление** | sysfs, nmcli, netplan, systemd-networkd | teamdctl, JSON |
| **Надежность** | Максимальная (минимум зависимостей) | Зависит от стабильности демона `teamd` |
| **Производительность** | Максимальная (обработка в ядре) | Ниже (переключение контекста) |
