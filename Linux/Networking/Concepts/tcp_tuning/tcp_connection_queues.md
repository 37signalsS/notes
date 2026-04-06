# Управление очередями соединений TCP

## Определения

**TCP Backlog** — очередь входящих TCP-подключений на сервере, состоящая из двух очередей:

- **SYN backlog** — очередь полуоткрытых соединений в состоянии `SYN_RECV`, контролируется параметром `net.ipv4.tcp_max_syn_backlog`.
- **Accept backlog** — очередь установленных соединений в состоянии `ESTABLISHED`, ожидающих вызова `accept()` приложением, размер определяется `net.core.somaxconn`.

**SYN Cookies** — механизм защиты от SYN-flood, позволяющий серверу отвечать на SYN-запросы без выделения памяти до завершения рукопожатия.

## Basic Concepts

### Жизненный цикл входящего соединения

```
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

| Параметр | Описание | Значение по умолчанию | Типичное для highload |
| :--- | :--- | :--- | :--- |
| `net.core.somaxconn` | Максимальный размер Accept backlog | 128–4096 | 65535 |
| `net.ipv4.tcp_max_syn_backlog` | Максимальный размер SYN backlog | 128–256 | 4096–8192 |
| `net.core.netdev_max_backlog` | Очередь пакетов от NIC к ядру | 1000 | 30000 |
| `net.ipv4.tcp_syncookies` | Включение SYN cookies (0/1/2) | 1 | 1 |

> **Примечание:** `tcp_syncookies=2` — форсированное включение (не рекомендуется). Значение `1` — автоматическая активация при риске переполнения.

### Последствия переполнения

- **SYN backlog:** отбрасывание SYN-пакетов (SYN drop) → задержки установления соединения, ретрансмиссии SYN.
- **Accept backlog:** сброс соединений с отправкой `RST` → ошибки «Connection refused» на клиенте.
- **netdev_max_backlog:** пакеты сбрасываются на уровне NIC → ретрансмиссии TCP, рост задержек.

## Practical Scenarios

### Проверка текущих значений

```bash
sysctl net.core.somaxconn
sysctl net.ipv4.tcp_max_syn_backlog
sysctl net.core.netdev_max_backlog
sysctl net.ipv4.tcp_syncookies
```

### Настройка очередей

**Временно:**

```bash
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=4096
sudo sysctl -w net.core.netdev_max_backlog=30000
sudo sysctl -w net.ipv4.tcp_syncookies=1
```

**Постоянно** (`/etc/sysctl.d/99-network.conf`):

```ini
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 4096
net.core.netdev_max_backlog = 30000
net.ipv4.tcp_syncookies = 1
```

Применение: `sudo sysctl -p /etc/sysctl.d/99-network.conf`

### Диагностика переполнения backlog

**Просмотр счётчиков SYN drop:**

```bash
# Счётчик SYN-ретрансмиссий и дропов
nstat -az | grep -i syn
# TcpExtTCPReqQFullDrop — отброшены из-за переполнения SYN backlog
# TcpExtTCPListenOverflow — срабатывание защиты от переполнения Accept backlog
```

**Анализ состояния сокетов:**

```bash
# Количество SYN_RECV (полуоткрытые)
ss -tan 'state syn-recv' | wc -l

# Количество ESTABLISHED (активные соединения)
ss -tan 'state established' | wc -l

# Детальная информация по каждому сокету
ss -tan state syn-recv
```

**Мониторинг в реальном времени:**

```bash
# Отслеживание RST-пакетов (симптом переполнения Accept backlog)
watch -n1 'nstat -az | grep -i listenoverflow'
```

### Рекомендации по размерам

| Сценарий | somaxconn | tcp_max_syn_backlog | netdev_max_backlog | Обоснование |
| :--- | :--- | :--- | :--- | :--- |
| **Веб-сервер (общий)** | 4096 | 2048 | 5000 | Умеренная нагрузка |
| **Highload (тысячи conn/s)** | 65535 | 8192 | 30000 | Максимальная пропускная способность |
| **Прокси/балансировщик** | 65535 | 4096 | 30000 | Множество одновременных соединений |
| **Внутренний сервис** | 1024 | 512 | 3000 | Низкая нагрузка, стандартные значения |

> **Важно:** `somaxconn` также ограничивается на уровне приложения (например, `listen(backlog)` в Nginx/Node.js). Значение в sysctl — верхний лимит, приложение может запросить меньше.

### Защита от SYN-flood

SYN cookies включены по умолчанию (`tcp_syncookies=1`) в современных ядрах Linux. Они активируются автоматически при приближении SYN backlog к пределу.

**Проверка работы:**

```bash
# Статистика SYN cookies
nstat -az | grep -i syncookie
# TcpExtSyncookiesSent — отправлено SYN cookies
# TcpExtSyncookiesRecv — подтверждено SYN cookies
# TcpExtSyncookiesFailed — отброены (невалидный ответ)
```

## Additional Information

### Связанные темы

- **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
- **Диагностика сокетов:** [Диагностика сокетов TCP](./tcp_socket_diagnostics.md)
- **Состояния соединений:** [Состояния TCP-соединений](../../../Networking/Protocols/TCP/connection/tcp_connection_states.md)
- **SYN-flood атаки:** [DDoS Overview](../../../Networking/Concepts/dos_ddos_overview.md)
- **sysctl:** [Настройка sysctl](../../Core/kernel/sysctl.md)
- **ss:** [Диагностика ss](../../../Diagnostics/Networking/ss.md)
