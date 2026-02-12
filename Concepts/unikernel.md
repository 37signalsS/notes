# Unikernel

## Определение

**Unikernel** — это специализированный, single-address-space образ машины, созданный путем компиляции высокоуровневого исходного кода в автономный образ, который включает только необходимые библиотеки ОС и приложение.

**Ключевая идея:** Вместо ОС общего назначения (Linux, Windows) + приложение, unikernel объединяет приложение и минимальные компоненты ОС в один образ, работающий непосредственно на гипервизоре или железе.

## Архитектура Unikernel

### Традиционный подход vs Unikernel

```
ТРАДИЦИОННЫЙ ПОДХОД (VM с Linux):

┌─────────────────────────────────────────────────────────────┐
│                    APPLICATION                              │
│              (Your code + dependencies)                     │
├─────────────────────────────────────────────────────────────┤
│              USER SPACE LIBRARIES                           │
│    (libc, openssl, etc.)                                    │
├─────────────────────────────────────────────────────────────┤
│                       LINUX KERNEL                          │
│    (Scheduling, Memory mgmt, Drivers, File systems,         │
│     Networking stack, Security modules, etc.)              │
├─────────────────────────────────────────────────────────────┤
│                     HYPERVISOR (optional)                   │
│    (KVM, Xen, VMware, Hyper-V)                             │
├─────────────────────────────────────────────────────────────┤
│                      HARDWARE                               │
└─────────────────────────────────────────────────────────────┘

Размер: 500MB - 2GB
Boot time: 10-60 секунд
Attack surface: Огромная
Memory: 1GB+

UNIKERNEL:

┌─────────────────────────────────────────────────────────────┐
│                    APPLICATION                              │
│              (Your code + dependencies)                     │
├─────────────────────────────────────────────────────────────┤
│              MINIMAL OS LIBRARIES                           │
│    (Только нужное: network driver, TCP/IP stack,           │
│     memory allocator - если требуется)                     │
├─────────────────────────────────────────────────────────────┤
│                     HYPERVISOR / HARDWARE                   │
│    (KVM, Xen, или bare metal)                              │
├─────────────────────────────────────────────────────────────┤
│                      HARDWARE                               │
└─────────────────────────────────────────────────────────────┘

Размер: 1-50MB
Boot time: 10-50 миллисекунд
Attack surface: Минимальная
Memory: MBs
```

### Типы Unikernels

| Тип | Описание | Примеры |
|-----|----------|---------|
| **Clean-slate** | Написаны с нуля на безопасных языках | MirageOS (OCaml), IncludeOS (C++) |
| **POSIX-compliant** | Поддержка POSIX API для совместимости | OSv, HermitCore |
| **Language-specific** | Привязаны к конкретному языку | MirageOS (OCaml), LING (Erlang) |
| **Linux-compatible** | Могут запускать Linux бинарники | UniK, Rumprun |

## Популярные Unikernels

### MirageOS

```ocaml
(* Простое HTTP-сервер на MirageOS (OCaml) *)
open Lwt.Infix

module Main (S: Mirage_stack.V4) = struct
  let start s =
    let port = Key_gen.port () in
    S.listen_tcpv4 s ~port (fun flow ->
      let dst, dst_port = S.TCPV4.dst flow in
      Logs.info (fun f -> f "new tcp connection from %s:%d"
        (Ipaddr.V4.to_string dst) dst_port);
      S.TCPV4.write flow (Cstruct.of_string "Hello from MirageOS!")
      >>= fun _ -> S.TCPV4.close flow
    );
    S.listen s
end
```

**Характеристики:**
- Язык: OCaml
- Размер: ~1MB для простых приложений
- Безопасность: Type-safe, memory-safe
- Использование: DNS серверы, SSL прокси, брандмауэры

### IncludeOS

```cpp
// Простое HTTP-сервер на IncludeOS (C++)
#include <os>
#include <net/inet4>
#include <http>

void Service::start(const std::string&) {
    auto& inet = net::Inet4::stack();
    
    inet.tcp().listen(80, [](auto conn) {
        conn->write("HTTP/1.1 200 OK\r\n"
                   "Content-Type: text/plain\r\n"
                   "Content-Length: 20\r\n\r\n"
                   "Hello from IncludeOS!");
    });
}
```

**Характеристики:**
- Язык: C++
- Размер: ~5MB для простых приложений
- Производительность: Близка к bare metal
- Использование: Edge computing, CDN, IoT

### OSv

**Характеристики:**
- POSIX-compliant
- Поддержка Java, Python, Node.js, Ruby
- Работает на KVM, Xen, VMWare, AWS, GCE
- Оптимизация для JVM

```bash
# Запуск Java приложения на OSv
./scripts/run.py -e "java -jar myapp.jar"

# Размер образа: ~20-50MB для Java приложения
```

### Rumprun

```bash
# Компиляция существующего приложения в unikernel
rumprun-bake hw_generic myapp.bin myapp

# Запуск
rumprun kvm -i myapp.bin

# Поддержка: C, C++, Python, Node.js, Erlang, и др.
```

**Характеристики:**
- POSIX-compliant
- Работает с существующими приложениями
- Поддержка rump kernel (NetBSD drivers)
- Easy migration path

## Преимущества Unikernels

### 1. Размер и эффективность

| Метрика | Linux VM | Container | Unikernel |
|---------|----------|-----------|-----------|
| **Размер образа** | 500MB - 2GB | 100MB - 1GB | 1MB - 50MB |
| **Boot time** | 30-60 сек | 1-5 сек | 10-50 мс |
| **Memory footprint** | 1GB+ | 100MB+ | 5-20MB |
| **Density** | 10s VMs/host | 100s containers | 1000s unikernels |

### 2. Безопасность

- **Minimal attack surface**: Нет лишних сервисов
- **No shell**: Невозможно залогиниться
- **Single address space**: Нет kernel/userspace boundary
- **Immutable**: Образ read-only
- **Type safety** (MirageOS): Компилятор предотвращает многие баги

### 3. Производительность

- **No context switches**: Single address space
- **No ring transitions**: Нет kernel/userspace переключений
- **Direct hardware access**: Без прослойки ОС
- **Lock-free**: Нет необходимости в сложной синхронизации

## Ограничения Unikernels

### 1. Отладка

- Нет shell для troubleshooting
- Ограниченные инструменты мониторинга
- Сложнее диагностировать проблемы

### 2. Разработка

- Кривая обучения (новые языки/фреймворки)
- Ограниченная экосистема
- Не все библиотеки доступны

### 3. Многозадачность

- Single-process (обычно)
- Нет fork()
- Ограниченная поддержка многопоточности

### 4. Persistence

- Stateless по умолчанию
- Сложности с сохранением данных
- Требуется внешнее хранилище

## Сценарии использования

### 1. Edge Computing

```
┌─────────────────────────────────────────────────────────────┐
│                    EDGE LOCATION                            │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  DNS Cache  │  │  SSL Term.  │  │  Firewall   │         │
│  │  (MirageOS) │  │ (IncludeOS) │  │ (Rumprun)   │         │
│  │  ~2MB       │  │  ~5MB       │  │  ~3MB       │         │
│  │  10ms boot  │  │  15ms boot  │  │  12ms boot  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                             │
│  Преимущества:                                              │
│  - Мгновенный старт на edge-устройствах                     │
│  - Минимальное использование ресурсов                       │
│  - Высокая плотность размещения                             │
└─────────────────────────────────────────────────────────────┘
```

### 2. Serverless / Function-as-a-Service

```yaml
# AWS Firecracker + MicroVMs (unikernel-подобный подход)
# Запуск функций за миллисекунды

apiVersion: v1
kind: Pod
metadata:
  name: firecracker-microvm
spec:
  runtimeClassName: firecracker
  containers:
  - name: function
    image: my-unikernel-function:latest
    resources:
      limits:
        memory: "32Mi"
        cpu: "100m"
```

### 3. High-Performance Applications

- **High-frequency trading**: Минимальная latency
- **CDN edge nodes**: Быстрый старт, высокая плотность
- **IoT gateways**: Малый footprint, безопасность

### 4. Security Appliances

- **VPN concentrators**
- **Firewall appliances**
- **IDS/IPS sensors**

## Инструменты и фреймворки

### UniK (Unikernel Compiler)

```bash
# Установка
go get -u github.com/solo-io/unik

# Создание unikernel из Go приложения
unik build --name my-go-app --path ./myapp --language go --provider virtualbox

# Запуск
unik run --instanceName my-go-app-instance --imageName my-go-app
```

### OPS (NanoVMs)

```bash
# Установка
curl https://ops.city/get.sh -sSfL | sh

# Создание образа
ops load node_v14.2.0 -a myapp.js

# Запуск
ops run myapp

# Деплой в облако
ops image create myapp -t gcp -c config.json
ops instance create myapp -t gcp -z us-west1-b
```

**Поддерживаемые языки:**
- C, C++, Go, Node.js, Python, Ruby, Java, Rust, и др.

### Docker + Unikernel

```dockerfile
# Dockerfile для unikernel с помощью IncludeOS
FROM includeos/includeos:0.14.0 as builder
COPY . /src
WORKDIR /src
RUN mkdir build && cd build && cmake .. && make

FROM scratch
COPY --from=builder /src/build/my_unikernel /boot/my_unikernel
ENTRYPOINT ["/boot/my_unikernel"]
```

## Будущее Unikernels

### AWS Firecracker

AWS Firecracker — это virtualization technology, использующая MicroVMs:

```
Firecracker = KVM + Minimal device model + Fast boot

- Boot time: 125ms
- Memory overhead: < 5MB
- Density: 1000s MicroVMs per host
- Используется в AWS Lambda и Fargate
```

### WebAssembly (Wasm) + Unikernels

```
WebAssembly как "легкий unikernel":

┌─────────────────────────────────────────────────────────────┐
│                    WASM RUNTIME                             │
│              (Wasmtime, Wasmer, WasmEdge)                   │
├─────────────────────────────────────────────────────────────┤
│                    WASM MODULE                              │
│              (Sandboxed, portable)                          │
├─────────────────────────────────────────────────────────────┤
│                    HOST OS / Container                      │
└─────────────────────────────────────────────────────────────┘

Преимущества:
- Near-native performance
- Sandbox без hypervisor
- Поддержка множества языков
- Cloud-native
```

## Сравнение с альтернативами

| Технология | Размер | Безопасность | Производительность | Гибкость |
|------------|--------|--------------|-------------------|----------|
| **VM** | Большой | Средняя | Средняя | Высокая |
| **Container** | Средний | Средняя | Высокая | Высокая |
| **Unikernel** | Маленький | Высокая | Очень высокая | Низкая |
| **Wasm** | Маленький | Высокая | Высокая | Средняя |

## Дополнительная информация

- [MirageOS](https://mirage.io/)
- [IncludeOS](https://www.includeos.org/)
- [OSv](http://osv.io/)
- [Rumprun](https://github.com/rumpkernel/rumprun)
- [UniK](https://github.com/solo-io/unik)
- [OPS/NanoVMs](https://ops.city/)
- [AWS Firecracker](https://firecracker-microvm.github.io/)
