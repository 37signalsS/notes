# Укрепление безопасности контейнеров (Hardening)

**Актуально для:** Docker Engine 29.x. Linux (ядро 5.4+ с поддержкой user namespaces и cgroups v2).

Данный документ описывает комплекс мер по минимизации поверхности атаки и усилению изоляции запущенных контейнеров на уровне среды выполнения (**runtime**).

## Предварительные требования

- **Docker Engine 29.x** с включённой поддержкой cgroups v2 (включено по умолчанию начиная с Docker 20.10).
- **Linux** с включёнными user namespaces: `sysctl user.max_user_namespaces > 0` или `kernel.unprivileged_userns_clone=1`.
- **LSM-подсистема:** AppArmor (Ubuntu/Debian) или SELinux (RHEL/CentOS/Fedora) — включена и активна на хосте.
- **Пакет `uidmap`:** содержит `newuidmap` и `newgidmap`, необходимые для rootless Docker и userns-remap.
- **Файлы `/etc/subuid` и `/etc/subgid`:** каждому пользователю, запускающему rootless Docker, назначен диапазон из минимум 65 536 подчинённых UID/GID.
- **`util-linux`:** для `setpriv` (применяется в SSH-agent hardening‑сценариях, см. [SSH-agent в rootless Docker](./ssh-agent-rootless.md)).
- **OpenSSH 9.x+:** для работы ssh-agent и передачи сокета в контейнеры.

## Определения

**Укрепление контейнеров (Container Hardening)** — процесс снижения рисков компрометации путем применения защитных конфигураций, ограничивающих возможности процессов внутри контейнера и их доступ к ресурсам ядра хоста.

**Принцип наименьших привилегий (Principle of Least Privilege)** — архитектурный подход, при котором процессу предоставляется минимально необходимый набор прав (Capabilities, доступ к ФС, сетевые доступы) для выполнения его функций.

**Поверхность атаки (Attack Surface)** — совокупность всех доступных точек взаимодействия (системные вызовы, открытые порты, примонтированные файлы), которые могут быть использованы злоумышленником для взлома.

**Sandboxed Runtimes** — дополнительные уровни изоляции (gVisor, Kata Containers), которые создают более жёсткую границу между контейнером и ядром хоста по сравнению со стандартным `runc`.

**Seccomp (Secure Computing Mode)** — механизм ядра Linux, позволяющий фильтровать системные вызовы. В Docker по умолчанию применяется профиль `docker-default`, который блокирует около 44 потенциально опасных вызовов (например, `mount`, `reboot`, `ptrace`, `kexec_load`).

**LSM (Linux Security Modules)** — подсистемы ядра, обеспечивающие мандатный контроль доступа (MAC). AppArmor (Ubuntu/Debian) и SELinux (RHEL/CentOS) ограничивают действия процессов на основе политик, даже если процесс запущен от `root`.

## Базовые концепции

Безопасность контейнеров в Linux строится на многоуровневой изоляции, предоставляемой ядром. В 2026 году основой является использование **Cgroups v2** и **User Namespaces**.

1. **Namespaces (Пространства имён):** Обеспечивают логическую изоляцию ресурсов. **User Namespaces** критичны для Hardening, так как позволяют маппить UID 0 (root) контейнера на непривилегированного пользователя хоста, предотвращая "побег" с правами суперпользователя. Подробнее: [**Изоляция контейнеров: Namespaces и Cgroups**](../../Docker/Concepts/linux_isolation.md).
2. **Cgroups v2 (Control Groups):** В 2026 году это стандарт по умолчанию. Позволяют жёстко ограничивать потребление CPU, RAM и I/O. Важнейшим параметром для защиты от DoS‑атак является `pids-limit` (защита от fork‑бомб).
3. **Linux Capabilities:** Разделяют монолитные права `root` на мелкие привилегии. Docker по умолчанию оставляет около 14 возможностей. Большинство атак на контейнеры начинаются с эксплуатации избыточных прав (например, `CAP_SYS_ADMIN`). Подробнее: [**Linux Capabilities**](../../Linux/Security/Mechanisms/Capabilities.md).
4. **LSM (Linux Security Modules):** Системы принудительного контроля доступа (MAC). **AppArmor** (Ubuntu/Debian) и **SELinux** (RHEL/CentOS) ограничивают действия процессов (доступ к файлам, сокетам) даже если процесс запущен от root.

### Влияние харденинга ядра хоста

Настройки безопасности хостовой ОС (см. [**Харденинг ядра Linux**](../../Linux/Security/Mechanisms/Kernel/hardening.md)) напрямую влияют на возможности контейнеров:

*   **Ограничение User Namespaces:** Установка `user.max_user_namespaces=0` на хосте ломает **Rootless Docker** и **Podman**.
*   **Блокировка eBPF:** Параметр `kernel.unprivileged_bpf_disabled=1` требует предоставления контейнеру `CAP_SYS_ADMIN` или `CAP_BPF` для работы инструментов мониторинга (Falco) или сетевых плагинов (Cilium).
*   **Скрытие адресов ядра:** `kernel.kptr_restrict=2` мешает инструментам безопасности на базе eBPF корректно сопоставлять события с функциями ядра.

### Регуляторные требования: шесть доменов защиты ФСТЭК (РФ, 2025)

Для соответствия требованиям Информационного сообщения ФСТЭК от 13.01.2025, харденинг должен покрывать шесть ключевых доменов:

1.  **Классификация:** Разделение на Runtime (сертификация по 118 приказу) и App (сертификация на функции безопасности).
2.  **Инвентаризация:** Обязательный SBOM в формате CycloneDX 1.6+ с разметкой поверхности атаки.
3.  **Контроль целостности:** Проверка образов и ELF‑файлов в runtime или при установке (например, через `gostsum`).
4.  **Совместимость:** Использование сертифицированных базовых образов и подтверждение работы функций безопасности в заявленных средах.
5.  **Минимизация привилегий:** Использование принципа "Drop All" для Capabilities и запрет избыточных прав.
6.  **Управление доступом:** Настройка изоляции на уровне компонентов (RBAC), хоста (Namespaces, Seccomp) и периметра (NetworkPolicies).

Подробнее: **[Сертификация ФСТЭК для контейнеров](../../Linux/Security/Fstec/container_certification.md)**.

## Практические сценарии

### 1. Управление привилегиями (Capabilities)

Docker по умолчанию оставляет около 14 возможностей. Безопасный паттерн 2026 года — **"Drop All" подход**: сбросить всё и добавлять только явно обоснованные права.

```bash
# Сброс всех прав и добавление только возможности биндинга портов < 1024
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE my-app
```

*   **Обоснование:** Любая добавленная Capability должна пройти через архитектурный комитет или быть подтверждена документацией вендора (например, Red Hat или официальные доклады).
*   **Запрет `--privileged`:** Этот флаг отключает Seccomp, AppArmor и предоставляет все Capabilities. **Категорически запрещён в Production**, за исключением редких инфраструктурных задач (например, запуск узла Kubernetes внутри Docker).
*   **Запрет повышения прав:** Флаг `no-new-privileges` блокирует получение дополнительных прав дочерними процессами через SUID/SGID бинарники (например, `sudo`).
  ```bash
  docker run --security-opt=no-new-privileges my-app
  ```

### 2. Фильтрация системных вызовов (Seccomp)

Seccomp‑профиль Docker по умолчанию блокирует около 44 опасных вызовов (например, `mount`, `reboot`, `ptrace`).

```bash
# Запуск с кастомным профилем (например, для приложения, которому не нужен execve)
docker run --security-opt seccomp=/path/to/custom-profile.json my-app
```

*   **Рекомендация:** Всегда используйте `RuntimeDefault` (в K8s) или стандартный профиль Docker. Отключение seccomp (`unconfined`) резко расширяет поверхность атаки на ядро.
*   Подробнее: [**Seccomp в Linux**](../../Linux/Security/Mechanisms/Seccomp.md).

### 3. Изоляция файловой системы

Режим **Read-Only Root FS** является самым эффективным способом борьбы с закреплением злоумышленника в системе (установка бэкдоров, майнеров).

```bash
docker run \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid \
  --tmpfs /run:rw,noexec,nosuid \
  my-app
```

*   **`--tmpfs`:** Позволяет приложению писать временные данные в RAM без записи на диск хоста. Флаг `noexec` запрещает выполнение файлов из этих директорий.
*   **Bind Mounts:** При использовании монтирований с хоста всегда добавляйте флаг `:ro`, если приложению не нужна запись.
    ```bash
    docker run -v /host/config:/app/config:ro my-app
    ```

### 4. Ограничение ресурсов (Cgroups v2)

Лимиты предотвращают DoS‑атаки, при которых один скомпрометированный контейнер «вешает» весь хост.

```bash
docker run \
  --memory="512m" \
  --memory-swap="512m" \
  --cpus="0.5" \
  --pids-limit 100 \
  --ulimit nofile=1024:2048 \
  my-app
```

*   **`pids-limit`:** Ограничение количества процессов/потоков внутри контейнера. Защищает от fork‑бомб.
*   **`memory-swap`:** Установка в то же значение, что и `--memory`, отключает использование свопа, что делает производительность предсказуемой и защищает от утечек памяти.
*   **`--ulimit nofile`:** Ограничение количества открытых файловых дескрипторов процессом.

### 5. Sandboxed Runtimes (Повышенная изоляция)

В средах с повышенными требованиями к безопасности (Multi‑tenancy) стандартного `runc` недостаточно.

| Runtime | Механизм изоляции | Overhead | Когда применять |
| :--- | :--- | :--- | :--- |
| **runc** (default) | Namespaces + capabilities | Базовый | Доверенные образы, стандартные сервисы |
| **gVisor (`runsc`)** | Ядро в пространстве пользователя: перехват syscall'ов внутри песочницы (Sentry), без прямого обращения к ядру хоста | ~5–15% CPU, +30–50 МБ RAM на контейнер | Untrusted код, multi-tenancy |
| **Kata Containers** | Микро-VM (QEMU/Cloud-Hypervisor): аппаратная изоляция через гипервизор | Высокий (запуск ~секунды, память VM) | Строгая изоляция, требования compliance |
| **Sysbox** | Улучшенные namespaces: поддержка systemd, Docker-in-Docker без `--privileged` | Низкий, близок к runc | Нестандартные workload (systemd, k8s-in-Docker) |

```bash
# Запуск контейнера через gVisor (если рантайм настроен в daemon.json)
docker run --runtime=runsc my-app
```

*   **gVisor (`runsc`):** Ядро в пространстве пользователя. Перехватывает системные вызовы и обрабатывает их внутри песочницы, не обращаясь напрямую к ядру хоста. Идеально для untrusted кода.
*   **Kata Containers:** Контейнеры в микро‑виртуальных машинах (QEMU/Cloud‑Hypervisor). Обеспечивают аппаратную изоляцию.

Настройка рантаймов в `daemon.json`, сравнение runc/crun/containerd и детали по Kata/gVisor/Sysbox — в **[Альтернативные среды выполнения](../alternative_runtimes_and_tools.md)**. Производительность gVisor — в **[Container runtime security (K8s)](../../Kubernetes/Security/container_runtime_security.md)**.

## Устранение неполадок

### Аудит и проверка конфигурации

Для проверки текущих настроек безопасности запущенного контейнера:

```bash
docker inspect <container_id> --format='{{json .HostConfig.SecurityOpt}}'
```

**Проверка отдельных параметров:**

```bash
# Проверка capabilities (должен быть CapDrop=ALL, CapAdd=NET_BIND_SERVICE)
docker inspect <container_id> --format='{{json .HostConfig.CapAdd}}'
docker inspect <container_id> --format='{{json .HostConfig.CapDrop}}'
# → ["ALL"], ["NET_BIND_SERVICE"]

# Проверка read-only rootfs
docker inspect <container_id> --format='{{.HostConfig.ReadonlyRootfs}}'
# → true

# Проверка Seccomp
docker inspect <container_id> --format='{{json .HostConfig.SecurityOpt}}'
# → ["seccomp=..." ]

# Проверка resource limits
docker stats <container_id> --no-stream
# → MEM USAGE, PIDS, CPU %
```

### Типичные ошибки и решения

* **Ошибка: `operation not permitted` при `--cap-drop=ALL`**
    * **Причина:** Приложение требует capability, не включённую в явный `--cap-add`.
    * **Решение:** Запустите без `--cap-drop=ALL`, изучите `docker inspect` для определения нужного capability, добавьте его конкретно.

* **Ошибка: `cannot enable seccomp override: ...`**
    * **Причина:** Кастомный seccomp‑профиль содержит синтаксическую ошибку или ссылается на несуществующие syscall.
    * **Решение:** Валидируйте JSON через `jq` и проверяйте наличие syscall через `grep 'SYS_' /usr/include/asm/unistd_64.h`.

* **Ошибка: `permission denied` при bind mount:**
    * **Причина:** SELinux/AppArmor блокирует доступ к смонтированному пути.
    * **Решение:** Добавьте `:Z` (SELinux relabel) или `:ro` к bind mount, либо настройте AppArmor‑профиль для контейнера.

* **Ошибка: `overlayfs` не поддерживается с `userns-remap`**
    * **Причина:** Некоторые ядра не позволяют использовать `overlay2` с user namespaces.
    * **Решение:** Переключитесь на `fuse-overlayfs` или `vfs` в `daemon.json`.

* **Ошибка: контейнер не запускается с `--read-only`**
    * **Причина:** Приложение пытается писать во встроенную ФС (например, `/tmp`, `/var/log`).
    * **Решение:** Добавьте `--tmpfs` для нужных директорий или используйте named volumes.

## Лучшие практики

1.  **Drop All Capabilities:** Всегда используйте `--cap-drop=ALL`, добавляйте только необходимые capabilities через `--cap-add`. Никогда не используйте `--privileged` в production.
2.  **Read-Only Root FS:** Запускайте контейнеры с `--read-only`, используйте `--tmpfs` для временных директорий (`/tmp`, `/run`) и named volumes для данных.
3.  **Seccomp по умолчанию:** Оставляйте стандартный профиль Docker или используйте `RuntimeDefault` в Kubernetes. Никогда не выключайте seccomp (`--security-opt seccomp=unconfined`) без строгой необходимости.
4.  **No-new-privileges:** Добавляйте `--security-opt=no-new-privileges` для предотвращения SUID/SGID‑атак.
5.  **Resource Limits:** Устанавливайте `--memory`, `--cpus`, `--pids-limit` и `--ulimit` для предотвращения DoS‑атак.
6.  **LSM‑профили:** Используйте профили AppArmor или SELinux для дополнительного уровня изоляции. Docker применяет `docker-default` (AppArmor) и `container_t` (SELinux) по умолчанию.
7.  **Минимизация образа:** Используйте distroless‑образы или `scratch` для снижения числа syscall и файлов в контейнере.
8.  **Не запускайте от root:** Используйте `--user` с non‑root UID. Приложения, требующие портов < 1024, используют `CAP_NET_BIND_SERVICE`.
9.  **Регулярный аудит:** Используйте `docker bench --check` или Trivy для периодической проверки конфигурации на соответствие CIS Benchmark.
10. **Non‑Root SSH-agent:** При передаче ssh‑агента в контейнер используйте `setpriv` с `--clear-groups --inh-caps=-all --no-new-privileges` и передавайте только сокет, не ключ. См. **[SSH-agent в rootless Docker](./ssh-agent-rootless.md)**.

## Граничные случаи и ограничения

* **Размер ключей и сертификатов:** Стандартные образы `alpine` и `busybox` не содержат CA‑bundle. Если контейнеру нужен TLS‑клиент, добавляйте `ca-certificates` или монтируйте `/etc/ssl/certs:ro`.
* **Rootless + `--user`:** В rootless режиме `--user 0` внутри контейнера маппится на реального пользователя хоста. Если приложению требуется настоящий root внутри контейнера, rootless не подходит.
* **SELinux и контекст меток:** При включённом SELinux дополнительная метка контекста может блокировать доступ к сокету или bind mount. Проверяйте `ls -lZ` на хосте и используйте `:Z` или `--security-opt label=disabled` при необходимости.
* **systemd в контейнерах:** Запуск `systemd` внутри контейнера требует `--privileged` и `--tmpfs /run`, что противоречит харденингу. Для systemd‑based workload используйте Podman или Kubernetes с `init: true`.
* **Windows/macOS:** Rootless Docker недоступен на этих платформах. Используйте встроенную функцию SSH‑agent forwarding в Docker Desktop (настройки → Resources → SSH Agent).
* **AppArmor на плоских образах:** Если базовый образ не содержит AppArmor‑профиль, Docker не применяет `docker-default`. Проверьте наличие профиля через `docker info | grep -i apparmor`.

## Дополнительная информация

### Инструменты

* **Docker Bench for Security:** Скрипт для проверки соответствия CIS Docker Benchmark.
* **Trivy:** Сканирование образов и конфигураций (IaC).
* **Inspektor Gadget:** Трассировка и аудит через eBPF.

### Связанные документы

- **[Безопасность в Dockerfile](../Dockerfile/Docker_best_practices/security.md)** — практики на этапе сборки.
- **[Сертификация ФСТЭК для контейнеров](../../Linux/Security/Fstec/container_certification.md)** — регуляторные требования к архитектуре и рантайму.
- **[Защита хоста и демона](./host_daemon_hardening.md)** — Rootless режим и настройка демона.
- **[SSH-agent в rootless Docker без экспозиции приватного ключа](./ssh-agent-rootless.md)** — безопасная передача сокета ssh-agent в контейнер.
- **[Механизмы безопасности Linux](../../Linux/Security/Linux_Security_Mechanisms_Overview.md)** — обзор Seccomp, AppArmor и SELinux.
- **[Мониторинг в Runtime](./runtime_monitoring.md)** — обнаружение аномалий (Falco, Tetragon).
- **[Пользовательские профили безопасности](./custom_security_profiles.md)** — кастомные AppArmor/SELinux/seccomp-профили для контейнеров.
- **[CVE побегов из контейнеров](./container_escape_cves.md)** — почему харденинг не заменяет патчинг рантайма.

### Глубокое изучение

- **[Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md)** — полный справочник всех capabilities, bounding set, ambient capabilities. В Docker: `--cap-drop=ALL --cap-add=NET_BIND_SERVICE`, запрет `--privileged`, `no-new-privileges`.
- **[Linux Namespaces](../../Linux/Core/namespaces.md)** — глубокий разбор 8 типов namespaces. В Docker: PID namespace (PID 1 внутри контейнера), NET namespace (veth‑пара, bridge), USER namespace (rootless, userns-remap).
- **[Cgroups v2](../../Linux/Core/cgroups.md)** — сравнение v1/v2, ручное управление. В Docker: `docker stats`, `memory.events` для OOM detection, `cpu.stat` для throttling, PSI метрики.
- **[Seccomp](../../Linux/Security/Mechanisms/Seccomp.md)** — создание кастомных профилей. В Docker: профиль по умолчанию блокирует ~44 syscall, `--security-opt seccomp=profile.json`.
