# Настройка IPv6-адресов в Linux

---

**Reliability Score: 10** (SSoT + Современные стандарты 2026 года)  
**Freshness: Актуально на июль 2026**

---

## Определения

**Персистентная настройка сети** — конфигурация параметров сетевых интерфейсов, которая сохраняется после перезагрузки системы.

**Методы назначения адресов:**

- **SLAAC (Stateless Address Autoconfiguration)** — автоматическая генерация адреса на основе префикса сети, полученного от маршрутизатора в сообщениях **Router Advertisement (RA)**.
- **DHCPv6** — получение адреса и параметров сети (DNS, домен) от специализированного сервера. Может работать в режиме *Stateful* (выдача адреса) или *Stateless* (только доп. параметры).
- **Static (Manual)** — ручное назначение фиксированного адреса администратором.

## Основные концепции

В современных дистрибутивах Linux управление сетью осуществляется через высокоуровневые менеджеры, которые абстрагируют работу с ядром:

1.  **NetworkManager (nmcli)**: стандарт для RHEL, CentOS, Fedora, Debian и Ubuntu Desktop. Идеален для динамических окружений и рабочих станций.
2.  **Netplan**: декларативная надстройка в Ubuntu (Server/Desktop). Использует YAML-файлы для генерации конфигураций бэкендов (`networkd` или `NetworkManager`).
3.  **systemd-networkd**: легковесное и производительное решение для серверов, контейнеров и минималистичных инсталляций.

Для временной настройки и оперативного просмотра состояния используется пакет **iproute2** (`ip addr`, `ip route`).

## Практические сценарии

### 1. NetworkManager (nmcli)

#### Статический IPv6 (Manual)

```bash
# Установка метода 'manual' и адреса
sudo nmcli connection modify "eth0" ipv6.method manual ipv6.addresses "2001:db8::10/64"

# Настройка шлюза и DNS
sudo nmcli connection modify "eth0" ipv6.gateway "2001:db8::1" ipv6.dns "2001:db8::ffff"

# Применение изменений
sudo nmcli connection up "eth0"
```

#### Автоматическая настройка (SLAAC + DHCPv6)

Это значение по умолчанию для большинства соединений.

```bash
sudo nmcli connection modify "eth0" ipv6.method auto
```

#### Privacy Extensions (Временные адреса)

Используются для защиты от отслеживания устройства по его идентификатору EUI-64.

```bash
# Включение генерации временных адресов (RFC 4941)
sudo nmcli connection modify "eth0" ipv6.ip6-privacy 2
```

### 2. Netplan (Ubuntu)

Конфигурация хранится в `/etc/netplan/*.yaml`. В современных версиях (2024+) параметры `gateway6` устарели, используйте блок `routes`.

#### Статический адрес

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      addresses:
        - "2001:db8::10/64"
      routes:
        - to: default
          via: "2001:db8::1"
      nameservers:
        addresses: ["2001:db8::ffff", "2606:4700:4700::1111"]
```

#### Автоконфигурация (SLAAC)

```yaml
network:
  version: 2
  ethernets:
    enp0s3:
      dhcp6: yes
      accept-ra: yes
```

Применение: `sudo netplan apply`.

### 3. systemd-networkd

Конфигурация в `/etc/systemd/network/`.

#### Статический адрес

```ini
# /etc/systemd/network/10-static-ipv6.network
[Match]
Name=eth0

[Network]
IPv6AcceptRA=no
Address=2001:db8::10/64
Gateway=2001:db8::1
DNS=2001:db8::ffff
```

#### Автоконфигурация с Privacy Extensions

```ini
[Match]
Name=eth0

[Network]
DHCP=ipv6
IPv6AcceptRA=yes
IPv6PrivacyExtensions=yes
```

Применение: `sudo systemctl restart systemd-networkd`.

## Проверка и диагностика

### Основные команды

```bash
# Проверка наличия адреса и его флагов
ip -6 addr show dev eth0

# Проверка маршрутов
ip -6 route show

# Тестирование связности
ping6 -c 3 google.com
```

### Состояния адреса (DAD)

При настройке IPv6 адрес проходит проверку на уникальность (**Duplicate Address Detection**):

- **tentative**: адрес проверяется ядром, он еще не активен.
- **dadfailed**: адрес уже занят другим устройством в сети. Необходимо сменить IP.
- **deprecated**: временный адрес, срок жизни которого подходит к концу (новые соединения его не используют).

## Дополнительная информация

### Типичные проблемы

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Нет шлюза по умолчанию | Заблокированы RA-пакеты в файрволе | См. **[Firewall для IPv6](./firewall.md)** |
| Конфликт менеджеров | NetworkManager и Netplan запущены одновременно | Оставьте только один активный сервис |
| Адрес не назначается | Отключен IPv6 в параметрах ядра | Проверьте `sysctl net.ipv6.conf.all.disable_ipv6` |

### См. также

- **[Концепции IPv6 в Linux](./concepts.md)** — типы адресов и механизмы работы.
- **[Диагностика IPv6](./diagnostics.md)** — глубокая отладка сетевых проблем и NDP.
- **[Настройка Netplan](../Persistent_Network/ubuntu_netplan.md)** — подробное руководство по Netplan.
- **[NetworkManager через nmcli](../Persistent_Network/centos_rhel_networkmanager.md)** — расширенные команды nmcli.
