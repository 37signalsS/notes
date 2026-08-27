# Безопасность DPDK — Trust, Spoof, MACsec

### Определения

- **Trust mode**: Режим NIC, при котором гостевая ОС может изменять параметры интерфейса (MAC address, VLAN, Promiscuous mode). Отключается для изоляции (no trust mode = изолированный VF).
- **Spoof checking**: Аппаратная проверка NIC на соответствие MAC-адреса пакета MAC-адресу VF. Если MAC не совпадает — пакет отбрасывается. Защита от MAC spoofing.
- **VLAN anti-spoof**: Аппаратная проверка NIC на соответствие VLAN-тега пакета разрешённым VLAN на VF. Если VLAN не разрешён — пакет отбрасывается.
- **MACsec (802.1AE)**: Протокол L2 шифрования и аутентификации Ethernet frames. Шифрует весь Ethernet frame (включая MAC headers). Требует поддержки NIC и switch.
- **Promiscuous mode**: Режим NIC, при котором NIC принимает ВСЕ кадры, независимо от MAC-адреса. Опасен в виртуализации (sniffing трафика других VF).
- **Isolated VF**: VF с отключённым trust mode и включёнными проверками (spoof checking, VLAN anti-spoof). Используется для изоляции tenant в NFV/cloud.
- **Rate limiting (VF)**: Аппаратное ограничение пропускной способности VF (egress rate limiting). Предотвращает "noisy neighbors".
- **MAC address filtering**: Аппаратная фильтрация по MAC-адресу. NIC принимает только кадры с разрешёнными MAC-адресами.
- **Trust domain**: Концепция изоляции, при которой каждый VF находится в своём trust domain. Невозможно перехватить трафик другого VF.
- **IEEE 802.1X**: Протокол портовой аутентификации (NAC). Используется для контроля доступа к сети на L2.
- **Port security**: Механизм ограничения количества MAC-адресов на порту (dynamic MAC limiting).

---

### Теория

#### 1. Модель безопасности DPDK

```
┌─────────────────────────────────────────────────────────┐
│ Уровень 1: Hardware Isolation (NIC)                     │
│ ├── Spoof checking (MAC, VLAN)                          │
│ ├── Rate limiting (per-VF)                              │
│ ├── VLAN anti-spoof                                     │
│ └── Promiscuous mode disable                            │
└─────────────────────────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────────────────┐
│ Уровень 2: IOMMU Isolation (CPU)                        │
│ ├── DMA isolation (VT-d / AMD-Vi)                      │
│ ├── Memory isolation (MMIO regions)                    │
│ └── IRQ isolation (MSI-X)                               │
└─────────────────────────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────────────────┐
│ Уровень 3: Software Isolation (DPDK)                    │
│ ├── Mempool isolation (per-VF pools)                   │
│ ├── rte_flow isolation (traffic steering)              │
│ └── rte_mtr isolation (QoS per-VF)                     │
└─────────────────────────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────────────────┐
│ Уровень 4: Encryption (Crypto)                          │
│ ├── MACsec (L2, 802.1AE)                               │
│ ├── IPsec (L3, RFC 4303)                               │
│ └── TLS (L4, RFC 8446)                                 │
└─────────────────────────────────────────────────────────┘
```

#### 2. Trust vs No-Trust

| Параметр | Trust Mode | No-Trust Mode |
| :--- | :--- | :--- |
| **Promiscuous mode** | Разрешён | Запрещён |
| **MAC spoofing** | Разрешён | Запрещён |
| **VLAN spoofing** | Разрешён | Запрещён |
| **Broadcast** | Разрешён | Разрешён (обычно) |
| **Multicast** | Разрешён | Разрешён (фильтрация по group) |
| **Broadcast storm** | Возможно | Предотвращено |
| **Использование** | Доверенные VM (admin access) | Tenant VM (NFV, cloud) |

#### 3. MACsec (802.1AE)

```
Обычный Ethernet frame:
┌──────────┬──────────┬──────────┬──────┬─────┐
│ Dst MAC  │ Src MAC  │ EtherType│ Data │ FCS │
└──────────┴──────────┴──────────┴──────┴─────┘

MACsec frame:
┌──────────┬──────────┬──────────┬──────────┬──────┬─────┐
│ Dst MAC  │ Src MAC  │ 0x88E5   │ SecTag   │ Data │ ICV │
│          │          │ (MACsec) │ (SCI,AN, │(enc) │(auth│
│          │          │          │  SCI,etc)│      │ tag)│
└──────────┴──────────┴──────────┴──────────┴──────┴─────┘

- SecTag: 16 bytes (SCI, AN, E, C, S bits)
- ICV: 16 bytes (integrity check value)
- Шифрование: AES-GCM-128/256
```

---

### Практическое руководство

#### 1. Отключение trust mode на VF

```bash
# Отключение trust mode (no-trust)
ip link set enp1s0 vf 0 trust off

# Включение trust mode (для admin VM)
ip link set enp1s0 vf 0 trust on

# Проверка
ip link show enp1s0
# → vf 0 MAC 52:54:00:00:00:01, vlan 100, spoof checking on, rate 1000, trust off
```

#### 2. Включение spoof checking

```bash
# Включение MAC spoof checking
ip link set enp1s0 vf 0 spoof on

# Отключение MAC spoof checking (для debugging)
ip link set enp1s0 vf 0 spoof off

# Включение VLAN spoof checking (обычно включено по умолчанию)
ethtool --set-priv-flags enp1s0 "vf-vlan-spoofcheck" on

# Проверка
ip link show enp1s0
# → vf 0 MAC ... spoof checking on
```

#### 3. Ограничение пропускной способности VF

```bash
# Ограничение VF до 1 Gbps (egress)
ip link set enp1s0 vf 0 rate 1000

# Ограничение до 100 Mbps
ip link set enp1s0 vf 0 rate 100

# Проверка
ip link show enp1s0
# → vf 0 MAC ... rate 1000, spoof checking on, trust off
```

#### 4. VLAN isolation

```bash
# Назначение VF только VLAN 100
ip link set enp1s0 vf 0 vlan 100

# Несколько VLAN для VF
ip link set enp1s0 vf 0 vlan 100,200,300

# Отключение VLAN filter
ip link set enp1s0 vf 0 vlan -1

# Проверка
ip link show enp1s0
# → vf 0 MAC ... vlan 100
```

#### 5. Настройка MACsec (802.1AE)

```bash
# Проверка MACsec support
ethtool -S enp1s0 | grep -i macsec
# → macsec_tx_sa_0: 0
# → macsec_rx_sa_0: 0

# Создание MACsec security association
macsecctl link add macsec0 \
  macaddr 00:11:22:33:44:55 \
  cipher-suite GCM-AES-128 \
  key 0123456789abcdef01234567

# Включение MACsec на интерфейсе
ip link set macsec0 up
ip addr add 10.0.0.1/24 dev macsec0

# Проверка
ip macsec show
# → macsec0: sa 0, pn 0, dir tx, active on
```

#### 6. Валидация безопасности в DPDK-приложении

```c
// Проверка что trust mode отключен
struct rte_eth_dev_info dev_info;
rte_eth_dev_info_get(port_id, &dev_info);

if (dev_info.vf != 0) {
    // Проверяем что trust mode off
    // (нужно через sysfs или ip link)
}

// Проверка spoof checking
// через ethtool -S: проверка counters spoofing errors

// Проверка rate limiting
// через ip link show: rate лимит

// Проверка VLAN isolation
// через ethtool -n: VLAN фильтры
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| VM видит чужой трафик | Promiscuous mode включен | Trust mode включен | `ip link set ... vf N trust off` |
| MAC spoofing атака | VM отправляет чужой MAC | Spoof checking отключен | `ip link set ... vf N spoof on` |
| VF превышает rate | Другие VF'ы теряют пакеты | Rate limiting не настроен | `ip link set ... vf N rate 1000` |
| MACsec handshake fails | Шифрование не работает | Ключи не совпадают на两端 | Проверьте key на обоих концах |
| Broadcast storm | Все VF'ы забиты broadcast | Нет风暴 protection | Включите storm control на NIC |

---

### Дополнительная информация

- **[DPDK: SR-IOV](sriov.md)** — VF isolation через SR-IOV.
- **[DPDK: rte_flow API](dpdk_rte_flow.md)** — hardware flow isolation.
- **[DPDK: QoS](dpdk_qos.md)** — rate limiting через rte_mtr.
- **[DPDK: IPsec/Crypto](dpdk_cryptodev.md)** — L3/L4 шифрование.
- **[IEEE 802.1AE MACsec](https://standards.ieee.org/standard/802_1AE-2018.html)** — официальный стандарт.
- **[IOMMU isolation](https://www.kernel.org/doc/Documentation/Intel-IOMMU.txt)** — документация по Intel VT-d.
