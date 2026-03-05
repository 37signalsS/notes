# GRE (Generic Routing Encapsulation)

## Определения

**GRE (Generic Routing Encapsulation)** — протокол туннелирования, разработанный Cisco, для инкапсуляции широкого спектра сетевых протоколов (IPv4, IPv6, Ethernet) внутри IP-пакетов.

**Ключевые характеристики:**

- **Протокол:** Номер `47` в заголовке внешнего IP
- **Уровень:** L2/L3 (поддерживает GRETAP для L2)
- **Шифрование:** Отсутствует (опционально через IPsec)
- **Топология:** Point-to-Point, Multipoint (mGRE)

## Базовые концепции

### Формат заголовка GRE

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|C|R|K|S|s|Recur|  Flags  | Ver |         Protocol Type         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|      Checksum (optional)      |       Reserved1 (optional)    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Key (optional)                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                 Sequence Number (optional)                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

**Флаги:**

- **C (Checksum Present)** — бит 0: наличие контрольной суммы
- **K (Key Present)** — бит 2: наличие поля Key
- **S (Sequence Number Present)** — бит 3: наличие порядкового номера

**Поле Key:**

- 32-битный идентификатор туннеля
- **Не является шифрованием** — служит для различения множественных туннелей между одними хостами
- Используется в mGRE/DMVPN для идентификации туннелей

### Принцип работы

1. Пассажирский пакет (IPv4/IPv6/Ethernet) поступает на GRE-интерфейс
2. Добавляется заголовок GRE (4+ байта)
3. Добавляется внешний IP-заголовок (20 байт)
4. Пакет передаётся через физическую сеть
5. На удалённой точке — декапсуляция

**Overhead:** ~24 байта (без Key) или ~28 байт (с Key)

### MTU и фрагментация

GRE уменьшает эффективный MTU туннеля:

| Базовый MTU | GRE Overhead | Эффективный MTU |
|-------------|--------------|-----------------|
| 1500 | 24 байта | 1476 |
| 1500 | 28 байт (с Key) | 1472 |

**Рекомендации:**

- Установить `ip link set <gre_if> mtu 1476`
- Включить Path MTU Discovery: `sysctl -w net.ipv4.ip_no_pmtu_disc=0`
- Для TCP: `tcp_mtu_probing=1`

## Практические сценарии

### 1. Point-to-Point GRE

Базовый режим — туннель между двумя статическими точками.

**Пример настройки в Linux:**

```bash
# Сторона 1 (192.0.2.1)
ip link add gre0 type gre remote 192.0.2.2 local 192.0.2.1 key 100
ip link set gre0 up
ip address add 10.0.1.1/30 dev gre0

# Сторона 2 (192.0.2.2)
ip link add gre0 type gre remote 192.0.2.1 local 192.0.2.2 key 100
ip link set gre0 up
ip address add 10.0.1.2/30 dev gre0
```

**Проверка:**

```bash
ip -d link show gre0
ping -I gre0 10.0.1.2
tcpdump -i gre0 -n
```

### 2. Multipoint GRE (mGRE)

Режим без указания `remote` — соединение с множеством точек.

**Применение:** DMVPN (Dynamic Multipoint VPN) с NHRP.

**Пример настройки:**

```bash
# Hub (192.0.2.1)
ip link add gre_mp type gre local 192.0.2.1 key 345
ip link set gre_mp up
ip address add 10.0.3.1/24 dev gre_mp

# Spoke (192.0.2.2)
ip link add gre_mp type gre local 192.0.2.2 key 345
ip link set gre_mp up
ip address add 10.0.3.2/24 dev gre_mp

# Статическая запись соседа (для Spoke)
ip neighbour add 10.0.3.1 dev gre_mp lladdr 192.0.2.1
```

**Параметры:**

- `key 345` — идентификатор туннеля (общий для всех точек)
- `lladdr` — внешний IP удалённой точки (MAC-адрес для L3)

### 3. GRETAP (L2-туннелирование)

Инкапсуляция Ethernet-кадров для расширения L2-сегментов.

**Применение:**

- Объединение VLAN между площадками
- Соединение виртуальных машин на разных гипервизорах
- Миграция VM без смены IP

**Пример настройки:**

```bash
# Сторона 1
ip link add gretap0 type gretap remote 192.0.2.2 local 192.0.2.1
ip link set gretap0 up
ip link set gretap0 master br0

# Сторона 2
ip link add gretap0 type gretap remote 192.0.2.1 local 192.0.2.2
ip link set gretap0 up
ip link set gretap0 master br0
```

**Overhead:** ~42 байта (Ethernet + GRE + IP)

### 4. GRE с IPsec

Комбинация для защищённого туннеля.

**Схема:**

```
[IP-пакет] → [GRE] → [IPsec ESP] → [Внешний IP]
```

**Пример (strongSwan):**

```bash
# GRE-туннель
ip link add gre_sec type gre remote 203.0.113.2 local 198.51.100.1
ip link set gre_sec up
ip address add 10.0.0.1/30 dev gre_sec

# IPsec защищает протокол 47 (GRE)
# conn gre-tunnel in /etc/ipsec.conf:
# left=198.51.100.1, right=203.0.113.2
# leftprotoport=47, rightprotoport=47
```

## Дополнительная информация

### Сравнение с другими протоколами

| Критерий | GRE | IPIP/SIT | VXLAN |
|----------|-----|----------|-------|
| **Уровень** | L2/L3 | L3 | L2 |
| **Протоколы** | Любые | IPv4/IPv6 | Ethernet |
| **Key/ID** | Да (32 бит) | Нет | VNI (24 бит) |
| **Транспорт** | IP (47) | IP (4/41) | UDP (4789) |
| **Масштаб** | Средний | Низкий | Высокий (16M) |
| **Сценарий** | Универсальный | Транзит протокола | Дата-центр |

### Преимущества GRE

- **Гибкость:** Инкапсуляция любых протоколов
- **Мультиплексирование:** Multiple туннелей через Key
- **Простота:** Минимальная конфигурация
- **Совместимость:** Поддержка всеми вендорами

### Недостатки GRE

- **Нет шифрования:** Требуется IPsec для безопасности
- **Overhead:** Уменьшение MTU на 24-42 байта
- **Масштабируемость:** Хуже чем VXLAN в больших средах
- **Stateless:** Нет встроенного контроля состояния

### Troubleshooting

**Проверка статуса:**

```bash
ip -d link show <gre_if>
ip address show <gre_if>
ip route get <remote_ip>
```

**Диагностика:**

```bash
# Проверка маршрута до remote
traceroute -n <remote_ip>

# Проверка инкапсуляции
tcpdump -i <phys_if> proto 47 -n

# Проверка MTU
ping -M do -s 1472 <remote_tunnel_ip>
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
|----------|---------|---------|
| Туннель не поднимается | Нет маршрута до remote | Проверить маршрут до внешнего IP |
| Пакеты не проходят | MTU слишком большой | Установить MTU 1476 |
| Асимметричная маршрутизация | Разные пути туда/обратно | Настроить policy-based routing |
| Фрагментация | PMTU Discovery отключён | Включить `ip_no_pmtu_disc=0` |

### Ссылки

- [RFC 2784 — Generic Routing Encapsulation](https://datatracker.ietf.org/doc/html/rfc2784)
- [RFC 2890 — Key and Sequence Number Extensions to GRE](https://datatracker.ietf.org/doc/html/rfc2890)
- [Linux GRE Documentation](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
