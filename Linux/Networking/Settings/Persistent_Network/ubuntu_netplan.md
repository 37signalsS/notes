# Ubuntu Netplan: декларативная настройка сети

## Обзор

**Netplan** — утилита для настройки сети в Ubuntu (17.10+), использующая декларативный подход на основе YAML-файлов. Генерирует конфигурацию для `systemd-networkd` (серверы) или `NetworkManager` (десктопы).

**Путь к конфигурации:** `/etc/netplan/*.yaml` (например, `01-netcfg.yaml`, `50-cloud-init.yaml`).

---

## Базовая структура

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: no
```

| Параметр | Описание |
| :--- | :--- |
| `network:` | Корневой блок конфигурации |
| `version: 2` | Версия схемы YAML (актуальная) |
| `renderer:` | Бэкенд: `networkd` или `NetworkManager` |
| `ethernets:` | Блок настройки физических интерфейсов |
| `dhcp4: no` | Отключить DHCP для IPv4 (для IPv6 — `dhcp6`) |

---

## Примеры конфигурации

### Статический IP-адрес

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: no
      macaddress: bb:11:13:ab:ff:32
      addresses: [10.10.10.2/24, 10.10.10.3/24]
      routes:
        - to: default
          via: 10.10.10.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
```

- **Несколько IP:** указываются в квадратных скобках через запятую с пробелом
- **`macaddress:`** — привязка к MAC-адресу
- **`routes:`** — статические маршруты (заменяет `gateway4` в новых версиях). Поддерживает параметры `table` и `metric` для policy-based routing.
- **`nameservers.addresses:`** — DNS-серверы (список)

### DHCP с переопределением параметров (dhcp4-overrides)

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: yes
      dhcp4-overrides:
        use-dns: no
        use-domains: no
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]
```

#### Параметры dhcp4-overrides

| Параметр | Описание |
| :--- | :--- |
| `use-dns: no` | Игнорировать DNS-серверы от DHCP |
| `use-domains: no` | Игнорировать домены поиска от DHCP |
| `use-ntp: no` | Игнорировать NTP-серверы от DHCP |
| `route-metric: <число>` | Установить метрику маршрута |

#### Формат списков

YAML допускает блочный и строчный формат:

```yaml
nameservers:
  addresses: [8.8.8.8, 8.8.4.4]
# или
nameservers:
  addresses:
    - 8.8.8.8
    - 8.8.4.4
```

---

## Bonding (агрегация каналов)

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

| Параметр | Описание |
| :--- | :--- |
| `bonds:` | Блок настройки bonding-интерфейсов |
| `bond0:` | Произвольное имя bond-интерфейса |
| `interfaces:` | Физические интерфейсы для агрегации |
| `parameters.mode:` | Режим bonding (`802.3ad`, `active-backup`, `balance-xor`, etc.) |
| `parameters.mii-monitor-interval:` | Интервал мониторинга в секундах |

### Режимы bonding

| Режим | Описание |
| :--- | :--- |
| `802.3ad` | LACP (требует поддержки на коммутаторе) |
| `active-backup` | Активный/резервный (отказоустойчивость) |
| `balance-xor` | Балансировка по XOR |
| `round-robin` | Циклическая отправка пакетов |

---

## VLAN

```yaml
network:
  version: 2
  renderer: networkd
  vlans:
    vlan10:
      id: 10
      link: bond0
      dhcp4: no
      addresses: [10.10.10.2/24]
      routes:
        - to: 10.10.10.0/24
          via: 10.10.10.1
          on-link: true
    vlan20:
      id: 20
      link: bond0
      dhcp4: no
      addresses: [10.10.11.2/24]
      gateway4: 10.10.11.1
      nameservers:
        addresses: [8.8.8.8]
```

| Параметр | Описание |
| :--- | :--- |
| `vlans:` | Блок настройки VLAN-интерфейсов |
| `id:` | VLAN ID (1-4094) |
| `link:` | Базовый интерфейс (физический или bond) |
| `on-link: true` | Маршрут считается доступным напрямую |

**Устаревшие параметры:** `gateway4` и `gateway6` устарели, используйте `routes:` с `to: default`.

---

## Полный пример (Ethernet + Bonding + VLAN)

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
  vlans:
    vlan10:
      id: 10
      link: bond0
      dhcp4: no
      addresses: [10.10.10.2/24]
      routes:
        - to: 10.10.10.0/24
          via: 10.10.10.1
          on-link: true
    vlan20:
      id: 20
      link: bond0
      dhcp4: no
      addresses: [10.10.11.2/24]
      routes:
        - to: default
          via: 10.10.11.1
      nameservers:
        addresses: [8.8.8.8]
```

---

## Применение конфигурации

```bash
# 1. Проверить синтаксис и сгенерировать конфиги
sudo netplan generate

# 2. Применить конфигурацию (с проверкой)
sudo netplan apply

# 3. Отладка (подробный вывод)
sudo netplan --debug apply

# 4. Проверить статус
networkctl status
```

### Команды

| Команда | Описание |
| :--- | :--- |
| `netplan generate` | Проверка синтаксиса и генерация конфигов для бэкенда |
| `netplan apply` | Применение конфигурации (автоматически вызывает `generate`) |
| `netplan --debug` | Подробный вывод для отладки |

Конфигурация применяется автоматически при загрузке системы.

---

## Дополнительные ресурсы

- **[Агрегация каналов](../../../../Networking/Concepts/link_aggregation.md)** — теория bonding
- **[VLAN](../../../../Networking/Protocols/VLAN/vlan_overview.md)** — теория VLAN
- **[VLAN: практические сценарии](../../../../Networking/Concepts/vlan_l2_switching/practical_scenarios.md)** — примеры настройки
