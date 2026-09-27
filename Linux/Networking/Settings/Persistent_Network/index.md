# Постоянная настройка сети

**Постоянная настройка сети** (Persistent Network Configuration) — это процесс конфигурации параметров сетевых интерфейсов (IP-адреса, маршруты, DNS, параметры L2), которые сохраняются в энергонезависимой памяти системы и автоматически применяются при загрузке ОС или перезапуске сетевых служб. В отличие от временных настроек, выполняемых через стек [iproute2](../../Tools/iproute2/overview.md), персистентность обеспечивается специализированными системными менеджерами.

## Определения

- **Сетевой менеджер (Network Manager)** — системный демон, управляющий жизненным циклом сетевых соединений, отслеживающий состояние линков и применяющий конфигурационные профили.
- **Императивный подход** — метод настройки, при котором администратор описывает последовательность действий или использует жестко заданные параметры в конфигурационных файлах (например, `/etc/network/interfaces`).
- **Декларативный подход** — метод настройки, при котором описывается желаемое конечное состояние сети (часто в формате YAML или JSON), а конкретную реализацию берет на себя абстрактный слой (например, Netplan или Nmstate).
- **Renderer (Бэкенд)** — низкоуровневая служба (systemd-networkd или NetworkManager), которая исполняет конфигурацию, подготовленную высокоуровневой утилитой.
- **Nmstate** — декларативный API для управления сетевыми настройками хоста, предоставляющий унифицированный способ описания состояния сети независимо от используемого бэкенда (преимущественно в экосистеме RHEL/Kubernetes).
- **Wicked** — сетевой менеджер, используемый по умолчанию в дистрибутивах SUSE/openSUSE, поддерживающий сложную иерархию интерфейсов и динамическое управление.

## Базовые концепции

Выбор инструмента для постоянной настройки зависит от семейства дистрибутива, версии ОС и роли узла (сервер или рабочая станция).

### Сводная таблица сетевых менеджеров

| Инструмент | Дистрибутивы | Тип конфигурации | Основные утилиты | Путь конфигурации |
| :--- | :--- | :--- | :--- | :--- |
| **`ifupdown` / `ifupdown2`** | Debian, Proxmox, старые Ubuntu | Императивная | `ifup`, `ifdown`, `ifreload` | `/etc/network/interfaces` |
| **NetworkManager** | RHEL 8/9, CentOS, AlmaLinux, Rocky Linux, Fedora, Ubuntu Desktop | Императивная / Декларативная (keyfile) | `nmcli`, `nmtui` | `/etc/NetworkManager/system-connections/*.nmconnection` |
| **Netplan** | Ubuntu 17.10+, Debian 12 (опционально) | Декларативная (YAML) | `netplan` | `/etc/netplan/*.yaml` |
| **`systemd-networkd`** | Arch Linux, Ubuntu Server, Debian 12, контейнеры | Декларативная (INI-like) | `networkctl` | `/etc/systemd/network/*.{link,netdev,network}` |
| **Wicked** | SUSE Linux Enterprise, openSUSE | Декларативная (XML) / Императивная | `wicked` | `/etc/wicked/*.xml`, `/etc/sysconfig/network/ifcfg-*` |
| **Nmstate** | RHEL 8/9, OKD/OpenShift, Fedora | Декларативная (YAML/JSON) | `nmstatectl` | `/etc/nmstate/` (или через API) |

### Рекомендации по выбору

1. **Серверные системы без контейнерной оркестрации**:
   - В экосистеме Ubuntu/Debian предпочтителен **Netplan** с бэкендом **systemd-networkd**. Это обеспечивает минимальное потребление ресурсов и высокую скорость загрузки.
   - В семействе RHEL 9 стандартным инструментом является **NetworkManager**. Для автоматизации (IaC) рекомендуется использовать **Nmstate** или Ansible-роли (`rhel-system-roles.network`).
   - Для систем с **Proxmox VE** используется **ifupdown2** (расширение классического `ifupdown`), который поддерживает динамическое применение изменений без перезагрузки узла.
2. **Веб-интерфейсы и рабочие станции**: **NetworkManager** остается стандартом благодаря поддержке мобильных интерфейсов, Wi-Fi и графических утилит настройки.
3. **Контейнеры и минималистичные образы**: **systemd-networkd** предпочтительнее, так как не требует дополнительных зависимостей и интегрируется с `network-online.target`.
4. **SUSE/openSUSE**: **Wicked** — родной менеджер, обеспечивающий поддержку сложных сценариев (bonding, bridging, VLAN) и DHCP-ретрансляции.

> **Важно (RHEL 9 / AlmaLinux 9 / Rocky Linux 9):** Классические скрипты `network-scripts` (файлы `ifcfg-ethX`) полностью удалены. Попытка их использования не приведет к настройке сети. Основным форматом хранения профилей стал **keyfile** в директории `/etc/NetworkManager/system-connections/`.

## Жизненный цикл конфигурации и systemd-интеграция

Постоянная настройка сети тесно связана с загрузкой системы. Понимание systemd-юнитов и таргетов критично для SRE при отладке проблем «сетевого линка» при старте.

### systemd targets и сеть

Сетевые службы интегрируются в систему зависимостей systemd:

- **`network-pre.target`** — запускается до любой сетевой активности. Используется для правил файрвола, которые должны быть готовы до поднятия интерфейсов.
- **`network.target`** — общий таргет «сеть активна». Большинство служб используют `After=network.target`, но это **не гарантирует** наличия маршрута по умолчанию или работоспособности DNS.
- **`network-online.target`** — активен только после того, как сеть действительно готова к работе (есть IP, шлюз и, желательно, подтверждена достижимость). Для его достижения используется **`systemd-networkd-wait-online`** (в случае systemd-networkd) или встроенная логика NetworkManager.

Для критичных сервисов (базы данных, мониторинг) указывайте обе зависимости:

```ini
[Unit]
After=network-online.target
Wants=network-online.target
```

### systemd-networkd-wait-online

Демон ожидания (`systemd-networkd-wait-online`) опрашивает состояние интерфейсов и завершается только когда все интерфейсы с параметром `RequiredForOnline=yes` перейдут в состояние `routable` (по умолчанию) или иной заданный статус. Тайм-аут по умолчанию составляет 2 минуты. При превышении тайм-аута загрузка продолжается, но сервис, зависящий от сети, может запуститься преждевременно.

Настройка тайм-аута в `/etc/systemd/system/systemd-networkd-wait-online.service.d/override.conf`:

```ini
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --timeout=30
```

### Инициализация через udev

Перед применением постоянной конфигурации ядро и `systemd-udevd` определяют устройства и применяют `.link`-файлы. Если интерфейс не получает ожидаемого имени (`enp0s3` вместо `eth0`), проверяйте:

```bash
# Просмотр событий udev для сетевых устройств
udevadm monitor --kernel --property --subsystem-match=net

# Проверка примененных .link правил
networkctl status enp0s3 | grep "Network File"
```

## Автоматизация и IaC

В контексте DevOps и SRE постоянная конфигурация сети должна управляться кодом (Infrastructure as Code).

### Ansible и rhel-system-roles

В экосистеме RHEL для идемпотентного управления сетью через Ansible используется роль **`rhel-system-roles.network`**:

```yaml
- name: Настройка сети через rhel-system-roles
  hosts: all
  roles:
    - role: rhel-system-roles.network
      vars:
        network_connections:
          - name: eth0
            type: ethernet
            ip:
              address:
                - "192.168.1.100/24"
              gateway4: "192.168.1.1"
              dns:
                - "8.8.8.8"
                - "1.1.1.1"
```

Роль абстрагирует различия между `nmcli` и `NetworkManager` keyfile, обеспечивая одинаковый playbook для RHEL 8 и 9.

### Nmstate как декларативный API

Для автоматизации без привязки к конкретному менеджеру используется **Nmstate**. Он предоставляет единую схему (JSON Schema) для описания состояния сети и может применяться через:

- CLI: `nmstatectl apply <state.yaml>`
- Python-библиотеку
- Внешние системы управления через API

Пример минимального состояния:

```yaml
interfaces:
  - name: eth0
    type: ethernet
    state: up
    ipv4:
      enabled: true
      address:
        - ip: 192.168.1.100
          prefix-length: 24
```

### Диспетчерские скрипты (Dispatcher Scripts)

Для реакции на события изменения состояния интерфейса используются скрипты-диспетчеры:

- **NetworkManager**: каталог `/etc/NetworkManager/dispatcher.d/`. Скрипт получает два аргумента: `$1` — имя интерфейса, `$2` — действие (`up`, `down`, `vpn-up` и др.). Скрипты выполняются синхронно и блокируют службу; поэтому код должен быть максимально компактным.
- **systemd-networkd**: используется пакет **`networkd-dispatcher`**, который предоставляет каталоги `/etc/networkd-dispatcher/*.d/` (например, `routable.d/`, `no-carrier.d/`). Скрипты выполняются асинхронно.

Пример для systemd-networkd — перезапуск службы мониторинга при появлении маршрута:

```bash
# /etc/networkd-dispatcher/routable.d/99-restart-prometheus-node-exporter
#!/bin/bash
IFACE=$1
ACTION=$2
systemctl restart prometheus-node-exporter
```

### Верификация конфигурации ( dry-run )

Перед применением изменений в production-среде используйте возможности проверки:

- **Netplan**: `sudo netplan --debug generate` — генерирует конфигурацию для бэкенда без применения, выводя ошибки синтаксиса.
- **ifupdown2**: `ifreload -dn` — dry-run, показывает, какие интерфейсы будут перезагружены.
- **NetworkManager**: `nmcli connection show` + `nmcli -f all connection show <name>` — позволяет проверить параметры без активации.
- **systemd-networkd**: `networkctl status <iface>` показывает выбранный `.network` файл без перезапуска службы.

## Миграция между менеджерами

Переход с одного сетевого менеджера на другой требует аккуратной переноса конфигурации.

### ifupdown → Netplan (Debian/Ubuntu)

Конвертировать файл `/etc/network/interfaces` вручную в YAML-формат Netplan. Внимание: хуки (`post-up`, `pre-down`) не имеют прямого аналога в Netplan и требуют отдельного решения (диспетчерские скрипты или `networkd-dispatcher`).

### ifcfg → NetworkManager keyfile (RHEL 9)

Для миграции legacy-профилей используйте встроенную команду:

```bash
sudo nmcli connection migrate
```

После миграции проверяйте директорию `/etc/NetworkManager/system-connections/` и удаляйте старые `ifcfg-*` файлы, чтобы предотвратить дублирование.

### NetworkManager → systemd-networkd

Требует полного повторного описания конфигурации в `.network` и `.netdev` файлах. Особое внимание уделите:
- DNS: в NetworkManager он хранится в профиле, в networkd — в `.network` или в `systemd-resolved`.
- Диспетчерские скрипты: требуется перевод на `networkd-dispatcher`.
- Маршрутизация по политикам (PBR): в NetworkManager через `ipv4.routing-rules`, в networkd через секцию `[RoutingPolicyRule]`.

## Валидация и откат изменений

### Обязательный бэкап

Перед любым изменением создайте резервную копию:

```bash
# Netplan
sudo cp -r /etc/netplan /root/netplan.bak.$(date +%F)

# NetworkManager
sudo cp -r /etc/NetworkManager/system-connections /root/nm-conn.bak.$(date +%F)

# systemd-networkd
sudo cp -r /etc/systemd/network /root/networkd.bak.$(date +%F)

# ifupdown2
sudo cp /etc/network/interfaces /root/interfaces.bak.$(date +%F)
```

### Пошаговая валидация

1. Проверьте синтаксис конфигурации (см. раздел «Автоматизация и IaC»).
2. Примените изменения к одному интерфейсу, не затрагивая остальные.
3. Проверьте доступность удаленного узла через резервный канал (out-of-band, console, another NIC) перед закрытием сессии.
4. Убедитесь, что служба `systemd-networkd-wait-online` завершилась успешно: `systemctl status systemd-networkd-wait-online`.

### Откат

При потере доступа к узлу после изменения конфигурации используйте:

- **Console/vKVM** для ручного восстановления конфигурации из бэкапа.
- **PXE-загрузку** с rescue-образа, если файловая система доступна.
- **Аварийный shell** через systemd: `systemctl edit --full getty@tty1.service` и добавление `ExecStart=-/bin/bash` для получения root-доступа при загрузке.

## Типовые ошибки при загрузке

### network-online.target не достигается

**Причина:** Интерфейс не получил IP-адрес или не установлен шлюз по умолчанию.
**Диагностика:**
```bash
# Проверка статуса всех интерфейсов
networkctl status

# Проверка логов systemd-networkd
journalctl -u systemd-networkd -b

# Проверка DHCP-клиента
journalctl -u systemd-networkd | grep -i dhcp
```
**Решение:** Убедитесь, что кабель подключен, DHCP-сервер доступен, или задайте статический IP для тестирования.

### Конфликт менеджеров при загрузке

**Причина:** Два менеджера управляют одним интерфейсом.
**Симптомы:** Один из интерфейсов получает IP, второй — нет, или оба получают адреса из разных подсетей.
**Решение:** Отключите ненужный менеджер:

```bash
# Отключение NetworkManager в пользу systemd-networkd
sudo systemctl disable --now NetworkManager

# Или наоборот
sudo systemctl disable --now systemd-networkd
```

### Потеря persistent-конфигурации после обновления ядра

**Причина:** Драйвер NIC изменился, и predictable-имя интерфейса сменилось (например, `enp0s3` → `enp1s0`).
**Диагностика:**
```bash
# Сравнение имен до и после обновления
dmesg | grep -i "renamed.*eth"
ip link show
```
**Решение:** Используйте привязку по MAC-адресу или драйверу в `.link`-файлах или секции `match` в Netplan/NetworkManager, а не жесткие имена.

### DNS не разрешает имена

**Причина:** `systemd-resolved` не настроен на прием DNS от менеджера, или `/etc/resolv.conf` является симлинком на неверный файл.
**Диагностика:**
```bash
# Проверка текущего резолвера
resolvectl status

# Проверка симлинка
ls -la /etc/resolv.conf
```
**Решение:** Для systemd-resolved настройте `DNS=systemd-resolved` в NetworkManager или убедитесь, что `systemd-networkd` передает DNS в `resolved` через параметры `.network` файла.

## Практические сценарии

Детальная настройка конкретных менеджеров представлена в специализированных разделах:

- **[Debian/Ubuntu: /etc/network/interfaces](./debian_ubuntu_interfaces.md)** — управление через `ifupdown` и `ifupdown2`. Основной метод для **Proxmox** и классических инсталляций Debian.
- **[RHEL/CentOS/Rocky: NetworkManager](./centos_rhel_networkmanager.md)** — использование `nmcli` и современные форматы конфигурации в Red Hat-подобных системах.
- **[Ubuntu: Netplan](./ubuntu_netplan.md)** — работа с YAML-конфигурациями и абстракцией над бэкендами.
- **[systemd-networkd](./systemd_networkd.md)** — настройка через `.network` и `.netdev` файлы, глубоко интегрированная в экосистему systemd.
- **[sysctl: сетевые параметры ядра](../sysctl_network.md)** — параметры ядра, критичные для persistent-конфигурации (ip_forward, rp_filter, conntrack).
- **[Диагностика persistent-конфигурации](./persistent_network_troubleshooting.md)** — flowchart диагностики и типичные сценарии устранения неполадок.

## Дополнительная информация

### Конфликты сетевых менеджеров: coexistence NetworkManager и systemd-networkd

Одновременная работа нескольких менеджеров (например, `systemd-networkd` и `NetworkManager`) на одном интерфейсе недопустима. Это приводит к конфликтам в таблицах маршрутизации и нестабильной работе DNS.

**Правила coexistence:**

| Сценарий | Рекомендация | Как реализовать |
| :--- | :--- | :--- |
| **Сервер Ubuntu/Debian** | Только systemd-networkd | `systemctl disable --now NetworkManager` |
| **Сервер RHEL 9+/Fedora** | Только NetworkManager | `systemctl disable --now systemd-networkd` |
| **Desktop Ubuntu** | NM для Wi-Fi/DSL, networkd для серверных интерфейсов | `managed=false` в NetworkManager.conf для серверных интерфейсов |
| **Kubernetes-нода** | NM + unmanaged CNI-интерфейсы | `unmanaged-devices=interface-name:cali*;interface-name:flannel*;interface-name:cilium*` |
| **Docker-хост** | NM + bridge-management | NM управляет host-интерфейсами, Docker — bridge |

**Частичное coexistence (NM управляет部分 интерфейсами):**

```ini
# /etc/NetworkManager/conf.d/99-unmanaged.conf
[ifupdown]
managed=false

# /etc/NetworkManager/conf.d/99-unmanaged-interfaces.conf
[keyfile]
unmanaged-devices=interface-name:docker0;interface-name:br-*
```

**Решение:** Оставляйте активным только один менеджер для каждого интерфейса. Остальные должны быть остановлены и отключены:
`systemctl disable --now NetworkManager` (если используется networkd).

### Безопасное обновление конфигурации при активной SSH-сессии

При изменении persistent-сетевой конфигурации через SSH существует риск потери доступа. Рекомендуемые подходы:

| Инструмент | Безопасный метод | Описание |
| :--- | :--- | :--- |
| **Netplan** | `netplan try` | Автооткат через 120 сек, если не подтвердить |
| **ifupdown2** | `ifreload -i <iface>` | Перезагрузка одного интерфейса без влияния на другие |
| **NetworkManager** | `nmcli connection up` | Переключение на профиль без потери связи (если есть резервный интерфейс) |
| **systemd-networkd** | `networkctl reconfigure <iface>` | Применение изменений без перезапуска службы |

**Dispatcher-скрипт для мониторинга SSH при перенастройке:**

```bash
#!/bin/bash
# /etc/NetworkManager/dispatcher.d/99-ssh-monitor
INTERFACE=$1
ACTION=$2

# Логирование всех событий изменения состояния
logger "NM-dispatcher: $INTERFACE is $ACTION"

# Если интерфейс опускается — проверяем наличие других активных интерфейсов
if [ "$ACTION" = "down" ]; then
    ACTIVE=$(nmcli -t -f DEVICE device status | grep -v "$INTERFACE" | grep -v "^lo:" | wc -l)
    if [ "$ACTIVE" -eq 0 ]; then
        logger "WARNING: No active interfaces remaining after $INTERFACE down"
    fi
fi
```

### Метрики маршрутов и Float Gateway

При наличии двух маршрутов по умолчанию (primary + backup) критично правильно настроить метрики:

```yaml
# Netplan: два default-маршрута с разными метриками
network:
  version: 2
  ethernets:
    eth0:
      addresses: [10.0.0.10/24]
      routes:
        - to: default
          via: 10.0.0.1
          metric: 100    # основной маршрут
    eth1:
      addresses: [10.0.1.10/24]
      routes:
        - to: default
          via: 10.0.1.1
          metric: 200    # резервный маршрут
```

```bash
# NetworkManager: два шлюза с разными метриками
sudo nmcli connection modify 'eth0' ipv4.gateway 10.0.0.1
sudo nmcli connection modify 'eth0' ipv4.route-metric 100
sudo nmcli connection modify 'backup' ipv4.gateway 10.0.1.1
sudo nmcli connection modify 'backup' ipv4.route-metric 200

# systemd-networkd: метрики в .network файле
# [Route]
# Gateway=10.0.0.1
# Metric=100
```

**Поведение ядра:** Маршрут с наименьшей метрикой используется первым. При падении основного маршрута (потеря линка) ядро переключается на резервный. Это работает только с `link-down` событиями; если шлюз недоступен, но линк активен, failover не произойдёт (требуется `nqa` или `netwatch`).

### Взаимодействие с DNS (systemd-resolved)

Современные сетевые менеджеры часто не пишут данные напрямую в `/etc/resolv.conf`, а передают их в **systemd-resolved**.
- **Netplan**: параметр `nameservers` в YAML транслируется в настройки бэкенда.
- **NetworkManager**: требует плагина (например, `dns=systemd-resolved` в конфигурации), чтобы передавать DNS-серверы из DHCP в резолвер.

### Фиксация имен интерфейсов

Механизм **Predictable Network Interface Names** (например, `enp0s3`) гарантирует стабильность имен при изменении аппаратного состава, но иногда требует ручного переопределения (например, для лицензионного ПО, привязанного к `eth0`). Это реализуется через `.link` файлы systemd.

**Пример конфигурации (`/etc/systemd/network/10-eth0.link`):**

```ini
[Match]
MACAddress=52:54:00:ab:cd:ef

[Link]
Name=eth0
```

### Диагностика состояния

| Команда | Контекст | Описание |
| :--- | :--- | :--- |
| `networkctl status` | systemd-networkd | Состояние линков и примененные настройки |
| `networkctl list` | systemd-networkd | Общий список интерфейсов и их операционный статус |
| `networkctl reload` | systemd-networkd | Перезагрузка конфигурации без перезапуска службы |
| `nmcli device status` | NetworkManager | Список устройств и активных профилей |
| `nmcli -f all connection show <NAME>` | NetworkManager | Детальная информация о конкретном соединении |
| `netplan status` | Netplan | Текущее состояние конфигурации и IP-адреса |
| `netplan --debug generate` | Netplan | Проверка синтаксиса и генерация конфигов без применения |
| `nmstatectl show` | Nmstate | Текущее состояние сети в формате YAML |
| `ifquery --list` / `ifreload -dn` | ifupdown2 | Проверка синтаксиса и dry-run применения |
| `journalctl -u <service_name>` | Общий | Анализ логов конкретного менеджера |
| `journalctl -u systemd-networkd-wait-online` | systemd | Проверка тайм-аута ожидания сети при загрузке |
| `resolvectl status` | systemd-resolved | Проверка работы DNS-резолвера и полученных серверов |

### См. также

- **[Настройка DNS-клиента](../../Concepts/dns_client.md)** — взаимодействие резолверов с сетевыми менеджерами.
- **[Policy-Based Routing (PBR)](../../Policy_Based_Routing/index.md)** — сохранение сложных правил маршрутизации.
- **[VLAN](../../../../Networking/Protocols/vlan.md)** — особенности персистентной настройки виртуальных сетей.
- **[Linux Bridge](../../Concepts/linux_bridge.md)** — программные мосты и их конфигурация через менеджеры.
- **[Link Aggregation](../../../../Networking/Concepts/link_aggregation.md)** — bonding и teaming через systemd-networkd и NetworkManager.
- **[Predictable Network Interface Names](../../Concepts/linux_network_interfaces.md#1-физические-интерфейсы)** — подробный обзор механизмов именования.
- **[iproute2: Обзор](../../Tools/iproute2/overview.md)** — временное управление сетевым стеком (контраст с постоянной настройкой).
- **[sysctl: сетевые параметры ядра](../sysctl_network.md)** — параметры ядра для persistent-конфигурации.
- **[Диагностика persistent-конфигурации](./persistent_network_troubleshooting.md)** — flowchart и типичные сценарии.
- **[DHCP-клиенты Linux](../../Services/DHCP/dhcp_clients_comparison.md)** — dhclient vs NetworkManager vs systemd-networkd (сравнение DHCP-клиентов).
- **[Асимметричная маршрутизация](../../../../Networking/Concepts/asymmetric_routing.md)** — rp_filter и сценарии использования.
