# Ubuntu Netplan

**Netplan** — утилита для настройки сети в Ubuntu (начиная с версии 17.10), использующая декларативный подход на основе файлов в формате YAML (Yet Another Markup Language). Netplan не настраивает сеть напрямую, а генерирует конфигурационные файлы для бэкендов (renderers): `systemd-networkd` (используется на серверах) или `NetworkManager` (используется на десктопах).

## Определения

- **Backend (Renderer)** — системная служба (`systemd-networkd` или `NetworkManager`), которая непосредственно управляет сетевыми интерфейсами на основе конфигурации, созданной Netplan.
- **YAML (Yet Another Markup Language)** — человекочитаемый формат сериализации данных, используемый Netplan для описания конфигурации сети.
- **Пути конфигурации:**
  - `/etc/netplan/*.yaml` — основные настройки администратора.
  - `/run/netplan/*.yaml` — временные настройки.
  - `/lib/netplan/*.yaml` — настройки, поставляемые пакетами или облачными провайдерами.

## Базовые концепции

Конфигурация Netplan строится на иерархической структуре YAML. Важно соблюдать отступы (пробелы), так как они определяют вложенность элементов.

### Структура файла

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: no
```

- **`network:`** — корневой блок конфигурации.
- **`version: 2`** — актуальная версия схемы конфигурации.
- **`renderer:`** — определяет бэкенд: `networkd` (по умолчанию для серверов) или `NetworkManager`.
- **`ethernets:`**, **`bonds:`**, **`vlans:`**, **`bridges:`** — блоки для настройки соответствующих типов интерфейсов.

## Практические сценарии

### 1. Настройка статического IP-адреса

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: no
      addresses:
        - 10.10.10.2/24
        - 10.10.10.3/24
      routes:
        - to: default
          via: 10.10.10.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
```

- **`addresses:`** — список IP-адресов в формате CIDR (Classless Inter-Domain Routing).
- **`routes:`** — статические маршруты. Секция `to: default` со шлюзом `via` заменяет устаревшие параметры `gateway4` и `gateway6`.
- **`nameservers:`** — список DNS-серверов (Domain Name System).

### 2. Настройка DHCP с переопределением параметров

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: yes
      dhcp4-overrides:
        use-dns: no
        route-metric: 100
      nameservers:
        addresses: [8.8.8.8]
```

- **`dhcp4-overrides:`** — позволяет игнорировать определенные данные от DHCP-сервера (например, DNS) или задать приоритет маршрута (`route-metric`).

### 3. Агрегация каналов (Bonding)

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
      interfaces: [enp3s0f0, enp3s0f1]
      parameters:
        mode: 802.3ad
        mii-monitor-interval: 1
      addresses: [10.10.10.5/24]
```

- **`mode:`** — режим работы (например, `802.3ad` для LACP или `active-backup`).

### 4. Настройка VLAN (Virtual Local Area Network)

```yaml
network:
  version: 2
  renderer: networkd
  vlans:
    vlan10:
      id: 10
      link: bond0
      addresses: [10.10.11.2/24]
```

### 5. Применение изменений

Для активации настроек используются следующие команды:

```bash
# Проверка синтаксиса и применение с возможностью отката
sudo netplan try

# Прямое применение конфигурации
sudo netplan apply

# Отладка в случае проблем
sudo netplan --debug apply
```

## Дополнительная информация

### Типичные ошибки

- **Ошибки отступов:** YAML чувствителен к количеству пробелов. Не используйте табуляцию.
- **Дублирование параметров:** несколько файлов в `/etc/netplan/` объединяются в алфавитном порядке; параметры в файлах с бОльшим лексикографическим именем переопределяют предыдущие.

### См. также

- **[Агрегация каналов](../../../../Networking/Concepts/link_aggregation.md)** — теоретические основы bonding.
- **[VLAN](../../../../Networking/Protocols/vlan.md)** — общие сведения о виртуальных сетях.
- **[systemd-networkd](./systemd_networkd.md)** — детальная настройка бэкенда networkd.
