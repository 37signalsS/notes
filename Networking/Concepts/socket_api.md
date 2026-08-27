# Интерфейс сокетов (Socket API)

## Определения

*   **Сокет (Socket):** Программный интерфейс (API) для обеспечения обмена данными между процессами. В контексте сетей сокет представляет собой логическую конечную точку (endpoint) соединения. Это абстракция, позволяющая приложению взаимодействовать с сетевым стеком ОС через файловые дескрипторы, скрывая детали реализации протоколов L4 ([TCP](../Protocols/TCP/overview.md), [UDP](../Protocols/udp.md)).
    В Unix-подобных системах сокеты следуют философии «все есть файл» (`S_IFSOCK`), что позволяет использовать для работы с ними системные вызовы `read()`, `write()`, `select()`, `poll()` и `epoll()`.

*   **Интерфейс сокетов Беркли (Berkeley Sockets):** Спецификация API, ставшая стандартом де-факто (POSIX) для сетевого программирования. Большинство современных сетевых библиотек являются обертками над этим низкоуровневым интерфейсом.

*   **Пятерка параметров (5-tuple):** Уникальный идентификатор сетевого потока на транспортном уровне:
    `{Протокол, IP источника, Порт источника, IP назначения, Порт назначения}`.

*   **Файловый дескриптор (FD):** Целое число, возвращаемое ядром при создании сокета, служащее индексом в таблице открытых файлов процесса. После закрытия дескриптора ядро освобождает ресурсы сокета (буферы, структуры `sock`), но только если на него нет других ссылок (дубликатов через `dup()`).

*   **Сетевой порядок байт (Network Byte Order):** Порядок байт, используемый в протоколах TCP/IP — big-endian. Для преобразования между сетевым и порядком хоста (host order) используются функции `htons()` (host to network short), `htonl()` (host to network long), `ntohs()` и `ntohl()`.

*   **socklen_t:** Стандартный POSIX-тип для передачи длины адресных структур в системных вызовах (`bind()`, `connect()`, `accept()`). В Linux имеет размер, достаточный для хранения `int`.

*   **Орфанный сокет (Orphaned Socket):** Сокет, который не имеет соответствующего файлового дескриптора в пользовательском пространстве (например, после `fork()` и `close()` в родителе), но все еще существует в ядре, обслуживая соединение. Такие сокеты видны через `ss -s` в поле `orphaned`.

## Предварительные требования

*   **ОС:** Linux (ядро 4.4+ для современных особенностей), BSD/macOS или POSIX-совместимая система.
*   **Компилятор:** GCC, Clang или аналогичный, поддерживающий стандарт C99 (для примеров на C).
*   **Права:** Для биндинга на привилегированные порты (0–1023) требуются права `root` или capability `CAP_NET_BIND_SERVICE`. В Rootless-средах (Docker/Podman) можно настроить `net.ipv4.ip_unprivileged_port_start`.
*   **Инструменты диагностики:** `ss` (из пакета `iproute2`), `tcpdump`, `nstat`, `strace`, `bpftrace` (для eBPF-анализа).

## Базовые концепции

### Модель «Клиент-Сервер»

1.  **Сервер (Пассивный участник):**
    *   Слушает входящие запросы на определенном IP и порту.
    *   Использует вызовы `bind()` и `listen()`.
    *   Создает новый сокет для каждого нового клиента через `accept()`, оставляя основной «слушающий» сокет свободным для других подключений.
2.  **Клиент (Активный участник):**
    *   Инициирует соединение через `connect()`.
    *   Использует **[эфемерный порт](./network_ports.md)**, назначаемый ОС динамически из диапазона (обычно `32768–60999` в Linux).

### Семейства адресов и типы сокетов

При вызове `socket(domain, type, protocol)` определяются:

| Параметр | Значения | Описание |
| :--- | :--- | :--- |
| **Domain** | `AF_INET` | IPv4 ([IP addressing](../Protocols/IP_addressing/ip_overview.md)). |
| | `AF_INET6` | IPv6. |
| | `AF_UNIX` / `AF_LOCAL` | [Unix Domain Sockets](../../Linux/Core/processes/ipc.md) (локальный IPC, быстрее TCP). |
| | `AF_PACKET` | Прямой доступ к канальному уровню (L2), аналогично `SOCK_RAW` для Ethernet. |
| **Type** | `SOCK_STREAM` | Потоковый сокет (**TCP**). Гарантирует доставку и порядок. |
| | `SOCK_DGRAM` | Датаграммный сокет (**UDP**). Быстрый, без гарантий, сохраняет границы сообщений. |
| | `SOCK_RAW` | Прямой доступ к IP-пакетам (используется в `ping`, `nmap`). |
| | `SOCK_SEQPACKET` | Последовательный пакетный канал (например, SCTP). Гарантирует порядок и целостность сообщений. |
| **Protocol** | `0` | Автоматический выбор (IPPROTO_TCP для STREAM, IPPROTO_UDP для DGRAM). |

### Основные операции (Berkeley Sockets API)

| Операция | Назначение | TCP | UDP |
| :--- | :--- | :---: | :---: |
| `socket()` | Создание дескриптора сокета. | Да | Да |
| `bind()` | Привязка к локальному адресу и порту. | Сервер | Да (опц.) |
| `listen()` | Очередь ожидания подключений (`backlog`). | Сервер | Нет |
| `accept()` | Принятие соединения (создает новый FD). | Сервер | Нет |
| `connect()`| Установка соединения (3-way handshake). | Клиент | Да (опц.) |
| `send` / `recv` | Передача/прием данных. | Да | Нет |
| `sendto` / `recvfrom` | Передача/прием с указанием адреса. | Нет | Да |
| `sendmsg` / `recvmsg` | Передача/прием с дополнительными флагами (SCM_RIGHTS, IP_PKTINFO). | Да | Да |
| `shutdown()` | Частичное закрытие (только RX или только TX). | Да | Нет |
| `close()` | Полное закрытие дескриптора. | Да | Да |
| `getsockname()` | Получение локального адреса сокета. | Да | Да |
| `getpeername()` | Получение удаленного адреса сокета. | Да | Нет |

### Размеры буферов сокета

По умолчанию ядро Linux выделяет буферы приема и передачи размерами 128 КБ каждый (можно проверить через `cat /proc/sys/net/core/rmem_default` и `wmem_default`). Для высоконагруженных приложений требуется явное увеличение:

```bash
# Глобальные значения по умолчанию
sysctl net.core.rmem_default net.core.wmem_default

# Максимальные лимиты, разрешенные для приложения
sysctl net.core.rmem_max net.core.wmem_max
```

В коде размер устанавливается через `setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &size, sizeof(size))` до вызова `connect()`/`listen()`.

### Опции сокетов (setsockopt) — расширенный список

| Опция | Уровень | Назначение |
| :--- | :--- | :--- |
| **`SO_REUSEADDR`** | `SOL_SOCKET` | Позволяет немедленно запустить сервер на том же порту, если старое соединение находится в `TIME_WAIT`. |
| **`SO_REUSEPORT`** | `SOL_SOCKET` | (Linux 3.9+) Позволяет нескольким процессам/потокам слушать один и тот же порт. Ядро балансирует нагрузку между ними. |
| **`SO_KEEPALIVE`** | `SOL_SOCKET` | Периодическая проверка доступности клиента (по умолчанию через 2 часа). |
| **`SO_LINGER`** | `SOL_SOCKET` | Управляет поведением `close()`: ждать ли отправки данных из буферов или сбросить соединение (`RST`). |
| **`SO_RCVBUF`** | `SOL_SOCKET` | Размер буфера приема. Ядро может удвоить значение для служащих буферов. |
| **`SO_SNDBUF`** | `SOL_SOCKET` | Размер буфера передачи. |
| **`TCP_NODELAY`** | `IPPROTO_TCP` | Отключение алгоритма Нагла. Отправка пакетов немедленно, даже если они малы. Критично для latency-чувствительных приложений. |
| **`TCP_CORK`** | `IPPROTO_TCP` | (Linux) Предотвращает отправку неполных сегментов до `UNCORK`. Используется для построения запросов/ответов фиксированного размера. |
| **`TCP_DEFER_ACCEPT`** | `IPPROTO_TCP` | (Linux) Соединение остается в `SYN_RECV` до поступления первых данных от клиента или истечения таймаута. Экономит ресурсы приложения. |
| **`TCP_QUICKACK`** | `IPPROTO_TCP` | (Linux) Отключает задержку ACK (обычно 40–200 мс) для снижения задержек на коротких соединениях. |
| **`TCP_INFO`** | `IPPROTO_TCP` | Получение структуры `struct tcp_info` с детальной статистикой (RTT, cwnd, ретрансмиссии, состояние). Только для чтения (`getsockopt`). |

## Жизненный цикл соединения (TCP)

### Установка и разрыв
1.  **Three-way Handshake:** `SYN` (клиент) → `SYN-ACK` (сервер) → `ACK` (клиент). Состояние переходит в `ESTABLISHED`.
2.  **Завершение:** Одна сторона отправляет `FIN`.
    *   **TIME_WAIT:** Состояние на стороне, инициировавшей закрытие. Длится 2*MSL (обычно 60с). Защищает от «заблудившихся» пакетов старого соединения.
    *   **CLOSE_WAIT:** Сторона получила `FIN`, но еще не закрыла свой дескриптор. Опасное состояние при утечках FD.

### Очереди Backlog в Linux
Вызов `listen(fd, backlog)` управляет двумя очередями:
1.  **SYN Queue:** Соединения, ожидающие ACK от клиента. Лимит: `net.ipv4.tcp_max_syn_backlog`.
2.  **Accept Queue:** Готовые соединения, ожидающие `accept()`. Лимит: `min(backlog, net.core.somaxconn)`. Если очередь полна, сервер игнорирует новые SYN (или шлет RST, если `tcp_abort_on_overflow=1`).

При переполнении Accept Queue срабатывают счетчики `TcpExtTCPListenOverflows` / `TcpExtTCPListenDrops` (проверяются через `nstat`).

## Продвинутые механизмы и производительность

### Опции сокетов (setsockopt)
*   **`SO_REUSEADDR`:** Позволяет немедленно запустить сервер на том же порту, если старое соединение находится в `TIME_WAIT`.
*   **`SO_REUSEPORT`:** (Linux 3.9+) Позволяет нескольким процессам/потокам слушать один и тот же порт. Ядро балансирует нагрузку между ними.
*   **`SO_KEEPALIVE`:** Периодическая проверка доступности клиента (по умолчанию через 2 часа).
*   **`SO_LINGER`:** Управляет поведением `close()`: ждать ли отправки данных из буферов или сбросить соединение (`RST`).
*   **`TCP_NODELAY`:** Отключение алгоритма Нагла. Отправка пакетов немедленно, даже если они малы. Критично для Latency-чувствительных приложений.

### Современные технологии (Linux 6.x - 7.0+)
*   **io_uring Zero-Copy:** Асинхронный ввод-вывод.
    *   `IORING_OP_SEND_ZC` / `IORING_OP_RECV_ZC`: Передача данных напрямую из/в пользовательские буферы без копирования в ядро.
    *   `Multishot Accept`: Один запрос на `accept` обрабатывает серию входящих подключений. Подробнее: [io_uring](../../Linux/Core/kernel/io_uring.md).
*   **eBPF Socket Redirection:**
    *   Использование `BPF_MAP_TYPE_SOCKMAP`. eBPF-программа перенаправляет пакеты между сокетами напрямую в ядре, минуя TCP-стек. Идеально для Service Mesh (Sidecar-коммуникация). Подробнее: [Service Mesh: основные концепции](../../Service_Mesh/service_mesh_concepts.md).
*   **AccECN (Accurate ECN):** (Linux 7.0) Более точное уведомление о перегрузке сети, снижающее задержки (Tail Latency).
*   **Device Memory TCP (DMTCP):** Передача данных напрямую в память GPU/ускорителей, минуя системную RAM.

## Практические сценарии

### Пример на C (Низкоуровневый TCP Клиент с обработкой ошибок)
```c
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>

int main() {
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) {
        perror("socket");
        return 1;
    }

    struct sockaddr_in serv_addr;
    memset(&serv_addr, 0, sizeof(serv_addr));
    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(8080);
    if (inet_pton(AF_INET, "127.0.0.1", &serv_addr.sin_addr) <= 0) {
        perror("inet_pton");
        close(sock);
        return 1;
    }

    if (connect(sock, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        perror("connect");
        close(sock);
        return 1;
    }

    const char *msg = "Hello";
    if (send(sock, msg, strlen(msg), 0) != (ssize_t)strlen(msg)) {
        perror("send");
    }

    shutdown(sock, SHUT_WR);
    char buf[1024];
    ssize_t n;
    while ((n = recv(sock, buf, sizeof(buf) - 1, 0)) > 0) {
        buf[n] = '\0';
        write(STDOUT_FILENO, buf, n);
    }
    if (n < 0) perror("recv");

    close(sock);
    return 0;
}
```

### Пример на Go (Высокоуровневый сервер)
```go
package main

import (
    "net"
    "fmt"
)

func main() {
    ln, _ := net.Listen("tcp", ":8080")
    for {
        conn, _ := ln.Accept()
        go func(c net.Conn) {
            fmt.Fprintf(c, "HTTP/1.1 200 OK\r\n\r\nHello from Go")
            c.Close()
        }(conn)
    }
}
```

### Пример на Python (Эхо-сервер с таймаутами)
```python
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 8888))
    s.listen()
    # Установка таймаута на ожидание подключения
    s.settimeout(10.0) 
    
    try:
        conn, addr = s.accept()
        with conn:
            conn.settimeout(5.0) # Таймаут на чтение/запись
            data = conn.recv(1024)
            if data:
                conn.sendall(data)
    except socket.timeout:
        print("Таймаут истек")
```

### Пример на Python (UDP Echo-сервер)
```python
import socket

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
    s.bind(('0.0.0.0', 9999))
    while True:
        data, addr = s.recvfrom(4096)
        if not data:
            break
        print(f"Получено {len(data)} байт от {addr}")
        s.sendto(data, addr)
```

### Пример на C (Unix Domain Socket — путь в ФС)
```c
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>

#define SOCKET_PATH "/tmp/my_socket"

int main() {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);

    // Удалить старый файл сокета, если существует
    unlink(SOCKET_PATH);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(fd); return 1;
    }

    listen(fd, 5);
    int client = accept(fd, NULL, NULL);
    if (client >= 0) {
        const char *msg = "Hello from Unix socket";
        send(client, msg, strlen(msg), 0);
        close(client);
    }
    close(fd);
    unlink(SOCKET_PATH);
    return 0;
}
```

### Пример на C (Получение TCP_INFO)
```c
#include <netinet/tcp.h>
#include <stdio.h>

struct tcp_info info;
socklen_t len = sizeof(info);
if (getsockopt(fd, IPPROTO_TCP, TCP_INFO, &info, &len) == 0) {
    printf("RTT: %u us, cwnd: %u, retrans: %u\n",
           info.tcpi_rtt, info.tcpi_snd_cwnd, info.tcpi_retrans);
}
```

## Валидация

### Проверка работоспособности сокетного приложения
1.  **Запуск сервера и подключение клиента:**
    ```bash
    # Запустить сервер в фоне
    ./tcp_server &
    # Проверить, что порт слушается
    ss -tlnp | grep <port>
    # Подключиться клиентом
    ./tcp_client
    ```
2.  **Проверка через `nc` (netcat):**
    ```bash
    # TCP
    echo "test" | nc 127.0.0.1 8080
    # UDP
    echo "test" | nc -u 127.0.0.1 9999
    ```
3.  **Проверка Unix-сокета:**
    ```bash
    curl --unix-socket /tmp/my_socket http://localhost/
    ```
4.  **Проверка сбора статистики:**
    ```bash
    ss -ti dst 127.0.0.1
    # Ожидаемый вывод: rtt, cwnd, retrans, delivery_rate
    ```
5.  **Нагрузочное тестирование:**
    ```bash
    # Простой тест на 1000 последовательных соединений
    for i in $(seq 1 1000); do echo "" | nc 127.0.0.1 8080; done
    ```

## Диагностика и устранение неисправностей

### Общие ошибки (Errno)
| Код | Название | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **EADDRINUSE** | Address already in use | Порт занят другим процессом или в `TIME_WAIT`. | `SO_REUSEADDR`, поиск процесса через `ss -ltnp`, завершение процесса. |
| **ECONNREFUSED**| Connection refused | На порту никто не слушает или файрвол блокирует SYN. | Проверить `ss -tlnp`, firewall (`iptables -L -n`), routing. |
| **ETIMEDOUT** | Connection timed out | Нет ответа (проблемы с маршрутизацией, дроп пакетов). | `traceroute`, `ping`, проверка маршрутов, файрволов. |
| **EPIPE** | Broken pipe | Попытка записи в сокет, который уже закрыт удаленной стороной. | Обработать `SIGPIPE` (`signal(SIGPIPE, SIG_IGN)`), проверять возврат `send()`. |
| **ECONNRESET** | Connection reset by peer | Удаленная сторона принудительно сбросила соединение (`RST`). | Приложение на другой стороне упало или вызвало `close()` с `SO_LINGER`. |
| **EADDRNOTAVAIL** | Cannot assign requested address | Исчерпание портов (`TIME_WAIT`) или исчерпание IP-адресов. | `tcp_tw_reuse`, расширение `ip_local_port_range`, [connection pooling](./connection_pooling.md). |
| **EAGAIN / EWOULDBLOCK** | Resource temporarily unavailable | Сокет в неблокирующем режиме, операция не может быть выполнена немедленно. | Повторить операцию через `poll()`/`epoll` или `select()`. |

### Инструменты анализа
1.  **`ss -ntlp`**: Список слушающих TCP-портов с PID процессов.
2.  **`ss -ti`**: Внутренняя статистика сокета (RTT, окно, ретрансмиссии).
3.  **`lsof -i :8080`**: Поиск процесса, занявшего порт.
4.  **`strace -e network <app>`**: Отслеживание системных вызовов сокетов в реальном времени.
5.  **`tcpdump -i any port 8080`**: Захват трафика для анализа флагов (SYN, FIN, RST).
6.  **`nstat -az | grep -E 'ListenOverflows|ListenDrops|ReqQFullDrop'`**: Анализ переполнения очередей backlog.
7.  **`ss -tan state time-wait | wc -l`**: Подсчет сокетов в `TIME_WAIT`.

## Особые случаи и ограничения

*   **SIGPIPE:** При записи в разорванное соединение процесс получает сигнал `SIGPIPE` и завершается. Стандартная защита: `signal(SIGPIPE, SIG_IGN)`. Или используйте флаг `MSG_NOSIGNAL` в `send()`.
*   **Одновременное открытие (Simultaneous Open):** Если обе стороны одновременно вызывают `connect()`, соединение устанавливается без `LISTEN`/`accept()`. В Linux поддерживается, но редко используется.
*   **Орфанные сокеты:** После `fork()` и `close()` в родителе сокет продолжает существовать в ядре до закрытия в дочернем процессе. Могут накапливаться при неаккуратной обработке сигналов.
*   **TCP_DEFER_ACCEPT:** Ускоряет обработку входящих соединений, откладывая `accept()` до поступления первых данных. Несовместим с некоторыми протоколами, которые отправляют данные после рукопожатия с задержкой.
*   **SO_REUSEPORT и ядро:** В ядрах до 5.x `SO_REUSEPORT` использовал хэш по 4-tuple для балансировки, что могло приводить к скоплению горячих соединений на одном ядре. Начиная с 5.x используется более равномерный алгоритм.
*   **Проблема C10k/C10M:** При ориентации на десятки тысяч соединений классические процессы/потоки неэффективны. Используйте Event Loop (`epoll`, `io_uring`) или рантаймы с переключением задач (Go, Rust).

## Best Practices
*   **Используйте таймауты:** Никогда не оставляйте `recv` без таймаута в продакшене.
*   **Обрабатывайте частичное чтение:** `recv` может вернуть меньше байт, чем запрошено. Используйте циклы или `MSG_WAITALL`.
*   **Graceful Shutdown:** Используйте `shutdown(SHUT_WR)` перед `close()`, чтобы дать удаленной стороне понять, что данных больше не будет, но сохранить возможность чтения.
*   **Ограничивайте Backlog:** Не ставьте слишком большой `backlog`, если приложение не может быстро обрабатывать `accept()`, это приведет к росту задержек для клиентов.
*   **Безопасность (Unix Sockets):** Для локального IPC используйте Unix-сокеты с ограничением прав доступа на файл сокета.
*   **Проверяйте возвраты всех вызовов:** `socket()`, `bind()`, `listen()`, `accept()`, `send()`, `recv()` могут возвращать `-1`. Игнорирование ошибок — частая причина "зависших" сервисов.
*   **Используйте `MSG_NOSIGNAL`:** Вместо `signal(SIGPIPE, SIG_IGN)` для предотвращения падения процесса при разрыве соединения.
*   **Настраивайте `TCP_NODELAY` отдельно от `SO_SNDBUF`:** Отключение Нагла уменьшает задержки, но может увеличить количество пакетов. Для высоконагруженных серверов комбинируйте с увеличенными буферами.

---

**См. также:**
- [Мультиплексирование ввода-вывода (I/O Multiplexing)](./io_multiplexing.md)
- [Протокол TCP](../Protocols/TCP/overview.md)
- [Сетевые порты и эфемерные порты](./network_ports.md)
