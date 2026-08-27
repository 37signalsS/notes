# MAC-адрес (Media Access Control)

## Определения

*   **MAC-адрес (Media Access Control Address):** Уникальный 48-битный (6 байт) идентификатор, назначаемый сетевому интерфейсу для связи на канальном уровне ([Layer 2](../OSI_TCP_IP_Model/osi_model.md)). Является физическим адресом устройства в сегменте локальной сети. Определяется стандартами **IEEE 802** (IEEE Std 802-2014).
*   **Стандарт IEEE 802:** Разделяет канальный уровень на два подуровня:
    *   **LLC (Logical Link Control):** Отвечает за взаимодействие с сетевым уровнем и мультиплексирование протоколов.
    *   **MAC (Media Access Control):** Отвечает за управление доступом к среде передачи и физическую адресацию.
*   **OUI (Organizationally Unique Identifier):** Первые 3 байта (24 бита) адреса, идентифицирующие производителя оборудования. Выдаются организацией IEEE. Актуальную базу OUI можно найти в пакете `hwdata` (Debian/Ubuntu) или на сайте IEEE.
*   **NIC Specific / Extension Identifier:** Последние 3 байта (24 бита) в формате EUI-48, уникальный номер, назначаемый производителем для конкретного устройства. В EUI-64 к OUI добавляются дополнительные 2 байта, а поле NIC Specific расширяется до 4 байт.
*   **UAA (Universally Administered Address):** Аппаратный адрес, прошитый в ПЗУ адаптера при производстве («Burned-In Address», BIA).
*   **LAA (Locally Administered Address):** Программный адрес, назначенный администратором или ОС, который переопределяет аппаратный адрес. В Linux применяется флаг `IFF_LIVE_ADDR_CHANGE`.
*   **IEEE Registration Authority:** Организация, управляющая распределением глобальных идентификаторов (OUI, OUI-36, IAB). Форматы регистрации описаны в документе [Guidelines for Use of EUI, OUI, and CID](https://standards.ieee.org/wp-content/uploads/import/documents/tutorials.pdf).
*   **CAM-таблица (Content Addressable Memory):** Специализированная аппаратная память коммутатора, хранящая сопоставления MAC-адресов → порт + VLAN. В Linux Bridge реализуется как хэш-таблица в ОЗУ (FDB).
*   **FDB (Forwarding Database):** Логическая таблица пересылки. В аппаратных коммутаторах — CAM-память (часто реализованная на TCAM); в программных мостах (Linux Bridge, OVS) — структура данных в ОЗУ.
*   **TCAM (Ternary Content Addressable Memory):** Сверхбыстрая память, поддерживающая поиск по маске (wildcard). Используется в коммутаторах и маршрутизаторах для поиска записей в таблицах MAC-адресов, VLAN и маршрутов за один такт. Лимит TCAM определяет масштабируемость коммутатора.

## Предварительные требования

### Железо и ОС
*   Сетевой интерфейс с поддержкой изменения MAC-адреса (большинство современных NIC; драйвер должен поддерживать `SIOCSIFHWADDR` или `ethtool -E`).
*   ОС: Linux (iproute2, ethtool, systemd-networkd, NetworkManager), macOS (networksetup, ifconfig), Windows (netsh, PowerShell, WMI).
*   Права суперпользователя (`root`/`sudo`) для изменения MAC-адреса.
*   Пакеты для диагностики: `ethtool`, `tcpdump`/`Wireshark`, `macchanger` (опционально), `bridge-utils` (устарело, но полезно для `brctl`), `arpwatch`.

### Начальное состояние
*   Интерфейс должен быть **поднят (up)** для просмотра текущего MAC.
*   Для изменения MAC на большинстве драйверов интерфейс нужно предварительно **опустить (down)**. Исключения: драйверы, поддерживающие `ethtool --permaddr` или live address change (например, virtio-net с `set_features`).
*   В виртуализированных средах (KVM, VMware, Hyper-V) изменение MAC через guest OS возможно только при поддержке «гибкого» (para-virtualized) драйвера (`virtio-net`, `vmxnet3`).
*   В облачных средах (AWS EC2, GCP, Azure) изменение MAC хостового интерфейса через guest OS обычно невозможно из-за ограничений гипервизора. Для смены MAC используется API облака или secondary private IP.

## Основные концепции

### Структура и формат записи
MAC-адрес записывается в шестнадцатеричном виде. Существует три основных формата записи:
*   Двоеточия (стандарт Unix/Linux): `00:11:22:33:44:55`
*   Дефисы (стандарт Windows): `00-11-22-33-44-55`
*   Точки (стандарт Cisco): `0011.2233.4455`

#### Битовая структура первого байта
Первый байт MAC-адреса (младший байт при отображении в двоеточиях) содержит два критически важных служебных бита:

1.  **I/G бит (Individual/Group):** Самый младший бит первого байта (0-й бит, least significant bit).
    *   `0`: Unicast (индивидуальный адрес).
    *   `1`: Multicast/Broadcast (групповой адрес).
2.  **U/L бит (Universal/Local):** Второй по старшинству бит первого байта (1-й бит).
    *   `0`: Universally administered (глобально уникальный, выдан IEEE).
    *   `1`: Locally administered (локально назначенный, например, администратором или рандомизатором).

**Пример дешифровки:** `02:00:00:00:00:00` — в двоичном виде первый байт `00000010`. Бит 1 (U/L) равен `1` → локально назначенный адрес (LAA).

### Типы адресации

| Тип | Назначение | Особенности |
| :--- | :--- | :--- |
| **Unicast** | Доставка конкретному узлу. | Адрес одного сетевого интерфейса. |
| **Multicast** | Доставка группе узлов. | Младший бит первого байта всегда равен `1`. |
| **Broadcast** | Доставка всем узлам в L2-домене. | Специальный адрес `FF:FF:FF:FF:FF:FF`. |

### Формирование Multicast MAC (IPv4)
MAC-адрес для групповой рассылки IPv4 формируется путем маппинга 23 младших бит IP-адреса в зарезервированный префикс IEEE:
*   Префикс: `01:00:5E` (24 бита).
*   Разделительный бит: `0` (1 бит).
*   Данные: 23 бита из IP-адреса.

**Проблема коллизий (32 к 1):**
Так как в Multicast IP-адресе 28 значимых бит, а в MAC переносится только 23, то **32 разных IP-адреса** будут иметь один и тот же MAC-адрес. Это означает, что сетевая карта может принять пакет, предназначенный для другой группы, и фильтрация произойдет на сетевом уровне ОС.

### Формирование Multicast MAC (IPv6)
В IPv6 используется другой диапазон для многоадресных MAC-адресов Neighbor Discovery Protocol (NDP):
*   Префикс: `33:33` (16 бит).
*   Младшие 32 бита берутся из младших 32 бит IPv6-адреса.

Пример: для адреса `ff02::1:ff28:9c5a` MAC будет `33:33:ff:28:9c:5a`.

### Метод EUI-64 (IPv6)
Используется для генерации 64-битного идентификатора интерфейса на основе 48-битного MAC:
1.  MAC-адрес делится пополам: `00:11:22` и `33:44:55`.
2.  В середину вставляется константа `FF:FE`: `00:11:22:FF:FE:33:44:55`.
3.  **Инвертируется U/L бит (7-й бит слева):**
    *   Если адрес был глобальным (бит = 0), он становится локальным (бит = 1) в контексте EUI-64.
    *   Это делается для удобства ручной настройки IPv6-адресов (чтобы короткие адреса вроде `::1` считались локальными).
    *   Результат: `02:11:22:FF:FE:33:44:55`.

**Проблемы приватности и современные альтернативы:**
EUI-64 позволяет отслеживать хост при перемещении между сетями, так как идентификатор интерфейса постоянен. В ответ на это разработаны механизмы:
*   **Privacy Extensions (RFC 4941):** Генерация временных случайных адресов для исходящих соединений.
*   **Stable Privacy (RFC 7217):** Генерация стабильного, но случайного адреса для каждой сети, что предотвращает отслеживание при перемещении между сетями, сохраняя стабильность внутри одной сети. Современные ОС (Linux systemd-networkd, Windows 10+, macOS, iOS) используют Stable Privacy по умолчанию вместо EUI-64.

### Роль MAC-адреса в кадре Ethernet
MAC-адреса отправителя и получателя являются частью заголовка кадра Ethernet II (DIX). Полная структура кадра описана в [Ethernet — основы](../Protocols/ethernet.md). Для целей адресации критически важны следующие поля:

| Поле | Размер | Описание |
| :--- | :--- | :--- |
| **Destination MAC** | 6 байт | Адрес получателя (unicast, multicast или broadcast). |
| **Source MAC** | 6 байт | Адрес отправителя. Коммутатор использует его для обучения CAM-таблицы. |
| **EtherType** | 2 байта | Тип протокола L3 (например, `0x0800` для IPv4, `0x86DD` для IPv6). |
| **Payload** | 46–1500 байт | Полезная нагрузка (MTU). |
| **FCS** | 4 байта | Контрольная сумма CRC, проверка целостности кадра. |

**Минимальный размер кадра:** 64 байта. Если полезная нагрузка меньше 46 байт, добавляется дополнение (padding). **Jumbo Frames:** В высокопроизводительных сетях (ЦОД) используются кадры с MTU до 9000 байт (Jumbo MTU), что снижает количество прерываний и overhead на обработку заголовков.

## Процесс коммутации и работа CAM/FDB

### Обучение коммутатора
Коммутатор строит таблицу соответствия MAC-адресов портам (**MAC Address Table** или **CAM Table**), анализируя **MAC-адрес источника (Source MAC)** входящих кадров.

**Жизненный цикл записи в CAM-таблице:**
1.  **Ingress:** Коммутатор принимает кадр на порту и считывает Source MAC.
2.  **Learning:** MAC-адрес источника записывается в CAM-таблицу с привязкой к порту и VLAN. Если запись существует, таймер обновляется.
3.  **Lookup:** Для Destination MAC выполняется поиск в таблице.
4.  **Decision:** Если адрес найден — Forwarding на конкретный порт. Если не найден — Flooding во все порты той же VLAN (кроме входного).
5.  **Aging:** Если MAC-адрес не активен в течение **Aging Time** (по умолчанию 300 секунд на большинстве коммутаторов), запись удаляется.

**Методы коммутации:**
*   **Store-and-Forward:** Читает весь кадр, проверяет CRC перед отправкой. Надежно, но с задержкой.
*   **Cut-Through:** Начинает пересылку сразу после чтения адреса получателя. Минимальная задержка, но риск трансляции битых кадров.
*   **Fragment-Free:** Ждёт первых 64 байт для отсечения коллизионных фрагментов.

*   **Aging Time:** Время жизни записи в таблице (обычно 300 секунд). Если от устройства нет трафика, запись удаляется.
*   **Flooding:** Если адрес назначения (Destination MAC) отсутствует в таблице, коммутатор рассылает кадр во все порты, кроме порта-источника.
*   **TCAM vs CAM:** Аппаратные коммутаторы используют TCAM для поиска записей по маске. Размер TCAM определяет количество записей (например, 16K, 32K, 128K, 1M). При превышении лимита коммутатор вынужден работать в «режиме хаба».

### Распределённое обучение MAC (EVPN/VXLAN)
В overlay-сетях (VXLAN) коммутаторы не видят исходных MAC-адресов, так как кадры инкапсулируются в UDP-туннели. Для решения этой проблемы используется **BGP EVPN (Ethernet VPN, RFC 7432, RFC 8365)**:
*   VTEP-терминалы обмениваются информацией о MAC-адресах через BGP.
*   Каждый VTEP знает, на каком конечном узле (ESI) находится конкретный MAC, и туннелирует трафик напрямую.
*   Это устраняет необходимость в flooding и масштабирует L2-сегменты за пределы одного коммутатора.

### MAC-адреса и виртуализация
*   **SR-IOV (Single Root I/O Virtualization):** Позволяет одной физической NIC создавать несколько **VF (Virtual Functions)**. Каждая VF имеет собственный MAC-адрес и может быть напрямую проброшена (passthrough) в виртуальную машину или контейнер, минуя гипервизор. Это обеспечивает производительность на скорости линии (wire-speed).
*   **KVM/QEMU:** При создании VM с libvirt можно задать MAC через атрибут `<mac address='52:54:00:xx:xx:xx'/>`. По умолчанию libvirt генерирует случайные MAC из диапазона `52:54:00:00:00:00`–`52:54:00:FF:FF:FF` (OUI, зарегистрированный за Red Hat).
*   **Proxmox VE:** MAC-адрес VM задаётся в конфигурации `.conf` интерфейса или через GUI. При миграции VM MAC перемещается вместе с конфигурацией. Для uplink-сети может потребоваться настройка Promiscuous Mode на физическом коммутаторе.

### Проблемы и аномалии
*   **MAC Flapping:** Ситуация, когда один и тот же MAC-адрес обнаруживается на разных портах за короткий промежуток времени. Причины: петли в сети (L2 Loops), нестабильный линк (flapping port) или попытка дублирования адреса.
*   **MAC Spoofing:** Подмена MAC-адреса злоумышленником для перехвата трафика или обхода фильтров.
*   **MAC Flooding Attack:** Атака, направленная на заполнение CAM-таблицы мусорными адресами, что заставляет коммутатор работать как хаб (рассылать весь трафик на все порты).
*   **Port Security:** Механизм защиты, ограничивающий количество и конкретный перечень MAC-адресов, которым разрешён доступ к порту. Защищает от атак типа MAC Flooding и CAM Table Overflow.
*   **Sticky MAC:** Автоматическое запоминание текущего подключенного адреса и внесение его в конфигурацию.
*   **802.1X Network Access Control (NAC):** Протокол аутентификации на порту. Если 802.1X недоступен, используется **MAC Authentication Bypass (MAB)** — коммутатор определяет устройство по MAC и проверяет его в RADIUS-сервере. MAB менее безопасен, так как MAC подделать проще, чем сертификат или пароль 802.1X.
*   **IP Source Guard (IPSG):** Фильтр, использующий таблицу DHCP Snooping (связка MAC + IP + VLAN + Port) для блокировки пакетов с неверной комбинацией MAC/IP. Защищает от IP-spoofing.

### MACsec (IEEE 802.1AE)
Стандарт шифрования на канальном уровне, обеспечивающий конфиденциальность, целостность и аутентификацию данных между двумя конечными точками Ethernet:
*   Работает между хостом и коммутатором или между двумя хостами.
*   Использует ассоциации безопасности (SecY) с ключевыми парами CAK/CKN.
*   **MKA (802.1X-2010/802.1AR):** Протокол управления ключами для MACsec.
*   **Relevant Commands (Cisco):** `macsec` под интерфейсом, `mka policy`, `key-server-priority`.
*   **Linux:** Поддержка через `macsec` утилиту (`ip link add link eth0 macsec0`).

## Современные технологии

### Рандомизация и приватность
Современные ОС (iOS, Android, Windows 11, macOS, Linux) используют рандомизацию MAC-адресов для защиты от трекинга в Wi-Fi сетях:
*   **Scanning MAC (Non-Persistent Random):** Случайный адрес при поиске сетей (Probe Request). Генерируется заново для каждого сеанса сканирования.
*   **Per-Connection MAC / Per-Network MAC:** Разный адрес для каждой сохраненной Wi-Fi сети или соединения.
*   **Ограничения:** Рандомизация может вызывать проблемы с DHCP-серверами, которые привязывают IP к MAC, а также с Port Security на корпоративных сетях. После ассоциации (Association) AP часто видит реальный MAC клиента, так как 802.11 association frames используют реальный MAC.

### Виртуализация (macvlan и ipvlan)
*   **macvlan:** Позволяет создавать виртуальные сетевые интерфейсы с собственными MAC-адресами на базе одного физического. Каждый интерфейс виден в сети как отдельное устройство. Подробнее — в [SSoT: macvlan](../../Docker/Docker_network/drivers/macvlan.md).
*   **ipvlan:** Несколько виртуальных интерфейсов делят один MAC-адрес, но имеют разные IP. Полезно для обхода ограничений на количество MAC-адресов на порту (например, в публичных облаках). Подробнее — в [SSoT: ipvlan](../../Docker/Docker_network/drivers/ipvlan.md).

**Сравнение macvlan и ipvlan:**

| Характеристика | macvlan | ipvlan |
| :--- | :--- | :--- |
| **MAC-адрес** | Уникальный для каждого интерфейса | Общий (MAC-адрес родителя) |
| **Уровень OSI** | L2 (Ethernet) | L2 или L3 (IP) |
| **Совместимость** | Низкая (часто блокируется Wi-Fi, Port Security) | Высокая (работает в облаках и Wi-Fi) |
| **Производительность** | Немного выше (прямая L2) | Слегка ниже в L3 режиме (требуется маршрутизация) |
| **DHCP** | Полноценная поддержка | Ограничена (требует Relay или статический IP в L3 режиме) |

### Контейнеризация
В Docker и Podman macvlan позволяет контейнерам получать IP из физической сети, минуя NAT. При этом контейнер виден в сети как отдельное устройство с собственным MAC. Однако многие публичные облака и корпоративные сети блокируют несколько MAC-адресов на одном физическом порту. Для обхода этого ограничения используйте `ipvlan` в L3 или L3S режиме.

### MAC-адреса и системный стек Linux
*   **NetworkManager:** Изменение MAC через `nmcli` сохраняется в профиле соединения. `nmcli connection modify <conn> 802-11-wireless.cloned-mac-address random` (для Wi-Fi) или `ethernet.cloned-mac-address` (для Ethernet).
*   **systemd-networkd:** В `.network` файле есть параметр `MACAddress=`. Изменение требует `systemctl restart systemd-networkd` (или `networkctl reload`).
*   **udev:** Постоянное назначение MAC через udev-правила (`/etc/udev/rules.d/70-persistent-net.rules`). На современных системах обычно заменяется на systemd-networkd или NetworkManager.
*   **ethtool:** Просмотр аппаратного MAC: `ethtool -P eth0`. Некоторые NIC поддерживают изменение permanent MAC через `ethtool -E` (редко, требует драйверной поддержки).

## Практические сценарии

### Просмотр MAC-адреса

#### Linux (iproute2)
```bash
# Просмотр всех интерфейсов и их MAC-адресов
ip link show

# Просмотр конкретного интерфейса
ip link show eth0

# Вывод только MAC-адреса
ip -br link show eth0 | awk '{print $3}'

# Через ethtool (показывает также аппаратный MAC)
ethtool -P eth0

# Через NetworkManager
nmcli device show eth0 | grep GENERAL.HWADDR
```

#### macOS
```bash
# Просмотр всех интерфейсов
ifconfig | grep -E "ether|en"

# Конкретный интерфейс
ifconfig en0 | grep ether

# Через networksetup
networksetup -listallhardwareports
```

#### Windows
```powershell
# Просмотр всех адаптеров
Get-NetAdapter | Format-Table Name, MacAddress, Status

# Детальная информация (включая драйвер и версию)
Get-NetAdapterHardwareInfo -Name "Ethernet"

# Через классическую утилиту
getmac /v /fo list
```

### Смена MAC-адреса (LAA)

#### Linux
```bash
# Вариант 1: iproute2 (современный)
sudo ip link set dev eth0 down
sudo ip link set dev eth0 address 02:01:02:03:04:05
sudo ip link set dev eth0 up

# Проверка
ip link show eth0 | grep link/ether

# Вариант 2: macchanger (случайный MAC)
sudo apt install macchanger
sudo ip link set dev eth0 down
sudo macchanger -r eth0
sudo ip link set dev eth0 up

# Проверка
macchanger -s eth0
```

#### Linux (NetworkManager)
```bash
# Смена MAC через nmcli (сохраняется в профиле)
nmcli connection modify "Wired connection 1" ethernet.cloned-mac-address 02:01:02:03:04:05
nmcli connection up "Wired connection 1"
```

#### Linux (systemd-networkd)
```ini
# /etc/systemd/network/25-eth0.network
[Match]
Name=eth0

[Link]
MACAddress=02:01:02:03:04:05
```

```bash
systemctl restart systemd-networkd
```

#### macOS
```bash
# Смена MAC через ifconfig
sudo ifconfig en0 ether 02:01:02:03:04:05

# Или через networksetup (для Wi-Fi)
sudo networksetup -setairportpower en0 off
sudo ifconfig en0 ether 02:01:02:03:04:05
sudo networksetup -setairportpower en0 on
```

#### Windows
```powershell
# Через PowerShell (Windows 10+)
Set-NetAdapter -Name "Ethernet" -MacAddress "02-01-02-03-04-05"

# Через netsh (требует перезагрузки интерфейса)
netsh interface set interface "Ethernet" admin=disable
# Затем изменить реестр или через Device Manager
netsh interface set interface "Ethernet" admin=enable
```

### Управление FDB/CAM

#### Просмотр таблицы MAC-адресов
```bash
# Linux Bridge
bridge fdb show
bridge fdb show dev br0

# Просмотр с указанием VLAN
bridge fdb show dev br0 | grep vlan

# Cisco
show mac address-table dynamic
show mac address-table address 00:11:22:33:44:55
show mac address-table vlan 10

# Aruba/HPE
show mac-address | include 0011.2233.4455
show mac-address vlan 10

# Juniper
show ethernet-switching table
show ethernet-switching table detail
```

#### Добавление статической записи в FDB
```bash
# Linux Bridge
sudo bridge fdb add 00:11:22:33:44:55 dev br0 master permanent

# Удаление записи
sudo bridge fdb del 00:11:22:33:44:55 dev br0

# Изменение времени ageing
sudo bridge link set dev br0 ageing_time 600
```

#### MACsec (Linux)
```bash
# Создание MACsec-интерфейса
sudo ip link add link eth0 macsec0 type macsec
sudo ip macsec add macsec0 tx sa 0 pn 1 on key 00112233445566778899aabbccddeeff
sudo ip macsec add macsec0 rx address 00112233445566778899aabbccddeeff port 0 sa 0 pn 1 on key 00112233445566778899aabbccddeeff
sudo ip link set macsec0 up
```

### Поиск производителя по MAC (OUI)
```bash
# Linux: grep по базе OUI
grep -i "00:11:22" /usr/share/hwdata/oui.txt

# Через утилиту manuf (из пакета hwdata)
manuf 00:11:22:33:44:55

# Онлайн-сервисы (API)
curl "https://api.macvendors.com/00:11:22:33:44:55"
curl "https://macvendors.co/api/00:11:22:33:44:55/json"

# Через wireshark/tshark (если установлен базу OUI)
tshark -o "gui.column.format:\"%m\",\"%m\""
```

### Обнаружение конфликтов MAC-адресов
```bash
# Wireshark/tshark: фильтр по дублирующим MAC
tshark -i eth0 -Y "eth.src == 00:11:22:33:44:55" -T fields -e frame.time -e eth.src -e eth.dst

# Linux: проверка локальной ARP-таблицы на дубликаты
ip neigh show | awk '{print $5}' | sort | uniq -d

# Cisco: проверка MAC flapping
show mac address-table
show logging | include MACFLAP

# arpwatch: автоматический мониторинг дубликатов
sudo arpwatch -i eth0
# Логи в /var/log/syslog или /var/lib/arpwatch/arp.dat
```

### Фильтрация и мониторинг

#### Wireshark / tshark display filters
```text
# Фильтр по MAC-отправителю
eth.src == 00:11:22:33:44:55

# Фильтр по MAC-получателю
eth.dst == 00:11:22:33:44:55

# Исключить broadcast/multicast
!eth.dst[0] & 1

# Только multicast
eth.dst[0] & 1

# Фильтр по OUI (первые 3 байта)
eth.src[0:3] == 00:11:22

# Фильтр по типу кадра
eth.type == 0x0806  # ARP
eth.type == 0x0800  # IPv4
eth.type == 0x86DD  # IPv6
eth.dst == ff:ff:ff:ff:ff:ff  # Broadcast
```

#### eBPF / XDP фильтрация по MAC
```c
// Пример XDP-программы: отбросить кадры с неверным Destination MAC
SEC("xdp")
int filter_mac(struct xdp_md *ctx) {
    void *data_end = (void *)(long)ctx->data_end;
    void *data = (void *)(long)ctx->data;
    struct ethhdr *eth = data;

    if (data + sizeof(*eth) > data_end)
        return XDP_PASS;

    if (eth->h_dest[0] == 0x00 && eth->h_dest[1] == 0x11 &&
        eth->h_dest[2] == 0x22 && eth->h_dest[3] == 0x33 &&
        eth->h_dest[4] == 0x44 && eth->h_dest[5] == 0x55) {
        return XDP_PASS;
    }

    return XDP_DROP;
}
```

### Безопасность на коммутаторах
*   **MAC Filtering:** Разрешение доступа только конкретным адресам. Легко обходится подменой.
*   **Port Security:** Ограничение количества MAC-адресов на физическом порту и блокировка при попытке подключения несанкционированного устройства.
    *   **Sticky MAC:** Автоматическое запоминание текущего подключенного адреса и внесение его в конфигурацию.

**Пример конфигурации Port Security на Cisco IOS:**
```cisco
interface GigabitEthernet0/1
 switchport mode access
 switchport port-security
 switchport port-security maximum 2
 switchport port-security mac-address sticky
 switchport port-security violation shutdown
```

**Пример конфигурации Port Security на Arista EOS:**
```arista
interface Ethernet1
 switchport access vlan 10
 switchport port-security maximum 2
 switchport port-security mac-address sticky
 switchport port-security violation shutdown
```

**Пример конфигурации на Juniper Junos:**
```juniper
set interfaces ge-0/0/1 unit 0 family ethernet-switching port-security
set interfaces ge-0/0/1 unit 0 family ethernet-switching port-security maximum 2
set interfaces ge-0/0/1 unit 0 family ethernet-switching port-security mac-settings sticky-mac
```

### Управление macvlan (Docker)
```bash
# Создание macvlan-сети
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  macvlan_net

# Запуск контейнера с собственным MAC
docker run -d --name web --network macvlan_net nginx
```

Подробные сценарии настройки, включая режимы `bridge`, `vepa`, `private` и `passthru`, а также решение проблемы связи хост-контейнер (shim-интерфейс), описаны в [SSoT: macvlan](../../Docker/Docker_network/drivers/macvlan.md).

### Обнаружение MAC-спуфинга и инструменты анализа
```bash
# arpwatch: мониторинг изменений MAC/IP пар
sudo arpwatch -i eth0

# macof (из dsniff): генерация случайных MAC для тестирования порта security
sudo macof -i eth0

# ettercap: ARP spoofing detection и MITM анализ
sudo ettercap -T -q -i eth0

# nmap: определение MAC через ARP ping
sudo nmap -sn -PR 192.168.1.0/24

# Wireshark: экспорт списка MAC
tshark -r capture.pcap -T fields -e eth.src -e eth.dst | sort | uniq
```

## Валидация

### Проверка корректности изменения MAC
1.  **Проверка текущего MAC:** `ip link show eth0 | grep link/ether` — адрес должен совпадать с заданным.
2.  **Проверка UAA/LAA:** Первый байт адреса. Если второй младший бит (U/L) равен `1` — адрес локально назначенный (LAA). Например, `02:01:02:03:04:05` — LAA, так как `02` в двоичном виде `00000010`, бит 1 = 1.
3.  **Проверка доступности:** После смены MAC выполните `ping` до шлюза или другого узла в сети.
4.  **Проверка на конфликты:** Запустите `tcpdump` или `tshark` на несколько секунд и проверьте, нет ли ARP-реплаев с тем же IP, но другим MAC.

### Проверка CAM-таблицы коммутатора
```bash
# Linux Bridge
bridge fdb show
bridge fdb show dev br0

# Cisco
show mac address-table dynamic
show mac address-table count

# Aruba/HPE
show mac-address

# Juniper
show ethernet-switching table
```

### Проверка EUI-64 (IPv6)
```bash
# Получение IPv6-адреса и проверка формирования EUI-64
ip -6 addr show eth0

# Ручная проверка: замените FF:FE и инвертируйте 7-й бит первого байта
# Например: 00:11:22:33:44:55 -> 02:11:22:FF:FE:33:44:55
```

### Проверка Port Security
```bash
# Cisco
show port-security interface GigabitEthernet0/1
show port-security address

# Arista
show port-security
show port-security interface Ethernet1

# Linux (ebtables)
sudo ebtables -L
```

## Диагностика и устранение неисправностей

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `RTNETLINK answers: Operation not supported` | Драйвер NIC не поддерживает изменение MAC | Использовать `macvlan` или изменить MAC на коммутаторе (LAA на порту) |
| `RTNETLINK answers: Device or resource busy` | Интерфейс не опущен перед сменой MAC | `ip link set dev eth0 down` перед изменением |
| `RTNETLINK answers: Cannot assign requested address` | Некорректный формат MAC или зарезервированный адрес | Проверить формат (6 байт, шестнадцатеричные цифры) |
| Потеря связности после смены MAC | Конфликт MAC или блокировка на коммутаторе | Проверить `bridge fdb show`, `show mac address-table` |
| DHCP не работает после смены MAC | DHCP-сервер привязал старый MAC к записи | Очистить запись на DHCP-сервере или использовать статический IP |
| MAC flapping в логах | Дублирование MAC на разных портах | Проверить петли L2, дубликаты адресов, заменить проблемный кабель/NIC |
| `Port Security` violation | Подключено больше MAC, чем разрешено | Проверить лимит, использовать sticky MAC или увеличить maximum |
| `arpwatch` duplicate IP alert | Два хоста используют один IP | Найти конфликтующий MAC через `ip neigh show` и `arp -a` |
| `ethtool -P` показывает другой MAC, чем `ip link` | NIC в режиме passthrough/vmware flexible | Проверить конфигурацию гипервизора |

### Инструменты анализа

```bash
# Статистика ошибок интерфейса (дропы, коллизии, CRC)
ethtool -S eth0

# Просмотр всех событий интерфейса (flapping, duplex mismatch)
ip monitor link

# Журналы ядра о MAC-адресах и линках
dmesg | grep -i "mac\|link\|eth"

# Wireshark/tshark: фильтр по MAC
tshark -i eth0 -Y "eth.dst == 00:11:22:33:44:55"

# Проверка состояния порта (Link, Speed, Duplex)
ethtool eth0
```

### Диагностика MAC Flapping
```bash
# Linux: мониторинг FDB на мосту
bridge fdb show | grep 00:11:22:33:44:55

# Cisco: поиск флапов
show logging | include MACFLAP
show mac address-table address 00:11:22:33:44:55

# Aruba/HPE
show mac-address | include 0011.2233.4455
show mac-address vlan 10

# Juniper
show ethernet-switching table | match 52:54:00:12:34:56
```

### Диагностика «невидимых» проблем L2
Когда IP настраивается, но связь отсутствует или периодически замирает (микро-фризы SSH/VoIP):
1.  Проверьте состояние линка: `ethtool eth0`.
2.  Проверьте duplex mismatch: `ethtool -S eth0 | grep -i "err\|drop\|coll"`.
3.  Проверьте ARP-таблицу: `ip n`. Если записи в состоянии `INCOMPLETE` или `FAILED` — проблема на L2.
4.  Проверьте MAC-таблицу коммутатора: `show mac address-table dynamic | include <MAC>`.
5.  Если MAC постоянно пропадает или «прыгает» между портами — проблема в сегментации, петле L2 или нестабильном линке.
6.  Запустите `tcpdump -i eth0 -e arp` для отслеживания ARP-запросов без ответов.

## Особые случаи и ограничения

*   **Ограничение на количество MAC на порт (Cloud):** Публичные облака (AWS, GCP, Azure) часто ограничивают количество MAC-адресов на один vNIC/ENI. При превышении лимита пакеты отбрасываются. Решение — использовать `ipvlan` (L3 mode) или запросить увеличение лимита через API облака.
*   **Wi-Fi и рандомизация:** В режиме Infrastructure Wi-Fi клиент не может свободно выбирать MAC после ассоциации. AP ассоциирует клиента по MAC. Рандомизация работает на этапе сканирования (Probe Request), а после ассоциации часто используется реальный MAC (зависит от ОС и настроек).
*   **Порты uplink:** На некоторых коммутаторах порты uplink (между коммутаторами) не поддерживают Port Security, так как между ними постоянно проходит множество MAC-адресов.
*   **Гибкие MAC-адреса (VMware):** В виртуальных средах VMware позволяет настроить «Adapters: Flexible», который при миграции VM автоматически обновляет MAC на целевом хосте.
*   **Дублирование MAC в кластерах:** В некоторых реализациях кластеров (Pacemaker/Corosync) на разных узлах может использоваться один MAC на виртуальном интерфейсе, что требует настройки Gratuitous ARP и поддержки на коммутаторе.
*   **MAC-адреса в IPv6-средах:** При использовании Stable Privacy (RFC 7217) MAC-адрес не участвует в формировании IPv6-адреса, что усложняет диагностику. Используйте `ip -6 addr show` для просмотра сгенерированных адресов.
*   **Контейнеризация и Kubernetes:** В Kubernetes CNI-плагинах (Calico, Cilium) MAC-адреса управляются автоматически. Ручная смена MAC может привести к нарушению работы CNI и потере связности пода.
*   **VXLAN/EVPN:** В overlay-сетях MAC-адреса конечных устройств "распространяются" через BGP. Некорректная настройка EVPN может привести к "MAC flapping" между VTEP-терминалами.

## Best Practices

*   **Используйте LAA вместо UAA** только при необходимости (отладка, обход ограничений). UAA обеспечивает глобальную уникальность и упрощает диагностику.
*   **Назначайте MAC-адреса статически** на критическую инфраструктуру (серверы, маршрутизаторы) для предотвращения сбоев после замены оборудования или миграций.
*   **Включайте Port Security** на access-портах коммутаторов с ограничением `maximum 1` для конечных узлов. Используйте `sticky` для автоматического обучения.
*   **В публичных облаках** используйте `ipvlan` вместо `macvlan`, если провайдер ограничивает количество MAC на порт.
*   **Не изменяйте MAC-адрес в production** без проверки impact на DHCP-серверы, IP Source Guard и системы мониторинга.
*   **Для IPv6** используйте Stable Privacy (RFC 7217) вместо EUI-64 по умолчанию, чтобы предотвратить отслеживание хоста.
*   **Мониторьте CAM-таблицу** на коммутаторах регулярно: `show mac address-table count` (Cisco) для проверки заполненности.
*   **Настройка ageing time:** В больших сетях с мобильными устройствами уменьшайте ageing time (например, до 60 секунд), чтобы CAM-таблица быстрее обновлялась. В стабильных сетях можно увеличить до 600–1800 секунд для снижения overhead.
*   **Используйте MACsec** для чувствительных к безопасности сегментов (финансы, государственные структуры), особенно при наличии требований FIPS/PCI-DSS.
*   **Kubernetes:** Не изменяйте MAC-адреса интерфейсов внутри пода — это нарушит работу CNI. Используйте NetworkPolicy для изоляции на L3/L4.
*   **Документируйте** назначенные MAC-адреса в CMDB, особенно для критической инфраструктуры.

## Дополнительная информация

*   [Канальный уровень (Data Link Layer)](../OSI_TCP_IP_Model/data_link_layer.md) — детали работы коммутации.
*   [Протокол ARP](../Protocols/arp.md) — связывание IP и MAC-адресов.
*   [Ethernet — основы](../Protocols/ethernet.md) — формат кадра и L2-среда.
