# Управление очередями соединений TCP в Linux

## Определения

* **TCP Backlog** — очередь входящих TCP-подключений на сервере, состоящая из двух уровней:
  * **SYN backlog** — очередь полуоткрытых соединений в состоянии `SYN_RECV`. Контролируется параметром `net.ipv4.tcp_max_syn_backlog`.
  * **Accept backlog** — очередь установленных соединений в состоянии `ESTABLISHED`, ожидающих вызова `accept()` приложением. Размер определяется `net.core.somaxconn`.
* **SYN Cookies** — механизм защиты от **SYN-flood**, позволяющий серверу отвечать на SYN-запросы без выделения памяти до завершения рукопожатия. Подробнее: [DDoS Overview](../../../Security/ApplicationSecurity/ddos_overview.md).
* **netdev_max_backlog** — максимальное количество пакетов в очереди на обработку ядром, полученных от сетевого интерфейса (**NIC**), до того как они будут переданы в стек протоколов.

## Основные концепции

### Жизненный цикл входящего соединения

```text
Клиент → SYN → Сервер
         ↓
    [SYN backlog]  ← состояние SYN_RECV
         ↓
    3-way handshake завершён
         ↓
   [Accept backlog]  ← состояние ESTABLISHED, ожидает accept()
         ↓
   Приложение вызывает accept() → соединение обработано
```

### Параметры ядра

| Параметр | Описание | Значение по умолчанию | Типичное для Highload |
| :--- | :--- | :--- | :--- |
| `net.core.somaxconn` | Максимальный размер Accept backlog | 128–4096 | 65535 |
| `net.ipv4.tcp_max_syn_backlog` | Максимальный размер SYN backlog | 128–256 | 4096–8192 |
| `net.core.netdev_max_backlog` | Очередь пакетов от NIC к ядру | 1000 | 30000 |
| `net.ipv4.tcp_syncookies` | Включение SYN cookies (0/1/2) | 1 | 1 |

> **Примечание:** `tcp_syncookies=2` — форсированное включение (не рекомендуется). Значение `1` — автоматическая активация при риске переполнения.

### Последствия переполнения

* **SYN backlog:** отбрасывание SYN-пакетов (**SYN drop**) → задержки установления соединения, ретрансмиссии SYN.
* **Accept backlog:** сброс соединений с отправкой **RST** → ошибки «Connection refused» на клиенте.
* **netdev_max_backlog:** пакеты сбрасываются на уровне NIC → ретрансмиссии TCP, рост задержек.

## Практические сценарии

### Проверка текущих значений

```bash
sysctl net.core.somaxconn
sysctl net.ipv4.tcp_max_syn_backlog
sysctl net.core.netdev_max_backlog
sysctl net.ipv4.tcp_syncookies
```

### Настройка очередей через sysctl

**Временно (до перезагрузки):**

```bash
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=4096
sudo sysctl -w net.core.netdev_max_backlog=30000
sudo sysctl -w net.ipv4.tcp_syncookies=1
```

**Постоянно (`/etc/sysctl.d/99-network.conf`):**

```ini
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 4096
net.core.netdev_max_backlog = 30000
net.ipv4.tcp_syncookies = 1
```

Применение: `sudo sysctl --system`

### Диагностика переполнения backlog

**Просмотр счётчиков SYN drop:**

```bash
# Счётчик SYN-ретрансмиссий и дропов
nstat -az | grep -i syn
# TcpExtTCPReqQFullDrop — отброшены из-за переполнения SYN backlog
# TcpExtTCPListenOverflow — срабатывание защиты от переполнения Accept backlog
```

**Анализ состояния сокетов через `ss`:**

```bash
# Количество SYN_RECV (полуоткрытые)
ss -tan state syn-recv | wc -l

# Количество ESTABLISHED (активные соединения)
ss -tan state established | wc -l

# Детальная информация по каждому сокету
ss -tan state syn-recv
```

Подробнее об утилите: [Диагностика ss](../../../Linux/Diagnostics/Networking/ss.md).

**Мониторинг ListenOverflow в реальном времени:**

```bash
watch -n1 'nstat -az | grep -i listenoverflow'
```

### Рекомендации по выбору значений

| Сценарий | somaxconn | tcp_max_syn_backlog | netdev_max_backlog |
| :--- | :--- | :--- | :--- |
| **Веб-сервер (общий)** | 4096 | 2048 | 5000 |
| **Highload (тысячи conn/s)** | 65535 | 8192 | 30000 |
| **Прокси/балансировщик** | 65535 | 4096 | 30000 |

> **Важно:** `somaxconn` также ограничивается на уровне приложения (например, директива `backlog` в конфигурации Nginx). Системное значение является верхним пределом.

## Дополнительная информация

### Связанные темы

* [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
* [Диагностика сокетов TCP](./tcp_socket_diagnostics.md)
* [Состояния TCP-соединений](../../../Networking/Protocols/TCP/connection/tcp_connection_states.md)

### См. также

* [Настройка параметров ядра (sysctl)](../../Core/kernel/sysctl.md)
* [DDoS (Distributed Denial of Service)](../../../Security/ApplicationSecurity/ddos_overview.md)
