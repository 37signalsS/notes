# GRE: практические сценарии настройки

## Определения

**Point-to-Point GRE** — туннель между двумя статическими конечными точками с явным указанием `remote` и `local` адресов. Базовый режим GRE.

**Multipoint GRE (mGRE)** — туннель без указания `remote`, позволяющий соединяться с множеством точек. Основа DMVPN (Dynamic Multipoint VPN) с протоколом NHRP.

**GRETAP** — режим GRE для инкапсуляции Ethernet-кадров (L2-туннелирование). Позволяет расширять L2-сегменты через L3-инфраструктуру.

**Сравнение режимов:**

| Параметр | Point-to-Point | mGRE | GRETAP |
|----------|---------------|------|--------|
| **Уровень** | L3 | L3 | L2 |
| **Remote** | Обязательно | Не указан | Обязательно |
| **Топология** | Точка-точка | Hub-and-Spoke / Mesh | Точка-точка |
| **Overhead** | ~24 байта | ~24 байта | ~42 байта |
| **Применение** | Простые VPN | DMVPN | L2-оверлей |

---

## Базовые концепции

### Общие принципы настройки GRE в Linux

**Синтаксис iproute2:**

```bash
ip link add <name> type gre \
    remote <remote_ip> local <local_ip> \
    key <tunnel_id> ttl <ttl_value>
ip link set <name> up
ip address add <tunnel_ip>/<prefix> dev <name>
```

**Общие параметры:**

| Параметр | Описание | Обязательный |
|----------|----------|--------------|
| `remote` | Внешний IP удалённой точки | Нет (для mGRE) |
| `local` | Внешний IP локальной точки | Да |
| `key` | 32-битный идентификатор туннеля | Нет (рекомендуется) |
| `ttl` | Time-to-Live внешнего пакета | Нет (по умолчанию 64) |
| `tos` | Type of Service | Нет |
| `dev` | Физический интерфейс для привязки | Нет |

**Важно:** Значение `key` должно совпадать на обеих сторонах туннеля. Без `key` ядро Linux может некорректно маршрутизировать ответные пакеты.

### Маршрутизация через GRE

После создания туннеля необходимо добавить маршруты:

```bash
# Статический маршрут через туннель
ip route add 10.10.0.0/16 dev gre0

# Или через шлюз в туннеле
ip route add 10.10.0.0/16 via 10.0.1.2
```

### Проверка конфигурации

```bash
ip -d link show <gre_if>        # Детальная информация (remote, local, key)
ip address show <gre_if>        # IP-адресация туннеля
ip route show dev <gre_if>      # Маршруты через туннель
ping -I <gre_if> <remote_ip>    # Проверка связности
tcpdump -i <gre_if> -n          # Трафик внутри туннеля
tcpdump -i eth0 proto 47 -n    # Инкапсулированные GRE-пакеты
```

---

## Практические сценарии

### 1. Point-to-Point GRE

Базовый туннель между двумя статическими точками.

**Сценарий:** Объединение двух офисов через интернет-провайдера.

```bash
# Сторона 1 (192.0.2.1)
ip link add gre0 type gre remote 192.0.2.2 local 192.0.2.1 key 100 ttl 255
ip link set gre0 up
ip address add 10.0.1.1/30 dev gre0
ip route add 10.10.0.0/16 via 10.0.1.2

# Сторона 2 (192.0.2.2)
ip link add gre0 type gre remote 192.0.2.1 local 192.0.2.2 key 100 ttl 255
ip link set gre0 up
ip address add 10.0.1.2/30 dev gre0
ip route add 10.20.0.0/16 via 10.0.1.1
```

**Проверка:**

```bash
ip -d link show gre0
# gre0: <POINTOPOINT,NOARP,UP,LOWER_UP> ... gre remote 192.0.2.2 local 192.0.2.1 key 100

ping -I gre0 10.0.1.2
tcpdump -i gre0 -n
```

**MTU:** 1476 (1500 - 24 байта GRE)

### 2. Multipoint GRE (mGRE)

Туннель с множеством точек без указания `remote`.

**Сценарий:** DMVPN — hub-and-spoke топология с динамическим обнаружением spoke-точек.

```bash
# Hub (192.0.2.1) — центральный офис
ip link add gre_mp type gre local 192.0.2.1 key 345 ttl 255
ip link set gre_mp up
ip address add 10.0.3.1/24 dev gre_mp

# Spoke 1 (192.0.2.2)
ip link add gre_mp type gre local 192.0.2.2 key 345 ttl 255
ip link set gre_mp up
ip address add 10.0.3.2/24 dev gre_mp
ip neighbour add 10.0.3.1 dev gre_mp lladdr 192.0.2.1

# Spoke 2 (192.0.2.3)
ip link add gre_mp type gre local 192.0.2.3 key 345 ttl 255
ip link set gre_mp up
ip address add 10.0.3.3/24 dev gre_mp
ip neighbour add 10.0.3.1 dev gre_mp lladdr 192.0.2.1
```

**Параметры:**

- `key 345` — общий идентификатор для всех точек DMVPN
- `lladdr` — внешний IP hub-точки (используется как L3-адрес соседа)
- Для динамического discovery требуется NHRP (Next Hop Resolution Protocol)

**Ограничения в Linux:**

- Полноценный DMVPN требует NHRP-демон (OpenNHRP)
- Статическая запись соседей работает для фиксированных топологий
- Spoke-to-spoke туннели требуют дополнительной настройки

**MTU:** 1476

### 3. GRETAP (L2-туннелирование)

Инкапсуляция Ethernet-кадров для расширения L2-сегментов через L3-сеть.

**Сценарий:** Объединение двух площадок в единый L2-сегмент для миграции VM.

```bash
# Сторона 1 (192.0.2.1)
ip link add gretap0 type gretap remote 192.0.2.2 local 192.0.2.1 ttl 255
ip link set gretap0 up
ip link set gretap0 master br0

# Сторона 2 (192.0.2.2)
ip link add gretap0 type gretap remote 192.0.2.1 local 192.0.2.2 ttl 255
ip link set gretap0 up
ip link set gretap0 master br0
```

**Применение:**

- Объединение VLAN между площадками
- Соединение виртуальных машин на разных гипервизорах
- Миграция VM без смены IP (vMotion, Live Migration)
- Расширение L2-сегментов через L3-инфраструктуру

**Overhead:** ~42 байта

- Ethernet: 14 байт
- GRE: 4 байта
- Внешний IP: 20 байт
- Внешний Ethernet: 14 байт (уже учтён в Ethernet 14)

**Итого:** 14 (Ethernet) + 4 (GRE) + 20 (IP) = 38 байт + Ethernet внешний 14 = ~42 байта

**MTU:** 1458 (1500 - 42 байта GRETAP)

**Важно:** GRETAP передаёт broadcast-трафик — возможны broadcast-штормы при петлях. Используйте STP на мостах.

### 4. GRE с IPsec

Защищённый туннель: GRE обеспечивает мультипротокольность, IPsec — шифрование.

**Краткий пример:**

```bash
# GRE-туннель
ip link add gre_sec type gre remote 203.0.113.2 local 198.51.100.1 key 500
ip link set gre_sec up
ip address add 10.0.0.1/30 dev gre_sec

# IPsec настраивается отдельно (strongSwan/LibreSwan)
# /etc/ipsec.conf: leftprotoport=47, rightprotoport=47
```

Подробно: [GRE с IPsec](./gre_ipsec_integration.md)

### 5. Постоянная конфигурация (systemd-networkd)

```ini
# /etc/systemd/network/gre0.netdev
[NetDev]
Name=gre0
Kind=gre

[Tunnel]
Remote=192.0.2.2
Local=192.0.2.1
Key=100
TTL=255
```

```ini
# /etc/systemd/network/gre0.network
[Match]
Name=gre0

[Network]
Address=10.0.1.1/30
```

---

## Дополнительная информация

### Диагностика и Troubleshooting

**Проверка работоспособности:**

```bash
# Статус интерфейса
ip -d link show <gre_if>

# Проверка ARP/соседей
ip neighbour show dev <gre_if>

# Проверка MTU
ping -M do -s 1472 <remote_tunnel_ip>

# Проверка инкапсуляции
tcpdump -i eth0 proto 47 -n -vv
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
|----------|---------|---------|
| Туннель не поднимается | Нет маршрута до remote IP | Проверить маршрут: `ip route get <remote>` |
| Пакеты не проходят | MTU слишком большой | Установить MTU: `ip link set <gre_if> mtu 1476` |
| Асимметричная маршрутизация | Разные пути туда/обратно | Настроить policy-based routing |
| Фрагментация | PMTU Discovery отключён | `sysctl -w net.ipv4.ip_no_pmtu_disc=0` |
| mGRE не видит соседей | Нет NHRP/static записей | Добавить `ip neighbour add` |
| GRETAP шторм | Петля в L2 | Включить STP на мосте |

### Сравнение с альтернативами

| Задача | GRE | Альтернатива | Когда выбрать альтернативу |
|--------|-----|-------------|---------------------------|
| L3-туннель без шифрования | GRE | IPIP | IPIP проще, если только IPv4 |
| L2-туннель | GRETAP | VXLAN | VXLAN при >100 туннелей |
| L3 с шифрованием | GRE+IPsec | WireGuard | WireGuard для новых развёртываний |
| DMVPN | mGRE+NHRP | WireGuard mesh | WireGuard проще в настройке |

### Связанные документы

- [GRE (SSoT)](./gre.md) — определения, формат заголовка, версии, сравнение протоколов
- [GRE с IPsec](./gre_ipsec_integration.md) — защищённая комбинация GRE + IPsec
- [IPSec (SSoT)](../ipsec/ipsec.md) — защищённое туннелирование
- [VXLAN](../vxlan.md) — масштабируемое L2-оверлей-туннелирование
- [Обзор туннелирования](../tunneling_overview.md) — классификация протоколов
