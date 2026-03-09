# GRE: практические сценарии настройки

## 1. Point-to-Point GRE

Базовый режим — туннель между двумя статическими точками.

### Пример настройки в Linux

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

### Проверка

```bash
ip -d link show gre0
ping -I gre0 10.0.1.2
tcpdump -i gre0 -n
```

---

## 2. Multipoint GRE (mGRE)

Режим без указания `remote` — соединение с множеством точек.

**Применение:** DMVPN (Dynamic Multipoint VPN) с NHRP.

### Пример настройки

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

### Параметры

- `key 345` — идентификатор туннеля (общий для всех точек)
- `lladdr` — внешний IP удалённой точки (MAC-адрес для L3)

---

## 3. GRETAP (L2-туннелирование)

Инкапсуляция Ethernet-кадров для расширения L2-сегментов.

### Применение

- Объединение VLAN между площадками
- Соединение виртуальных машин на разных гипервизорах
- Миграция VM без смены IP

### Пример настройки

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

---

## Связанные документы

- **[GRE: архитектура](./gre_architecture.md)** — формат заголовка, версии, сравнение
- **[GRE с IPsec](./gre_ipsec_integration.md)** — защищённая комбинация
- **[Troubleshooting GRE](./gre_troubleshooting.md)** — диагностика проблем
