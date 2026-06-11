# Настройка initcwnd в Linux: управление начальным окном

## Определения

* **initcwnd (Initial Congestion Window — начальное окно перегрузки)** — параметр **TCP (Transmission Control Protocol — протокол управления передачей)**, определяющий объём данных, который сервер может отправить сразу после установления соединения, не дожидаясь подтверждений **ACK (Acknowledgment)**.
* **MSS (Maximum Segment Size — максимальный размер сегмента)** — максимальный объём полезных данных в одном пакете. Для сетей Ethernet с **MTU (Maximum Transmission Unit — максимальная единица передачи)** 1500 байт стандартный MSS составляет 1460 байт.
* **initrwnd (Initial Receive Window — начальное окно приема)** — объём данных, который получатель готов принять в первой «волне» до получения первого ACK.

## Базовые концепции

В ядре Linux значение `initcwnd` по умолчанию составляет 10 MSS (согласно RFC 5681), что эквивалентно примерно 14.3 КБ. Это значение является отправной точкой для алгоритма **Slow Start (Медленный старт)**.

В отличие от многих других сетевых параметров, `initcwnd` в Linux настраивается не через `sysctl`, а индивидуально для каждого маршрута в таблице маршрутизации. Это позволяет задавать разные окна для локальной сети и внешних соединений.

Теория правила 14 КБ и влияние на производительность описаны в основном источнике: **[Правило 14 КБ и оптимизация initcwnd](../../../../Networking/Protocols/TCP/congestion/tcp_initcwnd_and_optimization.md)**.

## Практические сценарии

### 1. Проверка текущего значения

Если параметр не указан явно в выводе команды, ядро использует значение по умолчанию (10 MSS).

```bash
# Просмотр параметров для всех маршрутов
ip route show

# Просмотр для конкретного интерфейса
ip route show dev eth0
```

### 2. Временная настройка initcwnd

Изменения вступают в силу немедленно, но сбрасываются после перезагрузки системы или сетевого интерфейса.

```bash
# Определение шлюза и интерфейса по умолчанию
GATEWAY=$(ip route | grep default | awk '{print $3}')
DEVICE=$(ip route | grep default | awk '{print $5}')

# Установка initcwnd=30 и initrwnd=30
sudo ip route change default via "$GATEWAY" dev "$DEVICE" initcwnd 30 initrwnd 30
```

### 3. Настройка постоянного сохранения (Persistence)

#### Через systemd-networkd

Если система управляется через `systemd-networkd`, параметр добавляется в секцию `[Route]`.

```ini
# /etc/systemd/network/10-eth0.network
[Route]
Gateway=192.168.1.1
InitialCongestionWindow=30
InitialReceiveWindow=30
```

#### Через NetworkManager (Dispatcher script)

Для систем с **NetworkManager** можно использовать скрипт в директории `/etc/NetworkManager/dispatcher.d/99-initcwnd`.

```bash
#!/bin/bash
if [ "$2" = "up" ]; then
    ip route change default via "$(ip route | grep default | awk '{print $3}')" \
        dev "$1" initcwnd 30 initrwnd 30
fi
```

*Не забудьте сделать скрипт исполняемым: `sudo chmod +x /etc/NetworkManager/dispatcher.d/99-initcwnd`.*

### 4. Мониторинг активных соединений

Для проверки реального размера окна перегрузки в установленных сессиях используется утилита `ss`.

```bash
# Показать cwnd для всех установленных TCP-соединений
ss -tin state established

# Отфильтровать только значение cwnd
ss -tin state established | grep -o 'cwnd:[0-9]*'
```

## Дополнительная информация

### Взаимодействие с BBR

При использовании алгоритма **BBR (Bottleneck Bandwidth and Round-trip propagation time)** влияние `initcwnd` на общую скорость меньше, так как BBR агрессивнее оценивает доступную полосу. Тем не менее, для первого **RTT (Round-Trip Time — время кругового обхода)** значение `initcwnd` остается решающим фактором скорости доставки первого блока данных.

См. также:

* [Алгоритмы контроля перегрузки TCP](./tcp_congestion_algorithms.md)
* [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
* [Настройка маршрутов через iproute2](../../Tools/iproute2/ip_route.md)
