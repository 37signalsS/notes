# DPDK и ядро — KNI, Tap devices, взаимодействие с network stack

### Определения

- **KNI (Kernel NIC Interface)**: Механизм DPDK для перенаправления части трафика из DPDK в kernel network stack. Позволяет использовать kernel-based инструменты (tcpdump, ip route, iptables) с NIC, управляемым DPDK.
- **rte_kni**: Библиотека DPDK для создания KNI интерфейсов. Создаёт виртуальный NIC в kernel, привязанный к DPDK-порту.
- **KNI interface**: Виртуальный сетевой интерфейс в kernel (eth0, eth1, ...), привязанный к DPDK-порту через KNI. Поддерживает стандартные kernel операции (ip addr, ip route, tcpdump).
- **TAP device**: Виртуальный сетевой интерфейс в userspace (управляемый через /dev/net/tun). Используется для перенаправления трафика между DPDK-приложением и kernel.
- **vhost-user**: Протокол для взаимодействия DPDK-приложения с QEMU/KVM виртуальными машинами. Реализуется через Unix socket и shared memory.
- **vhost-user-client**: Режим vhost-user, при котором DPDK-приложение выступает как клиент (подключается к QEMU). В отличие от server mode, где QEMU подключается к DPDK.
- **vdpa (vDPA, virtio Data Path Acceleration)**: Механизм для аппаратного ускорения virtio через SR-IOV. Позволяет ВМ использовать virtio API, но данные обрабатываются аппаратно через VF.
- **Macvtap**: Упрощённый виртуальный интерфейс для VM networking (альтернатива TAP). Используется для прямого подключения VM к физическому NIC.
- ** bonded interface**: Linux kernel bonding interface, используемый для объединения KNI-интерфейсов в bond.

---

### Теория

#### 1. Когда нужно взаимодействие с kernel

| Сценарий | Зачем нужен kernel | Механизм |
| :--- | :--- | :--- |
| **tcpdump на NIC** | Отладка трафика (lenient capture) | KNI |
| **ip route/iptables** | Управление маршрутизацией, файрволом | KNI |
| **DHCP client** | Получение IP-адреса от DHCP сервера | KNI |
| **ARP** | Разрешение MAC-адресов (базовый L3) | KNI |
| **Control plane** | Обработка BGP, OSPF, IS-IS | KNI |
| **VM networking** | Подключение VM к DPDK-управляемому NIC | vhost-user |
| **Legacy apps** | Приложения, не поддерживающие DPDK | TAP |

#### 2. Архитектура KNI

```
┌─────────────────────────────────────────────────────────┐
│ Userspace                                                │
│ ┌──────────────────────────────────────────────────────┐│
│ │ DPDK Application                                     ││
│ │   ├── rte_eth_rx_burst() ← NIC                      ││
│ │   ├── process_packet()                               ││
│ │   └── rte_kni_tx_burst(kni, mbufs) → KNI           ││
│ └──────────────────────────────────────────────────────┘│
│         │                                                │
│         ▼                                                │
│ ┌──────────────────────────────────────────────────────┐│
│ │ KNI Library (librte_kni)                             ││
│ │   └── /dev/kni                                       ││
│ └──────────────────────────────────────────────────────┘│
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│ Kernel                                                   │
│ ┌──────────────────────────────────────────────────────┐│
│ │ KNI Driver                                           ││
│ │   └── KNI interface (eth0)                           ││
│ │       ├── ip addr show                               ││
│ │       ├── tcpdump -i eth0                            ││
│ │       └── ip route add 10.0.0.0/8 via 10.0.0.1     ││
│ └──────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**KNI workflows:**
- **RX (от NIC к kernel)**:一部分 пакетов копируются из DPDK mempool в kernel через `/dev/kni`
- **TX (от kernel к NIC)**: Kernel отправляет пакеты через KNI → DPDK получает через `rte_kni_rx_burst`
- **Select**: Приложение решает какие пакеты идти в kernel (по фильтру, по protocol type)

#### 3. KNI vs TAP vs vhost-user

| Критерий | KNI | TAP | vhost-user |
| :--- | :--- | :--- | :--- |
| **Производительность** | ~1-2 Mpps | ~0.5-1 Mpps | ~5-10 Mpps |
| **Задержка** | ~5-10 мкс | ~10-20 мкс | ~2-5 мкс |
| **Сценарий** | Control plane, tcpdump | Legacy apps | VM networking |
| **Сложность** | Средняя | Низкая | Высокая |
| **Kernel involvement** | Полный | Полный | Minimal |
| **DPDK offload** | Частичный | Нет | Полный |

---

### Практическое руководство

#### 1. Создание KNI interface

```c
#include <rte_kni.h>

// Инициализация KNI
struct rte_kni_conf conf;
strlcpy(conf.name, "kni0", sizeof(conf.name));
conf.core_id = rte_lcore_id();
conf.force_bind = 1;  // Привязка к ядру
conf.mbuf_size = 2048;
conf.mbuf_cache_size = 256;

// Настройка networking
conf.addr = 0x0A000001;  // IP: 10.0.0.1
conf.netmask = 0xFFFFFF00; // Mask: 255.255.255.0
conf.link = 1;            // Link up

struct rte_kni *kni = rte_kni_init(port_id, &conf);

// Использование в RX path
unsigned nb_rx = rte_eth_rx_burst(port_id, queue_id, pkts_burst, 32);
for (unsigned i = 0; i < nb_rx; i++) {
    if (should_go_to_kernel(pkts_burst[i])) {
        // Отправить в kernel через KNI
        rte_kni_tx_burst(kni, &pkts_burst[i], 1);
    } else {
        // Обработать в DPDK
        process_packet(pkts_burst[i]);
        rte_eth_tx_burst(port_id, queue_id, &pkts_burst[i], 1);
    }
}

// Получение пакетов из kernel
struct rte_mbuf *kni_pkts[32];
unsigned nb_kni = rte_kni_rx_burst(kni, kni_pkts, 32);
rte_eth_tx_burst(port_id, queue_id, kni_pkts, nb_kni);
```

#### 2. Настройка KNI в kernel

```bash
# Загрузка KNI модуля
sudo modprobe rte_kni

# Конфигурация KNI
echo 1 | sudo tee /sys/module/rte_kni/parameters/kernel_core
echo 4 | sudo tee /sys/module/rte_kni/parameters/lo_mode

# Проверка KNI интерфейсов
ip link show
# → kni0: <BROADCAST,MULTICAST,UP> mtu 1500
# → kni1: <BROADCAST,MULTICAST,UP> mtu 1500

# Настройка IP
sudo ip addr add 10.0.0.1/24 dev kni0
sudo ip link set kni0 up

# Тестирование
ping 10.0.0.2
tcpdump -i kni0 -nn

# Маршрутизация
sudo ip route add 192.168.0.0/16 via 10.0.0.2
```

#### 3. TAP device (упрощённая альтернатива KNI)

```c
// Создание TAP устройства
int tap_fd = open("/dev/net/tun", O_RDWR);
struct ifreq ifr;
ifr.ifr_flags = IFF_TAP | IFF_NO_PI;
strlcpy(ifr.ifr_name, "tap0", IFNAMSIZ);
ioctl(tap_fd, TUNSETIFF, &ifr);

// Чтение пакетов из TAP
char buf[2048];
int n = read(tap_fd, buf, sizeof(buf));
// → Пакет из kernel

// Запись пакета в TAP
write(tap_fd, buf, len);
// → Пакет уходит в kernel
```

#### 4. vhost-user (для VM networking)

```c
#include <rte_vhost.h>

// Создание vhost-user socket
int vid = rte_vhost_driver_register(
    "/var/run/dpdk/vhost-user.sock",
    0  // flags
);

// Настройка vhost-user
rte_vhost_driver_enable_features(vid,
    (1ULL << VIRTIO_NET_F_MAC) |
    (1ULL << VIRTIO_NET_F_STATUS));

// Получение virtqueue
struct rte_vhost_device_ops ops = {
    .new_device = vhost_new_device,
    .destroy_device = vhost_destroy_device,
};
rte_vhost_driver_callback_register("/var/run/dpdk/vhost-user.sock", &ops);
```

```bash
# QEMU: подключение к vhost-user socket
qemu-system-x86_64 \
  -chardev socket,id=char0,path=/var/run/dpdk/vhost-user.sock \
  -netdev vhost-user,id=net0,chardev=char0 \
  -device virtio-net-pci,netdev=net0,mac=52:54:00:00:00:01
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| KNI interface не создаётся | `rte_kni_init` fails | Модуль rte_kni не загружен | `sudo modprobe rte_kni` |
| Пакеты не доходят в kernel | tcpdump не видит трафик | KNI не привязан к queue | Проверьте `rte_kni_tx_burst` в RX path |
| vhost-user VM не видит сеть | VM не получает IP | Socket path неправильный | Проверьте `ls -la /var/run/dpdk/vhost-user.sock` |
| TAP устройство慢速 | ~0.5 Mpps | TAP overhead (kernel involvement) | Используйте KNI или vhost-user |

---

### Дополнительная информация

- **[DPDK: Архитектура](dpdk_overview.md)** — общая архитектура DPDK.
- **[DPDK: Тестирование](dpdk_testing.md)** — тестирование KNI и vhost-user.
- **[DPDK KNI Guide](https://doc.dpdk.org/guides/prog_guide/kernel_nic_interface.html)** — официальный гайд по KNI.
- **[Linux TUN/TAP](https://www.kernel.org/doc/Documentation/networking/tuntap.txt)** — документация TAP.
- **[vhost-user specification](https://qemu-project.gitlab.io/qemu/tech/vhost-user.html)** — спецификация vhost-user.
