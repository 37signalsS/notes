# Инструменты для сетевых расчётов

## Определения

**Инструменты для сетевых расчётов** — специализированный инструментарий (CLI-утилиты, программные библиотеки, веб-сервисы), предназначенный для автоматизации вычислений параметров IP-сетей. Эти инструменты позволяют выполнять преобразование масок, расчет границ подсетей, определение количества доступных хостов, агрегацию диапазонов и валидацию адресов в рамках CI/CD и сетевой автоматизации.

Для изучения теоретических основ IP-адресации и методов ручного расчёта см. **[расчёт параметров подсети](../../Networking/Protocols/IP_addressing/subnetting_calculation.md)**.

## Основные концепции

### ipcalc и ipcalc-ng

**ipcalc** — классическая утилита на C (или Perl-версия от Jodies) для быстрого расчёта параметров IPv4.
**ipcalc-ng** — современный форк (стандарт в RHEL 9+, Fedora), обеспечивающий полную поддержку IPv6, вывод в формате JSON и расширенную декомпозицию адресов.

**Основные возможности:**
- Расчёт сетевого адреса, широковещательного адреса (broadcast) и wildcard-маски.
- Определение диапазона HostMin/HostMax.
- Визуализация структуры адреса в двоичном виде (удобно для обучения).
- Проверка вхождения IP в подсеть (exit code 0/1).

**Установка:**
```bash
# Debian/Ubuntu
sudo apt install ipcalc

# Fedora/RHEL 9+ (ipcalc-ng)
sudo dnf install ipcalc-ng

# RHEL/CentOS (классический ipcalc)
sudo yum install ipcalc
```

**Ключевые CLI-флаги ipcalc:**
| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-n` | Только Network Address | `ipcalc -n 192.168.1.130/26` → `192.168.1.128` |
| `-b` | Только Broadcast Address | `ipcalc -b 192.168.1.130/26` → `192.168.1.191` |
| `-m` | Только Netmask | `ipcalc -m 192.168.1.0/26` → `255.255.255.192` |
| `-c` | HostMin и HostMax | `ipcalc -c 192.168.1.0/26` → `192.168.1.1 192.168.1.190` |
| `-h` | Количество хостов | `ipcalc -h 192.168.1.0/26` → `62` |
| `-i` | Reverse DNS (ICONV) | `ipcalc -i 192.168.1.130/26` → `130.1.168.192.in-addr.arpa` |
| `-a` | Двоичное представление | `ipcalc -a 192.168.1.130/26` |

**ipcalc-ng — JSON-вывод для автоматизации:**
```bash
# ipcalc-ng с JSON-выводом (удобно для парсинга в скриптах)
ipcalc-ng --json 192.168.1.0/26
```

```json
{
  "address": "192.168.1.0",
  "netmask": "255.255.255.192",
  "prefix": 26,
  "network": "192.168.1.0",
  "broadcast": "192.168.1.63",
  "hostmin": "192.168.1.1",
  "hostmax": "192.168.1.62",
  "hosts": 62
}
```

**Проверка вхождения IP в подсеть (exit code):**
```bash
# ipcalc возвращает exit code 0 если IP принадлежит подсети
ipcalc -c 192.168.1.130/26
echo $?  # → 0 (IP в подсети)

ipcalc -c 192.168.1.200/26
echo $?  # → 1 (IP не в подсети)
```

### sipcalc

**sipcalc** — продвинутая консольная утилита, ориентированная на работу со сложными IPv6-структурами. Она выводит информацию в структурированном виде, что делает её идеальной для парсинга в shell-скриптах.

**Установка:**
```bash
# Debian/Ubuntu
sudo apt install sipcalc

# Fedora/RHEL
sudo dnf install sipcalc

# Из исходников
git clone https://github.com/udhog/sipcalc && cd sipcalc
./configure && make && sudo make install
```

**Пример вывода — IPv4:**
```bash
sipcalc 192.168.10.0/24
```
```text
-[ipv4_cidr] - 192.168.10.0/24
[CIDR]   Host address    - 192.168.10.0
[HostMin]   192.168.10.1
[HostMax]   192.168.10.254
[Broadcast]   192.168.10.255
[Hosts/Net]   254                    Class C, Private Internet
```

**Пример вывода — IPv6:**
```bash
sipcalc 2001:db8:acad::/48
```
```text
-[ipv6_cidr] - 2001:db8:acad::/48
[Network]      2001:db8:acad::
[HostMin]      2001:db8:acad::1
[HostMax]      2001:db8:acad:ffff:ffff:ffff:ffff:ffff
[Host/Net]     1208925819614629174706176                  Class VERY LARGE AGGREGATE
```

**Преимущества sipcalc:**
- Полная поддержка IPv6 (в отличие от классического ipcalc)
- Вывод по каждому IPv6-блоку отдельно
- Удобный формат для парсинга (`-[имя_поля] - значение`)

### prips и grepcidr

Инструменты для массовой обработки списков адресов:
*   **prips**: Развёртывает CIDR-нотацию или диапазон (например, `10.0.0.1 10.0.0.10`) в полный список IP-адресов. Используется для генерации целей в циклах `for`.
*   **grepcidr**: Специализированная версия `grep`, которая понимает сетевую логику. Позволяет фильтровать текстовые файлы (логи) по вхождению IP в заданные CIDR-диапазоны.

**Установка prips:**
```bash
# Debian/Ubuntu
sudo apt install prips

# Fedora/RHEL
sudo dnf install prips

# Из исходников (если нет в репозитории)
wget https://github.com/iputils/iputils/raw/master/prips.c
gcc -o prips prips.c
sudo mv prips /usr/local/bin/
```

**Установка grepcidr:**
```bash
# Debian/Ubuntu
sudo apt install grepcidr

# Fedora/RHEL
sudo dnf install grepcidr

# Из исходников
wget https://www.foursys.org/download/grepcidr-2.0.tar.gz
tar xzf grepcidr-2.0.tar.gz && cd grepcidr-2.0
./configure && make && sudo make install
```

**Примеры prips:**
```bash
# Развернуть CIDR в список IP
prips 10.0.0.0/29
# → 10.0.0.0 10.0.0.1 10.0.0.2 10.0.0.3 10.0.0.4 10.0.0.5 10.0.0.6 10.0.0.7

# Развернуть диапазон
prips 192.168.1.1 192.168.1.5
# → 192.168.1.1 192.168.1.2 192.168.1.3 192.168.1.4 192.168.1.5

# Количество IP в CIDR (считает строки)
prips 10.0.0.0/24 | wc -l
# → 256

# Только хосты (без Network и Broadcast)
prips 10.0.0.0/24 | sed '1d;$d'
# → 10.0.0.1 ... 10.0.0.254
```

**Примеры grepcidr:**
```bash
# Фильтрация логов по двум подсетям
grepcidr "192.168.50.0/24 10.0.0.0/8" access.log

# Исключение диапазона из логов
grep -v "$(grepcidr 192.168.0.0/16 access.log)"

# Подсчёт запросов из конкретной подсети
grepcidr "10.0.0.0/8" access.log | wc -l

# Поиск в нескольких файлах
grep -rh "Failed password" /var/log/auth.log | grepcidr "10.0.0.0/8"
```

### aggregate

Утилита для оптимизации списков сетей. Она принимает список CIDR и объединяет их в минимально возможный набор (например, объединит две смежные `/24` в одну `/23`). Незаменима при настройке BGP-анонсов или правил брандмауэра.

**Установка:**
```bash
# Debian/Ubuntu
sudo apt install aggregate

# Fedora/RHEL
sudo dnf install aggregate

# Из исходников
wget https://www RESULTSnet.org/aggregate/aggregate-1.0.tar.gz
```

**Примеры:**
```bash
# Объединение смежных подсетей
echo "192.168.0.0/24
192.168.1.0/24
192.168.2.0/24
192.168.3.0/24" | aggregate
# → 192.168.0.0/22

# Оптимизация с wildcard (аспект mask)
echo "10.0.0.0/8
10.1.0.0/16
10.2.0.0/16" | aggregate
# → 10.0.0.0/8

# Формирование BGP prefix-list
echo "172.16.0.0/16
172.16.1.0/24
172.16.2.0/24
172.17.0.0/16" | aggregate -v
# → 172.16.0.0/15 (объединяет два /16 в один /15)

# Агрегация с сохранением detail (не объединять разные /N)
echo "192.168.0.0/24
192.168.1.0/24
192.168.2.0/25
192.168.2.128/25" | aggregate -s
# → 192.168.0.0/23, 192.168.2.0/24 (не объединяет /25 в /24)
```

### netmask

Утилита для преобразования между форматами масок (CIDR ↔ десятичная ↔ hexadecimal).

**Установка:**
```bash
# Debian/Ubuntu (обычно уже установлена)
sudo apt install netmask

# Fedora/RHEL
sudo dnf install netmask
```

**Примеры:**
```bash
# CIDR → десятичная
netmask 24
# → 255.255.255.0

# Десятичная → CIDR
netmask 255.255.255.192
# → /26

# Hex → десятичная
netmask 0xffffff00
# → 255.255.255.0

# Все форматы для /20
netmask 20
# → 255.255.240.0

# Проверка валидности маски
netmask 255.255.255.193 2>/dev/null && echo "Valid" || echo "Invalid"
# → Invalid (не непрерывная маска)
```

### Bash one-liners для быстрых расчётов

Когда нет установленных инструментов, можно использовать встроенные средства bash:

**Быстрый расчёт сети и broadcast:**
```bash
# Определение сети через位运算
ip=192.168.1.130; mask=26
# Сетевой адрес (AND операция)
echo "$(( ( $(echo $ip | tr '.' ' ') & $(echo $mask | tr '.' ' ') ) ))" | awk '{printf "%d.%d.%d.%d", and($1,255), and(rshift($1,8),255), and(rshift($1,16),255), rshift($1,24)}'
```

**Проверка CIDR через python3 (встроен во все современные Linux):**
```bash
# Быстрая проверка через Python
python3 -c "
import ipaddress
net = ipaddress.ip_network('192.168.1.0/26')
print(f'Network: {net.network_address}')
print(f'Broadcast: {net.broadcast_address}')
print(f'Hosts: {net.num_addresses - 2}')
print(f'Host range: {list(net.hosts())[:3]}...')
"

# Проверка вхождения IP в подсеть
python3 -c "
import ipaddress
addr = ipaddress.ip_address('192.168.1.130')
net = ipaddress.ip_network('192.168.1.128/26')
print(f'{addr} in {net}: {addr in net}')
"
```

**sed/awk для извлечения данных из ipcalc:**
```bash
# Извлечь только Network и Broadcast
ipcalc 192.168.1.130/26 | awk '/Network:/{print $2} /Broadcast:/{print $2}'

# Извлечь количество хостов
ipcalc 192.168.1.0/24 | awk '/Hosts\/Net:/{print $2}'

# Проверить, private ли адрес
ipcalc 10.0.0.1 | grep -q "Private" && echo "Private" || echo "Public"
```

### ip — CIDR в маршрутизации и адресации

Системная утилита `ip` (из пакета `iproute2`) активно использует CIDR-нотацию:

```bash
# Добавление IP с CIDR
sudo ip addr add 192.168.1.100/26 dev eth0

# Просмотр IP с маской
ip addr show eth0
# → inet 192.168.1.100/26 scope global eth0

# Добавление маршрута через CIDR
sudo ip route add 10.0.0.0/8 via 192.168.1.1

# Просмотр маршрутов с CIDR
ip route show
# → 10.0.0.0/8 via 192.168.1.1 dev eth0

# Проверка, является ли адрес link-local
ip addr show | grep "169.254"
```

### whois и ripestat

Инструменты для проверки владельца префикса и ASN:

```bash
# Установка whois
sudo apt install whois    # Debian/Ubuntu
sudo dnf install whois    # Fedora/RHEL

# Проверка владельца IP
whois 8.8.8.8 | grep -E "OrgName|org-name|netname"

# Проверка префикса
whois 192.168.0.0/16

# Проверка ASN
whois AS15169

# Ripestat API (веб-сервис)
curl -s "https://stat.ripe.net/data/whois/data.json?resource=8.8.8.8" | python3 -m json.tool | head -20

# Проверка whois для домена
whois example.com | grep -E "Creation Date|Registrar"
```

### Программные библиотеки

В современной разработке и DevOps-автоматизации расчеты выполняются через библиотеки:
*   **Python `ipaddress`**: Стандартная библиотека (Python 3.3+), позволяющая работать с IP как с объектами.
*   **Python `netaddr`**: Расширенная библиотека с поддержкой MAC-адресов, произвольных диапазонов и генерации сетей.
*   **Ansible `ipaddr` (netaddr)**: Фильтр Jinja2, являющийся стандартом де-факто для манипуляций с IP в плейбуках.
*   **Go `netip`**: Высокопроизводительный пакет (Go 1.18+), оптимизированный для работы без лишних аллокаций памяти.

## Практические сценарии

### Анализ подсети через ipcalc

Определение параметров сети `172.16.10.0/26`:

```bash
ipcalc 172.16.10.0/26
```

Результат выполнения (фрагмент):
```text
Address:   172.16.10.0          10101100.00010000.00001010.00 000000
Netmask:   255.255.255.192 = 26 11111111.11111111.11111111.11 000000
Network:   172.16.10.0/26       10101100.00010000.00001010.00 000000
HostMin:   172.16.10.1          10101100.00010000.00001010.00 000001
HostMax:   172.16.10.62         10101100.00010000.00001010.00 111110
Broadcast: 172.16.10.63         10101100.00010000.00001010.00 111111
Hosts/Net: 62                    Class B, Private Internet
```

### Агрегация сетей через aggregate

Оптимизация списка подсетей для BGP prefix-list:

```bash
# Исходный список (6 подсетей)
cat networks.txt
# 10.0.0.0/24
# 10.0.1.0/24
# 10.0.2.0/24
# 10.0.3.0/24
# 10.0.4.0/24
# 10.0.5.0/24

# Агрегация (2 подсети)
cat networks.txt | aggregate
# → 10.0.0.0/22
# → 10.0.4.0/23
```

**Пример с несмежными подсетями:**
```bash
echo "192.168.0.0/24
192.168.2.0/24
192.168.4.0/24
192.168.6.0/24" | aggregate
# → 192.168.0.0/22 (0-3), 192.168.4.0/22 (4-7)
```

### Генерация списка IP и сканирование (prips)

Использование в связке с другими инструментами для автоматизации проверок:

```bash
# Пинг всех хостов в сети /29
for ip in $(prips 192.168.1.0/29); do
    ping -c 1 -W 1 $ip > /dev/null && echo "$ip is UP"
done

# Сканирование TCP-портов через nmap
nmap -p 22,80,443 $(prips 10.0.0.0/28 | tr '\n' ' ')

# Проверка доступности HTTP-сервисов
for ip in $(prips 192.168.10.0/28 | sed '1d;$d'); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://$ip/health)
    [ "$code" = "200" ] && echo "$ip: OK" || echo "$ip: FAIL ($code)"
done
```

### Фильтрация логов по подсети (grepcidr)

Поиск всех запросов из доверенной сети в логах веб-сервера:

```bash
# Поиск по двум подсетям
grepcidr "192.168.50.0/24 10.0.0.0/8" access.log

# Исключение внутренних адресов
grep -v "$(grepcidr 192.168.0.0/16 access.log)" access.log

# Подсчёт уникальных IP из подсети
grepcidr "10.0.0.0/8" access.log | awk '{print $1}' | sort -u | wc -l

# Поиск FAILED Login из внешних адресов
grep "Failed password" /var/log/auth.log | grepcidr -v "192.168.0.0/16 10.0.0.0/8"
```

### Автоматизация на Python (ipaddress)

Разбиение большой сети на подсети заданного размера:

```python
import ipaddress

# 1. Разбиение сети на подсети
parent_net = ipaddress.ip_network('10.0.0.0/22')
subnets = list(parent_net.subnets(new_prefix=24))
for sn in subnets:
    print(sn) # → 10.0.0.0/24, 10.0.1.0/24, 10.0.2.0/24, 10.0.3.0/24

# 2. Проверка типа адреса
addr = ipaddress.ip_address('192.168.1.1')
print(addr.is_private) # → True
print(addr.version)    # → 4

# 3. Определение сети для IP
addr = ipaddress.ip_address('192.168.1.130')
network = ipaddress.ip_network('192.168.1.0/24')
print(addr in network)  # → True

# 4. Суммаризация (aggregate) в Python
nets = [
    ipaddress.ip_network('192.168.0.0/24'),
    ipaddress.ip_network('192.168.1.0/24'),
    ipaddress.ip_network('192.168.2.0/24'),
    ipaddress.ip_network('192.168.3.0/24'),
]
# Используем aggregate если доступен
from ipaddress import summarize_address_list
aggregated = list(summarize_address_list(nets))
for net in aggregated:
    print(net)  # → 192.168.0.0/22

# 5. Генерация IP из диапазона
network = ipaddress.ip_network('10.0.0.0/28')
for ip in network.hosts():
    print(ip)  # → 10.0.0.1 ... 10.0.0.14
```

### Python netaddr — расширенные операции

```python
from netaddr import IPNetwork, IPAddress, IPRange,cidr_merge

# 1. Базовые операции
net = IPNetwork('192.168.1.0/26')
print(net.network)      # 192.168.1.0
print(net.broadcast)    # 192.168.1.63
print(net.size)         # 64

# 2. Проверка вхождения
ip = IPAddress('192.168.1.130')
print(ip in net)        # True

# 3. Генерация диапазона IP
ip_range = IPRange('192.168.1.1', '192.168.1.10')
for addr in ip_range:
    print(addr)

# 4. CIDR merge (аналог aggregate)
nets = [
    IPNetwork('192.168.0.0/24'),
    IPNetwork('192.168.1.0/24'),
    IPNetwork('192.168.2.0/24'),
    IPNetwork('192.168.3.0/24'),
]
merged = cidr_merge(nets)
for net in merged:
    print(net)  # → 192.168.0.0/22

# 5. Преобразование форматов
from netaddr import IPNetwork
net = IPNetwork('10.0.0.0/8')
print(net.netmask)      # 255.0.0.0
print(net.hostmask)     # 0.255.255.255
```

### Сетевые фильтры в Ansible

Использование фильтра `ipaddr` (требует установленной библиотеки `netaddr` на хосте управления):

```yaml
- name: Сетевые расчеты в Ansible
  vars:
    my_net: "10.10.10.0/24"
  debug:
    msg:
      # Получить адрес сети
      network: "{{ my_net | ipaddr('network') }}"
      # Получить широковещательный адрес
      broadcast: "{{ my_net | ipaddr('broadcast') }}"
      # Получить 5-й доступный IP в подсети
      fifth_ip: "{{ my_net | ipaddr('5') }}"
      # Проверить, является ли строка корректным IP
      is_valid: "{{ '1.1.1.1' | ipaddr }}"
```

**Расширенные примеры Ansible:**
```yaml
- name: Автоматическое разбиение сети
  vars:
    parent_net: "10.0.0.0/22"
    subnet_prefix: 24
  debug:
    msg: "{{ parent_net | ipaddr('subnet(' + subnet_prefix | string + ')') }}"

- name: Фильтрация приватных адресов
  debug:
    msg: "{{ ansible_all_ipv4_addresses | ipaddr('private') }}"

- name: Проверка вхождения IP в подсеть
  debug:
    msg: "{{ '10.10.10.50' | ipaddr('10.10.10.0/24') }}"

- name: Генерация списка IP
  debug:
    msg: "{{ range(1, 255) | map('regex_replace', '^(.*)$', '10.0.0.\\1') | list }}"
```

### Go netip — высокопроизводительные расчёты

```go
package main

import (
    "fmt"
    "net/netip"
)

func main() {
    // 1. Парсинг CIDR
    prefix, _ := netip.ParsePrefix("192.168.1.0/26")
    fmt.Println("Network:", prefix.Addr())       // 192.168.1.0
    fmt.Println("Mask:", prefix.Masked().Addr())  // 192.168.1.0

    // 2. Проверка вхождения
    addr, _ := netip.ParseAddr("192.168.1.130")
    fmt.Println("Contains:", prefix.Contains(addr)) // true

    // 3. Перебор IP в подсети
    prefix, _ = netip.ParsePrefix("10.0.0.0/30")
    for addr := prefix.Addr(); prefix.Contains(addr); addr = addr.Next() {
        fmt.Println(addr)
    }
    // → 10.0.0.0, 10.0.0.1, 10.0.0.2, 10.0.0.3

    // 4. IPv6
    v6prefix, _ := netip.ParsePrefix("2001:db8::/32")
    fmt.Println("IPv6 prefix:", v6prefix)

    // 5. Compare masks
    p1, _ := netip.ParsePrefix("10.0.0.0/24")
    p2, _ := netip.ParsePrefix("10.0.0.0/25")
    fmt.Println("p1 larger:", p1.Bits() < p2.Bits()) // true (меньше бит = больше сеть)
}
```

### Преобразование масок — быстрая шпаргалка

| CIDR | Десятичная | Hex | Количество IP | Wildcard |
| :--- | :--- | :--- | :--- | :--- |
| /8 | 255.0.0.0 | 0xFF000000 | 16,777,216 | 0.255.255.255 |
| /16 | 255.255.0.0 | 0xFFFF0000 | 65,536 | 0.0.255.255 |
| /24 | 255.255.255.0 | 0xFFFFFF00 | 256 | 0.0.0.255 |
| /25 | 255.255.255.128 | 0xFFFFFF80 | 128 | 0.0.0.127 |
| /26 | 255.255.255.192 | 0xFFFFFFC0 | 64 | 0.0.0.63 |
| /27 | 255.255.255.224 | 0xFFFFFFE0 | 32 | 0.0.0.31 |
| /28 | 255.255.255.240 | 0xFFFFFFF0 | 16 | 0.0.0.15 |
| /29 | 255.255.255.248 | 0xFFFFFFF8 | 8 | 0.0.0.7 |
| /30 | 255.255.255.252 | 0xFFFFFFFC | 4 | 0.0.0.3 |
| /31 | 255.255.255.254 | 0xFFFFFFFE | 2 | 0.0.0.1 |
| /32 | 255.255.255.255 | 0xFFFFFFFF | 1 | 0.0.0.0 |

## Дополнительная информация

### Типичные ошибки и решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **IP не в подсети** | Неверная маска или неправильный CIDR | Проверить через `ipcalc -c` или `ipcalc -n` |
| **Маска не является непрерывной** | Ручной ввод ошибочной маски | Использовать `netmask` для проверки или CIDR-нотацию |
| **"No route to host" после добавления IP** | Маршрут не настроен или маска слишком широкая | Проверить `ip route show`, убедиться в правильности `/N` |
| **GREP не фильтрует по подсети** | Используется обычный `grep` вместо `grepcidr` | Заменить на `grepcidr` или `ipcalc + grep` |
| **aggregate не объединяет** | Подсети не смежные или разного размера | Проверить, что подсети действительно смежные (последовательные) |
| **prips выводит лишние IP** | Включены Network/Broadcast адреса | Использовать `sed '1d;$d'` для удаления первых и последних строк |
| **ipcalc не показывает IPv6** | Используется классический ipcalc | Перейти на `ipcalc-ng` или `sipcalc` |

### Сравнение инструментов

| Задача | Инструмент | Особенности |
| :--- | :--- | :--- |
| Быстрая проверка параметров в консоли | `ipcalc` | Лучшая визуализация двоичного вида |
| Глубокий анализ IPv6 | `sipcalc` | Подробный вывод по каждому IPv6-блоку |
| Генерация списка IP для циклов | `prips` | Поддерживает диапазоны и CIDR |
| Фильтрация логов по CIDR | `grepcidr` | Работает быстрее связки `grep + regex` |
| Оптимизация (суммирование) сетей | `aggregate` | Идеально для формирования BGP prefix-lists |
| Преобразование форматов масок | `netmask` | CIDR ↔ десятичная ↔ hex |
| Проверка владельца префикса | `whois` | Определение ASN и владельца IP |
| Инфраструктура как код (IaC) | **Ansible `ipaddr`** | Удобство работы внутри Jinja2 шаблонов |
| Программная логика | **Python `ipaddress`** | Строгая типизация и валидация объектов |
| Расширенные операции | **Python `netaddr`** | CIDR merge, MAC-адреса, произвольные диапазоны |
| Высокая производительность | **Go `netip`** | Без аллокаций, оптимизирован для массовых операций |

### Онлайн-ресурсы

- [jodies.de/ipcalc](http://jodies.de/ipcalc) — эталонный веб-калькулятор.
- [subnetonline.com](https://www.subnetonline.com/) — большой набор инструментов для IPv4 и IPv6.
- [cidr.xyz](https://cidr.xyz/) — интерактивная визуализация CIDR.
- [ripestat](https://stat.ripe.net/) — WHOIS и анализ IP-префиксов (RIPE NCC).
- [ipaddressguide.com](https://www.ipaddressguide.com/cidr/) — CIDR калькулятор.

### См. также

- **[Обзор IP-адресации](../../Networking/Protocols/IP_addressing/ip_overview.md)** — типы и назначение адресов.
- **[Специальные маски](../../Networking/Protocols/IP_addressing/special_masks.md)** — нюансы использования `/31`, `/32` и `/128`.
- **[Инструменты диагностики сети](../../Linux/Networking/network_diagnostics_tools.md)** — методы применения данных инструментов на практике.
- **[Расчет параметров подсети](../../Networking/Protocols/IP_addressing/subnetting_calculation.md)** — теория подсетей и VLSM.
