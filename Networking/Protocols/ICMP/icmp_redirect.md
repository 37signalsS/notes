# ICMP Redirect и Source Quench

## Определения

**ICMP Redirect (Type 5)** — сообщение, используемое маршрутизаторами для оптимизации маршрута доставки пакетов путём рекомендации хосту использовать более оптимальный шлюз.

**ICMP Source Quench (Type 4)** — устаревшее (deprecated) сообщение для контроля перегрузки, запрашивающее у отправителя уменьшение скорости передачи пакетов.

---

## Basic Concepts

### ICMP Redirect

**Параметры:**

- **Type:** 5
- **Code:** 0-3

**Коды ICMP Redirect:**

| Code | Описание |
|------|----------|
| **0** | Redirect Datagram for the Network (перенаправление для сети) |
| **1** | Redirect Datagram for the Host (перенаправление для хоста) |
| **2** | Redirect Datagram for the Type of Service and Network |
| **3** | Redirect Datagram for the Type of Service and Host |

**Назначение:** оптимизация маршрута доставки пакетов. Маршрутизатор уведомляет хост о наличии более оптимального пути, рекомендуя использовать другой шлюз.

### ICMP Source Quench (deprecated)

**Параметры:**

- **Type:** 4
- **Code:** 0

**Назначение:** уведомление отправителя о том, что получатель или маршрутизатор не успевает обрабатывать входящие пакеты (контроль перегрузки).

**Статус:** устарел, не используется в современных сетях.

**Причины депрекейта:**

- Неэффективен в высокоскоростных сетях
- Уязвим к DoS-атакам (ложные сообщения для замедления легитимного трафика)
- В современных сетях контроль перегрузки реализован на транспортном уровне (TCP congestion control)

**Рекомендация:** игнорировать Source Quench; использовать механизмы контроля перегрузки TCP ([TCP Congestion Control](../../TCP/congestion/tcp_congestion_control_overview.md)).

---

## Practical Scenarios

### Механизм работы ICMP Redirect

**Исходная конфигурация:**

- Хост 1: `10.0.0.1/24`
- Хост 2: `192.168.1.1/24`
- Маршрутизатор имеет два интерфейса в одной физической сети:
  - `10.0.0.100/24`
  - `192.168.1.100/24`

**Процесс:**

1. Хост 1 отправляет ICMP-запрос (например, ping) для хоста 2
2. Так как хосты в разных IP-сетях, хост 1 отправляет пакет на шлюз по умолчанию (маршрутизатор)
3. Маршрутизатор, получив пакет, определяет, что хост 2 находится в той же физической сети, что и хост 1 (через второй интерфейс)
4. Маршрутизатор:
   - Пересылает пакет хосту 2
   - Отправляет хосту 1 сообщение **ICMP Redirect** (Type 5, Code 1 — «Redirect Datagram for Host»)
5. Хост 1 обновляет свою таблицу маршрутизации и начинает отправлять пакеты хосту 2 напрямую, минуя маршрутизатор

**Результат:** при повторных запросах пакеты доставляются напрямую между хостами, сокращая путь и разгружая маршрутизатор.

### Механизм работы ICMP Source Quench (исторический)

1. Маршрутизатор или хост получает пакеты быстрее, чем может их обработать
2. Отправитель получает ICMP Source Quench-сообщение
3. Отправитель должен уменьшить скорость передачи

---

## Additional Information

### Проблемы безопасности ICMP Redirect

ICMP Redirect по умолчанию обрабатывается многими ОС, что создаёт риски:

- **Атака перенаправления трафика:** злоумышленник может отправлять ложные Redirect для перехвата трафика
- **MITM-атаки:** перенаправление трафика через компрометированный узел

### Защита

**1. Блокировка на файрволе:**

```bash
iptables -A INPUT -p icmp --icmp-type redirect -j DROP
```

**2. Отключение обработки на уровне ОС (Linux):**

```bash
# Проверка текущих настроек
sysctl net.ipv4.conf.all.accept_redirects
sysctl net.ipv4.conf.default.accept_redirects
sysctl net.ipv4.conf.<interface>.accept_redirects

# Отключение приёма Redirect
sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.default.accept_redirects=0

# Постоянное применение (/etc/sysctl.conf)
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
```

**3. Windows:** настройка в реестре

Путь: `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters`

Параметр: `EnableICMPRedirect` (DWORD) = 0

### Связанные концепты

Общая информация о протоколе ICMP — [ICMP Overview](./icmp_overview.md). Сообщения об ошибках — [ICMP Destination Unreachable](./icmp_destination_unreachable.md), [ICMP Time Exceeded](./icmp_time_exceeded.md). Диагностика и безопасность — [ICMP Diagnostics & Security](./icmp_diagnostics_security.md).
