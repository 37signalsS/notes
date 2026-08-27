# Wireshark — основные концепции

## Определения

**Фильтр захвата (Capture Filter)** — фильтр, применяемый на уровне библиотеки захвата (`libpcap` в Linux, `Npcap` в Windows) непосредственно **до** записи пакетов в буфер или файл. Он отбрасывает лишний трафик на этапе получения данных, что критично для экономии ресурсов CPU и дискового пространства при высокой нагрузке. Использует синтаксис BPF (Berkeley Packet Filter), аналогичный `tcpdump`.

**Фильтр отображения (Display Filter)** — фильтр, применяемый к уже захваченным и загруженным в память Wireshark пакетам. Он позволяет гибко скрывать или показывать данные на основе любых полей диссектированных протоколов. Использует собственный мощный синтаксис Wireshark с поддержкой логических и арифметических операций.

**Промискусный режим (Promiscuous Mode)** — режим работы сетевого адаптера, при котором он отключает аппаратную фильтрацию по MAC-адресу назначения и принимает все кадры, проходящие через сегмент сети (L2-домен), даже если они не адресованы данному хосту.

**Разрешение имён (Name Resolution)** — процесс преобразования числовых адресов в человекочитаемые идентификаторы:
*   **MAC-адреса:** Преобразуются в названия вендоров через базу OUI (Organizationally Unique Identifier).
*   **IP-адреса:** Преобразуются в доменные имена через DNS-запросы.
*   **Порты:** Преобразуются в названия сервисов через файл `services`.

**Вынос вычисления контрольных сумм (Checksum Offload)** — технология, при которой расчет и проверка контрольных сумм (IP, TCP, UDP) делегируются сетевой карте (NIC) для снижения нагрузки на CPU. При захвате трафика это часто приводит к ложным срабатываниям Wireshark (`Bad Checksum`), так как пакет перехватывается до того, как NIC запишет в него верную сумму.

**Срез пакета (Packet Slicing / Snaplen)** — ограничение максимального объема данных, сохраняемых для каждого пакета. Например, сохранение только первых 96 байт позволяет хранить все заголовки L2-L4, отбрасывая полезную нагрузку (Payload), что значительно экономит место и защищает PII-данные. Полный захват: `-s 0` (по умолчанию). При захвате на интерфейсах с jumbo frames (MTU > 1500) увеличивайте snaplen до 65535, иначе пакеты будут обрезаны.

**Кольцевой буфер (Ring Buffer)** — механизм ротации файлов захвата, предотвращающий переполнение диска при длительном мониторинге. Старые файлы автоматически перезаписываются новыми. Управляется параметрами: `filesize` (размер файла), `files` (количество файлов), `duration` (время жизни файла). См. **[Использование tshark](./tshark_usage.md#длительный-захват-с-кольцевым-буфером-ring-buffer)**.

**Offloading (LRO/GRO/TSO/GSO)** — аппаратные и программные оптимизации NIC, влияющие на захват:
*   **LRO/GRO (Large Receive Offload):** Склеивает мелкие пакеты в один крупный перед передачей ядру. Ускоряет обработку, но ломает логику анализа TCP-опций в Wireshark (ложные ретрансмиссии).
*   **TSO/GSO (TCP/UDP Segmentation Offload):** Позволяет NIC разбивать крупные сегменты на мелкие пакеты перед отправкой. При захвате пакеты могут выглядеть неестественно большими.
*   **Решение:** Для точной диагностики отключите: `ethtool -K eth0 gro off lro off tso off gso off`. Подробнее: **[Влияние offloading на анализ TCP](./tcp_performance/tcp_network_losses_and_offloading.md)**.

**NIC Ring Buffer (аппаратный)** — аппаратный буфер сетевой карты, в котором хранятся пакеты до обработки ядром Linux. При переполнении (dropped packets) пакеты отбрасываются до того, как их увидит `dumpcap`/`tcpdump`. Увеличение: `ethtool -g eth0` (просмотр) и `ethtool -G eth0 rx 4096` (установка). Проверка потерь: `ethtool -S eth0 | grep drop`.

## Базовые концепции

### Механизмы захвата в Linux

Современное ядро Linux предоставляет несколько способов получения сырых пакетов:
1.  **AF_PACKET:** Традиционный механизм. Пакеты копируются из ядра в пользовательское пространство. Надежен, но создает нагрузку на CPU при высоких скоростях (>1 Gbps) из-за копирования данных.
2.  **AF_XDP (eXpress Data Path):** Высокопроизводительный механизм (появился в ядре 4.18+), позволяющий передавать пакеты в пользовательское пространство почти без накладных расходов, минуя большую часть сетевого стека ядра. Поддерживает zero-copy режим для NIC с XDP-драйверами.
3.  **eBPF:** Позволяет запускать программы фильтрации и захвата непосредственно в ядре, что идеально для мониторинга без внедрения в сетевые неймспейсы контейнеров.

Для работы Wireshark/dumpcap без прав `root` необходимо установить POSIX-способности:
```bash
sudo setcap cap_net_raw,cap_net_admin+eip $(which dumpcap)
```

#### Сравнение AF_PACKET и AF_XDP

| Характеристика | AF_PACKET | AF_XDP |
| :--- | :--- | :--- |
| **Производительность** | Средняя (копирование в userspace) | Высокая (zero-copy) |
| **Совместимость** | Все ядра Linux ≥ 2.1 | Ядро ≥ 4.18 (полная: ≥ 5.3) |
| **Требования к NIC** | Любой | XDP-драйвер (Intel, Mellanox) |
| **Фильтрация** | BPF в ядре | XDP-программы + BPF |
| **Назначение** | Общие сценарии захвата | Высокоскоростные сети (10G+) |

### Форматы файлов: pcap vs pcapng

| Характеристика | pcap | pcapng |
| :--- | :--- | :--- |
| **Метаданные интерфейсов** | Нет | Да (имя, IP, MAC) |
| **Комментарии к пакетам** | Нет | Да |
| **Несколько потоков захвата** | Нет | Да (разделение по интерфейсам) |
| **Внедрение TLS-ключей (DSB)** | Нет | Да (с Wireshark 3.0) |
| **Сжатие** | gzip (внешнее) | LZ4 (встроенное, Wireshark 4.4+) |
| **Совместимость** | Универсальная (tcpdump, Wireshark) | Wireshark 1.5+, tshark, moderne tcpdump |
| **Рекомендация** | Совместимость с legacy-инструментами | Всегда (по умолчанию в Wireshark) |

### Захват трафика в контейнерах и Kubernetes

В контейнеризированных средах каждый Pod/контейнер имеет свой **Network Namespace**. Захват на физическом интерфейсе хоста (`eth0`) не покажет трафик внутри виртуальных мостов или `veth`-пар контейнеров.

**Методы захвата:**
*   **nsenter:** Вход в сетевой неймспейс процесса с хоста: `nsenter -t <PID> -n tcpdump -i eth0`. Самый простой способ для Docker-контейнеров.
*   **Ephemeral Containers:** Использование `kubectl debug -it <pod_name> --image=nicolaka/netshoot` для запуска временного контейнера с инструментами диагностики в том же неймспейсе. Подробнее: **[Эфемерные контейнеры](../../../Kubernetes/Base/Pod/ephemeral_containers.md)**.
*   **ksniff (kubectl krew):** Плагин для захвата трафика Pod'а через packet stream: `kubectl sniff <pod-name> -n <namespace>`. При mTLS (Istio/Linkerd) захват на интерфейсе `lo` внутри пода — данные до шифрования sidecar.
*   **Sidecar-инъекция:** Добавление контейнера с `tcpdump`/`tshark` в описание Pod'а (требует перезапуска).
*   **eBPF-инструменты:** Использование `Inspektor Gadget` или `pwru` для захвата трафика на уровне ядра без изменения состояния контейнеров.

#### Практические примеры захвата в контейнерах

```bash
# Docker: захват через nsenter (без --privileged)
PID=$(docker inspect -f '{{.State.Pid}}' <container_name>)
sudo nsenter -t $PID -n tshark -i eth0 -w /tmp/capture.pcapng

# Kubernetes: захват через ephemeral container
kubectl debug -it <pod_name> --image=nicolaka/netshoot -- tshark -i eth0 -w /tmp/capture.pcapng

# Kubernetes: захват через ksniff
kubectl krew install sniff
kubectl sniff <pod_name> -n <namespace> -f "tcp port 80" -w http_traffic.pcap

# Защита от утечки ключей: захват до шифрования sidecar (Istio/Linkerd)
kubectl exec -it <pod_name> -c istio-proxy -- tshark -i lo -f "tcp port 8080" -w /dev/stdout | tshark -r -
```

### Захват на виртуальных интерфейсах

При работе с виртуальными сетями захват требует понимания топологии:

```bash
# Bridge (vagrant, libvirt, docker0)
sudo tshark -i docker0 -w docker_traffic.pcapng

# VLAN (802.1Q)
sudo tshark -i eth0.100 -w vlan_traffic.pcapng

# Bond/Team (агрегация интерфейсов)
sudo tshark -i bond0 -w bond_traffic.pcapng

# WireGuard/OpenVPN (внутренний интерфейс)
sudo tshark -i wg0 -w vpn_traffic.pcapng

# GRE/IPsec туннели
sudo tshark -i gre0 -w tunnel_traffic.pcapng
```

### Мультиинтерфейсный захват

Захват с нескольких интерфейсов одновременно:

```bash
# tshark: два интерфейса в один файл (pcapng)
sudo tshark -i eth0 -i eth1 -w multi_interface.pcapng

# dumpcap: два интерфейса в отдельные файлы
sudo dumpcap -i eth0 -w eth0.pcapng -i eth1 -w eth1.pcapng

# Раздельный захват с фильтрацией
sudo tshark -i eth0 -f "tcp port 80" -w http_eth0.pcapng \
            -i eth1 -f "tcp port 443" -w tls_eth1.pcapng
```

### Фильтрация: Capture vs Display

| Характеристика | Фильтр захвата (BPF) | Фильтр отображения (Wireshark) |
| :--- | :--- | :--- |
| **Время применения** | В момент захвата (до записи) | После захвата (при просмотре) |
| **Производительность** | Очень высокая (ядро) | Средняя (пользовательское ПО) |
| **Гибкость** | Ограничена L2-L4 полями | Неограниченна (L7 диссекторы) |
| **Синтаксис** | `host 1.1.1.1 and port 80` | `ip.addr == 1.1.1.1 && tcp.port == 80` |
| **Возможность отмены** | Нет (данные отброшены) | Да (скрытые данные остаются в файле) |

**Wireshark 4.x+** поддерживает сложные выражения в фильтрах отображения, включая срезы данных (`udp.payload[0:4] == 01:02:03:04`) и арифметические операции.

## Практические сценарии

### Диагностика Checksum Offloading

Если Wireshark сообщает о битых контрольных суммах, проверьте настройки интерфейса:
```bash
ethtool -k eth0 | grep checksumming
# → rx-checksumming: on
# → tx-checksumming: on
```
Если `tx-checksumming` включен, ошибки в исходящем трафике являются «оптической иллюзией». Для чистого анализа их можно отключить в настройках протокола (TCP/UDP/IP) в Wireshark: `Edit → Preferences → Protocols → TCP → Validate the TCP checksum if possible (uncheck)`.

### Диагностика потерь на NIC Ring Buffer

Если при захвате видны пропуски пакеты или lower throughput:
```bash
# Просмотр текущего размера ring buffer
ethtool -g eth0

# Увеличение ring buffer (до максимального)
ethtool -G eth0 rx 4096

# Мониторинг потерь на NIC
ethtool -S eth0 | grep -E "drop|miss|discard"

# Проверка backpressure
ethtool -S eth0 | grep -E "flow_control|xoff"
```

### Удаленный захват через SSH-туннель

Для визуального анализа трафика на удаленном сервере без установки GUI-компонентов:
```bash
ssh root@remote-server "dumpcap -P -i eth0 -w -" | wireshark -k -i -
```
*   `-P`: использование `dumpcap` в режиме pcapng.
*   `-w -`: вывод сырого потока в `stdout`.
*   `wireshark -k -i -`: немедленный старт захвата из `stdin`.

Для удаленного захвата в файл:
```bash
ssh root@remote-server "sudo tshark -i eth0 -b filesize:102400 -b files:5 -w /tmp/remote_capture.pcapng" &
# Через 5 минут скопировать файлы
scp root@remote-server:/tmp/remote_capture*.pcapng ./
```

### Выбор стратегии захвата

| Условие | Стратегия | Обоснование |
| :--- | :--- | :--- |
| **High Load (>1 Gbps)** | Capture Filter + Snaplen + Ring Buffer | Минимизация нагрузки на диск и CPU. |
| **Отладка HTTP/gRPC** | Полный захват + SSLKEYLOGFILE | Необходим Payload для L7 анализа и расшифровки. |
| **Security Audit** | Фильтрация по портам + eBPF | Скрытый сбор данных без изменения конфигурации. |
| **Cloud/K8s** | `kubectl sniff` / Sidecar | Доступ к изолированным неймспейсам. |
| **10G+ скорость** | AF_XDP + `-n` + BPF-фильтр | Минимизация overhead, ядерная фильтрация. |
| **Длительный мониторинг** | Ring Buffer + `-a duration` | Ротация файлов, контроль размера. |

### Захват на интерфейсах с offloading

Для точной диагностики TCP-проблем отключите offloading:
```bash
# Отключение всех offloading-опций
sudo ethtool -K eth0 gro off lro off tso off gso off sg off

# Восстановление после анализа
sudo ethtool -K eth0 gro on lro on tso on gso on sg on

# Проверка текущих настроек
ethtool -k eth0 | grep -E "generic-receive|tcp-segmentation|large-receive"
```

## Дополнительная информация

### Типичные ошибки захвата и их решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` | Нет прав на интерфейс | `sudo` или `setcap cap_net_raw+eip $(which dumpcap)` |
| `No buffer space available` | Малый ring buffer NIC | `ethtool -G eth0 rx 4096` |
| `Dropped packets (interface)` | Переполнение ring buffer NIC | Увеличить ring buffer, отключить offloading |
| `Dropped packets (dumpcap)` | Малый буфер dumpcap | `dumpcap -B 64` (увеличить до 64 МБ) |
| `Bad checksum` | Checksum Offload | Отключить в настройках протокола или `ethtool -K` |
| `Spurious retransmission` | LRO/GRO | `ethtool -K eth0 gro off lro off` |
| `Packets look truncated` | Малый snaplen | `-s 0` (полный захват) или увеличить snaplen |
| `No interfaces found` | Нет прав или нет интерфейсов | `dumpcap -D` (проверить доступные интерфейсы) |

### Влияние offloading на анализ

Отключение offloading критично для корректной диагностики TCP:
```bash
# Полное отключение для анализа
sudo ethtool -K eth0 gro off lro off tso off gso off sg off gro IPv6 off tx-ip6-csum off

# Проверка влияния на throughput (до/после)
iperf3 -c <server> -t 30 -i 1

# Восстановление
sudo ethtool -K eth0 gro on lro on tso on gso on sg on
```

### Многопоточный захват

Для высокоскоростных сетей (10G+) одномпоточный захват может не справляться:
```bash
# Многопоточный захват через rss (Receive Side Scaling)
# Проверка настроек RSS
ethtool -l eth0

# Установка числа очередей
ethtool -L eth0 combined 8

# Захват на каждой очереди отдельно (requires multiple instances)
for i in $(seq 0 7); do
  sudo tshark -i eth0 -b filesize:102400 -b files:10 -w "capture_q${i}.pcapng" &
done
```

### Значение TCP-флагов для SRE

Анализ флагов позволяет быстро локализовать проблему без глубокого разбора Payload:
*   **SYN (без ACK):** Попытка открытия соединения. Всплеск означает DDoS (SYN-flood) или недоступность бэкенда.
*   **RST:** Принудительный разрыв. Означает, что порт закрыт, соединение сброшено файрволом или приложение аварийно завершилось.
*   **FIN:** Штатное закрытие. Большое количество `FIN_WAIT` указывает на утечки соединений в коде.
*   **Window Update:** Изменение размера окна. Нулевое окно (`Zero Window`) — признак того, что получатель не успевает обрабатывать данные.

### Точность временных меток

Wireshark поддерживает захват с точностью до наносекунд, но это требует:
1.  Поддержки со стороны сетевой карты и драйвера.
2.  Использования формата **pcapng**.
3.  Настройки `View → Time Display Format`. Для SRE наиболее полезен режим **Seconds since previous displayed packet** для поиска «замираний» трафика.

### См. также
*   **[Wireshark — определения](./definitions.md)** — подробнее о форматах pcap/pcapng.
*   **[Использование tshark](./tshark_usage.md)** — выполнение фильтрации в CLI.
*   **[Методы расшифровки TLS](./tls_decryption_methods.md)** — работа с защищенным трафиком.
*   **[tcpdump в Linux](../../../Linux/Diagnostics/Networking/tcpdump.md)** — синтаксис BPF-фильтров.
*   **[Диагностика производительности TCP](./tcp_performance/tcp_performance_diagnostics.md)** — анализ throughput и задержек.
*   **[Влияние offloading на анализ TCP](./tcp_performance/tcp_network_losses_and_offloading.md)** — проблема LRO/GRO/TSO.
