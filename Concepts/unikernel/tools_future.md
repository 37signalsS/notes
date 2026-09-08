# Юникернелы: Инструменты и будущее

## Определения

В данном документе рассматриваются современные инструменты для работы с юникернелами, а также смежные технологии изоляции — **MicroVM**, **WebAssembly (Wasm)** и **Sandbox-рантаймы**. Эти направления определяют вектор развития легковесных и безопасных вычислений в on-premise и Edge средах 2026 года.

- **MicroVM:** Технология аппаратной виртуализации, использующая минималистичные гипервизоры (VMM) для запуска изолированных ядер ОС с временем старта, сопоставимым с контейнерами.
- **WebAssembly (Wasm):** Бинарный формат инструкций для переносимой и безопасной среды выполнения, обеспечивающий изоляцию на уровне песочницы (sandbox) внутри процесса.
- **Library OS (Unikernel):** Приложение, скомпилированное вместе с необходимыми функциями ядра в единый образ, работающий напрямую на гипервизоре.

Базовые концепции технологии описаны в [Обзоре Unikernel](./unikernel_overview.md).

## Требования для использования

Для работы с современными инструментами изоляции требуется:
- **Аппаратная поддержка:** Процессор с поддержкой виртуализации (Intel VT-x / AMD-V). Доступ к `/dev/kvm` обязателен для MicroVM и юникернелов.
- **Окружение:** Linux (ядро 5.10+) для Firecracker и Kata Containers.
- **Инструментарий:** 
  - `rustc` и `cargo` (многие рантаймы написаны на Rust).
  - `containerd` версии 1.7+ с поддержкой `runwasi`.
  - Установленный гипервизор (QEMU, Firecracker).

## Основные концепции и технологии

### 1. AWS Firecracker и Kata Containers
**MicroVM** — это гибрид безопасности традиционных ВМ и скорости контейнеров. В 2026 году это база для Serverless-вычислений и безопасной изоляции недоверенного кода.

*   **AWS Firecracker (VMM на Rust):**
    *   **Механизм Jailer:** Обеспечивает дополнительный слой защиты, запуская процесс VMM внутри изолированной среды с минимальными правами (seccomp, namespaces, chroot). Jailer ограничивает системные вызовы, доступные процессу VMM, до минимума (~30 из ~300 доступных в Linux).
    *   **Снимки состояния (Snapshots):** Позволяют «замораживать» запущенную микро-ВМ и восстанавливать её за ~25 мс. Это критично для мгновенного масштабирования и disaster recovery.
    *   **Ограничение ресурсов (Rate Limiting):** Встроенные механизмы для лимитирования операций ввода-вывода и сетевого трафика на уровне каждой микро-ВМ.
    *   **Сетевой стек:** Каждая MicroVM получает виртуальный NIC (virtio-net) с возможностью настройки rate limiting через API. Сеть обрабатывается на стороне хоста через bridge или macvtap.
    *   **Хранилище:** Block devices монтируются через virtio-blk. Поддержка read-only rootfs и overlay для записи.

*   **Kata Containers 4.0:**
    *   Использование **Runtime-rs** (реализация на Rust) минимизировало оверхед по памяти (~30 МБ на контейнер).
    *   **Интеграция с Kubernetes:** Реализуется через `RuntimeClass`. Каждый под запускается в собственной микро-ВМ, что предотвращает атаки типа «Container Escape».
    *   **Гостевое ядро:** Kata использует оптимизированное ядро (~5 МБ) с минимальным набором драйверов. Конфигурация через `/etc/kata-containers/configuration.toml`.

### 2. gVisor (Sandbox-рантайм)
**gVisor** — это песочница от Google, реализующая ядро в пользовательском пространстве (Sentry). В отличие от MicroVM, gVisor не использует аппаратную виртуализацию, а перехватывает системные вызовы контейнера и обрабатывает их внутри изолированного процесса.

*   **Архитектура:**
    *   **Sentry:** Ядро в user-space, реализующее основные POSIX-вызовы (~70 из ~300). Обеспечивает изоляцию без аппаратной виртуализации.
    *   **Gofer:** Файловый сервер, ограничивающий доступ контейнера к файловой системе хоста через 9P-протокол.
    *   **Platformes:** `ptrace` (для совместимости) и `KVM` (для производительности). На Linux 5.10+ рекомендуется KVM-платформа.

*   **Преимущества перед runc:**
    *   Снижение поверхности атаки ядра хоста на ~95% (обращения к ядру хоста идут только через Sentry).
    *   Совместимость с OCI-образами без модификации.
    *   Потребление ~15 МБ RAM на инстанс (vs ~50+ МБ у Kata).

*   **Ограничения:**
    *   Не все POSIX-вызовы реализованы (~30% от Linux API). Приложение может потребовать модификации.
    *   Производительность I/O ниже, чем у runc (дополнительный слой перехвата).
    *   Не поддерживает запуск Docker-in-Docker и некоторых системных утилит.

### 3. WebAssembly (Wasm) и стандарт WASI 0.3
Wasm вышел за пределы браузера, став стандартом для Edge Computing и расширяемости (плагинов).

*   **WASI 0.3 (Preview 3):**
    *   **Асинхронность:** Нативная поддержка асинхронного I/O на уровне спецификации, устраняющая блокировки при работе с сетью.
    *   **Компонентная модель (Component Model):** Возможность вызывать функции одного Wasm-модуля из другого, даже если они написаны на разных языках (например, Rust и Go).
    *   **Песочница (Sandbox):** Модуль имеет доступ только к ресурсам, явно предоставленным через WASI-интерфейсы (filesystem, network, environment variables). Это обеспечивает изоляцию уровня контейнера без ядра Linux.
*   **Оркестрация (SpinKube):** Стек, позволяющий запускать Wasm-нагрузки в Kubernetes как нативные поды. Это обеспечивает «холодный старт» менее 10 мс и плотность размещения в 10–50 раз выше, чем у Docker.
*   **Рантаймы:**
    *   **Wasmtime:** Эталонная реализация от Bytecode Alliance. Поддержка WASI 0.3, компонентной модели и峰值ной производительности.
    *   **WasmEdge:** Оптимизирован для Edge/IoT. Поддержка SIMD и AI-инференса (through TensorFlow Lite).
    *   **Spin (Fermyon):** Фреймворк для serverless Wasm-приложений с встроенной оркестрацией.

## Сравнительная таблица технологий (2026)

| Характеристика | Контейнеры (runc) | Sandbox (gVisor) | MicroVM (Firecracker) | Unikernel (Unikraft) | Wasm (WASI 0.3) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Тип изоляции** | Программная (Kernel) | Программная (User-space kernel) | Аппаратная (VMM) | Аппаратная (VMM) | Программная (Sandbox) |
| **Размер образа** | 100+ МБ | 100+ МБ (OCI-совместимый) | 10–50 МБ | 5–50 МБ | **< 10 МБ** |
| **Холодный старт** | ~200–500 мс | ~200–500 мс | ~25–50 мс (Snapshot) | ~10–20 мс | **< 1 мс** |
| **Потребление RAM** | ~50–200 МБ | ~50–100 МБ | ~20–50 МБ | **< 10 МБ** | < 5 МБ |
| **Портативность** | Высокая | Высокая (OCI) | Средняя (KVM) | Средняя (под платформу) | **Максимальная** |
| **Поверхность атаки ядра** | Полная | ~5% (Sentry) | Минимальная (VMM) | Минимальная | Нет ядра Linux |
| **Совместимость с K8s** | Да (CRI) | Да (CRI) | Да (CRI + RuntimeClass) | Нет (отдельный запуск) | Да (SpinKube) |

## Практические сценарии и инструкции

### 1. Запуск Wasm в Kubernetes (SpinKube)

Для запуска Wasm-модуля необходимо создать `RuntimeClass` и описать под:

```yaml
# 1. Определение RuntimeClass
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: wasmtime-spin
handler: spin

---
# 2. Описание пода
apiVersion: v1
kind: Pod
metadata:
  name: wasm-app
spec:
  runtimeClassName: wasmtime-spin
  containers:
    - name: my-wasm-service
      image: registry.example.com/wasm-app:v1  # OCI-образ с .wasm файлом
```

**Валидация:**
```bash
# Проверка запуска
kubectl get pods -o wide | grep wasm-app
# → wasm-app   1/1   Running   0   5s   10.244.1.5   node-1

# Проверка логов
kubectl logs wasm-app
# → INFO: Wasm app listening on 0.0.0.0:8080
```

### 2. Настройка Kata Containers

В `containerd` конфигурации (`/etc/containerd/config.toml`) прописывается обработчик:

```toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata]
  runtime_type = "io.containerd.kata.v2"
  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata.options]
    ConfigPath = "/etc/kata-containers/configuration.toml"
```

**Проверка:**
```bash
# Перезапуск containerd
sudo systemctl restart containerd

# Проверка доступных рантаймов
crictl info | jq .config.containerd.runtimes
# → { "runc": {...}, "kata": {...} }
```

### 3. Базовый запуск AWS Firecracker (on-premise)

Минимальный пример полного цикла запуска MicroVM:

```bash
# Предварительные требования
# 1. Скачать Firecracker
curl -fsSL -o firecracker https://github.com/firecracker-microvm/firecracker/releases/latest/download/firecracker-v1.7.0-x86_64
chmod +x firecracker

# 2. Подготовить ядро и rootfs
wget https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/kernels/vmlinux-5.10.217
wget https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/rootfs/alpine-ext3.img

# 3. Запуск MicroVM
./firecracker --api-sock /tmp/firecracker.socket &

# 4. Настройка ядра
curl --unix-socket /tmp/firecracker.socket -X PUT \
  "http://localhost/boot-source" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
        "kernel_image_path": "vmlinux-5.10.217",
        "boot_args": "console=ttyS0 reboot=k panic=1 pci=off"
      }'

# 5. Настройка rootfs
curl --unix-socket /tmp/firecracker.socket -X PUT \
  "http://localhost/drives/rootfs" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
        "drive_id": "rootfs",
        "path_on_host": "alpine-ext3.img",
        "is_root_device": true,
        "is_read_only": false
      }'

# 6. Настройка сети (virtio-net)
curl --unix-socket /tmp/firecracker.socket -X PUT \
  "http://localhost/network-interfaces/eth0" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
        "iface_id": "eth0",
        "guest_mac": "AA:FC:00:00:00:01",
        "host_dev_name": "tap0"
      }'

# 7. Запуск
curl --unix-socket /tmp/firecracker.socket -X PUT \
  "http://localhost/actions" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"action_type": "InstanceStart"}'

# 8. Проверка (ожидаем ~25 мс)
time curl --unix-socket /tmp/firecracker.socket \
  "http://localhost/actions" \
  -d '{"action_type": "InstanceStart"}' -X PUT
# → real    0m0.025s
```

**Настройка сети на хосте:**
```bash
# Создание TAP-интерфейса для MicroVM
sudo ip tuntap add tap0 mode tap
sudo ip addr add 172.16.0.1/24 dev tap0
sudo ip link set tap0 up

# Включение IP Forwarding и NAT (для доступа в сеть)
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
sudo iptables -A FORWARD -i tap0 -o eth0 -j ACCEPT
sudo iptables -A FORWARD -i eth0 -o tap0 -m state --state RELATED,ESTABLISHED -j ACCEPT
```

### 4. Настройка gVisor (Sandbox-рантайм)

```bash
# Установка gVisor (runsc)
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
sudo apt update && sudo apt install -y runsc

# Настройка в containerd
cat <<EOF | sudo tee /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
EOF
sudo systemctl restart containerd

# Запуск контейнера с gVisor
docker run --runtime=runsc -it alpine sh
# → Контейнер работает в user-space ядре (Sentry)
```

**Сравнение производительности (Typical Workload):**
| Метрика | runc | gVisor (ptrace) | gVisor (KVM) | Firecracker |
| :--- | :--- | :--- | :--- | :--- |
| Cold Start | ~300 мс | ~350 мс | ~320 мс | ~25 мс |
| RAM overhead | ~5 МБ | ~15 МБ | ~12 МБ | ~20 МБ |
| Syscall latency | ~0.1 мкс | ~1.5 мкс | ~0.8 мкс | ~0.3 мкс |

## Интеграция с CI/CD

### Сборка Wasm-модулей в пайплайне
```yaml
# Пример GitLab CI для сборки Wasm
build-wasm:
  stage: build
  image: rust:1.75
  script:
    - rustup target add wasm32-wasi
    - cargo build --target wasm32-wasi --release
    - wasm-tools validate target/wasm32-wasi/release/my-app.wasm
  artifacts:
    paths:
      - target/wasm32-wasi/release/my-app.wasm

deploy-wasm:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f k8s/wasm-pod.yaml
    - kubectl wait --for=condition=Ready pod/wasm-app --timeout=30s
```

### Сборка MicroVM-образов
```bash
# Сборка Firecracker rootfs в CI
#!/bin/bash
set -euo pipefail

# 1. Скачивание базового образа
curl -fsSL -o rootfs.img https://example.com/base-rootfs-v2.img

# 2. Настройка приложения
mount -o loop rootfs.img /mnt
cp ./my-service /mnt/usr/local/bin/
umount /mnt

# 3. Валидация образа
file rootfs.img
# → rootfs.img: Linux rev 1.0 ext4 filesystem

# 4. Публикация в registry
skopeo copy docker-archive:rootfs.tar docker://registry.example.com/microvm-rootfs:v1
```

## Наблюдаемость (Observability)

### Мониторинг MicroVM на хосте
```bash
# Мониторинг процессов Firecracker
ps aux | grep firecracker | awk '{print $2, $4, $6, $11}'
# → PID RSS(MB) COMMAND

# Через eBPF: мониторинг сетевого трафика MicroVM
sudo bpftrace -e '
kprobe:vhost_net_ioctl {
    printf("vhost_net: pid=%d comm=%s\n", pid, comm);
}'
```

### Логирование
```bash
# Firecracker: перехват console-output
./firecracker --api-sock /tmp/fc.socket 2>&1 | tee /var/log/firecracker.log

# gVisor: логи через runsc
runsc --log=/var/log/gvisor.log --log-format=json run my-container

# Wasm: через WASI stdout
spin up my-app.wasm 2>&1 | tee /var/log/wasm.log
```

### Метрики для Prometheus
```yaml
# Экспортер метрик MicroVM (пример конфигурации)
scrape_configs:
  - job_name: 'microvm-host'
    static_configs:
      - targets: ['host-ip:9100']  # Node Exporter
  - job_name: 'firecracker'
    static_configs:
      - targets: ['host-ip:9101']  # Firecracker metrics endpoint
```

## Стратегии развёртывания

### Blue-Green для MicroVM
```
1. Запуск новой MicroVM (Green) параллельно со старой (Blue)
2. Валидация: curl http://green-ip:8080/health
3. Переключение трафика через bridge/iptables
4. Остановка старой MicroVM
Откат: переключение обратно на Blue
```

### Canary для Wasm
```
1. Запуск canary-модуля (1-5% трафика) через SpinKube
2. Мониторинг error rate и latency p99
3. Постепенное увеличение веса
4. Полный rollout
Откат: удаление canary-подов
```

### Disaster Recovery
- **Firecracker:** Использование snapshot/restore для мгновенного восстановления. RPO: момент снапшота, RTO: ~25 мс.
- **Wasm:** Перезапуск модуля из registry. RPO: 0 (код в Git), RTO: <1 мс.
- **gVisor:** Перезапуск контейнера из OCI-образа. RPO: 0, RTO: ~300 мс.

### Проверка изоляции
```bash
# Wasm: валидация модуля
wasm-tools validate my-module.wasm --features=component-model
# → OK if no error

# Firecracker: проверка что MicroVM изолирована от хоста
# Процесс firecracker не должен иметь доступа к данным других MicroVM
ls -la /proc/$(pgrep firecracker)/fd | grep /tmp/firecracker
# → только собственный socket

# gVisor: проверка что приложение не обращается напрямую к ядру хоста
strace -p $(pgrep -f "runsc") -e trace=network 2>&1 | head -5
# → должен показать только network-вызовы, не fs/io
```

### Тестирование скорости запуска
```bash
# Замер времени от запуска до готовности порта
# MicroVM (Firecracker)
time (
  ./firecracker --api-sock /tmp/fc-test.socket &
  FC_PID=$!
  sleep 0.05  # MicroVM уже должен быть готов
  curl --unix-socket /tmp/fc-test.socket "http://localhost/actions" \
    -d '{"action_type": "InstanceStart"}' -X PUT
  kill $FC_PID 2>/dev/null
)
# → Ожидаемый результат: <50 мс

# Wasm (Spin)
time spin up my-app.wasm 2>/dev/null &
sleep 0.01
curl -s http://localhost:8080/ > /dev/null
# → Ожидаемый результат: <10 мс
```

### Аудит безопасности
```bash
# Проверка seccomp-профиля Firecracker (Jailer)
cat /etc/firecracker/jailer.jail | grep seccomp
# → должен содержать allowed syscalls

# Проверка AppArmor/SELinux для gVisor
aa-status | grep runsc
# → должен показать активный профиль

# Проверка что MicroVM не имеет network access к другим инстансам
# (если настроен bridge с VLAN-isolation)
brctl show | grep virbr0
# → VLAN tagging должен быть настроен
```

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Firecracker: "Failed to open /dev/kvm"** | Отсутствие прав доступа или выключенная виртуализация | Добавить пользователя в группу `kvm` или включить VT-x в BIOS. Проверить: `ls -la /dev/kvm`. |
| **Firecracker: "No such file or directory" (API socket)** | Firecracker процесс не запущен или socket не создан | Убедиться, что процесс firecracker работает: `pgrep firecracker`. Проверить путь к socket. |
| **Wasm: "Link error: function not found"** | Несоответствие версии WASI в модуле и рантайме | Проверить поддержку WASI 0.3 в Wasmtime/WasmEdge: `wasmtime --help | grep wasi`. |
| **Wasm: "Memory allocation failed"** | Ограничение памяти в WASI-модуле | Увеличить лимит через `--wasm max-mem-size` в конфигурации рантайма. |
| **Kata: Тайм-аут при создании пода** | Ошибка загрузки гостевого ядра или агента | Проверить логи `kata-runtime` и наличие образа `guest-kernel`. Убедиться, что `ConfigPath` указывает на существующий файл. |
| **Kata: "Failed to mount"** | Несовместимость файловой системы гостя | Проверить, что rootfs отформатирован в ext4 (рекомендуется для Kata). |
| **gVisor: "Too many open files"** | Лимит файловых дескрипторов в Sentry | Увеличить `nofile` ulimit для процесса runsc: `ulimit -n 65536`. |
| **gVisor: "Permission denied" на /proc** | Ограничения Filesystem в gVisor | gVisor не монтирует /proc полностью. Используйте `--file-access=exclusive` для полного доступа. |
| **Низкая плотность Wasm в K8s** | Неправильные лимиты (Resources) в манифесте | Уменьшить `resources.requests.memory` до 2-4 Mi, так как Wasm потребляет на порядок меньше контейнера. |
| **Firecracker: сетевой трафик не маршрутизируется** | Отсутствие NAT или bridge-интерфейса | Настроить IP forwarding и iptables на хосте (см. раздел "Настройка сети" выше). |
| **Kata: высокий overhead по RAM** | Слишком большой лимит памяти для гостя | Уменьшить `default_memory` в `configuration.toml` (рекомендуется 128–256 МБ для типичных контейнеров). |

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md) — базовые концепции и определения.
- [Альтернативные среды выполнения](../../Docker/alternative_runtimes_and_tools.md) — каталог OCI-rantаймов (runc, crun, gVisor, Kata).
- [Container Runtime в Kubernetes](../../Kubernetes/Concepts/container_runtime.md) — архитектура CRI и выбор рантайма.

### Ссылки
- [Firecracker Documentation](https://firecracker-microvm.github.io/) — официальная документация.
- [gVisor Documentation](https://gvisor.dev/docs/) — архитектура и руководство по использованию.
- [Wasmtime Runtime](https://wasmtime.dev/) — быстрый и безопасный рантайм для Wasm.
- [SpinKube Project](https://www.spinkube.dev/) — оркестрация Wasm в Kubernetes.
- [WASI Preview 3 Specs](https://wasi.dev/) — спецификации асинхронного Wasm.
