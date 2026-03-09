# Администрирование Policy-Based Routing

## Определения

**Администрирование PBR** — проверка, сохранение и отладка конфигурации Policy-Based Routing.

> **Навигация:** [Главная PBR](./index.md) | [Сценарии](./scenarios.md)

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

Настройки `ip rule` и `ip route` **не сохраняются** после перезагрузки. Для постоянного применения:

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

**iptables-persistent:**

```bash
# Сохранить правила iptables
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

**Постоянная настройка:**

```bash
# /etc/sysctl.d/99-pbr-rpfilter.conf
net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
net.ipv4.conf.ens5.rp_filter=2
```

---

## Additional Information

### Связанные темы

- **[ip route](../Tools/iproute2/ip_route.md)** — базовая маршрутизация
- **[iproute2 overview](../../Tools/iproute2/overview.md)** — обзор утилит iproute2
- **[iptables](../Settings/linux_firewall_management.md)** — маркировка пакетов
- **[Network Diagnostics](../network_diagnostics_tools.md)** — диагностика сети
