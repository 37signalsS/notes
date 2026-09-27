# Debian/Ubuntu: /etc/network/interfaces

**Файл /etc/network/interfaces** — основной конфигурационный файл для управления сетевыми интерфейсами в дистрибутивах семейства Debian. Он используется пакетом **ifupdown** (классический) или **ifupdown2** (современный). Это императивный подход к настройке сети, при котором параметры каждого интерфейса описываются в виде строф (stanzas).

## Определения

- **ifupdown / ifupdown2** — набор утилит (`ifup`, `ifdown`, `ifquery`, `ifreload`) для управления сетевыми интерфейсами на основе конфигурации.
- **ifupdown2** — современная реализация на Python, поддерживающая применение настроек без перезагрузки интерфейсов (`ifreload -a`) и понимающая сложные зависимости (мосты поверх бондов и т.д.). Стандарт для **Proxmox VE**.
- **Stanza (Строфа)** — логический блок конфигурации, начинающийся с ключевого слова (например, `iface`, `auto`, `allow-hotplug`).
- **VRF (Virtual Routing and Forwarding)** — технология, позволяющая создавать несколько изолированных таблиц маршрутизации на одном физическом хосте. Полностью поддерживается в `ifupdown2`.
- **JSON Output** — возможность `ifupdown2` выводить информацию о состоянии интерфейсов в формате JSON (`ifquery -j`), что удобно для автоматизации и интеграции.
- **Bonding (Агрегация каналов)** — объединение нескольких физических интерфейсов в один логический для повышения пропускной способности или отказоустойчивости.
- **Bridge (Мост)** — программный коммутатор, объединяющий интерфейсы в одну L2-сеть. См. **[Linux Bridge](../../Concepts/linux_bridge.md)**.
- **VLAN (Virtual LAN)** — технология создания виртуальных сетей внутри одного физического канала (стандарт 802.1Q).
- **interfaces(5)** — man-страница формата файла `/etc/network/interfaces`.
- **resolvconf** — пакет/сервис, управляющий `/etc/resolv.conf` от нескольких источников (DHCP, статические DNS).
- **/etc/network/interfaces.d/** — каталог для модульных фрагментов конфигурации, подключаемых через `source`.
- **mapping** — паттерн `ifupdown2` для динамического сопоставления имён интерфейсов (например, по MAC или ID).
- **networking.service** — systemd-юнит, отвечающий за поднятие интерфейсов при загрузке в классическом `ifupdown`.

## Базовые концепции

### Структура файла и подключение конфигов

Современный стандарт подразумевает использование модульной структуры.

```ini
# /etc/network/interfaces

# Подключение всех файлов из директории
source /etc/network/interfaces.d/*

# Настройка локальной петли (обязательно)
auto lo
iface lo inet loopback
```

### Синтаксис файла и приоритеты

Файл `/etc/network/interfaces` чувствителен к форматированию:

- **Отступы:** используются только пробелы (рекомендуется 4); табуляция запрещена и приводит к ошибке парсинга.
- **Многострочные значения:** для переноса строки используется обратный слеш `\` в конце строки.
- **Комментарии:** символ `#` до конца строки; внутри секции `mapping` комментарии не поддерживаются в `ifupdown`.
- **Директива `source`:** подключает файлы по glob-шаблону; файлы обрабатываются в лексикографическом порядке по имени. Конфликты решаются по принципу «позже = приоритетнее».
- **Порядок обработки:** внутри одного файла строфы обрабатываются в порядке их появления. При изменении порядок следования `auto` и `iface` для одного интерфейса имеет значение.

### Основные директивы управления

| Директива | Описание |
| :--- | :--- |
| **`auto`** | Поднимает интерфейс при загрузке системы (`ifup -a`). |
| **`allow-hotplug`** | Поднимает интерфейс при обнаружении события от ядра (подключение кабеля). |
| **`iface`** | Основная строфа: `iface <имя> <семейство> <метод>`. |
| **`pre-up`** | Команда, выполняемая перед поднятием интерфейса. При ошибке (`exit != 0`) поднятие прерывается. |
| **`post-up`** | Команда, выполняемая после успешного поднятия интерфейса. |
| **`pre-down`** | Команда перед опусканием интерфейса. |
| **`post-down`** | Команда после опускания интерфейса. |
| **`hwaddress`** | Принудительное задание MAC-адреса (режим `ether`). |
| **`mtu`** | Установка MTU для интерфейса (например, `mtu 9000` для jumbo-frames). |
| **`dns-nameservers`** | Список DNS-серверов (передаётся в `resolvconf`). |
| **`dns-search`** | DNS-суффиксы для поиска имён. |
| **`vlan-raw-device`** | Родительское устройство для VLAN-интерфейса. |

- **Семейства:** `inet` (IPv4), `inet6` (IPv6).
- **Методы:** `static`, `dhcp`, `manual` (для интерфейсов без IP, входящих в мост), `loopback`.

### Жизненный цикл загрузки и systemd-интеграция

При использовании классического `ifupdown` загрузка сети происходит через `networking.service`:

```ini
# /lib/systemd/system/networking.service
[Unit]
Description=Raise network interfaces
After=local-fs.target
Wants=local-fs.target
```

Служба запускает `ifup -a --read-environment`, который поднимает все интерфейсы с директивой `auto`. Для обеспечения корректных зависимостей между службами используйте:

```ini
# В Unit-файле вашего сервиса
[Unit]
After=network-online.target
Wants=network-online.target
```

`network-online.target` достигается, когда все интерфейсы с `auto` перешли в состояние `routable` (если используется `systemd-networkd`) или просто подняты (в случае `ifupdown`). Для `ifupdown` нет встроенного wait-online; его роль выполняет сам `networking.service`.

### DNS и разрешение имён

Директивы `dns-nameservers`, `dns-search` и `dns-domain` передаются пакету **resolvconf**, который обновляет `/etc/resolv.conf` от всех источников (DHCP, статика, VPN). В системах с `systemd-resolved` resolvconf может быть перенаправлен в resolved через symlink или настройку `DNS=` в NetworkManager.

Если `resolvconf` не установлен, изменения в `/etc/network/interfaces` не попадут в `/etc/resolv.conf`. Проверка:

```bash
# Установка resolvconf
sudo apt install resolvconf

# Статус
systemctl status resolvconf
# → Active: active (running)
```

## Практические сценарии

### 1. Статическая настройка Dual-stack (IPv4 и IPv6)

Пример настройки одного интерфейса для работы в обеих сетях.

```ini
auto eth0
iface eth0 inet static
    address 192.168.1.10/24
    gateway 192.168.1.1
    # DNS-серверы (пакет resolvconf)
    dns-nameservers 8.8.8.8 1.1.1.1
    dns-search corp.internal

iface eth0 inet6 static
    address 2001:db8::10/64
    gateway 2001:db8::1
```

### 2. Создание сетевого моста (Bridge) и VLAN-aware

Конфигурация для систем виртуализации, позволяющая прокидывать тегированные сети внутрь ВМ.

```ini
auto vmbr0
iface vmbr0 inet static
    address 10.0.0.10/24
    gateway 10.0.0.1
    bridge-ports eth0
    bridge-stp off
    bridge-fd 0
    # Включение фильтрации VLAN (vlan-aware)
    bridge-vlan-aware yes
    bridge-vids 2-4094
```

### 3. Агрегация каналов (Bonding) и LACP

Объединение двух интерфейсов для отказоустойчивости и повышения пропускной способности.

```ini
auto bond0
iface bond0 inet manual
    bond-slaves eth1 eth2
    bond-mode 802.3ad
    bond-miimon 100
    bond-lacp-rate 1
    bond-xmit-hash-policy layer2+3
```

### 4. Настройка VRF (Virtual Routing and Forwarding)

Использование `ifupdown2` для изоляции трафика в отдельной таблице маршрутизации.

```ini
# Определение VRF устройства
auto vrf-blue
iface vrf-blue inet manual
    vrf-table 100

# Привязка интерфейса к VRF
auto eth3
iface eth3 inet static
    address 10.10.10.1/24
    vrf vrf-blue
```

### 5. Настройка VLAN (802.1Q)

Интерфейс создается с использованием суффикса `.<VLAN_ID>`. Требует пакета `vlan`.

```ini
auto eth0.100
iface eth0.100 inet static
    address 172.16.100.10/24
```

### 6. Использование хуков (Hook Scripts)

Хуки позволяют выполнять произвольные команды. Переменная `$IFACE` содержит имя текущего интерфейса.

```ini
iface eth0 inet static
    address 192.168.50.10/24
    # Добавление маршрута после поднятия интерфейса
    post-up ip route add 10.100.0.0/16 via 192.168.50.1
    # Очистка правил файрвола перед опусканием
    pre-down iptables -F
    # Безопасный post-up с проверкой exit code
    post-up ip route add 10.200.0.0/16 via 192.168.50.1 || echo "Route exists"
```

Для сложной логики лучше использовать скрипты в `/etc/network/if-up.d/` и `/etc/network/if-post-down.d/`.

### 7. Валидация и безопасное применение изменений

Перед применением конфигурации в production используйте dry-run и синтаксическую проверку.

```bash
# Проверка синтаксиса (ifupdown2)
ifquery --syntax-check /etc/network/interfaces
# → Exit code: 0 (OK)

# Dry-run: показывает, что будет перезагружено
ifreload -dn
# → enp0s3: reload
# → bond0: skip (unchanged)

# Применение только к одному интерфейсу (безопасно)
ifreload -i eth0

# Проверка состояния
ip -brief addr show enp0s3
# → enp0s3    UP    192.168.1.10/24
```

### 8. MTU и управление MAC-адресом

Привязка к MAC и изменение MTU выполняется в самой строфе:

```ini
iface eth0 inet static
    address 192.168.1.10/24
    gateway 192.168.1.1
    hwaddress ether 00:a1:b2:c3:d4:e5
    mtu 9000
```

Директива `hwaddress` полезна для:
- Лицензионного ПО, привязанного к MAC.
- Обхода пула адресов DHCP по MAC.
- Тестирования с другим MAC без физической замены карты.

Для offloading и ring-buffer параметров используйте `ethtool` в хуках, так как `interfaces` не поддерживает их напрямую.

### 9. VLAN на Bond (тегированный трафик поверх агрегата)

VLAN-под-интерфейсы создаются на логическом устройстве `bond0`, а не на физических портах.

```ini
auto bond0
iface bond0 inet manual
    bond-slaves enp1s0 enp2s0
    bond-mode 802.3ad
    bond-miimon 100
    bond-lacp-rate 1
    bond-xmit-hash-policy layer2+3

# VLAN 100 на bond0
auto bond0.100
iface bond0.100 inet static
    address 172.16.100.10/24
    vlan-raw-device bond0

# VLAN 200 с DHCP
auto bond0.200
iface bond0.200 inet dhcp
    vlan-raw-device bond0
```

### 10. Bridge расширенный (VLAN filtering, PVID)

`bridge-pvid` задаёт untagged VLAN для порта; `bridge-vids` ограничивает список разрешённых VLAN.

```ini
auto vmbr0
iface vmbr0 inet static
    address 10.0.0.10/24
    bridge-ports enp1s0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-pvid 10
    bridge-vids 10,20,30
```

Для портов, которым нужен собственный PVID, создайте отдельные строфы с методом `manual` и подключите к мосту. Подробная диагностика VLAN: **[VLAN в Linux: диагностика](../../../../Networking/Protocols/VLAN/vlan_linux_diagnostics.md)**.

### 11. Bonding расширенный (тюнинг LACP)

Дополнительные параметры для контроля балансировки и устойчивости:

```ini
auto bond0
iface bond0 inet manual
    bond-slaves enp1s0 enp2s0
    bond-mode 802.3ad
    bond-miimon 100
    bond-lacp-rate fast
    bond-xmit-hash-policy layer3+4
    bond-lacp-actor-sys-prio 65535
    bond-ad-num-grpd-agg 8
```

| Параметр | Назначение |
| :--- | :--- |
| `bond-lacp-rate fast` | Отправка LACP-анонсов каждые 1с (slow = 30с). |
| `bond-xmit-hash-policy layer3+4` | Хеширование по IP+порт для лучшей балансировки TCP. |
| `bond-lacp-actor-sys-prio` | Приоритет актора в LACP; младший = выше. |
| `bond-ad-num-grpd-agg` | Максимальное число агрегируемых партнёров. |

Полная теория агрегации: **[Агрегация каналов (Bonding)](../../../../Networking/Concepts/link_aggregation.md)**.

### 12. Политики маршрутизации (PBR) через хуки

Для изоляции трафика по источникам/политикам используйте `ip rule` и таблицы маршрутизации:

```ini
iface eth0 inet static
    address 192.168.50.10/24
    post-up ip rule add from 192.168.50.0/24 table 100
    post-up ip route add default via 192.168.50.1 table 100
    post-down ip rule del from 192.168.50.0/24 table 100
    post-down ip route flush table 100
```

Таблица `100` (и другие нестандартные) должна быть свободна или предварительно зарезервирована. Проверка:

```bash
ip rule show
# → 32765:  from 192.168.50.0/24 lookup 100

ip route show table 100
# → default via 192.168.50.1 dev eth0
```

### 13. Динамическое именование через mapping

`ifupdown2` поддерживает сопоставление логических имён с физическими интерфейсами:

```ini
mapping eth0
    script /etc/network/get-mac.map
    map 00:11:22:33:44:55 wan0

auto wan0
iface wan0 inet dhcp
```

Скрипт `/etc/network/get-mac.map` должен выводить пары `MAC <искомая_мак>`.

### 14. DHCP продвинутый

Конфигурация DHCP-клиента через `interfaces`:

```ini
iface eth0 inet dhcp
    dhcp-client-id 00:11:22:33:44:55
    dhcp-hostname webserver01
    dhcp-send-hostname yes
    # Таймаут запроса (секунды)
    dhcp-timeout 60
```

- `dhcp-client-id` — идентификатор клиента (обычно MAC).
- `dhcp-hostname` — передаётся как `host-name` опции DHCP.
- Статические маршруты от DHCP (option 121) подхватываются автоматически, если DHCP-сервер их анонсирует. Для пользовательских маршрутов используйте `post-up`.

### 15. Автоматизация через Ansible (IaC)

Идемпотентное управление конфигурацией через шаблон:

```yaml
# tasks/main.yml
- name: Deploy /etc/network/interfaces
  template:
    src: interfaces.j2
    dest: /etc/network/interfaces
    owner: root
    group: root
    mode: '0644'
  notify: Reload networking

# handlers/main.yml
- name: Reload networking
  service:
    name: networking
    state: reloaded
  when: ansible_facts.service_mgr == "systemd"
```

Шаблон `interfaces.j2` должен содержать условные блоки под переменные (`interfaces`, `vlans`, `bonds`). Для `ifupdown2` в уведомителе можно использовать `ifreload -a` вместо `systemctl restart networking`, чтобы избежать прерывания трафика.

### 16. Экстренный доступ и восстановление

При потере доступа после изменения конфигурации:

1. **Console / vKVM** — подключитесь через IPMI/iDRAC/iLO и восстановите файл из бэкапа.
2. **pre-up проверки** — добавьте валидацию в конфигурацию:

```ini
iface eth0 inet static
    address 192.168.1.10/24
    pre-up timeout 5 bash -c 'ping -c1 -W1 192.168.1.1 && exit 0 || exit 1'
    pre-up test -f /etc/network/interfaces.d/wan.conf || exit 1
```

3. **Резервный канал** — оставьте хотя бы один интерфейс с `allow-hotplug` и DHCP для аварийного доступа.

4. **Откат** — для классического `ifupdown`:

```bash
sudo cp /root/interfaces.bak.$(date +%F) /etc/network/interfaces
sudo systemctl restart networking
```

## Дополнительная информация

### Управление и диагностика

| Задача | ifupdown (Классический) | ifupdown2 (Современный) |
| :--- | :--- | :--- |
| Применить изменения | `systemctl restart networking` | `ifreload -a` |
| Проверить синтаксис | `ifquery --syntax-check` | `ifquery --syntax-check` / `ifreload -dn` (Dry-run) |
| Применить к одному интерфейсу | `ifdown --force <iface> && ifup <iface>` | `ifreload -i <iface>` |
| Поднять/Опустить | `ifup` / `ifdown` | `ifup` / `ifdown` |
| Статус интерфейса | `ifquery <iface>` | `ifquery <iface>` |
| JSON-вывод статуса | Не поддерживается | `ifquery -j <iface>` |

### Сравнение ifupdown и ifupdown2

| Особенность | ifupdown | ifupdown2 |
| :--- | :--- | :--- |
| **Язык реализации** | C + Shell | Python |
| **Зависимости** | Минимальные | Требует Python |
| **Контроль зависимостей** | Ограничен | Полный (автоматический порядок Bond -> Bridge) |
| **Применение на лету** | Нет (требуется перезапуск) | Да (`ifreload`) |
| **Проверка синтаксиса** | Поверхностная | Встроенная детальная проверка |

### Типовые ошибки и решения

- **Проблема:** После редактирования `/etc/network/interfaces` изменения не применяются через `ifup`.
  - **Решение:** `ifup` сверяет текущее состояние с файлом `/run/network/ifstate`. Если интерфейс уже помечен как «up», команда ничего не сделает. Используйте `ifdown --force <iface> && ifup <iface>`. В `ifupdown2` используйте `ifreload -a` или `ifreload -i <iface>`.
- **Проблема:** Конфликт с NetworkManager или systemd-networkd.
  - **Решение:** Если интерфейс описан в `interfaces`, NetworkManager по умолчанию игнорирует его (параметр `managed=false` в `NetworkManager.conf`). Для systemd-networkd убедитесь, что служба отключена или не настроена на те же интерфейсы.
- **Проблема:** Интерфейс не поднимается автоматически при загрузке.
  - **Решение:** Убедитесь, что для интерфейса указана директива `auto <имя>`. Директива `allow-hotplug` может не сработать для некоторых типов виртуальных интерфейсов (например, `dummy` или `veth`) в классическом `ifupdown`.
- **Проблема:** `ifupdown2` игнорирует изменения в `interfaces.d/`.
  - **Решение:** Проверьте, что директива `source /etc/network/interfaces.d/*` присутствует в `/etc/network/interfaces` и файлы в `.d/` имеют корректные права (`0644`, владелец `root:root`).
- **Проблема:** Bond не переходит в состояние LACP, коммутатор видит отдельные порты.
  - **Решение:** Убедитесь, что на коммутаторе порты объединены в LAG (LACP), а не настроены как individual. Проверьте `cat /sys/class/net/bond0/bonding/ad_aggregator`.
- **Проблема:** VLAN-интерфейс `eth0.100` не создаётся.
  - **Решение:** Проверьте загружен ли модуль `8021q` (`lsmod | grep 8021q`). В `ifupdown2` можно использовать явное указание `vlan-raw-device eth0`.
- **Проблема:** DNS не обновляется после изменения `dns-nameservers`.
  - **Решение:** Убедитесь, что пакет `resolvconf` установлен и активен (`systemctl status resolvconf`). В системах с `systemd-resolved` проверьте symlink `/etc/resolv.conf`.
- **Проблема:** `ifreload` зависает или прерывает трафик мостов.
  - **Решение:** `ifdown vmbr0` прерывает трафик всех гостей. Используйте `ifreload -i vmbr0` или настройте мост с `bridge-fd 0` и `bridge-stp off` для ускорения Convergence.

### См. также

- **[Сетевые технологии Proxmox](../../../../Proxmox/proxmox_networking.md)** — глубокая интеграция `ifupdown2` в виртуализацию.
- **[Агрегация каналов (Bonding)](../../../../Networking/Concepts/link_aggregation.md)** — теория LACP и тюнинг bonding.
- **[VLAN в Linux: диагностика](../../../../Networking/Protocols/VLAN/vlan_linux_diagnostics.md)** — практическая диагностика VLAN через ifupdown2.
- **[sysctl: сетевые параметры ядра](../sysctl_network.md)** — параметры ядра, критичные для ifupdown2.
