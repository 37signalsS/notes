# Популярные Unikernel-проекты

## Определения

В этом документе представлены основные фреймворки и реализации **юникернелов** (unikernels), актуальные на 2026 год. Описаны их ключевые характеристики, статус разработки и приведены практические фрагменты кода для старта.

Базовые концепции технологии (Library OS, изоляция) описаны в [Обзоре Unikernel](./unikernel_overview.md).

## Требования для реализации

Для on-premise развёртывания юникернелов необходима следующая инфраструктура:
- **Гипервизор:** KVM/QEMU (наиболее универсальный), Xen (для MirageOS) или AWS Firecracker (для автоматизации).
- **Аппаратная поддержка:** Процессор с инструкциями виртуализации (Intel VT-x / AMD-V). Проверка: `egrep -c '(vmx|svm)' /proc/cpuinfo` (ожидаем ≥1).
- **Инструментарий хоста:**
  - Доступ к `/dev/kvm` (группа `kvm` или root).
  - Утилиты сборки: `gcc`, `make`, `cmake`, `ninja` (в зависимости от проекта).
  - `rustc` и `cargo` (для Unikraft, Firecracker).
  - `dune` и `opam` (для MirageOS).
- **Сетевая конфигурация:** Поддержка TAP-интерфейсов или сетевых мостов (Bridge) для связи с внешним миром. Настройка NAT: `sudo sysctl -w net.ipv4.ip_forward=1` + `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE`.

## Основные концепции выбора фреймворка

При выборе инструмента в 2026 году следует ориентироваться на следующие параметры:

*   **Язык разработки:** OCaml (MirageOS), C/C++ (Unikraft, OSv) или поддержка любого языка через бинарную совместимость (Nanos).
*   **Безопасность:** Наличие ASLR (экспериментально в OSv, нативно в Unikraft), W^X (Write XOR Execute) и механизмов типа **Network Shield**.
*   **Поддержка оборудования:** Требуется ли доступ к GPU (Nanos) или работа на архитектурах ARM64/Apple Silicon.
*   **Размер образа:** От 1 МБ (MirageOS) до 50 МБ (Nanos с GPU-библиотеками).
*   **Совместимость:** Уровень поддержки POSIX и возможность запуска немодифицированных Linux ELF бинарников.
*   **On-premise развёртывание:** Наличие готовых инструментов для локальной сборки и запуска (Unikraft `kraft`, Nanos `ops`, OSv `run`) без привязки к облачным платформам.
*   **CI/CD:** Возможность автоматической сборки в пайплайне (GitLab CI, GitHub Actions) и публикации образов в локальный registry.

### Сводная таблица проектов (2026)

| Проект | Язык / Совместимость | Статус | Размер | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| **Unikraft** | C / POSIX (модульный) | Активен (v11+) | ~1-5 МБ | Релиз Metis: снапшоты, клонирование, модульность |
| **Nanos/Ops** | Любой / Binary comp. | Активен | ~5-15 МБ | **Native GPU**, ARM64, Inception speedup |
| **MirageOS** | OCaml / Clean-slate | Активен (v4.5) | ~1-2 МБ | Поддержка **OCaml 5** (Multicore/Effects) |
| **OSv** | C++ / POSIX | Стабилен | ~10-20 МБ | Оптимизирован для JVM; ASLR (Exp. 2026) |
| **IncludeOS** | C++ / Минимальная | Legacy | ~5-10 МБ | Проект практически не обновляется |
| **Rumprun** | C / POSIX | Legacy | ~5-15 МБ | Использует драйверы NetBSD |

## Практические сценарии использования

### 1. Unikraft (Linux Foundation)
В 2026 году релиз 11 «Metis» превратил Unikraft в полноценную платформу для распределенных вычислений и ephemeral-нагрузок.

*   **Ключевые фичи Metis:**
    *   **Instance Branching:** Клонирование запущенной микро-ВМ за миллисекунды.
    *   **Snapshots:** Мгновенные слепки состояния системы для отката или горизонтального масштабирования.
    *   **Модульность:** Возможность включения/отключения компонентов (сеть, FS, драйверы) на этапе сборки.
*   **On-premise сборка и запуск:**
    ```bash
    # Установка kraft (Linux/macOS)
    curl -sSf https://get.kraftkit.sh | bash

    # Инициализация проекта (Python)
    kraft init -p python3 my-service

    # Конфигурация (kraft.yaml — спецификация v0.6)
    cat <<EOF > kraft.yaml
    spec: v0.6
    name: my-service
    unikraft: v0.17.0
    targets:
      - name: qemu
        arch: x86_64
        platform: qemu
    libraries:
      - name: python3
        version: latest
    networks:
      - name: bridge0
    EOF

    # Сборка (создание ELF-бинарника)
    kraft build --target qemu --arch x86_64

    # Запуск on-premise (QEMU + KVM)
    kraft run --headless --background -p 8080:80

    # Проверка
    curl http://localhost:8080
    # → Hello from Unikraft!
    ```

*   **Управление через CLI:**
    ```bash
    # Создание снапшота (локально)
    kraft snapshot create app-v1 --name app-snapshot-v1

    # Клонирование из снапшота
    kraft run --snapshot app-snapshot-v1 --name app-clone-1 -p 8081:80

    # Остановка
    kraft stop app-clone-1

    # Проверка размера образа
    kraft image list --json | jq '.[] | {name: .name, size: .size}'
    ```

*   **Сборка из существующего кода:**
    ```bash
    # Клонирование репозитория с приложением
    git clone https://github.com/myorg/my-service
    cd my-service

    # Создание минимального Kraftfile
    cat <<EOF > Kraftfile
    name: my-service
    unikraft: v0.17.0
    targets:
      - name: qemu
        arch: x86_64
    libraries:
      - name: musl
        version: latest
    EOF

    # Сборка и запуск
    kraft build
    kraft run --headless --background -p 9090:8080
    ```

### 2. Nanos / OPS
Лидер в области запуска существующих бинарных файлов без перекомпиляции. Идеален для on-premise развёртывания legacy-приложений.

*   **Ключевые особенности:**
    *   **Бинарная совместимость:** Запуск немодифицированных Linux ELF-бинарников (Go, Python, Node.js, Java) без пересборки.
    *   **GPU Support:** Единственный юникернел с нативной поддержкой NVIDIA GPU через `gpu_nvidia` klib.
    *   **ARM64/Apple Silicon:** Полная поддержка архитектуры ARM64 для edge-устройств.
*   **On-premise установка и запуск:**
    ```bash
    # Установка OPS (Linux/macOS)
    curl -fsSL https://releases.nanovms.com/ops/ops-latest | tar -xzf -
    sudo mv ops /usr/local/bin/

    # Скачивание ядра Nanos
    ops kernel get latest

    # Запуск стандартного Linux-бинарника
    ops run -p 8080 ./my-app

    # Проверка
    curl http://localhost:8080
    ```

*   **Конфигурация (`config.json`):**
    ```json
    {
      "RunConfig": {
        "Ports": ["8080:80"],
        "Memory": "512M",
        "CPUs": 2,
        "Klibs": ["nfs"]
      },
      "BaseVolumeUuid": "22b1e7a8-5e0e-4b0c-8b5a-1e0c5e8b2a1f",
      "DisableKvmInBoot": false
    }
    ```

*   **Запуск с Docker-образа:**
    ```bash
    # Конвертация Docker-образа в Unikernel
    ops pkg from docker nginx:latest -a amd64

    # Запуск конвертированного образа
    ops run nginx:latest -p 8080:80
    ```

*   **On-premise networking (bridge + NAT):**
    ```bash
    # Создание TAP-интерфейса
    sudo ip tuntap add tap0 mode tap
    sudo ip addr add 10.0.0.1/24 dev tap0
    sudo ip link set tap0 up

    # Конфигурация OPS для использования tap0
    cat <<EOF > /etc/ops/ops.conf
    {
      "Network": {
        "Type": "tap",
        "Tap": "tap0"
      }
    }
    EOF

    # Запуск с указанием сети
    ops run -p 8080 --net tap0 ./my-app
    ```

*   **Проверка совместимости бинарника:**
    ```bash
    # Проверка всех системных вызовов
    ops run -i ./my-app 2>&1 | grep -i "syscall"
    # → Если ошибок нет, бинарник совместим
    ```

### 3. MirageOS
Современная версия 4.5 полностью совместима с **OCaml 5**, ориентирована на максимальную безопасность (Clean-slate).

*   **Effects-based Concurrency:** Использование библиотеки `Eio` позволяет писать высокопроизводительный асинхронный код без использования сложных монад (Lwt).
*   **Multicore:** Нативная поддержка многоядерности обеспечивает масштабирование сетевых приложений на современных CPU.
*   **Пример (OCaml 5 / Eio):**
    ```ocaml
    (* Использование прямых эффектов вместо Lwt.bind *)
    let main ~net =
      Eio.Net.listen net ~port:8080 @@ fun socket ->
        (* Логика обработки соединений *)
    ```

*   **On-premise установка и сборка:**
    ```bash
    # Установка OCaml и инструментов
    # Ubuntu/Debian
    sudo apt install ocaml dune opam
    opam init --bare --no-setup

    # Клонирование шаблона MirageOS
    git clone https://github.com/mirage/mirage-skeleton.git
    cd mirage-skeleton

    # Сборка unikernel (консоль-приложение)
    mirage configure -t hvt  # или -t unix для отладки
    make depend
    make

    # Запуск через QEMU/HVT
    mirage-boot-from-ssh hvt  # или через solo5-hvt
    ```

*   **Целевые платформы:**
    ```bash
    # Для Xen (продакшн)
    mirage configure -t xen
    make
    xl create config.xl

    # Для Unix (отладка)
    mirage configure -t unix
    make
    ./mir-middle  # Запуск как обычный процесс
    ```

*   **Безопасность:**
    *   **Формальная верификация:** Возможность верификации кода с помощью工具ов типа Coq.
    *   **Минимальная TCB:** Только ~5000 строк кода ядра, что упрощает аудит.

### 4. OSv
Остается лучшим выбором для запуска legacy Java-приложений и баз данных (Cassandra, ScyllaDB) в on-premise среде.

*   **Безопасность (2026):** Внедрение патчей ASLR для рандомизации базы приложения и стека значительно повысило устойчивость к эксплойтам.
*   **JVM:** Бесшовная поддержка OpenJDK 17/21/25 с оптимизацией ZGC.
*   **On-premise установка и запуск:**
    ```bash
    # Скачивание готового образа OSv
    wget https://github.com/cloudius-systems/osv/releases/latest/download/osv.qcow2

    # Запуск JVM-приложения через QEMU
    qemu-system-x86_64 \
      -m 2048 \
      -drive file=osv.qcow2,if=virtio \
      -netdev user,id=net0,hostfwd=tcp::8080-:80 \
      -device virtio-net-pci,netdev=net0 \
      -nographic

    # Внутри OSv shell
    run /path/to/my-java-app.jar
    ```

*   **Конфигурация для Cassandra:**
    ```bash
    # Конфигурация для запуска Cassandra
    qemu-system-x86_64 \
      -m 8192 \
      -smp 4 \
      -drive file=osv.qcow2,if=virtio \
      -netdev user,id=net0,hostfwd=tcp::9042-:9042 \
      -device virtio-net-pci,netdev=net0 \
      -nographic

    # Внутри OSv
    run /opt/cassandra/bin/cassandra -R
    ```

*   **POSIX-совместимость:** OSv реализует большинство POSIX-вызовов, что позволяет запускать немодифицированные Linux-приложения. Проверка совместимости:
    ```bash
    # Проверка реализованных системных вызовов
    strace -e trace=file ./my-app 2>&1 | head -20
    # → Показывает только те вызовы, которые реализованы в OSv
    ```

## Валидация и проверка работоспособности

### Проверка образа перед развёртыванием
```bash
# Unikraft: проверка размера и состава образа
kraft image list --json | jq '.[] | {name: .name, size: .size, libs: .libraries}'
# → { "name": "my-service", "size": 8388608, "libs": ["python3", "musl"] }

# Nanos: проверка ELF-бинарника
file ./my-app
# → ELF 64-bit LSB executable, x86-64, dynamically linked

# MirageOS: проверка конфигурации
cat _build/config.ml  # Проверка целевой платформы
```

### Тестирование производительности
```bash
# Замер времени холодного старта
time ./my-unikernel 2>/dev/null &
sleep 0.05
curl -s http://localhost:8080/ > /dev/null
# → Ожидаемый результат: <50 мс (Unikraft/Nanos), <100 мс (OSv)

# Проверка потребления RAM
ps aux | grep -E "qemu|firecracker" | awk '{print $6/1024 " MB", $11}'
# → Должно быть <50 МБ для большинства юникернелов

# Замер сетевой задержки
ping -c 100 10.0.0.2 | tail -1
# → rtt min/avg/max м / 1000 < 1.0 мс для loopback
```

### Проверка изоляции
```bash
# Юникернел не должен иметь доступа к данным других инстансов
# (проверка что /dev/kvm доступен только одному процессу)
ls -la /dev/kvm
# → crw-rw---- 1 root kvm 10, 232 ...

# Проверка что юникернел не может изменить конфигурацию хоста
# (внутри юникернела не должно быть шелла)
ssh root@10.0.0.2 2>&1
# → Connection refused (нет SSH-сервера)
```

## Интеграция с CI/CD

### GitLab CI: сборка Unikraft
```yaml
build-unikernel:
  stage: build
  image: unikraft/kraft:latest
  script:
    - kraft build --target qemu --arch x86_64 --log-level debug
  artifacts:
    paths:
      - .build/

deploy-unikernel:
  stage: deploy
  image: alpine:latest
  script:
    - apk add --no-cache qemu-system-x86
    - qemu-system-x86_64 -m 256 -nographic -drive file=.build/app.qcow2,if=virtio &
    - sleep 0.1
    - curl -f http://localhost:8080/health || exit 1
```

### GitHub Actions: сборка Nanos
```yaml
name: Build Nanos Unikernel
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install OPS
        run: |
          curl -fsSL https://releases.nanovms.com/ops/ops-latest | tar -xzf -
          sudo mv ops /usr/local/bin/
      - name: Build Unikernel
        run: ops build -c config.json ./my-app
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: unikernel-image
          path: /tmp/ops/
```

## Мониторинг и наблюдаемость

### Сбор метрик с хоста (еBPF)
```bash
# Мониторинг сетевого трафика юникернела
sudo bpftrace -e '
kprobe:virtio_net_rx {
    printf("virtio_rx: %s\n", comm);
}'
```

### Логирование через гипервизор
```bash
# Unikraft: перехват console-output
kraft run --headless --background -p 8080:80 2>&1 | tee /var/log/unikraft.log

# Nanos: логи через OPS
ops run -p 8080 ./my-app 2>&1 | tee /var/log/nanos.log

# OSv: логи через QEMU
qemu-system-x86_64 ... -serial file:/var/log/osv.log
```

### Prometheus: метрики хоста
```yaml
scrape_configs:
  - job_name: 'unikernel-host'
    static_configs:
      - targets: ['host-ip:9100']  # Node Exporter
  - job_name: 'qemu-unikernel'
    static_configs:
      - targets: ['host-ip:9090']  # QEMU metrics endpoint
```

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"Operation not permitted" в OPS** | Недостаточно прав для KVM | Проверьте права на `/dev/kvm` или запустите с `sudo`. |
| **MirageOS: ошибка сетевой линковки** | Несовпадение версии Xen/KVM драйвера | Проверьте целевую платформу (target) в `dune` конфигурации. |
| **Unikraft: нехватка памяти при сборке** | Сложная конфигурация требует много RAM | Увеличьте лимит памяти для процесса сборки или используйте `--log-level debug`. |
| **OSv: JVM не стартует** | Неверный путь к `JAVA_HOME` внутри образа | Укажите абсолютные пути в манифесте сборки. |
| **Unikraft: "Kernel Panic при загрузке"** | Несоответствие драйвера гипервизора (Virtio) | Проверить флаги компиляции и поддержку гипервизора в `kraft.yaml`. |
| **Nanos: "binary not compatible"** | Бинарник использует нереализованные syscall | Проверить через `ops run -i` и заменить недоступные вызовы. |
| **OSv: высокое потребление RAM** | Включены отладочные символы | Пересобрать с флагами Release (strip symbols). |
| **Все проекты: тайм-аут сети** | Не подключен модуль стека протоколов | Убедиться, что библиотеки типа `lib-lwip` включены в сборку. |

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md) — базовые концепции и определения.
- [Преимущества и ограничения](./unikernel_advantages_disadvantages.md) — подробный разбор безопасности и Ops.
- [Инструменты и будущее](./tools_future.md) — сравнение с Wasm и Firecracker.
- [Сценарии использования](./use_cases.md) — практические примеры DevOps/SRE.

### Ссылки
- [Unikraft Documentation](https://unikraft.org/docs/) — официальная документация.
- [Nanos / OPS](https://nanos.org/) — руководство по эксплуатации.
- [MirageOS](https://mirage.io/) — официальный портал.
- [OSv Project](https://osv.io/) — документация и примеры.
- [eBPF для наблюдаемости](../../Kubernetes/Networking/Network/CNI/ebpf.md) — мониторинг юникернелов через eBPF.
- [OpenTelemetry: Инструментация](../../OpenTelemetry/instrumentation_sdk.md) — отправка метрик из юникернелов.
