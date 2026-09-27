# I/O Multiplexing: select, poll, epoll

## Определения

**I/O Multiplexing** — механизм ядра Linux, позволяющий одному процессу отслеживать готовность нескольких файловых дескрипторов (FD) одновременно без блокировки на каждом из них. Вместо создания отдельного потока или процесса на каждое соединение, процесс регистрирует感兴趣的 FD в ядре и получает уведомление, когда один или более из них становятся готовы к чтению/записи.

**select** — системный вызов, первый интерфейс I/O multiplexing в POSIX. Ожидает изменения состояния набора файловых дескрипторов с заданным таймаутом. Имеет фундаментальное ограничение: на каждом вызове ядро должно сканировать все зарегистрированные FD, что даёт сложность O(n).

**poll** — эволюция select, использующая массив структур `pollfd` вместо битовых масок. Устраняет жесткое ограничение select на максимальное количество FD (`FD_SETSIZE` = 1024), но сохраняет O(n) сканирование.

**epoll** — высокоэффективный интерфейс ввода-вывода ядра Linux (доступен с ядра 2.6), реализующий модель event-driven I/O. В отличие от select/poll, epoll не пересоздаёт список отслеживаемых дескрипторов при каждом вызове и предоставляет уведомления только для готовых FD. Сложность O(1) для добавления/удаления FD и O(k) для получения событий (где k — количество готовых FD, а не общее число отслеживаемых).

**eventfd** — специальный файловый дескриптор ядра Linux, предназначенный для уведомлений между потоками/процессами. В отличие от pipe, он не передаёт данные — только 8-байтовое счётчик событий. Используется в комбинации с epoll для пробуждения при наступлении события.

## Основные концепции

### Архитектурные модели I/O

| Модель | Описание | Масштабируемость | Пример |
| :--- | :--- | :--- | :--- |
| **Blocking I/O** | Системный вызов блокирует процесс до завершения операции | Низкая (1 FD на поток) | `read()` на обычном сокете |
| **Non-blocking I/O** | FD открывается через `O_NONBLOCK`; чтение возвращает `EAGAIN` если данных нет | Средняя (активное опросание) | `fcntl(fd, F_SETFL, O_NONBLOCK)` |
| **I/O Multiplexing (select/poll)** | Один процесс отслеживает множество FD через системный вызов | Высокая (до数千) | Веб-сервер на epoll |
| **Asynchronous I/O (io_uring)** | Ядро выполняет операцию и уведомляет о завершении | Очень высокая (десятки тысяч) | Высокопроизводительные-proxy |

### select: системный вызов

```c
#include <sys/select.h>

int select(int nfds, fd_set *readfds, fd_set *writefds,
           fd_set *exceptfds, struct timeval *timeout);
```

**Принцип работы:**
1. Приложение создаёт битовые маски `fd_set` для чтения, записи и ошибок.
2. Вызывает `select()` с максимальным FD + 1 (`nfds`) и таймаутом.
3. Ядро проверяет каждый FD в наборе и модифицирует маски, оставляя только готовые.
4. Приложение проверяет маски и обрабатывает готовые FD.

**Ограничения:**
- `FD_SETSIZE` — максимальное количество FD в одной маске (обычно 1024, в glibc может быть увеличено через `sysconf()`).
- На каждом вызове ядро пересоздаёт внутренние копии масок — О(n) на каждый вызов.
- `nfds` должен быть корректным: ядро сканирует от 0 до nfds-1.

### poll: системный вызов

```c
#include <poll.h>

int poll(struct pollfd *fds, nfds_t nfds, int timeout);
```

**Принцип работы:**
1. Приложение создаёт массив `struct pollfd`, где каждый элемент описывает один FD и запрашиваемые события (`POLLIN`, `POLLOUT`, `POLLERR`).
2. Вызывает `poll()` с таймаутом.
3. Ядро проверяет все элементы массива и записывает произошедшие события в `revents`.
4. Приложение обрабатывает элементы с ненулевыми `revents`.

**Преимущества перед select:**
- Нет жесткого лимита `FD_SETSIZE`.
- Единый вызов для всех типов событий (чтение, запись, ошибки).

**Сохранённые ограничения:**
- Всё ещё O(n) сканирование при каждом вызове.
- Массив `fds` перезаписывается ядром — приложение должно проверять все элементы.

### epoll: системный вызов

epoll состоит из трёх системных вызовов:

```c
// 1. Создание экземпляра epoll
int epoll_create(int size);  // size игнорируется в современных ядрах
int epoll_create1(int flags); // epoll_create1(0) — стандартный способ

// 2. Управление отслеживаемыми FD
int epoll_ctl(int epfd, int op, int fd, struct epoll_event *event);
// op: EPOLL_CTL_ADD, EPOLL_CTL_MOD, EPOLL_CTL_DEL

// 3. Ожидание событий
int epoll_wait(int epfd, struct epoll_event *events,
               int maxevents, int timeout);
```

**Принцип работы:**
1. Приложение создаёт экземпляр epoll через `epoll_create1(0)`.
2. Добавляет FD через `epoll_ctl(EPOLL_CTL_ADD, fd, &event)`. Ядро регистрирует FD в внутренней структуре данных (RBTrees/linked list).
3. Вызывает `epoll_wait()` для получения готовых FD. Ядро возвращает только те FD, на которых произошли события.
4. Внутренняя структура epoll персистентна — нет пересоздания при каждом вызове.

**Флаги epoll:**

| Флаг | Описание |
| :--- | :--- |
| `EPOLLIN` | Данные доступны для чтения |
| `EPOLLOUT` | Сокет готов к записи (буфер не заполнен) |
| `EPOLLERR` | Произошла ошибка |
| `EPOLLHUP` | Соединение разорвано |
| `EPOLLRDHUP` | Удалённая сторона закрыла соединение |
| `EPOLLET` | Edge-Triggered режим (описан ниже) |
| `EPOLLONESHOT` | Одноразовое событие; после получения FD нужно пере-регистрировать |
| `EPOLLEXCLUSIVE` | Эксклюзивное пробуждение для multi-threaded epoll (с ядра 4.5) |

### Уровневое (LT) и.edge-triggered (ET) модели

| Режим | Поведение | Когда используется |
| :--- | :--- | :--- |
| **Level-Triggered (LT)** | epoll уведомляет о готовности FD **каждый раз** при вызове `epoll_wait()`, пока данные доступны | По умолчанию; безопасно для простых приложений |
| **Edge-Triggered (ET)** | epoll уведомляет **только при изменении** состояния FD (данные стали доступны или исчезли) | Максимальная производительность; требует non-blocking FD и полного прочтения/записи |

**Level-Triggered (пример):**
```
Данные пришли → epoll_wait() вернул EPOLLIN
Приложение прочитало часть данных → epoll_wait() СНОВА вернёт EPOLLIN
Приложение прочитало всё → epoll_wait() НЕ вернёт EPOLLIN до новых данных
```

**Edge-Triggered (пример):**
```
Данные пришли → epoll_wait() вернул EPOLLIN
Приложение прочитало часть данных → epoll_wait() НЕ вернёт EPOLLIN
Новые данные пришли → epoll_wait() вернёт EPOLLIN (только при изменении)
```

**Правила ET-режима:**
1. FD должен быть `O_NONBLOCK` — иначе чтение заблокирует процесс.
2. Необходимо читать/писать до `EAGAIN` / `EWOULDBLOCK` — иначе новые данные не будут уведомлены.
3. Один `epoll_wait()` может вернуть несколько событий — обрабатывайте все.

### EPOLLONESHOT (одноразовые события)

Флаг `EPOLLONESHOT` (ядро 2.6.17+) гарантирует, что после получения события FD автоматически деактивируется. Приложение должно заново активировать его через `epoll_ctl(EPOLL_CTL_MOD, ...)`.

**Зачем:** В multi-threaded серверах без `EPOLLONESHOT` один FD может быть обработан несколькими потоками одновременно (race condition). С `EPOLLONESHOT` событие достаётся ровно одному потоку.

### epoll vs select vs poll: сравнение

| Критерий | select | poll | epoll |
| :--- | :--- | :--- | :--- |
| **Лимит FD** | `FD_SETSIZE` (1024) | Нет лимита | Нет лимита |
| **Сложность добавления FD** | O(n) — пересоздание битовых масок | O(n) — пересоздание массива | O(1) — добавление в RBTrees |
| **Сложность ожидания** | O(n) — сканирование всех FD | O(n) — сканирование всех FD | O(k) — только готовые FD |
| **Копирование данных** | Копирование fd_set на каждый вызов | Копирование pollfd[] на каждый вызов | Персистентная структура в ядре |
| **Масштабируемость** | ~1000 FD | ~10K FD | ~100K+ FD |
| **Триггер** | Level-Triggered | Level-Triggered | LT + ET |
| **Уведомления** | Все FD в наборе | Все FD в массиве | Только готовые |

### Сравнение epoll и io_uring

| Критерий | epoll | io_uring |
| :--- | :--- | :--- |
| **Назначение** | Мониторинг готовности FD | Асинхронное выполнение I/O |
| **Системные вызовы** | epoll_wait на каждый цикл | Само уведомление без syscall (SQPOLL) |
| **Дисковый I/O** | Требует AIO или нити | Нативный async I/O |
| **Сетевой I/O** | epoll + send/recv | Нативный async send/recv |
| **Zero-Copy** | Нет | SEND_ZC, ZCRX |
| **Сложность** | Средняя | Высокая |
| **Сценарий** | Высоконагруженные TCP-серверы | Высокопроизводительные proxy, БД |

### Механизм уведомления: eventfd

Для пробуждения epoll из другого потока/процесса используется `eventfd`:

```c
#include <sys/eventfd.h>

// Создание eventfd
int efd = eventfd(0, EFD_NONBLOCK | EFD_SEMAPHORE);

// Регистрация в epoll
struct epoll_event ev = { .events = EPOLLIN, .data.fd = efd };
epoll_ctl(epfd, EPOLL_CTL_ADD, efd, &ev);

// Пробуждение из другого потока
uint64_t val = 1;
write(efd, &val, sizeof(val));

// Чтение в основном потоке (эпилог epoll_wait)
read(efd, &val, sizeof(val));
```

**Преимущества перед pipe:**
- Один FD вместо двух (pipe читает/пишет в两个方向).
- Нет передачи данных — только счётчик событий.
- Атомарная операция.

## Практические сценарии

### Простой HTTP-сервер на epoll (C, Level-Triggered)

```c
#include <sys/epoll.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>

#define MAX_EVENTS 64
#define PORT 8080

int main() {
    int epfd = epoll_create1(0);
    int listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    
    // Non-blocking socket
    int flags = fcntl(listen_fd, F_GETFL, 0);
    fcntl(listen_fd, F_SETFL, flags | O_NONBLOCK);
    
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(PORT),
        .sin_addr.s_addr = INADDR_ANY
    };
    bind(listen_fd, (struct sockaddr*)&addr, sizeof(addr));
    listen(listen_fd, 128);
    
    // Регистрация listen_fd в epoll
    struct epoll_event ev = {
        .events = EPOLLIN,
        .data.fd = listen_fd
    };
    epoll_ctl(epfd, EPOLL_CTL_ADD, listen_fd, &ev);
    
    struct epoll_event events[MAX_EVENTS];
    while (1) {
        int n = epoll_wait(epfd, events, MAX_EVENTS, -1);
        for (int i = 0; i < n; i++) {
            if (events[i].data.fd == listen_fd) {
                // Новое соединение
                int client_fd = accept(listen_fd, NULL, NULL);
                fcntl(client_fd, F_SETFL, 
                    fcntl(client_fd, F_GETFL, 0) | O_NONBLOCK);
                ev.events = EPOLLIN;
                ev.data.fd = client_fd;
                epoll_ctl(epfd, EPOLL_CTL_ADD, client_fd, &ev);
            } else if (events[i].events & EPOLLIN) {
                // Данные от клиента
                char buf[1024];
                ssize_t n = read(events[i].data.fd, buf, sizeof(buf));
                if (n <= 0) {
                    close(events[i].data.fd);
                    epoll_ctl(epfd, EPOLL_CTL_DEL, 
                        events[i].data.fd, NULL);
                } else {
                    write(events[i].data.fd, "HTTP/1.1 200 OK\r\n\r\nHello", 24);
                    close(events[i].data.fd);
                    epoll_ctl(epfd, EPOLL_CTL_DEL, 
                        events[i].data.fd, NULL);
                }
            }
        }
    }
}
```

### Edge-Triggered epoll (Python)

```python
import selectors
import socket

sel = selectors.DefaultSelector()

def accept(sock, mask):
    conn, addr = sock.accept()
    conn.setblocking(False)
    sel.register(conn, selectors.EVENT_READ, read)

def read(conn, mask):
    data = conn.recv(1024)
    if data:
        conn.sendall(b"HTTP/1.1 200 OK\r\n\r\nHello")
    sel.unregister(conn)
    conn.close()

sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', 8080))
sock.listen(100)
sock.setblocking(False)
sel.register(sock, selectors.EVENT_READ, accept)

while True:
    events = sel.select()
    for key, mask in events:
        callback = key.data
        callback(key.fileobj, mask)
```

### Пробуждение epoll из воркера через eventfd

```c
// Главный поток: ждёт событий от epoll
int efd = eventfd(0, EFD_NONBLOCK);
struct epoll_event ev = { .events = EPOLLIN, .data.fd = efd };
epoll_ctl(epfd, EPOLL_CTL_ADD, efd, &ev);

while (1) {
    int n = epoll_wait(epfd, events, MAX_EVENTS, -1);
    for (int i = 0; i < n; i++) {
        if (events[i].data.fd == efd) {
            uint64_t val;
            read(efd, &val, sizeof(val));
            printf("Получено %lu событий от воркеров\n", val);
        }
    }
}

// Воркер: уведомляет главный поток
void notify_main(int efd) {
    uint64_t val = 1;
    write(efd, &val, sizeof(val));  // Атомарно увеличивает счётчик
}
```

### EPOLLONESHOT для multi-threaded сервера

```c
// Регистрация FD с EPOLLONESHOT
ev.events = EPOLLIN | EPOLLONESHOT;
ev.data.fd = client_fd;
epoll_ctl(epfd, EPOLL_CTL_ADD, client_fd, &ev);

// В обработчике: повторная активация после обработки
void handle_client(int epfd, int client_fd) {
    // ... обработка ...
    
    // Пере-регистрация для следующего события
    struct epoll_event ev = {
        .events = EPOLLIN | EPOLLONESHOT,
        .data.fd = client_fd
    };
    epoll_ctl(epfd, EPOLL_CTL_MOD, client_fd, &ev);
}
```

### Диагностика epoll

```bash
# Просмотр FD процесса с epoll
ls -la /proc/<PID>/fd | grep epoll

# Проверка информации о epoll через procfs
cat /proc/<PID>/fdinfo/<EPOLL_FD>
# → pos: 0
# → flags: 02000000
# → mnt_id: 10
# → Inode: 12345

# Через strace: системные вызовы epoll
strace -e epoll_create1,epoll_ctl,epoll_wait -p <PID>

# Статистика epoll_wait
perf stat -e syscalls:sys_enter_epoll_wait -p <PID> sleep 5

# Просмотр количества FD в epoll (через /proc/net)
cat /proc/net/sockstat
# → TCP: inuse X orphan Y tw Z alloc W mem M
```

### Масштабирование epoll: epoll_create1 vs epoll_create

```c
// Устаревший способ (size игнорируется)
int epfd = epoll_create(10000);

// Современный способ
int epfd = epoll_create1(0);  // Флаг 0 — стандартный режим

// С ядра 2.6.31: EPOLL_CLOEXEC для наследования
int epfd = epoll_create1(EPOLL_CLOEXEC);
```

### Ловушки и edge cases

1. **EPOLLHUP + EPOLLIN:** Если соединение разорвано, epoll может вернуть `EPOLLHUP | EPOLLIN` одновременно. Необходимо проверять оба флага.
2. **EPOLLOUT после EAGAIN:** Если запись вернула `EAGAIN`, нужно зарегистрировать `EPOLLOUT` и ждать уведомления перед повторной попыткой.
3. **Closing FD:** При закрытии FD автоматически удаляется из epoll. Не вызывайте `epoll_ctl(EPOLL_CTL_DEL)` для уже закрытого FD — это UB.
4. **Re-arming:** В ET-режиме FD не требует повторного добавления. В LT-режиме — тоже, но `EPOLLONESHOT` требует `EPOLL_CTL_MOD`.

## Дополнительная информация

### Масштабируемость: nginx vs node.js vs Go

| Сервер | Модель I/O | Макс. соединений (1 ядро) |
| :--- | :--- | :--- |
| nginx | epoll (event-driven, воркеры) | ~100K–500K |
| Node.js | libuv (epoll на Linux, kqueue на BSD) | ~100K |
| Go | goroutines + epoll (netpoller) | ~1M+ |
| HAProxy | epoll | ~500K |

### Связанные темы

- [io_uring — асинхронный ввод-вывод нового поколения](../kernel/io_uring.md) — более совершенная замена epoll для дискового и сетевого I/O.
- [Файловые дескрипторы](../../FileSystems/file_descriptors.md) — базовые концепции FD, pipe, socket.
- [Планирование процессов](./scheduling.md) — взаимодействие epoll с планировщиком.

### См. также

- [DPDK и io_uring vs AF_XDP](../../Networking/Concepts/dpdk/dpdk_io_uring_vs_afxdp.md) — сравнение высокопроизводительных технологий ввода-вывода.
- [Tracing и отладка](../../Diagnostics/Troubleshooting/tracing_and_debugging.md) — strace для анализа epoll-вызовов.
