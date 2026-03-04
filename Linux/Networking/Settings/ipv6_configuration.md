# Настройка IPv6 в Linux

## Определения

**IPv6 (Internet Protocol version 6)** — версия протокола IP с длиной адреса 128 бит (16 байт). Создана для решения проблемы нехватки IPv4-адресов. Подробнее: [IP-протокол](../../../Networking/Protocols/ip.md), [Dual Stack IPv4/IPv6](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md).

**Unique Local Address (ULA)** — частные адреса IPv6 (RFC 4193). Диапазон: `fc00::/7` (обычно `fc00::/8`). Аналог приватных адресов IPv4 (RFC 1918).

**Link-Local Address** — адреса, действующие только в пределах одного канала связи. Для IPv6 автоматически генерируются на основе MAC-адреса (SLAAC). Диапазон: `fe80::/10`.

**Privacy Extensions (RFC 4941)** — механизм генерации временных случайных адресов для исходящих соединений, обеспечивающий конфиденциальность.

## Базовые концепции

### Отличия от IPv4 в контексте Linux

| Аспект | IPv4 | IPv6 |
| :--- | :--- | :--- |
| **Длина адреса** | 32 бита | 128 бит |
| **Автоконфигурация** | DHCP | SLAAC + DHCPv6 |
| **ARP/NDP** | ARP (broadcast) | NDP (multicast, ICMPv6) |
| **Фрагментация** | На маршрутизаторах | Только на хостах |
| **NAT** | Широко используется | Не требуется (теоретически) |
| **Файрвол** | iptables | ip6tables (отдельно!) |

### Типы IPv6-адресов

| Тип | Префикс | Описание | Пример |
| :--- | :--- | :--- | :--- |
| **Global Unicast** | `2000::/3` | Публичные маршрутизируемые адреса | `2001:db8::1` |
| **Unique Local (ULA)** | `fc00::/7` | Частные адреса (аналог RFC 1918) | `fc00::1` |
| **Link-Local** | `fe80::/10` | Автоматические, только локальная сеть | `fe80::1` |
| **Loopback** | `::1` | Локальная петля | `::1` |
| **Unspecified** | `::` | Неопределенный (аналог `0.0.0.0`) | `::` |
| **Multicast** | `ff00::/8` | Групповая рассылка | `ff02::1` (all nodes) |

### Privacy Extensions (RFC 4941)

Современные системы используют временные адреса для исходящих соединений для защиты конфиденциальности:

```bash
# Проверка статуса Privacy Extensions
sysctl net.ipv6.conf.all.use_tempaddr
sysctl net.ipv6.conf.default.use_tempaddr

# Значения:
# 0 — отключено
# 1 — включено, предпочтительны временные адреса
# 2 — включено, временные адреса для исходящих
```

**Включение Privacy Extensions:**

```bash
# Временно
sudo sysctl -w net.ipv6.conf.all.use_tempaddr=2
sudo sysctl -w net.ipv6.conf.default.use_tempaddr=2

# Постоянно (/etc/sysctl.d/60-ipv6-privacy.conf)
net.ipv6.conf.all.use_tempaddr=2
net.ipv6.conf.default.use_tempaddr=2
```

**См. также:** [Постоянная настройка сети](./persistent_network_configuration.md).

## Практические сценарии

### 1. Просмотр IPv6-адресов

```bash
# Показать все адреса (включая IPv6)
ip address show

# Показать только IPv6-адреса
ip -6 address show

# Показать маршруты IPv6
ip -6 route show

# Просмотр соседей NDP (аналог ARP)
ip -6 neigh show
```

### 2. Настройка IPv6 через NetworkManager (nmcli)

Конфигурация сетевых интерфейсов в RHEL/CentOS выполняется через NetworkManager.

**Просмотр текущих настроек IPv6:**

```bash
nmcli connection show
nmcli connection show <имя_соединения> | grep ipv6
```

**Настройка статического IPv6 (Manual):**

```bash
nmcli connection edit <имя_соединения>
set ipv6.method manual
set ipv6.addresses 2001:db8::1/64
set ipv6.gateway 2001:db8::ffff
set ipv6.dns "2001:db8::1"
save
quit
```

**Настройка ULA (Unique Local Address) для локальной сети:**

```bash
# Пример: сеть fc00::/124 (16 хостов)
nmcli connection edit <имя_соединения>
set ipv6.method manual
set ipv6.addresses fc00::1/124
quit

# Активация изменений
nmcli connection down <имя_соединения>
nmcli connection up <имя_соединения>
```

**Настройка Link-Local (автоматическая):**

```bash
nmcli connection edit <имя_соединения>
set ipv6.method link-local
save
quit
```

**Включение Privacy Extensions через nmcli:**

```bash
nmcli connection modify <имя_соединения> ipv6.ip6-privacy 2
```

### 3. Настройка IPv6 через systemd-networkd

**Статический IPv6:**

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
# IPv4 (опционально)
Address=10.10.10.10/24
Gateway=10.10.10.1

# IPv6 статический
IPv6AcceptRA=no
Address=2001:db8::1/64
Gateway=2001:db8::ffff
DNS=2001:db8::1

# ULA для локальной сети
Address=fc00::1/124
```

**SLAAC (автоконфигурация):**

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
# Принимать RA от роутера
IPv6AcceptRA=yes
# Включить Privacy Extensions
IPv6PrivacyExtensions=yes
```

**DHCPv6:**

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
DHCP=yes
# IPv6 через SLAAC + DHCPv6
IPv6AcceptRA=yes
```

**Управление:**

```bash
# Перезапуск
sudo systemctl restart systemd-networkd

# Проверка статуса
networkctl status eth0

# Журнал
journalctl -u systemd-networkd -f
```

### 4. Проверка доступности по IPv6

```bash
# Ping по IPv6 (используется ICMPv6)
ping6 <ipv6-адрес>
ping -6 <ipv6-адрес>

# Traceroute по IPv6
traceroute6 <ipv6-адрес>
tracepath6 <ipv6-адрес>

# Проверка DNS AAAA записи
dig AAAA example.com
host -t AAAA example.com
```

### 4. Настройка Firewall для IPv6

**Важно:** Правила `iptables` для IPv4 **НЕ применяются** к IPv6. Необходимо настраивать `ip6tables` или `nftables` с поддержкой IPv6.

**В firewalld:**

```bash
# Разрешить ICMPv6 (необходимо для работы IPv6)
firewall-cmd --permanent --add-protocol=icmpv6

# Разрешить трафик на конкретном порту для IPv6
firewall-cmd --permanent --add-port=80/tcp --ipv6

# Перезагрузить правила
firewall-cmd --reload
```

**Проблема с drop target в firewalld:**

При использовании зоны с `target: drop` входящие пакеты IPv6 могут блокироваться, включая ответы на ping. Решение:

```bash
# Добавить протокол IPv6-ICMP
firewall-cmd --permanent --add-protocol=icmpv6
firewall-cmd --reload
```

**В iptables/nftables:**

```bash
# ip6tables - базовые правила
sudo ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo ip6tables -A INPUT -i lo -j ACCEPT
sudo ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 -j ACCEPT
sudo ip6tables -P INPUT DROP

# Сохранение (Debian/Ubuntu)
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

**См. также:**
- [Настройка файрвола](./linux_firewall_management.md)
- [iptables основы](./tools/iptables_basics.md)
- [nftables](./tools/nftables.md)

### 5. Настройка сервисов для работы с IPv6

Большинство демонов требуют явной настройки для поддержки IPv6.

**Пример: chrony (NTP сервер)**

```bash
# В /etc/chrony.conf
# Разрешить доступ по IPv6
allow fc00::/64

# Перезапуск сервиса
systemctl restart chronyd

# Проверка прослушивания
ss -6 -unap | grep chronyd
```

**Пример: nginx**

```bash
# В конфигурации хоста
listen [::]:80;
listen [::]:443 ssl http2;
```

**Пример: SSH**

```bash
# В /etc/ssh/sshd_config
# ListenAddress 0.0.0.0  # Только IPv4
ListenAddress ::  # Только IPv6
# ListenAddress 0.0.0.0  # Оба (dual stack)
```

---

## Дополнительная информация

### Специальные адреса

| Адрес | Описание | Пример использования |
| :--- | :--- | :--- |
| `::1` | Loopback (аналог `127.0.0.1`) | `ping6 ::1` |
| `::` | Unspecified (аналог `0.0.0.0`) | `listen [::]:80` |
| `fe80::/10` | Link-Local (автоматические) | `ping6 fe80::1%eth0` |
| `fc00::/7` | ULA (Unique Local Address) | Внутренние сети |
| `ff02::1` | Multicast (all nodes) | NDP |
| `2001:db8::/32` | Documentation (RFC 3849) | Примеры, тесты |

### Туннелирование IPv6

Для передачи IPv6 через IPv4-сети используются туннели:

| Технология | Описание | Протокол |
| :--- | :--- | :--- |
| **6to4** | Автоматические туннели | Proto 41 |
| **Teredo** | Через NAT/UDP | UDP 3544 |
| **ISATAP** | Внутри организации | Proto 41 |
| **6rd** | Быстрый 6to4 (ISP) | Proto 41 |

**См. также:** [Туннели IPIP и SIT](../../../Networking/Tunnels/ipip_and_sit.md).

### Часто используемые утилиты

| Утилита | Назначение | Пример |
| :--- | :--- | :--- |
| `ip -6` | Адреса и маршруты | `ip -6 addr show` |
| `ping6` / `ping -6` | Проверка доступности | `ping6 example.com` |
| `traceroute6` | Трассировка | `traceroute6 example.com` |
| `ss -6` | Сокеты IPv6 | `ss -6 -tlnp` |
| `ip6tables` | Файрвол IPv6 | `ip6tables -L -n` |
| `ndptool` | NDP диагностика | `ndptool neigh show` |
| `resolvectl` | DNS IPv6 | `resolvectl query AAAA example.com` |

### Диагностика проблем

**1. Проверить, включен ли IPv6:**

```bash
sysctl net.ipv6.conf.all.disable_ipv6
# 0 — включен, 1 — отключен
```

**2. Проверить адреса:**

```bash
ip -6 address show
```

**3. Проверить маршруты:**

```bash
ip -6 route show
```

**4. Проверить файрвол:**

```bash
ip6tables -L -n -v
```

**5. Проверить NDP (аналог ARP):**

```bash
ip -6 neigh show
```

**6. Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Нет IPv6-адреса | Отключен IPv6 | `sysctl -w net.ipv6.conf.all.disable_ipv6=0` |
| Нет маршрута по умолчанию | Нет RA / не настроен gateway | Настроить статический маршрут |
| Не работает ping | Блокировка ICMPv6 | Разрешить `icmpv6` в файрволе |
| DNS не резолвит | Нет AAAA записи | Проверить DNS, добавить AAAA |

**См. также:**
- [Диагностика DNS](../Concepts/dns_client.md#Диагностика-проблем)
- [Сетевая диагностика](../network_diagnostics_tools.md)
- [Dual Stack IPv4/IPv6](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)
