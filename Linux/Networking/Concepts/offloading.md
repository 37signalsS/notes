# Сетевая разгрузка в Linux: GRO, LRO, TSO, GSO и аппаратное ускорение

## Определения

**Сетевая разгрузка (Network Offloading)** — технология переноса задач по обработке сетевых пакетов с центрального процессора (CPU) на специализированное оборудование сетевой карты (NIC) или оптимизированные уровни драйвера. Это позволяет высвободить циклы CPU для приложений и снизить задержки.

Приложение отправляет обычные данные, но часть работы с пакетами Linux может передавать непосредственно NIC.

**GRO (Generic Receive Offload)** — программная агрегация входящих пакетов в ядре Linux. Объединяет сегменты одного потока в один большой Socket Buffer (SKB) перед передачей в стек. Является стандартом и заменой небезопасному LRO. GRO работает в обратную сторону: ядро может объединять несколько полученных сегментов, уменьшая количество операций обработки.

**TSO (TCP Segmentation Offload)** — аппаратная сегментация исходящего TCP-потока. При TSO ядро передает NIC большой TCP-пакет (до 64 КБ), а карта сама разбивает его на отдельные Ethernet frames стандартного MTU и вычисляет контрольные суммы.

**GSO (Generic Segmentation Offload)** — программный аналог TSO. Ядро выполняет сегментацию в последний момент перед передачей драйверу, если NIC не поддерживает TSO. Это экономит ресурсы на прохождение всего сетевого стека крупным пакетом.

**XDP Offload (eBPF Offload)** — перенос выполнения eBPF-программ (Express Data Path) непосредственно в аппаратную логику сетевой карты. Позволяет отбрасывать или перенаправлять пакеты со скоростью линии (wire-speed) без участия CPU.

**TLS Offload (kTLS / Hardware TLS)** — перенос операций симметричного шифрования/дешифрования TLS на сетевую карту. kTLS выполняет это в ядре, а Hardware TLS — полностью на NIC (например, Mellanox ConnectX-6+).

**Switching Offload (TC / OVS Offload)** — перенос правил фильтрации и маршрутизации (Flows) в аппаратные таблицы NIC (ASIC). Используется для ускорения виртуальных коммутаторов (Open vSwitch) и `tc` (Traffic Control).

## Основные концепции

### Архитектура обработки пакетов и место оффлоуда

В Linux сетевой стек обрабатывает каждый пакет через несколько слоев. Оффлоуды встраиваются на границе между драйвером и стеком:

```
Приложение → Socket → TCP/UDP → IP → netfilter → qdisc → driver → NIC
                                              ↑
                                         [offload boundary]
```

На границе offload boundary драйвер передает пакет (или части пакета) в NIC, которая самостоятельно:
- вычисляет контрольные суммы (TX checksum offload)
- разбивает большой сегмент на стандартные кадры (TSO)
- агрегирует входящие сегменты в один SKB (GRO)
- выполняет eBPF-программы (XDP Offload)

После обработки NIC возвращает пакет в стек уже в стандартном виде или помещает готовый результат в RX-ring, откуда NAPI забирает его для дальнейшей обработки.

### Принцип агрегации на приеме (RX)

Для снижения количества прерываний и нагрузки на аллокатор памяти используется агрегация:
1. **LRO (Hardware):** NIC склеивает пакеты. Опасно для маршрутизаторов, так как теряются оригинальные заголовки и опции TCP.
2. **GRO (Software/Driver):** Ядро анализирует пакеты и склеивает их только если это безопасно. GRO поддерживает не только TCP, но и UDP (UDP GRO).

### Принцип сегментации на передаче (TX)

Позволяет стеку оперировать «суперпакетами» до 64 КБ:
*   **Checksum Offload:** NIC вычисляет CRC для IP, TCP и UDP. Почти все современные карты делают это по умолчанию.
*   **Scatter-Gather:** Позволяет NIC собирать пакет из разрозненных фрагментов памяти без лишнего копирования (Zero-copy).

### Справочник оффлоуд-флагов

| Флаг (ethtool -k) | Направление | Тип | Назначение |
| :--- | :--- | :--- | :--- |
| `tcp-segmentation-offload` | TX | Аппаратный | Разбиение больших TCP-сегментов на MSS-кадры |
| `generic-segmentation-offload` | TX | Программный | Аналог TSO, если NIC не поддерживает |
| `udp-segmentation-offload` | TX | Аппаратный/программный | Сегментация больших UDP-датаграмм |
| `generic-receive-offload` | RX | Программный | Агрегация входящих сегментов в ядре |
| `large-receive-offload` | RX | Аппаратный | Агрегация в NIC (устарел, заменен GRO) |
| `tx-checksum-ipv4` / `rx-checksum-ipv4` | TX/RX | Аппаратный | Контрольная сумма IPv4 |
| `tx-checksum-ipv6` / `rx-checksum-ipv6` | TX/RX | Аппаратный | Контрольная сумма IPv6 |
| `tx-checksum-tcp` / `rx-checksum-tcp` | TX/RX | Аппаратный | Контрольная сумма TCP |
| `tx-checksum-udp` / `rx-checksum-udp` | TX/RX | Аппаратный | Контрольная сумма UDP |
| `tx-checksum-sctp` / `rx-checksum-sctp` | TX/RX | Аппаратный | Контрольная сумма SCTP |
| `scatter` | TX | DMA | Сбор пакета из разрозненных буферов (Zero-copy TX) |
| `gather` | RX | DMA | Разброс приемного пакета по нескольким буферам |
| `tx-vlan-offload` / `rx-vlan-offload` | TX/RX | Аппаратный | Инкапсуляция/деинкапсуляция тегов 802.1Q в NIC |
| `tls-hw-tx-offload` / `tls-hw-rx-offload` | TX/RX | Аппаратный | Шифрование/дешифрование TLS на NIC |
| `tx-udp-tnl-segmentation` | TX | Аппаратный | Сегментация инкапсулированного UDP-туннеля (VXLAN, GENEVE) |
| `tx-gre-segmentation` | TX | Аппаратный | Сегментация инкапсулированного GRE |

### Взаимодействие с подсистемами ядра

Оффлоуды взаимодействуют с несколькими подсистемами Linux:

**NAPI:** GRO и LRO работают в контексте NAPI. При высокой нагрузке ядро переключается с прерываний на опрос (polling), и агрегация пакетов происходит пачками (budget). Если budget исчерпан, остальные пакеты остаются в RX-ring, что приводит к `rx_missed_errors`.

**netfilter/iptables:** Оффлоуды работают после netfilter ( OUTPUT / POST_ROUTING для TX, PREROUTING / INPUT для RX). Это значит, что правила iptables/nftables видят пакеты ДО того, как NIC выполнит сегментацию или агрегацию. Для диагностики это важно: в `tcpdump` пакеты могут выглядеть иначе, чем в логах netfilter.

**tc (Traffic Control):** Оффлоуды взаимодействуют с qdisc на уровне драйвера. `tc` может видеть суперпакеты (если TSO включен), что искажает статистику `tc -s class show`. Для корректного тюнинга HTB/FQ отключайте TSO/GSO.

**RSS/RPS/XPS:** Оффлоуды не влияют на распределение по очередям напрямую, но крупные агрегированные SKB (GRO) попадают в одну RX-очередь. Если одна очередь перегружена, остальные простаивают. Для полной масштабируемости комбинируйте GRO с RPS/RFS (см. [RSS, RPS, RFS](./rss_rps_rfs.md)).

### Современные методы ускорения (2026)

| Технология | Уровень | Назначение |
| :--- | :--- | :--- |
| **kTLS** | Ядро / NIC | Ускорение HTTPS/TLS трафика без копирования в userspace |
| **XDP Offload** | Аппаратный | Защита от DDoS и сверхбыстрый балансировщик |
| **SR-IOV** | Аппаратный | Прямой проброс виртуальных функций NIC в контейнеры/ВМ |
| **VDP (Video Data Path)** | Аппаратный | Специализированная разгрузка для передачи несжатого видео (SMPTE ST 2110) |

### Аппаратные требования и поддержка драйверов

Не все оффлоуды доступны на всех картах. Зависимость от драйвера критична при проектировании инфраструктуры:

| Драйвер | NIC | GRO | TSO | GSO | Checksum | VLAN Offload | kTLS | XDP Offload |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ixgbe** | Intel 10G | Да | Да | Да | Да | Да | Нет | Нет |
| **i40e** | Intel 40G | Да | Да | Да | Да | Да | Да | Частично |
| **ice** | Intel 25/100G | Да | Да | Да | Да | Да | Да | Да |
| **mlx5_core** | Mellanox 25-400G | Да | Да | Да | Да | Да | Да | Да |
| **bnxt_en** | Broadcom 10/100G | Да | Да | Да | Да | Да | Нет | Нет |
| **virtio-net** | Виртуализация | Да | Да | Да | Да | Да | Нет | Нет |

**Проверка поддержки:**
```bash
# Какие оффлоуды поддерживает драйвер (аппаратно + программно)
ethtool -k eth0
# → features с флагами [fixed] (аппаратные) и [requested] (запрошенные)
```

### Взаимодействие с виртуализацией и контейнерами

Внутри ВМ или контейнера оффлоуды могут работать в трех режимах:
1. **Эмуляция (virtio-net):** Драйвер `virtio-net` программно эмулирует GRO/TSO/GSO. Это снижает нагрузку на CPU хоста, но не дает линейной скорости.
2. **Проброс через vhost-net:** Обработка вынесена в ядро хоста (vhost-net), что снижает latency на 20–30%.
3. **SR-IOV / VFIO:** Прямой проброс физической функции (VF) в ВМ. Дает производительность уровня bare-metal, включая аппаратные оффлоуды.

Для контейнеров:
- **Docker:** По умолчанию контейнер видит виртуальный интерфейс (`eth0` в новом netns). Оффлоуды наследуются от хостового моста/устройства. Проверьте через `docker exec <container> ethtool -k eth0`.
- **Kubernetes:** Под работает в отдельном netns. При использовании CNI с overlay (VXLAN/GENEVE) важно, чтобы оффлоуды были согласованы между узлом и CNI-интерфейсом. Проверка: `kubectl exec -it <pod> -- ethtool -k eth0`.

### Взаимодействие с VLAN, bonding и bridge

Оффлоуды наложенные интерфейсы (VLAN subinterfaces) работают через родительский интерфейс. Однако есть нюансы:
- **rx-vlan-offload:** Если включен, NIC удаляет тег 802.1Q перед передачей пакета в стек. В `tcpdump` тег может не отображаться.
- **bonding (LACP):** Оффлоуды работают на уровне bond master, но TX-очереди распределяются по slave-интерфейсам. Проверяйте статус на master: `ethtool -k bond0`.
- **bridge:** Для мостового интерфейса включите `tx-vlan-offload` на slave-интерфейсах, иначе ядро будет самостоятельно инкапсулировать теги, увеличивая нагрузку.

## Практические сценарии

### Предварительные требования

Убедитесь, что установлены необходимые утилиты:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install ethtool iproute2 pciutils

# RHEL/CentOS/Rocky
sudo dnf install ethtool iproute pciutils

# Проверка версии ethtool (рекомендуется 6.x+ для JSON-вывода)
ethtool --version
# → ethtool version 6.7
```

### 1. Управление через ethtool

Утилита **[ethtool](../Tools/ethtool.md)** — основной инструмент управления оффлоудами. Полный справочник команд см. в **[ethtool](../Tools/ethtool.md)**; ниже — только offload-специфичные примеры.

```bash
# Показать статус всех функций
sudo ethtool -k eth0

# Пример включённых offload-механизмов:
# tcp-segmentation-offload: on
# generic-receive-offload: on
# receive-checksum-offload: on

# Проверить конкретный параметр:
ethtool -k eth0 | grep -E 'gro|gso|tso|checksum'

# Включить TLS-разгрузку (если поддерживается)
sudo ethtool -K eth0 tls-hw-tx-offload on tls-hw-rx-offload on

# Отключить все оффлоуды для «чистого» захвата трафика
sudo ethtool -K eth0 tso off gso off gro off lro off
```

### 2. Постоянная конфигурация через systemd-networkd

Изменения через `ethtool -K` сбрасываются при перезагрузке или переинициализации интерфейса. Для постоянства используйте `.link` файлы:

```ini
# /etc/systemd/network/10-eth0.link
[Match]
OriginalName=eth0

[Link]
ReceiveRingBuffer=4096
TransmitRingBuffer=4096
TCPSegmentationOffload=yes
GenericReceiveOffload=yes
RXChecksumming=yes
TXChecksumming=yes
```

Применить: `sudo systemctl restart systemd-udevd`

### 3. Постоянная конфигурация через Netplan (Ubuntu)

```yaml
# /etc/netplan/99-offload.yaml
network:
  version: 2
  ethernets:
    eth0:
      ethtool:
        feature:
          tso: true
          gso: true
          gro: true
          tx-checksum-ipv4: true
          rx-checksum-ipv4: true
```

Применить: `sudo netplan apply`

### 4. Сценарий: Диагностика «гигантских» пакетов

Если `tcpdump` показывает пакеты размером 10–20 КБ при MTU 1500 — это **не ошибка**, а результат работы TSO (на выходе) или GRO (на входе).
*   **Симптом:** Ошибки Checksum в Wireshark.
*   **Причина:** Карта еще не вычислила контрольную сумму (для исходящих) или Wireshark видит агрегированный пакет (для входящих). В захвате можно увидеть большой сегмент, хотя на физическом интерфейсе реально ушло несколько меньших пакетов.
*   **Решение:** Для отладки MTU/MSS всегда отключайте оффлоуды.

### 5. Сценарий: Проверка фактической работы оффлоуда

Включенный флаг в `ethtool -k` не гарантирует, что оффлоуд используется для конкретного трафика. Проверьте через `ethtool -S`:

```bash
# 1. Сбросьте счетчики
sudo ethtool -S eth0 | grep -E 'tx_hw_checksum|rx_hw_checksum|tso|gso|gro'
# Зафиксируйте начальные значения

# 2. Сгенерируйте трафик
iperf3 -c <server> -t 10

# 3. Проверьте прирост счетчиков
sudo ethtool -S eth0 | grep -E 'tx_hw_checksum|rx_hw_checksum|tso|gso|gro'
# → tx_hw_checksum: 15420   ← NIC действительно вычисляет checksum
# → tso_packets: 892        ← TSO активно
```

### 6. Сценарий: Валидация производительности (before/after)

Для измерения влияния оффлоуда на throughput и CPU:

```bash
# 1. Базовый замер с оффлоудами
sudo ethtool -K eth0 tso on gso on gro on
iperf3 -s &
iperf3 -c <server> -t 30 -P 8
# Зафиксируйте: Bitrate, CPU usage (mpstat -P ALL 1)

# 2. Замер без оффлоуда
sudo ethtool -K eth0 tso off gso off gro off
iperf3 -c <server> -t 30 -P 8
# Ожидаем: снижение throughput на 10–40%, рост CPU usage

# 3. Восстановление
sudo ethtool -K eth0 tso on gso on gro on
```

### 7. Сценарий: Настройка kTLS для повышения производительности Web-сервера

Использование kTLS (Kernel TLS) совместно с Nginx/Angie позволяет избежать копирования данных между ядром и приложением (Zero-copy TLS).

```bash
# Проверка поддержки kTLS в ядре
modprobe tls
# Включение в Nginx (требуется OpenSSL 3.0+)
# sendfile on;
# tcp_nopush on;
```

### 8. Сценарий: Отключение оффлоуда для диагностики в Wireshark/tcpdump

При анализе трафика TSO/GRO/Checksum Offload создают артефакты. Подробнее о влиянии на анализ см. [Сетевые потери и влияние offloading на анализ TCP](../../../Networking/ServicesAndTools/Wireshark/tcp_performance/tcp_network_losses_and_offloading.md).

```bash
# Полное отключение для «чистого» захвата
sudo ethtool -K eth0 tso off gso off gro off lro off rx-checksum off tx-checksum off

# После диагностики — восстановить
sudo ethtool -K eth0 tso on gso on gro on lro on rx-checksum on tx-checksum on
```

### 9. Диагностика при подозрительном сетевом поведении

При странном поведении сети полезно знать не только настройки IP и маршрутизации, но и какие операции Linux уже делегировал сетевой карте. Проверьте статус offload-механизмов через `ethtool -k <interface>` — это помогает исключить «артефакты» аппаратного ускорения при анализе захватов трафика и потерь пакетов.

### 10. Сценарий: Offloading в контейнерах (Docker)

```bash
# Проверка offloading внутри контейнера
docker exec <container> ethtool -k eth0 | grep -E 'segmentation|checksum'

# Отключение TSO/GRO для «чистого» захвата в контейнере
docker exec <container> ethtool -K eth0 tso off gro off

# Постоянная отключение: добавьте в docker-compose.yml или docker run
docker run --cap-add=NET_ADMIN --sysctl net.ipv4.tcp_tso=0 ...
```

### 11. Сценарий: Offloading в KVM/QEMU

При настройке ВМ для высоконагруженного сетевого I/O включите offloading в XML:

```xml
<interface type='bridge'>
  <source bridge='br0'/>
  <model type='virtio'/>
  <driver name='vhost' queues='8'/>
  <offload>
    <tx offload='tso'/>
    <tx offload='gso'/>
  </offload>
</interface>
```

Внутри гостя проверьте: `ethtool -k eth0 | grep -E 'tso|gso|gro'`. Подробнее: [Оптимизация производительности KVM](../../../Linux/Virtualization/kvm/performance_tuning_2026.md).

### 12. Сценарий: Offloading при работе с iSCSI

Для хранилищ iSCSI аппаратная разгрузка критична для снижения нагрузки на CPU:

```bash
# Оптимальная конфигурация для iSCSI
sudo ethtool -K eth1 tso on gro on lro off

# Проверка: lro off, так как iSCSI-target передаёт SCSI-команды, которые не должны агрегироваться
```

Подробнее: [iSCSI: Оптимизация производительности](../../../Linux/Networking/iSCSI/iscsi_performance.md).

## Дополнительная информация

### Конфликты и ограничения

1. **IP Forwarding:** На программных маршрутизаторах (Linux Router) **LRO должен быть всегда выключен**, так как он искажает заголовки пакетов, которые должны быть пересланы.
2. **CPU Pinning:** При использовании GRO пакеты могут агрегироваться в один поток, который обрабатывается одним ядром CPU. Если это ядро перегружено, остальные могут простаивать. Требуется настройка **[RSS/RPS/RFS](./rss_rps_rfs.md)**.
3. **Виртуализация:** Внутри ВМ оффлоуды часто эмулируются драйвером `virtio-net`. Настоящее ускорение достигается через SR-IOV или монтирование физических функций.

### Типичные проблемы и решения

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **LRO + forwarding** | Искажение заголовков, падение TCP | `ethtool -k \| grep lro` | `ethtool -K eth0 lro off` |
| **GRO + single queue** | Перегрузка одного CPU | `/proc/softirqs \| grep NET_RX` | Включить RPS/RFS |
| **TSO + tc shaping** | Некорректная статистика qdisc | `tc -s qdisc show` | Отключить TSO для отладки |
| **Checksum offload + tcpdump** | `bad cksum` в захвате | `ethtool -k \| grep checksum` | Это нормально на TX; для чистого захвата отключите |
| **VLAN offload + tcpdump** | Тег 802.1Q не виден | `ethtool -k \| grep vlan` | Отключить `rx-vlan-offload` для диагностики |
| **virtio-net + SR-IOV** | Отсутствует аппаратное ускорение | `ethtool -i eth0` | Проверьте режим (vfio-pci vs virtio-net) |

### Рекомендации по ролям

**Для SRE / Sysadmin:**
- По умолчанию оставляйте GRO/TSO/GSO включенными — это стандарт для Linux.
- LRO выключайте всегда, если интерфейс участвует в маршрутизации или используется как порт моста.
- При настройке мониторинга учитывайте, что `ethtool -S` показывает аппаратные счетчики, а `nstat` — программные.
- Включите постоянную конфигурацию через systemd-networkd или Netplan; отказ от `ethtool -K` в cron-скриптах.

**Для DevOps:**
- В IaC (Terraform/Ansible) добавляйте проверку: `ethtool -k {{ interface }} | grep -E 'gro|tso'`.
- При развертывании ВМ/контейнеров проверяйте, что offloading наследуется корректно.
- Для хранения логов/артефактов диагностики указывайте: при захвате трафика всегда отключайте оффлоуды.

**Для системных администраторов:**
- При проблемах с сетью (потери, high latency) проверяйте offloading только после исключения физических проблем (кабель, SFP, duplex).
- На серверах с high-load (100G+) отключайте EEE (`ethtool --set-eee eth0 eee off`) — EEE конфликтует с low-latency сетевыми стеками.
- Для iSCSI и NVMe-over-Fabrics включайте TCP segmentation offload, но отключайте LRO.

### Мониторинг в生产стве

```bash
# Сбор оффлоуд-метрик через node_exporter (textfile collector)
cat << 'EOF' > /etc/node_exporter/textfile_collector/offload.prom
# HELP node_net_offload_tso Статус TCP Segmentation Offload
# TYPE node_net_offload_tso gauge
node_net_offload_tso{device="eth0"} 1
# HELP node_net_offload_gro Статус Generic Receive Offload
# TYPE node_net_offload_gro gauge
node_net_offload_gro{device="eth0"} 1
EOF
```

### Чистка и откат изменений

```bash
# Временный откат (до перезагрузки интерфейса)
sudo ethtool -K eth0 tso off gso off gro off lro off

# Восстановление заводских настроек
sudo ethtool -K eth0 autoneg on
sudo ethtool -s eth0 speed 10000 duplex full autoneg on

# Удаление постоянной конфигурации (systemd-networkd)
sudo rm /etc/systemd/network/10-eth0.link
sudo systemctl restart systemd-udevd

# Удаление постоянной конфигурации (Netplan)
sudo rm /etc/netplan/99-offload.yaml
sudo netplan apply
```

### Крайние случаи

**musl/Alpine Linux:**
Некоторые утилиты (ethtool из Alpine) имеют статически слинкованные версии, которые не поддерживают новые флаги (например, `tls-hw-tx-offload`). Используйте версию из `testing` репозитория или собирайте из исходников.

**DNS64/NAT64:**
В средах с NAT64 (CLAT/PLAT) offloading не влияет на работу DNS64 напрямую, но может скрывать fragmentation issues. Проверяйте MTU на внешнем интерфейсе.

**Контейнеры с host network:**
При `--network host` контейнер видит хостовые интерфейсы напрямую. Все изменения offloading применяются немедленно к хосту.

**Отладка PTR-записей (Reverse DNS):**
При появлении задержек при обратных DNS-запросах проверяйте, не включен ли LRO на интерфейсе, обслуживающем DNS-трафик. LRO может задерживать доставку небольших UDP-пакетов (меньше MSS), что влияет на DNS-over-UDP.

**Несколько VPN (multi-VPN):**
При использовании нескольких туннелей (WireGuard + IPSec) на одном интерфейсе offloading на уровне NIC может конфликтовать с программной инкапсуляцией. Проверяйте `ethtool -k eth0 | grep tunnel` (если NIC поддерживает tunnel offload).

### См. также
* **[ethtool: справочник](../Tools/ethtool.md)** — команды управления сетевым адаптером.
* **[Обзор SR-IOV](../../../Networking/Concepts/dpdk/sriov.md)** — аппаратная виртуализация I/O.
* **[RSS, RPS, RFS](./rss_rps_rfs.md)** — распределение сетевой нагрузки по ядрам CPU.
* **[Оптимизация сетевых задержек](./network_latency_optimization.md)** — когда оффлоуды стоит отключать (Low Latency).
* **[Диагностика tcpdump](../../Diagnostics/Networking/tcpdump.md)** — особенности анализа трафика с оффлоудами.
* **[Сетевые потери и влияние offloading на анализ TCP](../../../Networking/ServicesAndTools/Wireshark/tcp_performance/tcp_network_losses_and_offloading.md)** — артефакты offloading в Wireshark.
* **[TCP Tuning](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — взаимодействие offloading с параметрами TCP.
* **[iSCSI: Оптимизация производительности](../../../Linux/Networking/iSCSI/iscsi_performance.md)** — offloading для блочного хранилища.
