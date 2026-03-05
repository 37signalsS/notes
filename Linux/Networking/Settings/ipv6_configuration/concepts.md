# IPv6 в Linux — Концепции

## Определения

**IPv6 (Internet Protocol version 6)** — версия протокола IP с длиной адреса 128 бит (16 байт). Создана для решения проблемы нехватки IPv4-адресов.

**Unique Local Address (ULA)** — частные адреса IPv6 (RFC 4193). Диапазон: `fc00::/7` (обычно `fc00::/8`). Аналог приватных адресов IPv4 (RFC 1918).

**Link-Local Address** — адреса, действующие только в пределах одного канала связи. Для IPv6 автоматически генерируются на основе MAC-адреса (SLAAC). Диапазон: `fe80::/10`.

**Privacy Extensions (RFC 4941)** — механизм генерации временных случайных адресов для исходящих соединений, обеспечивающий конфиденциальность.

**Подробнее:** [IP-протокол](../../../Networking/Protocols/ip.md), [Dual Stack IPv4/IPv6](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md).

## Отличия от IPv4 в контексте Linux

| Аспект | IPv4 | IPv6 |
| :--- | :--- | :--- |
| **Длина адреса** | 32 бита | 128 бит |
| **Автоконфигурация** | DHCP | SLAAC + DHCPv6 |
| **ARP/NDP** | ARP (broadcast) | NDP (multicast, ICMPv6) |
| **Фрагментация** | На маршрутизаторах | Только на хостах |
| **NAT** | Широко используется | Не требуется (теоретически) |
| **Файрвол** | iptables | ip6tables (отдельно!) |

## Типы IPv6-адресов

| Тип | Префикс | Описание | Пример |
| :--- | :--- | :--- | :--- |
| **Global Unicast** | `2000::/3` | Публичные маршрутизируемые адреса | `2001:db8::1` |
| **Unique Local (ULA)** | `fc00::/7` | Частные адреса (аналог RFC 1918) | `fc00::1` |
| **Link-Local** | `fe80::/10` | Автоматические, только локальная сеть | `fe80::1` |
| **Loopback** | `::1` | Локальная петля | `::1` |
| **Unspecified** | `::` | Неопределенный (аналог `0.0.0.0`) | `::` |
| **Multicast** | `ff00::/8` | Групповая рассылка | `ff02::1` (all nodes) |

## Privacy Extensions (RFC 4941)

Современные системы используют временные адреса для исходящих соединений для защиты конфиденциальности.

**Проверка статуса:**

```bash
sysctl net.ipv6.conf.all.use_tempaddr
sysctl net.ipv6.conf.default.use_tempaddr

# Значения:
# 0 — отключено
# 1 — включено, предпочтительны временные адреса
# 2 — включено, временные адреса для исходящих
```

**Включение:**

```bash
# Временно
sudo sysctl -w net.ipv6.conf.all.use_tempaddr=2
sudo sysctl -w net.ipv6.conf.default.use_tempaddr=2

# Постоянно (/etc/sysctl.d/60-ipv6-privacy.conf)
net.ipv6.conf.all.use_tempaddr=2
net.ipv6.conf.default.use_tempaddr=2
```

**См. также:** [Постоянная настройка сети](./persistent_network_configuration.md).

## Специальные адреса

| Адрес | Описание | Пример использования |
| :--- | :--- | :--- |
| `::1` | Loopback (аналог `127.0.0.1`) | `ping6 ::1` |
| `::` | Unspecified (аналог `0.0.0.0`) | `listen [::]:80` |
| `fe80::/10` | Link-Local (автоматические) | `ping6 fe80::1%eth0` |
| `fc00::/7` | ULA (Unique Local Address) | Внутренние сети |
| `ff02::1` | Multicast (all nodes) | NDP |
| `2001:db8::/32` | Documentation (RFC 3849) | Примеры, тесты |

## Связанные темы

* **[Настройка адресов](./address_configuration.md)** — конфигурация через nmcli и systemd-networkd
* **[Firewall](./firewall.md)** — настройка ip6tables и firewalld
* **[Диагностика](./diagnostics.md)** — решение проблем
* **[Туннелирование](./tunneling.md)** — IPv6 через IPv4
