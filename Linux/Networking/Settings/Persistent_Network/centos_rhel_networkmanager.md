# NetworkManager в RHEL/CentOS

**NetworkManager** — это динамическая система управления сетью, являющаяся стандартом в дистрибутивах семейства RHEL (Red Hat Enterprise Linux), включая CentOS Stream, AlmaLinux и Rocky Linux. Начиная с RHEL 9, NetworkManager стал единственным поддерживаемым инструментом, полностью вытеснив устаревшие скрипты `network-scripts` (ifcfg).

## Определения

- **NetworkManager** — системная служба, управляющая сетевыми интерфейсами, профилями соединений и состоянием линков. Взаимодействует с ядром через D-Bus и udev.
- **Active Connection (Активное соединение)** — экземпляр соединения, привязанный к конкретному устройству и находящийся в состоянии `activated`.
- **nmcli (Network Manager Command Line Interface)** — основной инструмент командной строкы для императивного управления сетью. Поддерживает три режима: `general` (состояние службы), `device` (устройства), `connection` (профили).
- **nmtui (Network Manager Text User Interface)** — интерактивный текстовый интерфейс для базовой настройки.
- **Keyfile** — современный формат хранения конфигурации (`.nmconnection`), представляющий собой INI-подобный файл с секциями `[connection]`, `[ipv4]`, `[ipv6]`, `[ethernet]` и др. В RHEL 9+ является форматом по умолчанию.
- **Nmstate** — декларативный API и библиотека для управления сетевыми настройками через YAML/JSON. Позволяет описывать "желаемое состояние" сети независимо от бэкенда.
- **Dispatcher-скрипт** — исполняемый файл в `/etc/NetworkManager/dispatcher.d/`, получающий аргументы `<interface> <action>` и выполняющий действия при изменении состояния интерфейса.
- **NetworkManager-cloud-setup** — специализированный компонент для автоматической настройки вторичных IP-адресов и маршрутов в облачных окружениях (AWS, Azure, GCP).

## Базовые концепции

NetworkManager разделяет **устройства** (физические адаптеры) и **соединения** (профили настроек). Одно устройство может иметь множество профилей, но активно одновременно только одно соединение.

### Архитектура и жизненный цикл

NetworkManager работает как демон (`NetworkManager.service`), взаимодействующий с подсистемой ядра через D-Bus. Основные компоненты:

- **Служба:** отслеживает линки, управляет DHCP-клиентом и применяет профили.
- **D-Bus интерфейс:** `org.freedesktop.NetworkManager` — позволяет внешним инструментам (`nmcli`, `nmtui`, настройки GNOME) управлять сетью.
- **udev:** отслеживает появление/исчезновение устройств и инициирует автоматическое поднятие подходящих соединений.
- **Dispatcher:** хуки в `/etc/NetworkManager/dispatcher.d/`, выполняемые при изменении состояния интерфейса.

Жизненный цикл соединения:
1. **Создание:** `nmcli connection add` создаёт профиль в памяти и на диске.
2. **Активация:** `nmcli connection up` или авто-поднятие. NM проверяет зависимость от устройства, выделяет ресурсы, запускает DHCP или применяет статику.
3. **Активировано (activated):** устройство имеет IP, маршруты, DNS. Трафик разрешён.
4. **Деактивация:** `nmcli connection down` или удаление устройства. NM освобождает ресурсы.
5. **Удаление:** `nmcli connection delete` удаляет профиль с диска.

Для обеспечения зависимости от сети при загрузке используется `NetworkManager-wait-online.service`, который блокирует `network-online.target` до достижения состояния `connected` или `completed`.

### Хранение конфигурации

| Версия | Формат хранения | Директория |
| :--- | :--- | :--- |
| **RHEL 9+** | **Keyfile** | `/etc/NetworkManager/system-connections/*.nmconnection` |
| **RHEL 7/8** | **ifcfg** | `/etc/sysconfig/network-scripts/ifcfg-*` |

**Важно:** В RHEL 9 формат `ifcfg` объявлен устаревшим (**deprecated**). В RHEL 10 поддержка `ifcfg` полностью удалена. Для миграции существующих соединений в современный формат используйте команду:
```bash
sudo nmcli connection migrate
```

**Пример Keyfile** (`/etc/NetworkManager/system-connections/eth0.nmconnection`):
```ini
[connection]
id=eth0
type=ethernet
interface-name=eth0
permissions=

[ipv4]
method=manual
address1=192.168.1.100/24,192.168.1.1
dns=1.1.1.1;
dns-search=example.com;

[ipv6]
method=auto

[ethernet]
mtu=1500
cloned-mac-address=00:11:22:33:44:55
```

Файлы keyfile имеют права `0600` и владельца `root:root`, так как содержат конфиденциальные данные (ключа не имеет, но могут хранить пароли Wi-Fi).

### Версионная совместимость и отличия дистрибутивов

| Дистрибутив / Версия | NetworkManager | Формат по умолчанию | Особенности |
| :--- | :--- | :--- | :--- |
| **RHEL / CentOS Stream 7** | 1.18.x | ifcfg | Legacy, требует `network-scripts` |
| **RHEL / CentOS Stream 8** | 1.22.x | ifcfg / Keyfile | Параллельная поддержка |
| **RHEL / AlmaLinux / Rocky 9** | 1.40.x | Keyfile | `ifcfg` deprecated |
| **RHEL / AlmaLinux / Rocky 10** | 1.44.x+ | Keyfile | `ifcfg` удалён, `teamd` удалён |

В **Fedora** NetworkManager также стандартен, но использует более актуальные версии; синтаксис `nmcli` идентичен RHEL.

### Декларативное управление (Nmstate)

Nmstate позволяет избежать выполнения множества команд `nmcli`. Вместо этого администратор создает YAML-файл с описанием всей сетевой топологии. Это идеальный подход для автоматизации через Ansible или Terraform.

```bash
# Проверка текущего состояния интерфейса
nmstatectl show eth0

# Применение YAML-файла с желаемым состоянием
sudo nmstatectl apply bridge.yaml
```

Поддерживаемые типы интерфейсов: `ethernet`, `linux-bridge`, `linux-bond`, `vlan`, `vrf`, `ip-tunnel` (GRE, IPIP, VTI).

### Справочник: основные типы соединений nmcli

| Тип (`type`) | Назначение | Пример |
| :--- | :--- | :--- |
| `ethernet` | Физический адаптер | `nmcli connection add type ethernet ...` |
| `bridge` | Мост (L2) | `nmcli connection add type bridge ...` |
| `bond` | Агрегация каналов | `nmcli connection add type bond ...` |
| `vlan` | Виртуальная сеть 802.1Q | `nmcli connection add type vlan ...` |
| `vrf` | Виртуальная маршрутизация | `nmcli connection add type vrf ...` |
| `ip-tunnel` | Тоннель (GRE, IPIP) | `nmcli connection add type ip-tunnel ...` |
| `wifi` | Беспроводная сеть | `nmcli connection add type wifi ...` |
| `team` | **Устарел** (удалён в RHEL 10) | Не использовать |

## Практические сценарии

### 1. Базовое управление (nmcli)

```bash
# Состояние всех устройств (кратко)
nmcli device status

# Полная информация о конкретном интерфейсе
nmcli device show eth0

# Список всех профилей соединений
nmcli connection show
```

### 2. Настройка статического IP и DNS (IPv4 и IPv6)

Для RHEL 9+ рекомендуется явно указывать параметры для обоих стеков.

```bash
# Настройка IPv4
sudo nmcli connection modify 'eth0' \
    ipv4.method manual \
    ipv4.addresses 192.168.1.100/24 \
    ipv4.gateway 192.168.1.1 \
    ipv4.dns "1.1.1.1,8.8.8.8"

# Настройка IPv6 (SLAAC + Static)
sudo nmcli connection modify 'eth0' \
    ipv6.method auto \
    ipv6.addresses "2001:db8::100/64"

# Применение изменений
sudo nmcli connection up 'eth0'
```

### 3. Декларативная настройка через Nmstate (Bridge)

Пример YAML-файла (`bridge.yaml`) для создания сетевого моста:

```yaml
interfaces:
  - name: br0
    type: linux-bridge
    state: up
    ipv4:
      enabled: true
      address:
        - ip: 192.168.100.1
          prefix-length: 24
      dhcp: false
    bridge:
      port:
        - name: eth1
```
Применение: `sudo nmstatectl apply bridge.yaml`

### 4. Настройка агрегации каналов (Bonding)

> **Внимание:** Технология **Teaming** (`teamd`) признана устаревшей в RHEL 9 и удалена в RHEL 10. Всегда используйте **Bonding**.

```bash
# 1. Создание мастер-интерфейса (LACP)
sudo nmcli connection add type bond con-name bond0 ifname bond0 mode 802.3ad

# 2. Добавление портов (slaves)
sudo nmcli connection add type ethernet con-name bond0-port1 ifname eth1 master bond0
sudo nmcli connection add type ethernet con-name bond0-port2 ifname eth2 master bond0

# 3. Настройка IP и запуск
sudo nmcli connection modify bond0 ipv4.addresses 10.0.0.10/24 ipv4.method manual
sudo nmcli connection up bond0
```

### 5. Настройка VRF (Изоляция маршрутизации)

Используется для разделения трафика управления и трафика данных. Подробнее: **[VRF в Linux](../../../../Linux/Networking/vrf.md)**.

```bash
# Создание VRF с таблицей маршрутизации 100
sudo nmcli connection add type vrf ifname vrf100 con-name vrf100 table 100

# Привязка интерфейса к VRF
sudo nmcli connection modify 'eth1' connection.slave-type vrf connection.master vrf100

# Запуск команды внутри VRF
ip vrf exec vrf100 curl icanhazip.com
```

### 6. Маршрутизация на основе политик (PBR)

Добавление правил маршрутизации через `nmcli` (сохраняется в профиле соединения). Подробнее: **[Администрирование PBR](../../../../Linux/Networking/Policy_Based_Routing/administration.md)**.

```bash
# Создание таблицы маршрутизации 200 для трафика из специфической подсети
sudo nmcli connection modify 'eth0' \
    +ipv4.routing-rules "from 172.16.1.0/24 table 200" \
    +ipv4.routes "0.0.0.0/0 172.16.1.254 table 200"

sudo nmcli connection up 'eth0'
```

### 7. Облачные настройки (NM-cloud-setup)

В публичных облаках (AWS, Azure) NetworkManager может автоматически настраивать вторичные интерфейсы:
```bash
# Включение автоматической настройки для всех интерфейсов
sudo systemctl enable --now nm-cloud-setup.service
sudo systemctl enable --now nm-cloud-setup.timer
```

### 8. Интеграция с systemd-resolved

Чтобы NetworkManager корректно передавал настройки DNS в `systemd-resolved`, проверьте конфиг:

```ini
# /etc/NetworkManager/conf.d/10-dns-resolved.conf
[main]
dns=systemd-resolved
```

### 9. Использование скриптов-диспетчеров

Dispatcher-скрипты позволяют выполнять действия при смене статуса интерфейса.

Пример скрипта (`/etc/NetworkManager/dispatcher.d/99-custom-log`):
```bash
#!/bin/bash
INTERFACE=$1
ACTION=$2

logger "NetworkManager: Interface $INTERFACE is $ACTION"
```
Не забудьте установить права: `sudo chmod +x /etc/NetworkManager/dispatcher.d/99-custom-log`

**Скрипт для безопасного обновления конфигурации при активном SSH:**

```bash
#!/bin/bash
# /etc/NetworkManager/dispatcher.d/99-ssh-safe-upgrade
# Проверяет наличие резервного интерфейса перед применением критичных изменений

INTERFACE=$1
ACTION=$2

# Только для событий "down"
if [ "$ACTION" = "down" ]; then
    # Проверяем количество активных интерфейсов с IP
    ACTIVE_IPS=$(ip -4 -o addr show | grep -v "127.0.0.1" | grep "inet " | wc -l)
    
    if [ "$ACTIVE_IPS" -eq 0 ]; then
        logger "CRITICAL: All interfaces lost IP after $INTERFACE down. Possible lockout."
        # Можно добавить алерт через webhook или email
    fi
fi
```

**Скрипт для автоматического перезапуска сервисов при смене IP:**

```bash
#!/bin/bash
# /etc/NetworkManager/dispatcher.d/98-restart-services
INTERFACE=$1
ACTION=$2

if [ "$ACTION" = "up" ]; then
    # Перезапуск сервисов, привязанных к интерфейсу
    systemctl restart haproxy 2>/dev/null
    systemctl restart keepalived 2>/dev/null
fi
```

### 10. Валидация конфигурации и тестирование перед применением

Перед применением изменений проверяйте синтаксис и simulate:

```bash
# Проверка синтаксиса конкретного соединения
sudo nmcli connection show "eth0" | grep -E "ipv4|ipv6|802-3-ethernet"

# Dry-run: показать что изменится (nmcli не имеет нативного dry-run, используйте сравнение)
sudo nmcli -f all connection show "eth0" > /tmp/before.txt
# ... внесите изменения ...
sudo nmcli -f all connection show "eth0" > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt

# Проверка routable состояния после применения
sudo nmcli connection up "eth0"
networkctl status eth0
ip route show dev eth0
```

### 11. DHCP с опциями (domain-search, ntp-servers, static routes)

Для параметров, передаваемых через DHCP-запрос:

```bash
sudo nmcli connection modify 'eth0' \
    ipv4.method auto \
    ipv4.dhcp-hostname "server01" \
    ipv4.dhcp-vendor-class-identifier "myorg" \
    ipv4.dns-search "example.com,corp.example.com" \
    ipv4.dns "10.0.0.2 10.0.0.3" \
    +ipv4.routes "10.10.0.0/16 192.168.1.254"
```

### 12. Несколько IP-адресов (алиасы)

NetworkManager поддерживает несколько адресов в одном соединении:

```bash
# Добавление вторичного IP
sudo nmcli connection modify 'eth0' \
    +ipv4.addresses "192.168.1.100/24" \
    +ipv4.addresses "10.0.0.10/24" \
    ipv4.method manual

# Проверка
nmcli device show eth0 | grep IP4.ADDRESS
# → IP4.ADDRESS[1]: 192.168.1.100/24
# → IP4.ADDRESS[2]: 10.0.0.10/24
```

### 13. Bridge с VLAN filtering через nmcli

Создание моста с включённым VLAN filtering (аналог `bridge-vlan-aware yes`):

```bash
# 1. Создание моста с VLAN-aware режимом
sudo nmcli connection add type bridge ifname br0 con-name br0 \
    bridge.vlan-aware yes \
    bridge.default-pvid 1 \
    bridge.stp no \
    bridge.priority 32768

# 2. Добавление порта (eth1) в мост
sudo nmcli connection add type ethernet con-name br0-eth1 ifname eth1 master br0

# 3. Настройка PVID и tagged VLAN на порту
sudo nmcli connection modify br0-eth1 \
    bridge-port.vlans "100,200 egress-tagged"

# 4. IP-адрес на мосте
sudo nmcli connection modify br0 ipv4.addresses 192.168.100.1/24 ipv4.method manual

# 5. Активация
sudo nmcli connection up br0
sudo nmcli connection up br0-eth1
```

Для глубокой диагностики VLAN: **[VLAN в Linux: диагностика](../../../../Networking/Protocols/VLAN/vlan_linux_diagnostics.md)**.

### 14. Bonding с расширенными LACP-параметрами

Для тонкой настройки bonding используйте `bond.options`:

```bash
# Создание bond0 с LACP и хешированием layer3+4
sudo nmcli connection add type bond con-name bond0 ifname bond0 mode 802.3ad

# Настройка параметров (проверьте supported-params через /sys)
sudo nmcli connection modify bond0 \
    bond.options "miimon=100,xmit_hash_policy=layer3+4,lacp_rate=fast,ad_select=bandwidth"

# Добавление портов
sudo nmcli connection add type ethernet con-name bond0-p1 ifname eth1 master bond0
sudo nmcli connection add type ethernet con-name bond0-p2 ifname eth2 master bond0

# IP и активация
sudo nmcli connection modify bond0 ipv4.addresses 10.0.0.10/24 ipv4.method manual
sudo nmcli connection up bond0

# Валидация
cat /sys/class/net/bond0/bonding/ad_aggregator
cat /sys/class/net/bond0/bonding/ad_num_ports
```

Полная теория агрегации: **[Агрегация каналов (Bonding)](../../../../Networking/Concepts/link_aggregation.md)**.

### 15. MTU и MAC-адрес

```bash
# Установка MTU (jumbo frames для хранилища/NVMe over Fabrics)
sudo nmcli connection modify 'eth0' 802-3-ethernet.mtu 9000
sudo nmcli connection up 'eth0'

# Клонирование MAC-адреса (MAC-спуфинг)
sudo nmcli connection modify 'eth0' 802-3-ethernet.cloned-mac-address 02:01:02:03:04:05
sudo nmcli connection up 'eth0'

# Проверка текущего HWADDR устройства
nmcli device show eth0 | grep GENERAL.HWADDR
```

### 16. Расширенные маршруты и метрики

```bash
# Добавление статического маршрута с метрикой
sudo nmcli connection modify 'eth0' \
    +ipv4.routes "10.20.0.0/16 192.168.1.254 100" \
    +ipv4.routes "172.16.0.0/12 192.168.1.254 200"

# Маршрут по умолчанию с метрикой (если несколько шлюзов)
sudo nmcli connection modify 'eth0' ipv4.gateway 192.168.1.1
sudo nmcli connection modify 'backup' ipv4.gateway 192.168.1.2 ipv4.route-metric 500

# Проверка таблицы маршрутизации
ip route show
```

### 17. Аварийный доступ и откат

Если после применения конфигурации SSH доступ пропал:

```bash
# 1. Откатить соединение на предыдущее состояние
sudo nmcli connection up "eth0"  # предыдущее имя соединения
# или
sudo nmcli connection reload

# 2. Если NM вообще не отвечает, переключитесь на консоль/VNC/ILO

# 3. Откат keyfile (если редактировали вручительно)
sudo cp /root/eth0.nmconnection.bak /etc/NetworkManager/system-connections/eth0.nmconnection
sudo chmod 600 /etc/NetworkManager/system-connections/eth0.nmconnection
sudo nmcli connection reload
sudo nmcli connection up eth0

# 4. Для классического отката оставьте хотя бы один интерфейс с DHCP:
# systemd-networkd или ifupdown могут параллельно управлять другими интерфейсами.
```

### 18. Ansible / IaC

Современный подход — управление через `nmcli` модуль Ansible. Подробные сценарии, валидация и troubleshooting см. в [Ansible: Модули управления сетевой конфигурацией Linux](../../Ansible/Modules/ansible_network_configuration_modules.md).

Для комплексного управления через Nmstate используйте модуль `nmstate.apply` из коллекции `nmstate.nmstate`.

### 19. Прямое редактирование Keyfile

В редких случаях удобнее редактировать файл напрямую:

```bash
# 1. Создайте бэкап
sudo cp /etc/NetworkManager/system-connections/eth0.nmconnection \
        /root/eth0.nmconnection.bak.$(date +%F)

# 2. Редактируйте (права root!)
sudo vi /etc/NetworkManager/system-connections/eth0.nmconnection

# 3. Проверьте синтаксис
sudo nmcli -g all connection show "eth0" >/dev/null

# 4. Примените
sudo nmcli connection reload
sudo nmcli connection up eth0
```

### 20. Интеграция с FirewallD

NetworkManager автоматически добавляет интерфейсы в зону `firewalld` при поднятии соединения:

```bash
# Установка зоны для конкретного соединения
sudo nmcli connection modify 'eth0' connection.zone "external"

# Применение
sudo nmcli connection up 'eth0'

# Проверка
firewall-cmd --get-active-zones
# → external: interfaces: eth0
```

## Дополнительная информация

### Диагностика и отладка

| Задача | Команда |
| :--- | :--- |
| Состояние всех устройств | `nmcli device status` |
| Подробная информация об устройстве | `nmcli device show eth0` |
| Все параметры соединения | `nmcli -f all connection show "eth0"` |
| Статус соединения (упрощённо) | `nmcli connection show --active` |
| Логирование в реальном времени | `journalctl -u NetworkManager -f` |
| Логи по конкретному устройству | `journalctl -u NetworkManager | grep -i eth0` |
| Включение Debug-режима | `nmcli general logging level DEBUG` |
| Проверка скриптов-диспетчеров | `ls -la /etc/NetworkManager/dispatcher.d/` |
| Состояние bonding | `cat /sys/class/net/bond0/bonding/*` |
| Проверка DNS, используемого NM | `resolvectl status eth0` или `nmcli device show eth0 \| grep DNS` |

### Типовые ошибки и решения

- **Проблема:** `nmcli connection up` не применяет маршрут.
  - **Решение:** Убедитесь, что используется `+ipv4.routes` (плюс добавляет, а не заменяет). Проверьте, что соединение действительно активно (`nmcli connection show --active`).
- **Проблема:** После изменения MTU в keyfile NM игнорирует его.
  - **Решение:** Используйте `nmcli connection modify ... 802-3-ethernet.mtu 9000`, а не прямое редактирование keyfile. После ручного редактирования выполните `nmcli connection reload`.
- **Проблема:** DNS не обновляется.
  - **Решение:** Проверьте `resolvectl dns eth0` (если systemd-resolved) или `/etc/resolv.conf`. Убедитесь, что в NM включён `dns=default` или `dns=systemd-resolved`, а не `dns=none`.
- **Проблема:** Bond не поднимается, коммутатор видит порты как individual.
  - **Решение:** Проверьте на коммутаторе LACP (mode 4 / active). Проверьте `cat /sys/class/net/bond0/bonding/ad_aggregator`. Если пусто — LACP не настроен.
- **Проблема:** Bridge не передаёт VLAN-трафик.
  - **Решение:** В RHEL 9+ мост по умолчанию не VLAN-aware. Добавьте `bridge.vlan-aware yes` и пересоздайте мост.
- **Проблема:** `NetworkManager-wait-online.service` зависает при загрузке.
  - **Решение:** Увеличьте таймаут через `TimeoutStartSec` в override, или отключите службу, если загрузка сети не блокирует ваши сервисы.
- **Проблема:** Соединение исчезает после перезагрузки.
  - **Решение:** Проверьте права на keyfile (`0600 root:root`), проверьте что соединение имеет `autoconnect yes`, и что устройство существует в udev.
- **Проблема:** NM конфликтует с systemd-networkd.
  - **Решение:** Отключите `systemd-networkd` (`systemctl disable --now systemd-networkd`) или настройте `unmanaged-devices` в `/etc/NetworkManager/conf.d/`, чтобы NM игнорировал нужные интерфейсы.

### См. также

- **[Постоянная настройка сети](./index.md)** — сравнение менеджеров и выбор инструмента.
- **[Link Aggregation (Bonding)](../../../../Networking/Concepts/link_aggregation.md)** — глубокое погружение в режимы бондинга и тюнинг bonding.
- **[VRF (Virtual Routing and Forwarding)](../../../../Linux/Networking/vrf.md)** — изоляция таблиц маршрутизации.
- **[sysctl: сетевые параметры ядра](../sysctl_network.md)** — параметры ядра, критичные для NetworkManager.
- **[Диагностика persistent-конфигурации](./persistent_network_troubleshooting.md)** — flowchart и типичные сценарии.
- **[DHCP-клиенты Linux](../../Services/DHCP/dhcp_clients_comparison.md)** — встроенный DHCP-клиент NM vs dhclient.
