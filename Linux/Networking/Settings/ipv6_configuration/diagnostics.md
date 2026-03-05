# Диагностика проблем IPv6 в Linux

## Проверка включения IPv6

```bash
# Проверка, включен ли IPv6
sysctl net.ipv6.conf.all.disable_ipv6
# 0 — включен, 1 — отключен

# Включение IPv6
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0
sudo sysctl -w net.ipv6.conf.default.disable_ipv6=0

# Постоянное включение (/etc/sysctl.d/60-ipv6.conf)
net.ipv6.conf.all.disable_ipv6=0
net.ipv6.conf.default.disable_ipv6=0
```

## Проверка адресов

```bash
# Показать все IPv6-адреса
ip -6 address show

# Показать только глобальные адреса
ip -6 addr show scope global

# Показать Link-Local адреса
ip -6 addr show scope link
```

## Проверка маршрутов

```bash
# Показать таблицу маршрутизации IPv6
ip -6 route show

# Маршрут по умолчанию
ip -6 route show default

# Проверка конкретного маршрута
ip -6 route get 2001:db8::1
```

## Проверка файрвола

```bash
# ip6tables правила
sudo ip6tables -L -n -v

# firewalld статус
firewall-cmd --list-all --ipv6

# nftables правила
sudo nft list ruleset | grep -A20 "ip6"
```

## Проверка NDP (аналог ARP)

```bash
# Просмотр соседей NDP
ip -6 neigh show

# Очистка кэша NDP
ip -6 neigh flush all

# Принудительное обновление
ping6 -c1 ff02::1%eth0
```

## Проверка DNS

```bash
# Проверка AAAA записей
dig AAAA example.com
host -t AAAA example.com
nslookup -query=aaaa example.com

# Проверка резолвера
resolvectl query example.com
cat /etc/resolv.conf
```

## Диагностика подключения

### Ping

```bash
# Проверка доступности
ping6 example.com
ping -6 example.com

# С указанием интерфейса
ping6 -I eth0 fe80::1

# Проверка loopback
ping6 ::1
```

### Traceroute

```bash
# Трассировка IPv6
traceroute6 example.com
tracepath6 example.com

# С указанием интерфейса
traceroute6 -i eth0 example.com
```

### Проверка портов

```bash
# Проверка доступности порта
nc -6 -zv example.com 80
telnet -6 example.com 80

# Сканирование портов
nmap -6 -p 80,443 example.com
```

## Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Нет IPv6-адреса** | Отключен IPv6 | `sysctl -w net.ipv6.conf.all.disable_ipv6=0` |
| **Нет маршрута по умолчанию** | Нет RA / не настроен gateway | Настроить статический маршрут |
| **Не работает ping** | Блокировка ICMPv6 | Разрешить `icmpv6` в файрволе |
| **DNS не резолвит** | Нет AAAA записей | Проверить DNS, добавить AAAA |
| **Соединение таймаут** | Файрвол блокирует | Проверить ip6tables/firewalld |
| **Link-Local не работает** | Не указан интерфейс | Использовать `ping6 fe80::1%eth0` |

## Мониторинг IPv6-трафика

### tcpdump

```bash
# Перехват IPv6-трафика
tcpdump -i eth0 -nn 'ip6'

# Только ICMPv6
tcpdump -i eth0 -nn 'icmp6'

# С подробной информацией
tcpdump -i eth0 -nn 'ip6' -vvv
```

### ss

```bash
# Все IPv6 сокеты
ss -6 -tlnp

# С детальной информацией
ss -6 -tmo
```

### netstat

```bash
# Статистика IPv6
netstat -s -6

# IPv6 подключения
netstat -6 -tlnp
```

## Проверка конфигурации NetworkManager

```bash
# Показать соединения
nmcli connection show

# Детальная информация
nmcli connection show <имя> | grep ipv6

# Статус устройства
nmcli device show eth0 | grep IPV6
```

## Проверка конфигурации systemd-networkd

```bash
# Статус сети
networkctl status eth0

# Журнал
journalctl -u systemd-networkd -f

# Проверка конфигурации
cat /etc/systemd/network/10-eth0.network
```

## Полезные команды для диагностики

```bash
# Быстрая проверка IPv6
ip -6 addr show && ip -6 route show && ping6 -c3 google.com

# Проверка всех интерфейсов
for iface in $(ip -6 addr show | grep -oP '^\d+: \K[^:]+'); do
    echo "=== $iface ==="
    ip -6 addr show dev $iface
done

# Проверка доступности шлюза
ip -6 route show default | awk '{print $3}' | xargs -I {} ping6 -c3 {}
```

## Связанные темы

* **[Концепции](./concepts.md)** — типы адресов, Privacy Extensions
* **[Настройка адресов](./address_configuration.md)** — конфигурация IPv6
* **[Firewall](./firewall.md)** — настройка файрвола
* **[Туннелирование](./tunneling.md)** — IPv6 через IPv4
