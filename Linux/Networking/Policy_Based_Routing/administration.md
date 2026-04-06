# Администрирование Policy-Based Routing

## Определения

**Администрирование PBR** — проверка, сохранение и отладка конфигурации Policy-Based Routing в Linux.

---

## Basic Concepts

### Ключевые файлы и утилиты

| Утилита | Назначение |
| :--- | :--- |
| `ip rule` | Управление правилами маршрутизации |
| `ip route` | Управление таблицами маршрутизации |
| `sysctl` | Настройка параметров ядра (rp_filter) |
| `iptables` | Маркировка пакетов для PBR |

### Механизм сохранения конфигурации

Настройки `ip rule` и `ip route` **не сохраняются** после перезагрузки. Требуется явная настройка механизма сохранения в зависимости от используемого сетевого менеджера.

---

## Practical Scenarios

### Проверка конфигурации PBR

```bash
# Показать все созданные правила и их приоритет
ip rule show

# Показать маршруты в таблице vpn_table
ip route show table vpn_table

# Показать маршруты в таблице direct_table
ip route show table direct_table

# Подробная информация о конкретном правиле
ip -d rule show

# Тестирование маршрута для пакета
ip route get <IP_назначения> from <IP_источника>
```

---

### Сохранение конфигурации

**Debian/Ubuntu (`/etc/network/interfaces`):**

```bash
auto eth0
iface eth0 inet static
    address 192.168.1.100
    netmask 255.255.255.0
    gateway 192.168.1.1
    # PBR
    post-up ip route add default via 192.168.1.1 table 100
    post-up ip rule add from 192.168.1.100 table 100 priority 1000
    pre-down ip rule del from 192.168.1.100 table 100 priority 1000
```

**Systemd-networkd (`/etc/systemd/network/10-eth0.network`):**

```ini
[Match]
Name=eth0

[Route]
Gateway=192.168.1.1
Table=100

[RoutingPolicyRule]
From=192.168.1.100
Table=100
Priority=1000
```

**NetworkManager (`/etc/NetworkManager/system-connections/`):**

```ini
[connection]
id=eth0
type=ethernet

[ipv4]
method=manual
address1=192.168.1.100/24,192.168.1.1
# PBR через routing-rules
routing-rules=ip from 192.168.1.100 table 100 priority 1000

[ipv4.route]
table=100
```

**iptables-persistent:**

```bash
# Сохранить правила iptables (включая маркировку для PBR)
sudo iptables-save > /etc/iptables/rules.v4
sudo ip6tables-save > /etc/iptables/rules.v6
```

---

### Типичные проблемы и решения

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Правила не работают** | Неправильный приоритет | Проверить `ip rule show`, приоритеты |
| **Асимметричная маршрутизация** | Нет правила для source IP | Добавить правило `from <IP>` |
| **Пакеты отбрасываются** | Reverse path filtering | `sysctl -w net.ipv4.conf.all.rp_filter=2` |
| **Настройки сбрасываются** | Нет сохранения | Добавить в `/etc/network/interfaces` или systemd |
| **Конфликт таблиц** | Одинаковые ID таблиц | Использовать уникальные ID в `rt_tables` |

---

### Reverse Path Filtering

**Reverse path filtering** — механизм безопасности ядра, который отбрасывает пакеты, если маршрут для ответа не совпадает с интерфейсом, на который пришел пакет.

```bash
# Проверить текущее значение
sysctl net.ipv4.conf.all.rp_filter

# Отключить строгую проверку (режим 2 — loose mode)
sysctl -w net.ipv4.conf.all.rp_filter=2
sysctl -w net.ipv4.conf.ens5.rp_filter=2
```

**Режимы:**

| Режим | Описание |
| :--- | :--- |
| `0` | Отключено (no source validation) |
| `1` | Strict mode (RFC 3704) — строгая проверка |
| `2` | Loose mode — ослабленная проверка (рекомендуется для PBR) |

**Взаимосвязь с PBR:**
При использовании policy-based routing для асимметричной маршрутизации (когда входящий и исходящий интерфейсы различаются) strict mode (`rp_filter=1`) будет отбрасывать легитимные пакеты. Режим `loose mode` (`rp_filter=2`) проверяет только достижимость источника, а не совпадение интерфейса.

Подробнее о концепции асимметричной маршрутизации — в [index.md](./index.md).

**Постоянная настройка:**

```bash
# /etc/sysctl.d/99-pbr-rpfilter.conf
net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
net.ipv4.conf.ens5.rp_filter=2
```

---

### Отладка PBR

```bash
# Трассировка прохождения пакета через правила маршрутизации
ip route get <IP_назначения> from <IP_источника> iif <интерфейс>

# Проверка маркировки пакетов iptables
iptables -t mangle -L -v -n

# Мониторинг изменений в правилах
watch -n 1 'ip rule show'

# Проверка доступности шлюзов из конкретной таблицы
ip route show table <table_name> | grep default
```

---

## Additional Information

См. также: [ip route](../Tools/iproute2/ip_route.md), [ip rule и PBR](../Tools/iproute2/ip_rule_pbr.md), [обзор iproute2](../Tools/iproute2/overview.md), [диагностика сети](../network_diagnostics_tools.md).
