# Настройка IPv6 в Linux

## Определения

**IPv6 (Internet Protocol version 6)** — это версия протокола IP с длиной адреса 128 бит (16 байт). Создана для решения проблемы нехватки IPv4-адресов. Подробнее о теоретических основах см. [IP-протокол](../../../Networking/Protocols/ip.md) и [Dual Stack IPv4/IPv6](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md).

**Unique Local Address (ULA)** — частные адреса IPv6, аналогичные приватным адресам IPv4 (RFC 4193). Диапазон: `fc00::/7` (обычно используется `fc00::/8`).

**Link-Local Address** — адреса, действующие только в пределах одного канала связи (локальной сети). Для IPv6 автоматически генерируются на основе MAC-адреса.

## Базовые концепции

### Отличия от IPv4 в контексте Linux

1. **Адресное пространство:** 128 бит вместо 32, что обеспечивает практически неограниченное количество адресов.
2. **Автоконфигурация:** Поддержка SLAAC (Stateless Address Autoconfiguration) и DHCPv6 (подробнее см. [DHCP для IPv6](../../../Networking/Protocols/dhcp.md)).
3. **ICMPv6:** В IPv6 протокол ICMPv6 выполняет функции ARP (через NDP — Neighbor Discovery Protocol).
4. **Безопасность:** IPv6 требует отдельных правил файрвола (не наследуются от IPv4).

### Типы IPv6-адресов

| Тип | Префикс | Описание |
| :--- | :--- | :--- |
| **Global Unicast** | `2000::/3` | Публичные адреса, маршрутизируемые в интернете |
| **Unique Local (ULA)** | `fc00::/7` | Частные адреса (аналог RFC 1918) |
| **Link-Local** | `fe80::/10` | Автоматические адреса, только для локальной сети |
| **Loopback** | `::1` | Аналог `127.0.0.1` |

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

### 3. Проверка доступности по IPv6

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

**Важно:** Правила iptables для IPv4 **НЕ применяются** к IPv6. Необходимо настраивать `ip6tables` отдельно.

**В firewalld:**

```bash
# Разрешить ICMPv6 (необходимо для работы IPv6)
firewall-cmd --permanent --add-protocol=icmp

# Разрешить трафик на конкретном порту для IPv6
firewall-cmd --permanent --add-port=80/tcp --ipv6

# Перезагрузить правила
firewall-cmd --reload
```

**Проблема с drop target в firewalld:**

При использовании зоны с `target: drop` входящие пакеты IPv6 могут блокироваться, включая ответы на ping. Для решения:

```bash
# Добавить протокол IPv6-ICMP
firewall-cmd --permanent --add-protocol=ipv6-icmp
firewall-cmd --reload
```

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

## Дополнительная информация

### Специальные адреса

| Адрес | Описание |
| :--- | :--- |
| `::1` | Loopback (аналог 127.0.0.1) |
| `::` | Unspecified (аналог 0.0.0.0) |
| `fe80::/10` | Link-Local (автоматические адреса) |
| `fc00::/7` | ULA (Unique Local Address) |

### Туннелирование IPv6

Для передачи IPv6 через сети, поддерживающие только IPv4, используются туннели. Подробнее см. [Туннели IPIP и SIT](../../../Networking/Tunnels/ipip_and_sit.md).

### Часто используемые утилиты

| Утилита | Назначение |
| :--- | :--- |
| `ip -6` | Управление адресами и маршрутами IPv6 |
| `ping6` | Проверка доступности по IPv6 |
| `tracepath6` | Трассировка по IPv6 |
| `ss -6` | Просмотр сокетов IPv6 |
| `ip6tables` | Файрвол для IPv6 |

### Диагностика проблем

1. **Проверить, что IPv6 включен:**
   ```bash
   sysctl net.ipv6.conf.all.disable_ipv6
   ```

2. **Проверить наличие адреса:**
   ```bash
   ip -6 address show
   ```

3. **Проверить маршруты:**
   ```bash
   ip -6 route show
   ```

4. **Проверить файрвол:**
   ```bash
   ip6tables -L -n
   ```
