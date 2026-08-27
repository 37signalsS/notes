# Мультиплексирование ввода-вывода (I/O Multiplexing)

## Определения

- **Мультиплексирование ввода-вывода (Input/Output Multiplexing):** Механизм, позволяющий одному процессу или потоку эффективно управлять множеством соединений (файловых дескрипторов) путем мониторинга их состояния и уведомления приложения о готовности к выполнению операций чтения или записи.
- **Блокирующий ввод-вывод (Blocking I/O):** Традиционная модель, где системный вызов (например, `read()`) приостанавливает выполнение программы до тех пор, пока данные не будут получены или буфер не будет готов к записи.
- **Неблокирующий ввод-вывод (Non-blocking I/O):** Режим, при котором системный вызов возвращает управление немедленно, даже если операция не завершена (возвращая ошибку `EAGAIN` или `EWOULDBLOCK`).
- **Проблема C10k:** Историческая задача эффективной обработки 10 000 и более одновременных соединений. В современных реалиях фокус сместился на **C10M** (10 миллионов соединений на один сервер).

## Проблема масштабирования: от C10k к C10M

Традиционная модель «один процесс/поток на соединение» не масштабируется при росте числа клиентов из-за следующих факторов:

1. **Потребление памяти:** каждый поток требует отдельного стека (по умолчанию 8 МБ в Linux), что при 10 000 соединений приводит к десяткам гигабайт RAM.
2. **Переключение контекста (Context Switch):** планировщик ОС тратит циклы CPU на сохранение и восстановление состояния регистров при каждом переключении между потоками.
3. **Лимиты ядра:** максимальное количество файловых дескрипторов на процесс (`ulimit -n`) и общесистемный лимит (`fs.file-max`).

Мультиплексирование решает эту проблему, позволяя одному потоку опрашивать состояние тысяч дескрипторов за одну операцию, получая от ядра только список готовых к работе ресурсов.

## Сравнение механизмов

| Метод | ОС | Сложность | Масштабируемость | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| **`select`** | POSIX | $O(n)$ | Низкая (лимит 1024) | Копирует весь список FD в ядро при каждом вызове. Линейное сканирование. |
| **`poll`** | POSIX | $O(n)$ | Средняя (нет лимита) | Использует массив структур `pollfd`. Проблема линейного сканирования остается. |
| **`epoll`** | Linux | $O(1)$* | Высокая | Использует rbtree для хранения FD и связный список для событий. |
| **`kqueue`** | BSD / macOS | $O(1)$ | Высокая | Поддерживает сокеты, сигналы, таймеры, события ФС. |
| **`IOCP`** | Windows | $O(1)$ | Высокая | Полностью асинхронный I/O (Completion Ports). Модель Proactor. |
| **`io_uring`** | Linux (5.1+) | $O(1)$ | Экстремальная | Обмен через разделяемые кольцевые буферы (Submission/Completion Queues). |

*\*Сложность `epoll_wait` пропорциональна количеству готовых событий, а не общему числу дескрипторов.*

## Основные концепции

### Блокирующий и неблокирующий I/O

В блокирующей модели вызов `read(fd)` приостанавливает поток, пока данные не поступят в буфер сокета. Это создает прямую зависимость между числом соединений и числом потоков. При 10 000 соединений требуется 10 000 потоков, что невозможно из-за ограничений памяти и переключений контекста.

В неблокирующей модели `read(fd)` возвращает `-1` и устанавливает `errno = EAGAIN`, если данных нет. Приложение должно проверять готовность дескриптора через механизм мультиплексирования и только тогда выполнять чтение/запись.

### Классические механизмы: `select()` и `poll()`

В этих моделях ядро вынуждено линейно сканировать каждый файловый дескриптор в переданном списке, чтобы проверить его готовность. При 10 000 соединений ядро выполняет 10 000 проверок при каждом запросе приложения, что создает огромную нагрузку на CPU (сложность $O(n)$ по дескрипторам).

- `select` имеет жесткое ограничение `FD_SETSIZE` (обычно 1024), зашитое в системные заголовки. При каждом вызове ядро копирует весь набор `fd_set` из пользовательского пространства в ядро, что создает дополнительную нагрузку при большом количестве дескрипторов.
- `poll` снимает ограничение на количество FD, но сохраняет неэффективность линейного перебора и требует копирования массива структур `pollfd` при каждом вызове.

Оба механизма страдают от проблемы «пробуждения толпы» (thundering herd): при возврате управления ядро не сообщает, какие именно дескрипторы готовы, поэтому приложение должно проверять все дескрипторы в списке.

### Современный стандарт Linux: `epoll`

`epoll` спроектирован для минимизации копирования данных между пространством пользователя и ядром. Он использует две ключевые структуры:
1.  **Red-Black Tree (rbtree):** Хранит все файловые дескрипторы, зарегистрированные в инстансе `epoll`. Это позволяет добавлять (`epoll_ctl_add`), удалять (`epoll_ctl_del`) и модифицировать дескрипторы за логарифмическое время $O(\log n)$.
2.  **Ready List (связный список):** Содержит ссылки только на те дескрипторы, на которых произошло событие. Когда данные приходят на сетевую карту, прерывание заставляет ядро поместить FD в этот список. Системный вызов `epoll_wait` просто проверяет, не пуст ли этот список, и возвращает готовые события приложению.

#### Режимы уведомлений (Triggering)
- **Level-triggered (LT, по умолчанию):** Ядро уведомляет о готовности дескриптора, пока в его буфере есть данные. Если приложение прочитало не всё, при следующем вызове `epoll_wait` дескриптор будет возвращен снова.
- **Edge-triggered (ET):** Уведомление происходит только в момент **изменения** состояния (например, когда буфер был пустым и пришли данные). Приложение обязано вычитывать данные в цикле до тех пор, пока не получит ошибку `EAGAIN`, иначе оно может "пропустить" событие и зависнуть. Этот режим потенциально производительнее, но сложнее в реализации.

#### Дополнительные флаги и режимы
- **`EPOLLONESHOT`:** После доставки события дескриптор отключается. Приложение должно явно переармировать его через `epoll_ctl()` с флагом `EPOLL_CTL_MOD`. Полезно для многопоточных сценариев, где нужно гарантировать, что только один поток обработает событие.
- **`EPOLLEXCLUSIVE`:** (Linux 4.5+) При нескольких параллельных вызовах `epoll_wait` на одном инстансе `epoll` ядро пробуждает только один поток для обработки события, предотвращая «пробуждение толпы».
- **`EPOLLWAKEUP`:** Предотвращает приостановку системы (autosleep/suspend) между моментом поступления события и возвратом из `epoll_wait`.
- **`EPOLLRDHUP`:** Уведомление о закрытии соединения удаленной стороной (получен `FIN`), что позволяет обработать разрыв до попытки `read()`, возвращающего 0.
- **`epoll_create1(EPOLL_CLOEXEC)`:** Создает инстанс `epoll` с флагом `CLOEXEC`, автоматически закрывающим дескриптор при вызове `exec()`. Это исключает утечку дескрипторов в дочерние процессы.

### BSD/macOS: `kqueue`

`kqueue` (kernel event queue) является универсальным механизмом событийного уведомления в BSD-системах. В отличие от `epoll`, который специализирован только на файловых дескрипторах, `kqueue` поддерживает:

- Сокеты (`EVFILT_READ`, `EVFILT_WRITE`)
- Сигналы (`EVFILT_SIGNAL`)
- Таймеры (`EVFILT_TIMER`)
- События файловой системы (`EVFILT_VNODE`)
- Процессы (`EVFILT_PROC`)

Режимы триггеров аналогичны `epoll`: `EV_CLEAR` соответствует Edge-triggered, а отсутствие флага — Level-triggered. В macOS `kqueue` лежит в основе реализация `libdispatch` (Grand Central Dispatch) и сетевого стека `NSTask`.

### Windows: IOCP (I/O Completion Ports)

IOCP представляет собой модель Proactor, где приложение инициирует асинхронную операцию (`ReadFileEx`, `WSARecv`), и ядро уведомляет о **завершении** операции через очередь завершений. Ключевые особенности:

- **Асинхронность:** приложение не блокируется в ожидании данных.
- **Масштабируемость:** один порт может обслуживать тысячи соединений с помощью ограниченного пула рабочих потоков (обычно по количеству ядер CPU).
- **Модель памяти:** IOCP использует APC (Asynchronous Procedure Call) для доставки уведомлений о завершении потоку, который вызвал `GetQueuedCompletionStatus`.

### Асинхронный ввод-вывод нового поколения: `io_uring`

Появился в ядре 5.1. Вместо постоянных системных вызовов `io_uring` использует два кольцевых буфера в разделяемой памяти:
1.  **Submission Queue (SQ):** Приложение пишет запросы на I/O.
2.  **Completion Queue (CQ):** Ядро пишет результаты выполненных операций.
Это позволяет избежать накладных расходов на переключение контекста между User-space и Kernel-space при каждом вызове.

#### Сетевые возможности `io_uring` (ядро 5.19–6.x)

Для сетевых серверов `io_uring` предоставляет специализированные операции, заменяющие или дополняющие `epoll`:

- **Multishot Accept (`IORING_OP_ACCEPT` с флагом `IORING_ACCEPT_MULTISHOT`, с ядра 5.19):** Один SQE (Submission Queue Entry) принимает серию входящих соединений. Ядро автоматически генерирует CQE (Completion Queue Event) для каждого нового клиента, пока SQ-запрос не будет отменен или не произойдет фатальная ошибка. Это устраняет необходимость переподачи `accept()` после каждого соединения.
- **Multishot Receive (`IORING_OP_RECV` с флагом `IOSQE_BUFFER_SELECT`, с ядра 6.0):** Один запрос на прием данных генерирует CQE каждый раз, когда на сокет поступают данные. Приложение заранее регистрирует пул буферов (`io_uring_register_buf_ring`), и ядро атомарно назначает свободный буфер для каждого прихода.
- **Zero-Copy Networking (`SEND_ZC`, `RECV_ZC`):** (с ядра 6.x) Сетевая карта считывает данные напрямую из пользовательских буферов (DMA), минуя страницы ядра. Требует поддержки NIC (Header/Data Split).
- **Fixed Files (`IORING_REGISTER_FILES`):** Предварительная регистрация файловых дескрипторов в таблице `io_uring` исключает повторный поиск FD в таблице процесса (`fdget`/`fdput`) при каждом SQE, снижая накладные расходы.

Подробнее: [io_uring — асинхронный ввод-вывод](../../Linux/Core/kernel/io_uring.md).

### Архитектурные паттерны: Reactor и Proactor

Для работы с мультиплексированием используются два основных паттерна проектирования:

- **Reactor (Синхронный):** Event Loop ожидает события готовности ресурсов (через `epoll`/`kqueue`). Когда ресурс готов, вызывается соответствующий обработчик, который выполняет **синхронную** операцию `read` или `write`. Пример: Nginx, Redis.
  - Вариация: **Thread-per-Core Reactor** (например, Nginx с `worker_processes = auto`). Каждый воркер имеет свой Event Loop, и ядро распределяет входящие соединения между ними через `SO_REUSEPORT`.
- **Proactor (Асинхронный):** Приложение инициирует операцию (например, "прочитай 1КБ в этот буфер") и продолжает работу. Ядро выполняет операцию в фоне и уведомляет приложение о **завершении**. Пример: IOCP в Windows, `io_uring` в Linux.

## Интеграция в современные рантаймы

- **Go (Netpoller):** Рантайм Go использует `epoll`/`kqueue` для реализации сетевого стека. Когда горутина блокируется на чтении из сети, она фактически уступает место другим, а Netpoller следит за дескриптором и пробуждает горутину, когда данные готовы. Вместо классического Event Loop используется модель M:N, где M горутин планируются на N потоков OS.
- **Node.js (libuv):** Библиотека `libuv` предоставляет кроссплатформенный Event Loop, абстрагируя `epoll`, `kqueue` и `IOCP`. Начиная с Node.js 13+, `libuv` поддерживает `io_uring` для асинхронного файлового I/O, что дает прирост производительности до 8× по сравнению с thread-pool реализацией.
- **Rust (Tokio / Mio):** Экосистема Rust полагается на библиотеку `mio` (Metal I/O) для низкоуровневого мультиплексирования. `Tokio` строит поверх `mio` асинхронный рантайм с futures, executors и таймерами. Начиная с `Tokio 1.x`, `io_uring` поддерживается через отдельный драйвер `tokio-uring`.
- **Java (NIO / epoll):** В JVM начиная с Java 16 `epoll` используется по умолчанию на Linux вместо устаревшего `/dev/poll`. С Java 21 `io_uring` получает экспериментальную поддержку через флаг `--enable-preview`.

## Практические сценарии

### Пример: эхо-сервер на `epoll` (C, Level-triggered)

```c
#define _GNU_SOURCE
#include <sys/epoll.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PORT 8080
#define MAX_EVENTS 64
#define BUF_SIZE 4096

int main(void) {
    int listen_fd, epfd, nfds, i;
    struct sockaddr_in addr;
    struct epoll_event event, events[MAX_EVENTS];
    char buf[BUF_SIZE];

    listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd < 0) { perror("socket"); return 1; }

    int opt = 1;
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(PORT);

    if (bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(listen_fd); return 1;
    }

    if (listen(listen_fd, SOMAXCONN) < 0) {
        perror("listen"); close(listen_fd); return 1;
    }

    epfd = epoll_create1(EPOLL_CLOEXEC);
    if (epfd < 0) { perror("epoll_create1"); return 1; }

    event.events = EPOLLIN;
    event.data.fd = listen_fd;
    if (epoll_ctl(epfd, EPOLL_CTL_ADD, listen_fd, &event) < 0) {
        perror("epoll_ctl: listen_sock"); return 1;
    }

    printf("Listening on 0.0.0.0:%d\n", PORT);

    while (1) {
        nfds = epoll_wait(epfd, events, MAX_EVENTS, -1);
        if (nfds < 0) {
            if (errno == EINTR) continue;
            perror("epoll_wait"); break;
        }

        for (i = 0; i < nfds; i++) {
            int fd = events[i].data.fd;

            if (fd == listen_fd) {
                while (1) {
                    int cfd = accept4(listen_fd, NULL, NULL, SOCK_NONBLOCK);
                    if (cfd < 0) {
                        if (errno == EAGAIN || errno == EWOULDBLOCK) break;
                        perror("accept4"); break;
                    }

                    event.events = EPOLLIN | EPOLLRDHUP;
                    event.data.fd = cfd;
                    if (epoll_ctl(epfd, EPOLL_CTL_ADD, cfd, &event) < 0) {
                        perror("epoll_ctl: conn_sock"); close(cfd);
                    }
                }
            } else {
                ssize_t n = recv(fd, buf, sizeof(buf) - 1, 0);
                if (n > 0) {
                    buf[n] = '\0';
                    send(fd, buf, n, MSG_NOSIGNAL);
                } else if (n == 0 || (n < 0 && errno != EAGAIN)) {
                    close(fd);
                }
            }
        }
    }

    close(epfd);
    close(listen_fd);
    return 0;
}
```

### Пример: эхо-сервер на `epoll` (Edge-triggered)

```c
    /* ... после accept4() ... */
    event.events = EPOLLIN | EPOLLET | EPOLLRDHUP;
    event.data.fd = cfd;
    if (epoll_ctl(epfd, EPOLL_CTL_ADD, cfd, &event) < 0) {
        perror("epoll_ctl: conn_sock"); close(cfd);
    }

    /* В цикле обработки: */
    ssize_t n;
    while ((n = recv(fd, buf, sizeof(buf) - 1, 0)) > 0) {
        buf[n] = '\0';
        send(fd, buf, n, MSG_NOSIGNAL);
    }
    if (n == 0 || (n < 0 && errno != EAGAIN)) {
        close(fd);
    }
```

В ET-режиме приложение должно вызывать `recv()`/`send()` в цикле до `EAGAIN`. Иначе при следующем `epoll_wait` дескриптор не вернется, даже если в буфере остались непрочитанные данные.

### Пример: эхо-сервер на `io_uring` (multishot accept)

```c
#include <liburing.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define PORT 8080
#define QUEUE_DEPTH 256
#define TAG_ACCEPT 1ULL

static void arm_accept(struct io_uring *ring, int listen_fd) {
    struct io_uring_sqe *sqe = io_uring_get_sqe(ring);
    io_uring_prep_multishot_accept(sqe, listen_fd, NULL, NULL, 0);
    io_uring_sqe_set_data64(sqe, TAG_ACCEPT);
    io_uring_submit(ring);
}

int main(void) {
    struct io_uring ring;
    struct io_uring_cqe *cqe;
    int listen_fd;

    listen_fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(PORT),
        .sin_addr.s_addr = INADDR_ANY,
    };
    bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr));
    listen(listen_fd, SOMAXCONN);

    io_uring_queue_init(QUEUE_DEPTH, &ring, 0);
    arm_accept(&ring, listen_fd);

    printf("io_uring server on :%d\n", PORT);

    for (;;) {
        if (io_uring_wait_cqe(&ring, &cqe) < 0) break;

        uint64_t tag = io_uring_cqe_get_data64(cqe);

        if (tag == TAG_ACCEPT) {
            if (cqe->res >= 0) {
                int cfd = cqe->res;
                /* Обработка клиента: recv/send */
                close(cfd);
            } else if (cqe->res != -ECANCELED) {
                fprintf(stderr, "accept: %s\n", strerror(-cqe->res));
            }

            bool more = cqe->flags & IORING_CQE_F_MORE;
            io_uring_cqe_seen(&ring, cqe);

            if (!more) arm_accept(&ring, listen_fd);
        } else {
            io_uring_cqe_seen(&ring, cqe);
        }
    }

    io_uring_queue_exit(&ring);
    close(listen_fd);
    return 0;
}
```

### Высокопроизводительные серверы

- **Nginx / Angie:** Используют архитектуру Event Loop на базе `epoll` (или `kqueue`), позволяя одному рабочему процессу обслуживать сотни тысяч соединений. В Nginx ключевые директивы: `worker_processes auto` (по числу ядер), `worker_connections 65535`, `use epoll`.
- **Redis:** Однопоточная база данных, производительность которой напрямую зависит от эффективности I/O мультиплексирования. С версии 6.x Redis поддерживает threaded I/O для фоновых операций (lazy free, active defrag), но основной обработчик команд остается однопоточным.
- **HAProxy:** Балансировщик, использующий `epoll` для обработки трафика с минимальными задержками. Поддерживает `nbthread` для привязки воркеров к ядрам.

### Диагностика: накопление очереди событий

Если приложение работает медленно, но CPU не загружен, возможно, оно не успевает вычитывать события из `epoll`.

```bash
# Проверка глобального лимита на количество epoll-вотчеров
cat /proc/sys/fs/epoll/max_user_watches
# → result: 1048576 (если лимит достигнут, новые соединения будут отклоняться)

# Сколько файловых дескрипторов реально держит процесс
lsof -p <PID> | wc -l
# → result: 12500

# Трассировка времени ожидания в epoll_wait
sudo strace -tt -e epoll_wait -p <PID>
# → result: epoll_wait(3, [{events=EPOLLIN, data={u32=15}}], 32, -1) = 1 <0.000120>

# Просмотр статистики сокетов и очередей
ss -ntlp
# → result: (показывает Send-Q и Recv-Q для слушающих сокетов)

# Проверка переполнения очереди accept (SYN/accept backlog)
nstat -az | grep -E 'TcpExtTCPListenOverflows|TcpExtTCPListenDrops'
# → result: 0 (если значения растут — backlog слишком мал)

# Мониторинг ошибок EPOLLERR
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_epoll_wait { @[comm] = count(); }'
```

### Тюнинг ядра для высоконагруженных серверов

Для работы с десятками тысяч соединений требуется предварительная настройка параметров ядра:

```bash
# /etc/sysctl.d/99-high-load.conf

# Максимальное количество открытых файловых дескрипторов
fs.file-max = 1000000

# Очередь полностью установленных соединений (Accept Queue)
net.core.somaxconn = 65535

# Очередь полуоткрытых соединений (SYN Queue)
net.ipv4.tcp_max_syn_backlog = 16384

# Диапазон эфемерных портов
net.ipv4.ip_local_port_range = 1024 65535

# Открытие сокетов в неблокирующем режиме по умолчанию
net.ipv4.tcp_syncookies = 1

# Включение TCP Fast Open (с ядра 4.11)
net.ipv4.tcp_fastopen = 3

# Включение ECN (Explicit Congestion Notification)
net.ipv4.tcp_ecn = 1

# Снижение задержки ACK (отключает задержку 40-200 мс)
net.ipv4.tcp_quickack = 1

# Включение BBR для управления перегрузками (с ядра 4.9+)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Лимит на количество epoll-вотчеров (по умолчанию ~4% lowmem)
fs.epoll.max_user_watches = 5242880
```

Применение:
```bash
sudo sysctl --system
# → result: Applying /etc/sysctl.d/99-high-load.conf ...
```

## Типичные ошибки и edge cases

### 1. Edge-triggered без неблокирующих дескрипторов

Использование `EPOLLET` с блокирующими FD приводит к зависанию Event Loop: один дескриптор блокирует чтение, и остальные соединения не обслуживаются. Всегда используйте `fcntl(fd, F_SETFL, O_NONBLOCK)` или `accept4(..., SOCK_NONBLOCK)`.

### 2. Неполное вычитывание в ET-режиме

Приложение должно читать данные в цикле до `EAGAIN`. Остановка после первого `read()` приведет к тому, что оставшиеся данные в буфере не вызовут новых уведомлений, так как состояние дескриптора не изменилось.

### 3. Дублирование дескрипторов в `epoll`

Дублирование FD через `dup()` или `fork()` регистрирует в `epoll` разные ключи (разные дескрипторы), но указывающие на одно Open File Description. При закрытии одного из дубликатов ядро может удалить запись из interest list, что приведет к потере событий для оставшихся дубликатов.

### 4. `accept()` в цикле

При использовании Level-triggered `epoll` после возврата `EPOLLIN` на слушающий сокет нужно вызывать `accept()` в цикле, пока не получим `EAGAIN`. Иначе при следующем `epoll_wait` событие вернется снова, создавая бесконечный цикл.

### 5. Проблема с `close()` и утечками FD

Закрытие дескриптора через `close()` автоматически удаляет его из `epoll` interest list. Однако если дескриптор был продублирован (`dup()`), `close()` удаляет запись только если счетчик ссылок достиг нуля. Для принудительного удаления конкретного FD из `epoll` используйте `epoll_ctl(epfd, EPOLL_CTL_DEL, fd, NULL)`.

### 6. Очередь Accept Queue vs SYN Queue

Переполнение `Accept Queue` (управляется `net.core.somaxconn`) приводит к `TcpExtTCPListenDrops`. Если приложение медленно вызывает `accept()`, но `Accept Queue` заполнена, новые SYN-пакеты игнорируются. При `tcp_abort_on_overflow=1` сервер отправляет RST, что ломает клиентские соединения.

### 7. `io_uring` и серийные номера CQE

`io_uring` не гарантирует упорядоченности CQE относительно времени отправки SQE. Приложение должно использовать поле `user_data` для сопоставления завершений с запросами, а не полагаться на порядок в Completion Queue.

## Дополнительная информация

- [Интерфейс сокетов (Socket API)](./socket_api.md).
- [Тюнинг TCP/IP в Linux](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md).
- [io_uring — асинхронный ввод-вывод нового поколения](../../Linux/Core/kernel/io_uring.md).

## Связанные темы

- [Файловые дескрипторы](../../Linux/FileSystems/file_descriptors.md) — абстракция, лежащая в основе мультиплексирования.
- [Обзор Nginx](../../WebServers/Nginx/Core/nginx_overview.md) — архитектурный паттерн Event Loop.
- [Интерфейс сокетов (Socket API)](./socket_api.md) — системные вызовы для работы с FD.
