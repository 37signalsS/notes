# Расчет параметров подсети (Subnetting)

**Необходимые знания:**
- Двоичная и десятичная системы счисления (перевод чисел)
- Понимание структуры IPv4-адреса (octet, 32 бита)
- Основы TCP/IP стека (модель OSI / TCP/IP)
- Базовые понятия сетевой маршрутизации (Default Gateway)

## Определения

**Адрес сети (Network Address)** — логический идентификатор всей подсети. Это первый адрес в диапазоне, у которого все биты хостовой части равны нулю. Используется маршрутизаторами для принятия решения о направлении трафика на сетевом уровне (L3). Не назначается конечным устройствам (исключение: маска `/31`).

**Широковещательный адрес (Broadcast Address)** — специальный адрес в сетях IPv4, предназначенный для отправки пакета всем узлам в рамках одной подсети. Это последний адрес в диапазоне, у которого все биты хостовой части равны единице.

**Subnetting (Сегментация)** — процесс логического разделения одной крупной IP-сети на несколько более мелких сегментов путем «заимствования» бит из хостовой части адреса в пользу сетевой.

**VLSM (Variable Length Subnet Masking)** — технология использования масок разной длины для разных подсетей в пределах одного адресного пространства, что позволяет минимизировать количество неиспользуемых IP-адресов.

## Основные концепции

### Двоичное представление и октеты

IPv4-адрес состоит из 32 бит, разделенных на 4 октета по 8 бит каждый. Каждый октет принимает значения от 0 до 255.

**Пример:** IP-адрес `192.168.1.130` в двоичном виде:
```text
Октет 1 (192): 11000000
Октет 2 (168): 10101000
Октет 3 (1):   00000001
Октет 4 (130): 10000010
Итог: 11000000.10101000.00000001.10000010
```

### Маска подсети и правило непрерывности

Маска подсети — это 32-битное число, которое определяет границу между сетевой и хостовой частями IP-адреса.
**Критическое правило:** Единицы в маске всегда должны идти непрерывным блоком слева направо. Недопустимы маски с разрывами (например, `11110011...`).

**Пример маски /26:**
- Префиксная запись: `/26` (26 единиц подряд).
- Двоичный вид: `11111111.11111111.11111111.11000000`.
- Десятичный вид: `255.255.255.192`.

### Формулы расчета вместимости

Количество доступных хостов зависит от количества «нулевых» бит ($h$) в маске.
Формула: $N = 2^h - 2$.

| Маска | Нулевых бит ($h$) | Расчет | Доступно хостов | Применение |
| :--- | :--- | :--- | :--- | :--- |
| `/24` | 8 | $2^8 - 2 = 254$ | 254 | Стандартная LAN |
| `/26` | 6 | $2^6 - 2 = 62$ | 62 | Средние отделы |
| `/30` | 2 | $2^2 - 2 = 2$ | 2 | PtP линки (устарело) |
| **`/31`** | 1 | $2^1$ | **2** | PtP (RFC 3021) |
| **`/32`** | 0 | $2^0$ | **1** | Хост-маршрут |

## Технические алгоритмы расчета

### Шаг 1. Расчет адреса сети (Network Address)

Вычисляется путем побитовой операции **логическое И (AND)** между IP и маской.

**Логика AND:** $1+1=1$, в остальных случаях $0$.

**Пример:** IP `192.168.1.130`, маска `/26` (`255.255.255.192`).
Работаем с 4-м октетом:
| Операнд | Бит 1 (128) | Бит 2 (64) | Бит 3 (32) | Бит 4 (16) | Бит 5 (8) | Бит 6 (4) | Бит 7 (2) | Бит 8 (1) | Итог |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **IP (130)** | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | **130** |
| **Mask (192)** | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | **192** |
| **AND Result** | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **128** |

**Итог:** Адрес сети — `192.168.1.128`.

### Шаг 2. Расчет широковещательного адреса (Broadcast)

Необходимо взять адрес сети и заменить все биты хостовой части (соответствующие нулям в маске) на единицы. Технически это операция `Network Address OR (NOT Mask)`.

**Пример для /26** (6 бит хоста):
1. Адрес сети (4-й октет): `10 000000` (128).
2. Заменяем 6 бит на `1`: `10 111111`.
3. Десятичный вид: $128 + 32 + 16 + 8 + 4 + 2 + 1 = 191$.
**Итог:** Broadcast — `192.168.1.191`.

### Шаг 3. Определение диапазона хостов

- **Первый хост:** Адрес сети + 1 (`192.168.1.129`).
- **Последний хост:** Broadcast - 1 (`192.168.1.190`).

## Практические сценарии

### Метод «магического числа» (Magic Number)

Позволяет быстро считать параметры подсети в уме.

1.  **Найти «интересный» октет маски** (тот, который не равен 0 или 255).
2.  **Вычислить шаг сети (S):** $S = 256 - \text{Значение октета}$.
3.  **Найти адрес сети:** Ближайшее кратное шагу $S$ число, которое меньше или равно соответствующему октету IP.

**Пример:** IP `172.16.10.50`, маска `255.255.255.240` (/28).
1.  Интересный октет: 4-й (240).
2.  Шаг сети: $256 - 240 = 16$.
3.  Кратные 16: `0, 16, 32, 48, 64...`
4.  Для числа 50 ближайшее меньшее кратное — **48**.
**Адрес сети:** `172.16.10.48`.
**Следующая сеть:** `172.16.10.64`.
**Broadcast текущей сети:** $64 - 1 = 63$.

### Проектирование сетей через VLSM

При проектировании расчет всегда начинается с самого большого сегмента.

**Задача:** Сеть `192.168.1.0/24`. Разделить для:
1.  Отдел продаж: 100 хостов.
2.  Технический отдел: 50 хостов.
3.  Серверная: 10 хостов.

**Решение:**
- **Продажи (100):** Требуется маска `/25` (126 хостов).
    - Сеть: `192.168.1.0/25`. Диапазон: `.1 – .126`. Broadcast: `.127`.
- **Техники (50):** Требуется маска `/26` (62 хоста).
    - Следующий свободный адрес: `192.168.1.128`.
    - Сеть: `192.168.1.128/26`. Диапазон: `.129 – .190`. Broadcast: `.191`.
- **Серверная (10):** Требуется маска `/28` (14 хостов).
    - Следующий свободный адрес: `192.168.1.192`.
    - Сеть: `192.168.1.192/28`. Диапазон: `.193 – .206`. Broadcast: `.207`.

### Проверка связности L2

Два узла могут общаться напрямую, если результат операции `IP AND Mask` у них совпадает.
**Критическая ошибка:** Если у двух хостов в одном физическом сегменте настроены разные маски (например, `/24` и `/25`), они могут видеть адрес сети по-разному, что приведет к тому, что один хост будет пытаться отправить пакет через шлюз, а другой — напрямую (ARP), вызывая асимметричную связность.

### Нюансы IPv6

- **Broadcast отсутствует:** Вместо него используется **Multicast**.
- **SLAAC:** Стандартный размер подсети для автоконфигурации — всегда **`/64`**. Расчет в IPv6 сводится к манипуляции 4-м квартетом (для префиксов `/48` или `/56`).

### Быстрый расчет через ipcalc

```bash
# Установка
sudo apt install ipcalc   # Debian/Ubuntu
sudo dnf install ipcalc   # Fedora/RHEL

# Базовый вывод
ipcalc 192.168.1.130/26
# → Network:   192.168.1.128/26
# → Broadcast: 192.168.1.191
# → HostMin:   192.168.1.129
# → HostMax:   192.168.1.190
# → Hosts/Net: 62

# Извлечение только network/broadcast (удобно для скриптов)
ipcalc 192.168.1.130/26 | grep -E "Network|Broadcast"
# → Network:   192.168.1.128/26
# → Broadcast: 192.168.1.191
```

### Bash-скрипт для автоматического расчета подсети

```bash
#!/bin/bash
# calc_subnet.sh — Расчет параметров подсети по IP и CIDR
# Использование: ./calc_subnet.sh 192.168.1.130/26

calculate_subnet() {
    local ip_cidr=$1
    local ip=$(echo "$ip_cidr" | cut -d'/' -f1)
    local cidr=$(echo "$ip_cidr" | cut -d'/' -f2)
    
    # Преобразование IP в число
    local ip_num=$(echo "$ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    
    # Маска
    local mask=$((0xFFFFFFFF << (32 - cidr)))
    
    # Network
    local network_num=$((ip_num & mask))
    local network=$(printf "%d.%d.%d.%d" $(( (network_num >> 24) & 0xFF )) $(( (network_num >> 16) & 0xFF )) $(( (network_num >> 8) & 0xFF )) $(( network_num & 0xFF )))
    
    # Broadcast
    local broadcast_num=$((network_num | ~mask & 0xFFFFFFFF))
    local broadcast=$(printf "%d.%d.%d.%d" $(( (broadcast_num >> 24) & 0xFF )) $(( (broadcast_num >> 16) & 0xFF )) $(( (broadcast_num >> 8) & 0xFF )) $(( broadcast_num & 0xFF )))
    
    # Host range
    local host_min=$(printf "%d.%d.%d.%d" $(( ((network_num + 1) >> 24) & 0xFF )) $(( ((network_num + 1) >> 16) & 0xFF )) $(( ((network_num + 1) >> 8) & 0xFF )) $(( (network_num + 1) & 0xFF )))
    local host_max=$(printf "%d.%d.%d.%d" $(( ((broadcast_num - 1) >> 24) & 0xFF )) $(( ((broadcast_num - 1) >> 16) & 0xFF )) $(( ((broadcast_num - 1) >> 8) & 0xFF )) $(( (broadcast_num - 1) & 0xFF )))
    
    # Total hosts
    local total_hosts=$((2 ** (32 - cidr) - 2))
    
    echo "=== Расчет подсети для $ip_cidr ==="
    echo "Network:   $network/$cidr"
    echo "Broadcast: $broadcast"
    echo "Host Range: $host_min — $host_max"
    echo "Total Hosts: $total_hosts"
    echo ""
}

# Пример использования
calculate_subnet "192.168.1.130/26"
calculate_subnet "10.0.0.50/24"
calculate_subnet "172.16.10.100/28"
```

### Проверка вхождения IP в подсеть (bash)

```bash
#!/bin/bash
# check_ip_in_subnet.sh — Проверка, принадлежит ли IP подсети

ip_in_subnet() {
    local ip=$1
    local subnet=$2
    local subnet_ip=$(echo "$subnet" | cut -d'/' -f1)
    local cidr=$(echo "$subnet" | cut -d'/' -f2)
    
    # Преобразование в числа
    local ip_num=$(echo "$ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    local subnet_num=$(echo "$subnet_ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    
    # Маска
    local mask=$((0xFFFFFFFF << (32 - cidr)))
    
    # Проверка
    if [ $((ip_num & mask)) -eq $((subnet_num & mask)) ]; then
        echo "✓ IP $ip принадлежит подсети $subnet"
        return 0
    else
        echo "✗ IP $ip НЕ принадлежит подсети $subnet"
        return 1
    fi
}

# Примеры использования
ip_in_subnet "192.168.1.150" "192.168.1.128/26"   # ✓
ip_in_subnet "192.168.1.200" "192.168.1.128/26"   # ✗
ip_in_subnet "10.0.1.100"    "10.0.0.0/16"         # ✓
```

### Автоматическое разбиение сети на подсети (bash)

```bash
#!/bin/bash
# split_subnet.sh — Разбиение сети на подсети нужного размера

split_subnet() {
    local network=$1
    local needed_hosts=$2
    
    local net_ip=$(echo "$network" | cut -d'/' -f1)
    local net_cidr=$(echo "$network" | cut -d'/' -f2)
    
    # Определяем所需的 маску
    local bits_needed=0
    local total=2
    while [ $total -lt $((needed_hosts + 2)) ]; do
        bits_needed=$((bits_needed + 1))
        total=$((2 ** (bits_needed + 1)))
    done
    local new_cidr=$((32 - bits_needed))
    
    echo "=== Разбиение $network на подсети по $needed_hosts хостов ==="
    echo "Требуется маска: /$new_cidr ($(($ total - 2)) хостов в каждой)"
    echo ""
    
    # Генерация подсетей
    local net_num=$(echo "$net_ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    local subnet_size=$((2 ** bits_needed))
    local mask=$((0xFFFFFFFF << (32 - new_cidr)))
    
    local count=0
    local current=$net_num
    
    while [ $count -lt 8 ] && [ $((current & ~mask)) -eq 0 ]; do
        local sub_ip=$(printf "%d.%d.%d.%d" $(( (current >> 24) & 0xFF )) $(( (current >> 16) & 0xFF )) $(( (current >> 8) & 0xFF )) $(( current & 0xFF )))
        local sub_broadcast=$((current | ~mask & 0xFFFFFFFF))
        local sub_bcast_ip=$(printf "%d.%d.%d.%d" $(( (sub_broadcast >> 24) & 0xFF )) $(( (sub_broadcast >> 16) & 0xFF )) $(( (sub_broadcast >> 8) & 0xFF )) $(( sub_broadcast & 0xFF )))
        
        echo "Сеть $((count+1)): $sub_ip/$new_cidr  (Broadcast: $sub_bcast_ip)"
        
        current=$((current + subnet_size))
        count=$((count + 1))
    done
}

# Пример: разбить /24 на подсети по 30 хостов
split_subnet "192.168.1.0/24" 30
```

### Расчет подсети в Python

```python
#!/usr/bin/env python3
# subnet_calc.py — Утилита для расчета параметров подсети

import ipaddress
import sys

def calc_subnet(ip_cidr):
    """Расчет параметров подсети"""
    try:
        network = ipaddress.ip_network(ip_cidr, strict=False)
        
        print(f"=== Расчет подсети для {ip_cidr} ===")
        print(f"Network:     {network.network_address}/{network.prefixlen}")
        print(f"Broadcast:   {network.broadcast_address}")
        print(f"Host Range:  {network.network_address + 1} — {network.broadcast_address - 1}")
        print(f"Total Hosts: {network.num_addresses - 2}")
        print(f"Netmask:     {network.netmask}")
        print(f"Wildcard:    {network.hostmask}")
        print()
        
        return network
    except ValueError as e:
        print(f"Ошибка: {e}")
        return None

def check_ip_in_subnet(ip_str, subnet_str):
    """Проверка принадлежности IP подсети"""
    ip = ipaddress.ip_address(ip_str)
    network = ipaddress.ip_network(subnet_str, strict=False)
    
    if ip in network:
        print(f"✓ {ip} принадлежит {network}")
        return True
    else:
        print(f"✗ {ip} НЕ принадлежит {network}")
        return False

def split_subnet(network_str, hosts_per_subnet):
    """Разбиение сети на подсети нужного размера"""
    network = ipaddress.ip_network(network_str, strict=False)
    
    # Определяем所需的.prefixlen
    bits_needed = 0
    total = 2
    while total < hosts_per_subnet + 2:
        bits_needed += 1
        total = 2 ** (bits_needed + 1)
    
    new_prefix = 32 - bits_needed
    
    print(f"=== Разбиение {network_str} на подсети по {hosts_per_subnet} хостов ===")
    print(f"Требуется маска: /{new_prefix} ({2**bits_needed - 2} хостов)")
    print()
    
    subnets = list(network.subnets(new_prefix=new_prefix))
    for i, sub in enumerate(subnets[:8], 1):
        print(f"Сеть {i}: {sub.network_address}/{sub.prefixlen}  "
              f"(Broadcast: {sub.broadcast_address})")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python3 subnet_calc.py <ip/cidr>")
        print("  python3 subnet_calc.py check <ip> <subnet>")
        print("  python3 subnet_calc.py split <network> <hosts>")
        sys.exit(1)
    
    if sys.argv[1] == "check":
        check_ip_in_subnet(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "split":
        split_subnet(sys.argv[2], int(sys.argv[3]))
    else:
        calc_subnet(sys.argv[1])
```

### Расчет для реальных сценариев

**Сценарий 1: Офисная сеть (50 хостов + рост 30%)**
```bash
# Требуется: 50 * 1.3 = 65 хостов
# Минимальная маска: /26 (62 хоста) — НЕ хватит!
# Нужна: /25 (126 хостов) — запас на рост

# Проверка через ipcalc
ipcalc 192.168.1.0/25
# → Hosts/Net: 126 — достаточно для 65 хостов
```

**Сценарий 2: Дата-центр (100 серверов, VLAN 100)**
```bash
# Требуется: 100 серверов + Gateway + network + broadcast
# Минимальная маска: /25 (126 адресов)

# Расчет
ipcalc 10.0.100.0/25
# → Network:   10.0.100.0/25
# → Broadcast: 10.0.100.127
# → HostMin:   10.0.100.1
# → HostMax:   10.0.100.126
# → Hosts/Net: 126 — идеально для 100 серверов
```

**Сценарий 3: PtP-линк между маршрутизаторами**
```bash
# Требуется: 2 адреса (маршрутизаторы)
# Оптимальная маска: /31 (RFC 3021) — 2 адреса без network/broadcast

# Проверка
ipcalc 10.0.0.0/31
# → Network:   10.0.0.0/31
# → HostMin:   10.0.0.0
# → HostMax:   10.0.0.1
# → Hosts/Net: 2 — идеально для PtP
```

### Визуализация подсети (bash)

```bash
#!/bin/bash
# visualize_subnet.sh — Визуализация диапазона подсети

visualize_subnet() {
    local ip=$1
    local cidr=$2
    
    echo "=== Визуализация подсети $ip/$cidr ==="
    echo ""
    
    # Используем ipcalc для получения параметров
    local output=$(ipcalc "$ip/$cidr")
    local network=$(echo "$output" | grep "Network:" | awk '{print $2}')
    local broadcast=$(echo "$output" | grep "Broadcast:" | awk '{print $2}')
    local hostmin=$(echo "$output" | grep "HostMin:" | awk '{print $2}')
    local hostmax=$(echo "$output" | grep "HostMax:" | awk '{print $2}')
    
    echo "Network:   $network"
    echo "Broadcast: $broadcast"
    echo ""
    
    echo "Диапазон хостов:"
    echo "  Минимум:  $hostmin"
    echo "  Максимум: $hostmax"
    echo ""
    
    # Простая визуализация
    local total_hosts=$(echo "$output" | grep "Hosts/Net:" | awk '{print $2}')
    echo "Всего хостов: $total_hosts"
    echo ""
    
    # Визуальная шкала (ограничена 64 символами)
    local used=0
    local bar=""
    local max_display=64
    local hosts_per_char=$((total_hosts / max_display + 1))
    
    for ((i=0; i<max_display; i++)); do
        if [ $used -le $total_hosts ]; then
            bar="${bar}█"
            used=$((used + hosts_per_char))
        else
            bar="${bar}░"
        fi
    done
    
    echo "Шкала заполненности:"
    echo "  [${bar}]"
    echo ""
}

# Примеры
visualize_subnet "192.168.1.0" 26
```

### Поиск всех подсетей в диапазоне IP (bash)

```bash
#!/bin/bash
# find_subnets.sh — Поиск всех подсетей в диапазоне IP

find_subnets() {
    local start_ip=$1
    local end_ip=$2
    
    echo "=== Поиск подсетей в диапазоне $start_ip — $end_ip ==="
    echo ""
    
    # Преобразуем IP в числа для сравнения
    local start_num=$(echo "$start_ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    local end_num=$(echo "$end_ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    
    local current=$start_num
    local count=0
    
    while [ $current -le $end_num ]; do
        # Определяем размер подсети (находим наибольшую маску)
        local temp=$current
        local cidr=32
        local mask=0
        
        # Ищем границу подсети
        while [ $cidr -gt 0 ]; do
            mask=$((0xFFFFFFFF << (32 - cidr)))
            local network=$((temp & mask))
            
            if [ $network -eq $temp ]; then
                break
            fi
            cidr=$((cidr - 1))
        done
        
        # Преобразуем обратно в IP
        local sub_ip=$(printf "%d.%d.%d.%d" $(( (current >> 24) & 0xFF )) $(( (current >> 16) & 0xFF )) $(( (current >> 8) & 0xFF )) $(( current & 0xFF )))
        
        # Вычисляем broadcast
        local sub_mask=$((0xFFFFFFFF << (32 - cidr)))
        local sub_broadcast=$((current | ~sub_mask & 0xFFFFFFFF))
        local sub_bcast_ip=$(printf "%d.%d.%d.%d" $(( (sub_broadcast >> 24) & 0xFF )) $(( (sub_broadcast >> 16) & 0xFF )) $(( (sub_broadcast >> 8) & 0xFF )) $(( sub_broadcast & 0xFF )))
        
        echo "Сеть: $sub_ip/$cidr  (Broadcast: $sub_bcast_ip)"
        
        current=$((sub_broadcast + 1))
        count=$((count + 1))
    done
    
    echo ""
    echo "Всего подсетей: $count"
}

# Пример: поиск подсетей в диапазоне 192.168.1.0 — 192.168.1.255
find_subnets "192.168.1.0" "192.168.1.255"
```

### Конвертация CIDR ↔ Netmask (bash)

```bash
#!/bin/bash
# cidr_to_mask.sh — Конвертация CIDR в dotted-decimal маску

cidr_to_mask() {
    local cidr=$1
    
    if [ $cidr -lt 0 ] || [ $cidr -gt 32 ]; then
        echo "Ошибка: CIDR должен быть от 0 до 32"
        return 1
    fi
    
    local mask=$((0xFFFFFFFF << (32 - cidr)))
    local dotted=$(printf "%d.%d.%d.%d" $(( (mask >> 24) & 0xFF )) $(( (mask >> 16) & 0xFF )) $(( (mask >> 8) & 0xFF )) $(( mask & 0xFF )))
    
    echo "/$cidr = $dotted"
}

# Примеры
for cidr in 0 8 16 24 25 26 27 28 29 30 31 32; do
    cidr_to_mask $cidr
done
```

## Troubleshooting

### Частые ошибки при подсетях

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Хост не пингуется** | `ping 192.168.1.x` — timeout | IP в другой подсети или неверная маска | Проверить `ip addr show`, маску на обоих хостах |
| **Duplicate IP** | Конфликт IP-адресов | Два устройства с одинаковым IP | `ip neigh show` — найти MAC, переименовать IP |
| **No route to host** | Маршрут не найден | Отсутствует route до подсети | `ip route get <IP>`, добавить route |
| **Asymmetric routing** | Пакеты идут разными путями | Разные маски на хостах в одном сегменте | Привести маски к единому значению |
| **DHCPNAK** | Клиент не получает IP | Запрос из другой подсети | Проверить relay agent, giaddr в пакете |
| **Broadcast storm** | Сеть перегружена | Петля или отсутствие STP | Включить STP, проверить топологию |

### Диагностика подсетных проблем

```bash
# Проверка IP и маски интерфейса
ip addr show | grep -E "inet |inet6 "
# → inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0

# Проверка таблицы маршрутизации
ip route show
# → default via 192.168.1.1 dev eth0
# → 192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.100

# Проверка, в какую подсеть попадает IP
ip route get 192.168.1.200
# → 192.168.1.200 dev eth0 src 192.168.1.100 uid 0

# Проверка ARP-таблицы (связь IP ↔ MAC)
ip neigh show | grep 192.168.1
# → 192.168.1.1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE

# Проверка, слушает ли сервис на правильном интерфейсе
ss -tlnp | grep :80
# → LISTEN  0  128  0.0.0.0:80  0.0.0.0:*  users:(("nginx",pid=1234,fd=6))
# Если 0.0.0.0:80 — слушает на всех интерфейсах
# Если 127.0.0.1:80 — только на loopback
# Если 192.168.1.100:80 — только на конкретном интерфейсе

# Проверка MTU (важно для подсетей с разными MTU)
ip link show eth0 | grep mtu
# → mtu 1500
```

### Автоматизация диагностики подсети

```bash
#!/bin/bash
# diagnose_subnet.sh — Полная диагностика подсетных проблем

diagnose_subnet() {
    local target_ip=$1
    local interface=${2:-eth0}
    
    echo "=== Диагностика подсети для $target_ip ==="
    echo ""
    
    # 1. Проверка локального IP
    echo "--- Локальный IP интерфейса ---"
    local local_ip=$(ip addr show "$interface" | grep "inet " | awk '{print $2}')
    echo "IP: $local_ip"
    
    local cidr=$(echo "$local_ip" | cut -d'/' -f2)
    local ip_addr=$(echo "$local_ip" | cut -d'/' -f1)
    
    # Преобразуем в числа для сравнения
    local ip_num=$(echo "$ip_addr" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    local mask=$((0xFFFFFFFF << (32 - cidr)))
    local local_network=$((ip_num & mask))
    
    echo "Сеть: $(printf "%d.%d.%d.%d" $(( (local_network >> 24) & 0xFF )) $(( (local_network >> 16) & 0xFF )) $(( (local_network >> 8) & 0xFF )) $(( local_network & 0xFF )))/$cidr"
    echo ""
    
    # 2. Проверка целевого IP
    echo "--- Целевой IP ---"
    local target_num=$(echo "$target_ip" | awk -F. '{print ($1*2^24)+($2*2^16)+($3*2^8)+$4}')
    local target_network=$((target_num & mask))
    
    if [ $target_network -eq $local_network ]; then
        echo "✓ $target_ip в той же подсети"
    else
        echo "✗ $target_ip в РАЗНОЙ подсети!"
        echo "  Локальная сеть: $(printf "%d.%d.%d.%d" $(( (local_network >> 24) & 0xFF )) $(( (local_network >> 16) & 0xFF )) $(( (local_network >> 8) & 0xFF )) $(( local_network & 0xFF )))/$cidr"
        echo "  Целевая сеть:  $(printf "%d.%d.%d.%d" $(( (target_network >> 24) & 0xFF )) $(( (target_network >> 16) & 0xFF )) $(( (target_network >> 8) & 0xFF )) $(( target_network & 0xFF )))/$cidr"
    fi
    echo ""
    
    # 3. Пинг
    echo "--- Пинг ---"
    if ping -c 1 -W 1 "$target_ip" >/dev/null 2>&1; then
        echo "✓ $target_ip доступен"
        # Замер latency
        local latency=$(ping -c 3 "$target_ip" | tail -1 | awk -F'/' '{print $5}')
        echo "  Среднее время: ${latency}ms"
    else
        echo "✗ $target_ip НЕ доступен"
    fi
    echo ""
    
    # 4. Маршрут
    echo "--- Маршрут ---"
    ip route get "$target_ip"
    echo ""
    
    # 5. ARP
    echo "--- ARP ---"
    ip neigh show | grep "$target_ip" || echo "ARP-запись не найдена"
    echo ""
    
    # 6. Traceroute (если target не пингуется)
    if ! ping -c 1 -W 1 "$target_ip" >/dev/null 2>&1; then
        echo "--- Traceroute ---"
        traceroute -n -m 5 "$target_ip" 2>/dev/null || echo "traceroute не установлен"
    fi
}

# Использование
diagnose_subnet "192.168.1.200" eth0
```

### Проверка конфликтов IP-адресов

```bash
#!/bin/bash
# check_ip_conflicts.sh — Проверка конфликтов IP в подсети

check_conflicts() {
    local subnet=$1
    
    echo "=== Проверка конфликтов IP в $subnet ==="
    echo ""
    
    # Получаем список активных IP через ARP
    echo "Активные IP (из ARP):"
    arp -a | grep -oE "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n | uniq
    echo ""
    
    # Проверка через nmap (если установлен)
    if command -v nmap >/dev/null 2>&1; then
        echo "Сканирование через nmap..."
        nmap -sn "$subnet" 2>/dev/null | grep -E "report|MAC" | head -20
    fi
}

# Использование
check_conflicts "192.168.1.0/24"
```

## Best Practices

### Правила проектирования подсетей

| Практика | Описание | Пример |
| :--- | :--- | :--- |
| **Резерв 20-30%** | Всегда оставляйте запас хостов на рост | Для 100 хостов → /25 (126 адресов) |
| **VLAN = Подсеть** | Один VLAN = одна подсеть = одна функция | VLAN 100 = серверы, VLAN 200 = пользователи |
| **Маска /31 для PtP** | Используйте /31 вместо /30 для PtP-линков | Экономия адресов (RFC 3021) |
| **Маска /32 для Loopback** | Loopback-интерфейсы всегда /32 | `ip addr add 10.0.0.1/32 dev lo` |
| **Consistent Masks** | Маски должны совпадать в пределах одного сегмента | Все хосты в VLAN должны иметь одну маску |

### Документирование

```bash
# Создание реестра подсетей (пример CSV)
cat > subnets_registry.csv << EOF
VLAN,Network,CIDR,Gateway,HostMin,HostMax,Description
100,192.168.100.0,24,192.168.100.1,192.168.100.2,192.168.100.254,Серверы
200,192.168.200.0,24,192.168.200.1,192.168.200.2,192.168.200.254,Пользователи
201,192.168.201.0,26,192.168.201.1,192.168.201.2,192.168.201.62,Бухгалтерия
300,192.168.250.0,28,192.168.250.1,192.168.250.2,192.168.250.14,DMZ
EOF

# Просмотр реестра
column -t -s',' subnets_registry.csv
```

### Оптимизация地址ного пространства

1. **Избегайте классовых масок:** Используйте CIDR, не привязывайтесь к классам A/B/C.
2. **Используйте VLSM:** Разные подсети — разные маски (экономия до 40% адресов).
3. **Суммаризация:** Объединяйте мелкие подсети в агрегированные маршруты.
4. **Приватные диапазоны:** Используйте RFC 1918 для внутренних сетей.

### Безопасность подсетей

- **Segmentation:** Разделяйте сеть по функциональному признаку (серверы, пользователи, DMZ).
- **ACL на границах:** Ограничивайте трафик между подсетями через firewall.
- **Мониторинг:** Отслеживайте появление неизвестных IP в подсетях.
- **Dynamic ARP Inspection:** Предотвращайте ARP-spoofing в критичных подсетях.

## Edge Cases

### Маска /31 для PtP-линков (RFC 3021)

**Особенности:**
- Нет network/broadcast адресов (оба адреса используются для хостов).
- Поддерживается не всем оборудованием (старые маршрутизаторы могут не поддерживать).
- Экономия: вместо 2 из 4 адресов (/30) используются 2 из 2 (/31).

```bash
# Проверка поддержки /31 на Cisco IOS
show ip interface brief | include /31

# Настройка /31 на Linux
ip addr add 10.0.0.0/31 dev eth0
ip addr add 10.0.0.1/31 dev eth1

# Проверка
ip addr show | grep "/31"
```

### Маска /32 для host-route

**Использование:**
- Loopback-интерфейсы: `ip addr add 10.0.0.1/32 dev lo`
- Host-маршруты в BGP: `network 10.0.0.1/32`
- VPN-туннели: точечные маршруты

```bash
# Добавление host-route
ip route add 10.0.0.1/32 via 192.168.1.1

# Проверка
ip route get 10.0.0.1
# → 10.0.0.1 via 192.168.1.1 dev eth0 src 192.168.1.100
```

### Overlapping Subnets

**Проблема:** Две подсети пересекаются (например, 192.168.0.0/16 и 192.168.1.0/24).

```bash
# Проверка пересечения подсетей
ipcalc 192.168.0.0/16
# → Network: 192.168.0.0/16

ipcalc 192.168.1.0/24
# → Network: 192.168.1.0/24 (внутри 192.168.0.0/16!)

# Маршрутизатор будет использовать longest prefix match:
# 192.168.1.100 → match 192.168.1.0/24 (longer)
# 192.168.2.100 → match 192.168.0.0/16 (only match)
```

### Unequal Subnet Masks в одном сегменте

**Проблема:** Два хоста в одном физическом сегменте с разными масками.

```bash
# Хост A: 192.168.1.10/24
# Хост B: 192.168.1.20/25

# Хост A видит сеть: 192.168.1.0/24
# Хост B видит сеть: 192.168.1.0/25

# Если Хост A пингует 192.168.1.200:
# - Хост A считает его в своей подсети → ARP напрямую
# - Хост B (192.168.1.20/25) считает 192.168.1.200 в другой подсети → шлёт через шлюз
# - Результат: асимметричная маршрутизация, возможны потери пакетов

# Решение: привести маски к единому значению
```

### IPv6 /64 — особенности расчета

**Отличия от IPv4:**
- SLAAC требует маску /64 (нельзя использовать другую для автоконфигурации).
- Broadcast отсутствует, используется multicast (ff02::1).
- ULA (fc00::/7) аналог IPv4 private (RFC 4193).

```bash
# Проверка IPv6-подсети
ip -6 addr show | grep "inet6"
# → inet6 2001:db8:1::100/64 scope global

# ГенерацияULA-адреса
python3 -c "
import ipaddress
ula = ipaddress.ULA('fc00::/7')
print(f'ULA: {ula}')
"

# Ping в IPv6 подсети
ping6 -I eth0 ff02::1  # Multicast all-nodes
```

### VLSM ошибки (перекрытие подсетей)

**Частые ошибки:**
- Начало с маленькой подсети вместо большой.
- Использование address space без учета границ.
- Забыть про network/broadcast адреса.

```bash
# ОШИБКА: Попытка выделить /25 после /26
# Сеть: 192.168.1.0/24
# 1. Выделили 192.168.1.0/26 (0-63)
# 2. Выделили 192.168.1.64/26 (64-127)
# 3. Хотим выделить 192.168.1.128/25 (128-255) — ОК!

# ОШИБКА: Перекрытие
# 1. 192.168.1.0/24
# 2. 192.168.1.0/25 (0-127)
# 3. 192.168.1.64/26 (64-127) — ПЕРЕКРЫТИЕ с /25!

# Проверка перекрытия через ipcalc
ipcalc 192.168.1.0/25
ipcalc 192.168.1.64/26
# → Обе сети содержат IP 192.168.1.64 — 192.168.1.127!
```

### Суммаризация (Route Aggregation)

**Проблема:** Объединение мелких подсетей в одну большую.

```bash
# Исходные подсети:
# 192.168.0.0/24
# 192.168.1.0/24
# 192.168.2.0/24
# 192.168.3.0/24

# Суммаризация:
# 192.168.0.0/22 (4 сети × 256 адресов = 1024 адреса)

# Проверка
ipcalc 192.168.0.0/22
# → Network: 192.168.0.0/22
# → Broadcast: 192.168.3.255
# → Hosts/Net: 1022

# Важно: суммаризация должна быть точной!
# 192.168.0.0/22 покрывает 192.168.0.0 — 192.168.3.255
# 192.168.0.0/23 покроет только 192.168.0.0 — 192.168.1.255 (неполная)
```

## Дополнительная информация

### Навигация по разделу
- **[IP-адресация — точка входа](./index.md)**
- **[Обзор IP-адресации](./ip_overview.md)** — структура пакетов и заголовков.
- **[Специальные маски](./special_masks.md)** — нюансы `/31`, `/32` и классовая адресация.
- **[Специальные адреса](./special_addresses.md)** — loopback, private, link-local, CGNAT.
- **[Инструменты для расчетов](../../ServicesAndTools/network_calculation_tools.md)** — `ipcalc`, `sipcalc`.
- **[VLAN Design Patterns](../../../Concepts/vlan_l2_switching/vlan_design_patterns.md)** — проектирование подсетей в VLAN.
- **[DHCP и подсети](../DHCP/dhcp_overview.md)** — автоматическое назначение адресов.
- **[Routing и подсети](../../../OSI_TCP_IP_Model/Network_layer/Concepts/routing_scenarios.md)** — маршрутизация между подсетями.

### Связанные темы
- **[NAT и приватные адреса](../../../Concepts/nat/overview.md)** — трансляция адресов.
- **[Dual-Stack (IPv4 + IPv6)](../../../OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)** — совместная работа протоколов.
- **[OSPF и подсети](../../ospf.md)** — динамическая маршрутизация подсетей.
- **[IPsec и подсети](../../../Tunnels/ipsec/ipsec.md)** — защита трафика между подсетями.

### Основные RFC
- **RFC 4632** — CIDR (Classless Inter-Domain Routing).
- **RFC 3021** — Префиксы `/31` на PtP линках.
- **RFC 1918** — Частные IP-адреса (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16).
- **RFC 4193** — Локальные IPv6 адреса (ULA, fc00::/7).
- **RFC 5737** — Документационные адреса (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
- **RFC 6598** — Shared Address Space для CGNAT (100.64.0.0/10).
- **RFC 3849** — Документационный префикс IPv6 (2001:db8::/32).
