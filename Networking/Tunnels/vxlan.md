# VXLAN (Virtual Extensible LAN)

## Определения

**VXLAN (Virtual Extensible LAN)** — протокол туннелирования для создания оверлейных сетей в крупных виртуализированных средах и облачных дата-центрах.

**Ключевые характеристики:**
- **Уровень:** L2 (инкапсуляция Ethernet в UDP)
- **Транспорт:** UDP порт `4789` (IANA), `8472` (Linux по умолчанию до стандартизации)
- **Идентификатор:** VNI (24 бита) — до 16 миллионов сетей
- **RFC:** [RFC 7348](https://datatracker.ietf.org/doc/html/rfc7348)
- **Шифрование:** Отсутствует (опционально через IPsec)

**VTEP (VXLAN Tunnel End Point)** — конечная точка, выполняющая инкапсуляцию/декапсуляцию VXLAN.

## Базовые концепции

### Формат заголовка VXLAN

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|R|R|R|R|I|R|R|R|            Reserved                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                VXLAN Network Identifier (VNI) |   Reserved    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

**Поля:**
- **I-бит (бит 3):** Указывает на наличие VNI (должен быть 1)
- **VNI (24 бита):** Идентификатор виртуальной сети
- **Reserved:** Зарезервированные биты (должны быть 0)

### Принцип работы

**Инкапсуляция:**
```
[Ethernet-кадр] → [VXLAN (8 байт)] → [UDP] → [Внешний IP] → Передача
```

**Overhead:** ~50 байт
- VXLAN: 8 байт
- UDP: 8 байт
- Внешний IP: 20 байт
- Внешний Ethernet: 14 байт

### Преимущества VXLAN

| Преимущество | Описание |
|-------------|----------|
| **Масштабируемость** | 16M VNI против 4096 VLAN |
| **L2 over L3** | Расширение L2 через маршрутизируемую L3-сеть |
| **NAT-friendly** | UDP-инкапсуляция проходит через NAT |
| **ECMP** | Поддержка Equal-Cost Multi-Path маршрутизации |
| **Мультитенантность** | Изоляция арендаторов через VNI |

### Компоненты VXLAN

**VTEP (VXLAN Tunnel End Point):**
- Выполняет инкапсуляцию/декапсуляцию
- Может быть программным (Linux, vSwitch) или аппаратным (NIC, switch)

**VNI (VXLAN Network Identifier):**
- Аналог VLAN ID, но 24 бита
- Локально значимый идентификатор сегмента

**VXLAN Segment:**
- Логический L2-домен внутри VXLAN
- Аналог broadcast-домена VLAN

## Практические сценарии

### 1. Unicast (точка-точка)

**Сценарий:** Простое соединение двух хостов.

```bash
# Сторона 1 (192.0.2.1)
ip link add vxlan0 type vxlan id 100 remote 192.0.2.2 local 192.0.2.1 dev eth0 dstport 4789
ip link set vxlan0 up
ip address add 10.8.0.1/24 dev vxlan0

# Сторона 2 (192.0.2.2)
ip link add vxlan0 type vxlan id 100 remote 192.0.2.1 local 192.0.2.2 dev eth0 dstport 4789
ip link set vxlan0 up
ip address add 10.8.0.2/24 dev vxlan0
```

**Параметры:**
- `id 100` — VNI виртуальной сети
- `dev eth0` — физический интерфейс для VXLAN-трафика
- `dstport 4789` — стандартный порт VXLAN

### 2. Multicast (многоточечный)

**Сценарий:** Динамическое обнаружение VTEP через multicast.

```bash
# Все участники группы
ip link add vxlan0 type vxlan id 100 group 239.0.0.10 local 192.0.2.1 dev eth0 dstport 4789
ip link set vxlan0 up
ip address add 10.8.0.1/24 dev vxlan0
```

**Требования:**
- Поддержка multicast в сети
- Настроенный IGMP для управления группами
- [Адреса 239.0.0.0/8](../Concepts/network_classification.md) — локально-административные

**Ограничения:**
- Multicast обычно не работает через публичный Интернет
- Требует настройки multicast-маршрутизации

### 3. VXLAN с FDB (Forwarding Database)

**Сценарий:** Статическая или динамическая таблица MAC-адресов.

```bash
# Создание VXLAN без remote (для FDB)
ip link add vxlan0 type vxlan id 100 dev eth0 dstport 4789
ip link set vxlan0 up

# Добавление записей FDB
bridge fdb append to 00:11:22:33:44:55 dev vxlan0 dst 192.0.2.2
bridge fdb append to 00:11:22:33:44:66 dev vxlan0 dst 192.0.2.3
```

**Применение:**
- Интеграция с SDN-контроллерами
- Динамическое обучение MAC-адресов

### 4. VXLAN в Kubernetes (CNI)

**Примеры CNI с VXLAN:**
- **Flannel:** VXLAN backend по умолчанию
- **Calico:** VXLAN для cross-subnet
- **Cilium:** VXLAN для cluster pooling

**Типичная конфигурация Flannel:**
```json
{
  "Network": "10.244.0.0/16",
  "Backend": {
    "Type": "vxlan",
    "VNI": 1,
    "Port": 8472
  }
}
```

### 5. Проверка и диагностика

```bash
# Статус VXLAN
ip -d link show vxlan0

# Таблица FDB (MAC-адреса)
bridge fdb show dev vxlan0

# Группы multicast
bridge mdb show

# Мониторинг трафика
tcpdump -i eth0 udp port 4789 -n
tcpdump -i vxlan0 -n
```

## Дополнительная информация

### Сравнение с другими L2-оверлеями

| Протокол | Overhead | Масштаб | Транспорт | Сценарий |
|----------|----------|---------|-----------|----------|
| **VXLAN** | ~50 байт | 16M VNI | UDP | Дата-центры |
| **GRETAP** | ~42 байта | Ограничен | IP (47) | Простые L2 |
| **Geneve** | ~50+ байт | 16M | UDP (6081) | Гибкий (TLV) |
| **STT** | ~50 байт | 16M | TCP | VMware NSX |
| **NVGRE** | ~42 байта | 16M | GRE | Hyper-V |

### Ограничения

| Ограничение | Описание | Митигация |
|-------------|----------|-----------|
| **Нет шифрования** | Трафик открыт | IPsec, MACsec |
| **MTU** | Уменьшение на ~50 байт | Jumbo frames, PMTUD |
| **Multicast** | Требует поддержки в сети | Unicast с FDB |
| **CPU overhead** | Инкапсуляция в userspace | Offload на NIC |

### VXLAN Offload

**Аппаратная поддержка:**
- Современные NIC поддерживают VXLAN checksum/TLS offload
- Проверка: `ethtool -k eth0 | grep vxlan`

**Включение offload:**
```bash
ethtool -K eth0 vxlan-hw-offload on
```

### MTU considerations

**Расчёт MTU для VXLAN:**
```
Базовый MTU (1500) - VXLAN overhead (50) = 1450
```

**Настройка:**
```bash
# Для физического интерфейса (jumbo frames)
ip link set eth0 mtu 9000

# Для VXLAN-интерфейса
ip link set vxlan0 mtu 1450
```

### Ссылки

- [RFC 7348 — VXLAN](https://datatracker.ietf.org/doc/html/rfc7348)
- [RFC 8365 — VXLAN-GPE (Generic Protocol Extension)](https://datatracker.ietf.org/doc/html/rfc8365)
- [Linux VXLAN Documentation](https://www.kernel.org/doc/Documentation/networking/vxlan.txt)
