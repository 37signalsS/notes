# WireGuard: производительность и тюнинг

## Определения

**Throughput** — полезная пропускная способность (Мбит/с) через туннель. **Latency** — время прохождения пакета (задержка) по туннелю. **WireGuard в ядре (kernel)** — реализация как модуль ядра (`wireguard.ko`). **Userspace-реализация** — wireguard-go и Cloudflare BoringTun, работающие в пространстве пользователя. **MTU/MSS** — максимальная единица передачи и сегмента TCP (влияют на фрагментацию и максимальную скорость TCP-потоков). **RSS/RPS** — распределение обработки входящих пакетов между CPU.

## Основные концепции

### Стек обработки пакета

Пакет клиента → сетевой стек → WireGuard (шифрование ChaCha20-Poly1305, инкапсуляция UDP encap) → сетевая карта. Горячие точки производительности:

1. **Криптография**: ChaCha20-Poly1305 очень быстра и имеет SIMD-оптимизации; при включённой разгрузке (NEON/AVX) близка к AES-NI.
2. **Очереди и CPU**: один поток ядро/один queue — бутылочное горло на многоядерных серверах; помогает RSS/RPS на интерфейсе wg0 (входящий UDP).
3. **MTU/фрагментация**: при MTU выше допустимого TCP нуждается в перефрагментации → задержки и потери на UDP-пути.
4. **TCP over UDP**: TCP-поток внутри туннеля видит «сеть» с потерями как UDP-лейер; оптимальная работа — корректный MTU/MSS и грамотный qdisc на концентраторе.

### Kernel vs Userspace

| Аспект | Kernel (модуль) | Userspace (wireguard-go / BoringTun) |
|--------|-----------------|---------------------------------------|
| Скорость | Максимальная (часто 5-10 Гбит/с на современном CPU) | Обычно на 30-60% ниже |
| Потребление CPU | Ниже (in-kernel) | Выше (syscall/копирование) |
| Когда | Linux 5.6+ / DKMS | Нет модуля (старое ядро, контейнеры без `/dev/net/tun` на хосте, иные ОС) |
| Настройка | `wg-quick` по умолчанию | `WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go wg-quick up wg0` |

На практике для продакшена на Linux — только kernel-модуль; userspace используют когда ядро/среда не позволяют.

### Где брать направляющие цифры

- Сравнение WireGuard vs IPsec vs OpenVPN по скорости/overhead — в [Vpn/wireguard.md](./wireguard.md).
- Расчёт MTU/overhead и MSS Clamping — [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md).

## Практические сценарии

### 1. Методология замеров (iperf3)

Замерять **по трафику через туннель**, а не по скорости интерфейса:

```bash
# На сервере (внутри VPN-подсети)
iperf3 -s
# На клиенте — туннель в одну сторону
iperf3 -c 10.0.0.1 -t 30
# → [ ID] Interval       Transfer     Bitrate
# → [  5]  0.00-30.00 sec  2.78 GBytes  796 Mbits/sec

# Baseline без VPN (снаружи, для сравнения) 
iperf3 -c vpn.example.com -t 30
```

Сравнение «baseline без VPN» vs «через туннель» показывает чистый overhead шифрования и инкапсуляции. Подробнее про утилиту: [iperf3](../Linux/Diagnostics/Networking/iperf3.md).

### 2. GPIO-чек: MTU и MSS Clamping

Частый симптом «медленного» WireGuard — фрагментация из-за MTU. Сначала проверьте MTU/PMTUD (короткая справка в [Vpn/wireguard.md](./wireguard.md), глубже — [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)):

```bash
# Определить рабочий MTU: от 1472 вниз, пинг без фрагментации
ping -M do -s 1472 -c 1 10.0.0.1
ping -M do -s 1400 -c 1 10.0.0.1
# → reply от 10.0.0.1 (рабочий размер)

# Установка MTU на интерфейсе
sudo ip link set wg0 mtu 1420

# MSS Clamping (для протоколов за туннелем)
sudo ip6tables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```

### 3. Разгрузка обработки на все ядра (RSS/RPS для UDP)

Входящие UDP-пакеты WireGuard обрабатывает один CPU по умолчанию (одна queue карты). Проверка и разгон:

```bash
# Сколько queue использует NIC
ethtool -l eth0 | grep -i combined

# RPS: распределить обработку по CPU байтмаском (пример — все CPU)
echo ffffffff | sudo tee /sys/class/net/wg0/queues/rx-0/rps_cpus
# Или проверить текущий статус
cat /sys/class/net/wg0/queues/rx-0/rps_cpus
```

Полноценная настройка RSS/RPS и проверка загрузки ядер — [RSS, RPS, RFS](../Linux/Networking/Concepts/rss_rps_rfs.md). Это прямая рекомендация для высоконагруженных концентраторов.

### 4. Проверка загрузки шифрования и queues

```bash
# Загрузка CPU во время нагрузки: смотреть на процессы softirq/ядро
top -H -p "$(pidof kworker | tr ' ' ',')" -d 1

# Пакетные ошибки/падения на wg0
ip -s link show wg0
# → RX: bytes packets errors dropped overrun mcast
# → TX: bytes packets errors dropped carrier collsns

# Очереди qdisc на физическом интерфейсе (буферы)
tc -s qdisc show dev eth0
```

Правильное поведение qdisc и BQL на физическом интерфейсе концентратора снижает RTT и потери: [TCP Queueing Disciplines](../Linux/Networking/Concepts/tcp_tuning/tcp_queueing_disciplines.md), [TC Diagnostics](../Linux/Diagnostics/Networking/tc_diagnostics.md).

### 5. Запуск userspace-реализации (когда kernel недоступен)

```bash
# Пакет wireguard-tools содержит wg-quick; пользовательская реализация wireguard-go
# Использование:
export WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go
sudo wg-quick up wg0

# Проверка, что работает именно userspace (нет модуля wireguard.ko)
lsmod | grep wireguard || echo "kernel module not loaded"
```

Перед принятием на продакшн измерьте разницу через iperf3; при возможности вернитесь к kernel-модулю.

### 6. Сетевой sysctl-тюнинг для концентратора

Для высоконагруженного WireGuard-шлюза (много пиров, высокая PPS) отдельные ядерные параметры дают измеримый выигрыш. Применяются на обеих сторонах, где возможен форвардинг:

```bash
# MTU/буферы на сокетах UDP
echo 1048576 | sudo tee /proc/sys/net/core/rmem_max
echo 1048576 | sudo tee /proc/sys/net/core/wmem_max
# per-socket (запрос часто превышает 208 КБ)
sudo sysctl -w net.core.rmem_default=262144
sudo sysctl -w net.core.wmem_default=262144

# Форвардинг IPv4/IPv6 (необходим даже для «просто туннеля»)
sudo sysctl -w net.ipv4.ip_forward=1
sudo sysctl -w net.ipv6.conf.all.forwarding=1

# Packet socket memory (для tcpdump/audit; не увеличивать без необходимости)
sudo sysctl -w net.core.netdev_max_backlog=10000
```

Главное — не «крутить всё подряд»: подбор параметров под конкретные очереди описан в [RSS/RPS/RFS](../Linux/Networking/Concepts/rss_rps_rfs.md) и [TCP Tuning](../Linux/Networking/Concepts/tcp_tuning/tcp_queueing_disciplines.md). Помните, что большая часть тюнинга WireGuard сводится к правильному **MTU/MSS** и учёту UDP-очередей, а не к ядерным «магическим» флагам.

### 7. Подбор размера XPS (Transmit Packet Steering)

На TX-пути концентратора можно распределять исходящие пакеты по CPU через XPS — аналог RPS для отправки. Обычно требуется только на физическом интерфейсе `eth0`, где формируется UDP-encap:

```bash
# Спросить поддержку multi-Q NIC
ethtool -l eth0 | grep -i combined
# → Combined: 4   (если 1 — XPS не поможет без DPDK/VMQ, остаётся RPS)

# Привязка очередей к CPU (пример: 4 queue → CPU 0,1,2,3)
for q in 0 1 2 3; do
  printf '1' | sudo tee /sys/class/net/eth0/queues/tx-$q/xps_cpus
done
```

Проверка эффекта — по `iperf3` и `top -H` до/после (см. §4). Сложные сценарии multi-queue увязываются с RSS: [RSS, RPS, RFS](../Linux/Networking/Concepts/rss_rps_rfs.md).

### 8. Имитация плохой сети: `tc netem` для проверки VPN

Перед продвижением нового клиента в «нестабильный» офис полезно загнать туннель в условия задержек/потерь локально (проверка тюнинга TCP/MTU):

```bash
# На сервере: добавить 30 мс задержки + 0.5% потерь на eth0 (входящий путь)
sudo tc qdisc add dev eth0 root netem delay 30ms loss 0.5%

# Через туннель: сравнить throughput (ожидаемое падение при потерях — сверхлинейное)
iperf3 -c 10.0.0.1 -t 30
# → при 0.5% потерь TCP-поток в туннеле просядет значительнее, чем без туннеля

# Убрать эмуляцию (обязательно после теста)
sudo tc qdisc del dev eth0 root
```

Синтаксис `netem` и комбинации с `tbf`/`htb` — [tc_netem (задержка/потери)](../Linux/Networking/Tools/iproute2/tc_netem.md). Тест полезен и для проверки, как ведёт себя RTT-чувствительный трафик в туннеле, что пригодится при диагностике HA ([wireguard-ha.md](./wireguard-ha.md)).

## Дополнительная информация

- **[Vpn/wireguard.md](./wireguard.md)** — MTU-таблица, MSS Clamping, мониторинг через `wg show`
- **[MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead всех стеков
- **[iperf3](../Linux/Diagnostics/Networking/iperf3.md)** — замер пропускной способности и задержки
- **[RSS/RPS/RFS](../Linux/Networking/Concepts/rss_rps_rfs.md)** — распределение обработки пакетов между CPU
- **[TCP Queueing Disciplines](../Linux/Networking/Concepts/tcp_tuning/tcp_queueing_disciplines.md)** — qdisc и BQL на концентраторе
- **[tc netem — эмуляция сети](../Linux/Networking/Tools/iproute2/tc_netem.md)** — задержки и потери для тестов VPN