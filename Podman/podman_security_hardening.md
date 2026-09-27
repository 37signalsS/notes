# Podman: Обеспечение безопасности и hardening

## Определения

**Security hardening** — процесс усиления безопасности контейнерной среды Podman путём ограничения привилегий, настройки политик доступа и сканирования уязвимостей.

**CIS Benchmark** — набор рекомендаций по конфигурации безопасности от Center for Internet Security. Существуют CIS Docker Benchmark и CIS Kubernetes Benchmark, применимые к Podman.

**Trivy** — сканер уязвимостей образов контейнеров, SBOM и конфигураций. Поддерживает Podman-образы через OCI-совместимые реестры.

**SBOM (Software Bill of Materials)** — машиночитаемый список всех компонентов (библиотеки, зависимости) в образе контейнера. Требуется для compliance и supply chain security.

**Cosign** — инструмент для подписи и верификации образов контейнеров из проекта Sigstore. Обеспечивает целостность и подлинность образов.

**Seccomp** — механизм фильтрации системных вызовов, ограничивающий доступ контейнера к ядру Linux.

**SELinux** — система mandatory access control, ограничивающая права процессов и файлов на уровне ядра.

**Rootless mode** — режим работы Podman без привилегий root, использующий user namespaces для изоляции.

---

## Теоретический блок

### Уровни безопасности Podman

```
┌─────────────────────────────────────────────────────────────┐
│                    Supply Chain Security                     │
│         (Cosign, SBOM, image signing, vulnerability scan)   │
└──────────────────────▲──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                  Runtime Security                            │
│       (seccomp, SELinux, capabilities, namespaces)          │
└──────────────────────▲──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                  Configuration Security                      │
│       (CIS Benchmark, containers.conf, policy files)        │
└──────────────────────▲──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                  Isolation Security                          │
│       (rootless, user namespaces, cgroups v2)               │
└─────────────────────────────────────────────────────────────┘
```

### Сравнение Podman vs Docker с точки зрения безопасности

| Аспект | Podman | Docker |
|---|---|---|
| Rootless по умолчанию | ✅ Да | ❌ Нет (требует настройки) |
| Daemon | ✅ Нет (daemonless) | ❌ Есть (Docker daemon = attack surface) |
| User namespaces | ✅ Нативно | ⚠️ Experimental |
| Seccomp profiles | ✅ По умолчанию | ✅ По умолчанию |
| SELinux | ✅ Интеграция | ⚠️ Ограниченная |
| Image signing | ✅ Skopeo/Cosign | ✅ Docker Content Trust |
| SBOM | ✅ Buildah/Skopeo | ✅ Docker Scout |

---

## Практический блок

### 1. Rootless режим (основа безопасности)

```bash
# Проверка rootless mode
podman info | grep rootless

# Запуск контейнера без root
podman run --rm -it alpine sh

# Проверка user namespace
podman unshare cat /proc/self/uid_map
# Пример вывода: 0 100000 65536

# Настройка поддиапазона UID (если нужно)
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER
```

### 2. Ограничение возможностей (capabilities)

```bash
# Запуск без всех capabilities
podman run --rm --cap-drop=ALL alpine sh

# Добавить только необходимые
podman run --rm \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --cap-add=CHOWN \
  nginx:alpine

# Полный список capabilities
podman run --rm alpine sh -c "cat /proc/1/status | grep Cap"

# Преобразование hex → readable
capsh --decode=00000000a80425fb
```

#### Типичные capabilities

| Capability | Описание | Когда нужно |
|---|---|---|
| `NET_BIND_SERVICE` | Привязка к портам <1024 | Web-серверы |
| `CHOWN` | Смена владельца файлов | Инициализация |
| `SETUID` / `SETGID` | Смена UID/GID | Многопользовательские приложения |
| `SYS_PTRACE` | Отладка процессов | Only для debugging |
| `NET_ADMIN` | Управление сетью | VPN, сетевые утилиты |

### 3. Seccomp профили

```bash
# Запуск с кастомным seccomp профилем
podman run --rm \
  --security-opt seccomp=/path/to/profile.json \
  alpine sh

# Отключение seccomp (НЕ рекомендуется)
podman run --rm \
  --security-opt seccomp=unconfined \
  alpine sh

# Просмотр дефолтного профиля
podman info | grep -A 5 seccomp
```

#### Создание кастомного seccomp профиля

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": [
        "accept", "access", "arch_prctl", "bind", "brk",
        "clone", "close", "connect", "dup", "dup2",
        "execve", "exit", "exit_group", "fcntl", "fstat",
        "getdents64", "getpid", "getsockname", "gettid",
        "ioctl", "listen", "lseek", "mmap", "mprotect",
        "munmap", "nanosleep", "newfstatat", "openat",
        "poll", "pread64", "prlimit64", "pwrite64",
        "read", "recvfrom", "rt_sigaction", "rt_sigprocmask",
        "sendto", "set_robust_list", "set_tid_address",
        "setsockopt", "shutdown", "sigaltstack", "socket",
        "stat", "write", "writev"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

### 4. SELinux для Podman

```bash
# Проверка SELinux
getenforce
sestatus

# Запуск с SELinux меткой
podman run --rm \
  --security-opt label=type:container_t \
  alpine sh

# Запуск без SELinux (НЕ рекомендуется)
podman run --rm \
  --security-opt label=disable \
  alpine sh

# Генерация SELinux контекста для тома
podman system migrate --force
```

### 5. Сканирование уязвимостей (Trivy)

```bash
# Установка Trivy
brew install trivy  # macOS
# или
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh

# Сканирование образа
trivy image my-app:latest

# Сканирование с фильтрацией по severity
trivy image --severity HIGH,CRITICAL my-app:latest

# Сканирование в JSON (для парсинга)
trivy image --format json --output result.json my-app:latest

# Сканирование Dockerfile
trivy config --severity HIGH,CRITICAL ./Dockerfile

# Сканирование файловой системы
trivy fs --security-checks vuln,secret,misconfig .

# Сканирование SBOM
trivy sbom ./sbom.json

# CI/CD интеграция (exit code 1 при найденных уязвимостях)
trivy image --exit-code 1 --severity HIGH,CRITICAL my-app:latest
```

### 6. SBOM (Software Bill of Materials)

```bash
# Генерация SBOM через Syft
syft my-app:latest -o spdx-json > sbom.json

# Генерация SBOM через Buildah
buildah from my-app:latest
buildah inspect my-app:latest | jq '.Docker.Config.Labels'

# Просмотр SBOM
cat sbom.json | jq '.packages[] | {name, version, supplier}'

# Проверка SBOM через Trivy
trivy sbom ./sbom.json

# Интеграция в CI/CD
syft my-app:latest -o spdx-json | trivy sbom -
```

### 7. Подпись образов (Cosign)

```bash
# Установка Cosign
brew install cosign

# Генерация ключевой пары
cosign generate-key-pair

# Подпись образа
cosign sign --key cosign.key my-registry/my-app:latest

# Верификация подписи
cosign verify --key cosign.pub my-registry/my-app:latest

# Подпись без ключей (keyless, через OIDC)
cosign sign my-registry/my-app:latest

# Верификация keyless
cosign verify \
  --certificate-identity=user@example.com \
  --certificate-oidc-issuer=https://accounts.google.com \
  my-registry/my-app:latest

# Сохранение SBOM как артефакт
cosign attach sbom --sbom sbom.json my-registry/my-app:latest
```

### 8. Конфигурация containers.conf

```toml
# /etc/containers/containers.conf (или ~/.config/containers/containers.conf)

[containers]
# Безопасность по умолчанию
default_capabilities = [
  "NET_BIND_SERVICE",
  "CHOWN",
  "SETUID",
  "SETGID",
  "FOWNER",
  "DAC_OVERRIDE"
]

# Ограничение ресурсов
pids_limit = 4096
shm_size = "256m"

# Логирование
log_driver = "journald"

# Сетевые настройки
dns_servers = []

[engine]
# События
events_logger = "journald"

# OCI runtime
oci_runtime = "crun"

# Максимальный размер контейнера
containers_max = 512

[network]
# Сетевой插件
network_backend = "netavark"
```

### 9. CIS Benchmark проверки

```bash
# Установка kube-bench (для Podman + Kubernetes)
brew install kube-bench

# Запуск CIS Docker Benchmark (через Docker в Podman)
podman run --rm \
  --net host \
  --pid host \
  --userns host \
  --cap-add audit_control \
  -e DOCKER_CONTENT_TRUST=$DOCKER_CONTENT_TRUST \
  -v /var/lib:/var/lib:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /usr/lib/systemd:/usr/lib/systemd:ro \
  -v /etc:/etc:ro \
  docker/docker-bench-security

# Ручные проверки CIS
# 1. Проверка rootless
podman info | grep rootless
# Ожидаемый результат: rootless: true

# 2. Проверка сёменей namespaces
podman info | grep -A 5 namespaces
# Ожидаемый результат: user: true

# 3. Проверка seccomp
podman info | grep -A 5 seccomp
# Ожидаемый результат: seccomp_profile: ""
```

### 10. Безопасность сети

```bash
# Изоляция контейнеров через сети
podman network create --internal isolated-net
podman run --rm --network isolated-net alpine sh

# Отключение сетевого доступа
podman run --rm --network none alpine sh

# Проверка открытых портов
podman port my-app

# Настройка DNS
podman run --rm \
  --dns=8.8.8.8 \
  --dns-search=example.com \
  alpine nslookup google.com
```

### 11. Безопасность хранилища

```bash
# Тома только для чтения
podman run --rm \
  -v /data:/data:ro \
  alpine sh

# Tmpfs (не сохраняется на диск)
podman run --rm \
  --tmpfs /tmp:rw,noexec,nosuid \
  alpine sh

# Без привязки к хосту
podman run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  alpine sh
```

### 12. Audit логирование

```bash
# Включение аудита Podman
sudo auditctl -w /usr/bin/podman -p rwxa -k podman

# Просмотр аудит-логов
sudo ausearch -k podman --interpret

# Настройка через auditd
cat <<EOF | sudo tee /etc/audit/rules.d/podman.rules
-w /usr/bin/podman -p rwxa -k podman
-w /usr/bin/buildah -p rwxa -k podman
-w /usr/bin/skopeo -p rwxa -k podman
-w /etc/containers/ -p wa -k podman-config
EOF

sudo systemctl restart auditd
```

### 13. CI/CD безопасность

```yaml
# GitLab CI: безопасная сборка
stages:
  - build
  - scan
  - sign

build:
  stage: build
  script:
    - podman build --layers -t myapp:${CI_COMMIT_SHA} .

scan:
  stage: scan
  script:
    - trivy image --exit-code 1 --severity HIGH,CRITICAL myapp:${CI_COMMIT_SHA}
    - trivy config --exit-code 1 ./Dockerfile

sign:
  stage: sign
  only:
    - main
  script:
    - cosign sign --key /path/to/cosign.key ${REGISTRY}/myapp:${CI_COMMIT_SHA}
    - syft myapp:${CI_COMMIT_SHA} -o spdx-json > sbom.json
    - cosign attach sbom --sbom sbom.json ${REGISTRY}/myapp:${CI_COMMIT_SHA}
```

---

## Дополнительная информация

### Чеклист безопасности Podman

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Rootless mode | `podman info \| grep rootless` | `rootless: true` |
| Seccomp включен | `podman info \| grep seccomp` | Профиль настроен |
| SELinux | `getenforce` | `Enforcing` |
| Нет привилегий root | `podman ps --format "{{.User}}"` | Не `root` |
| TTY не привязан | `podman inspect --format '{{.Config.Tty}}'` | `false` |
| Read-only FS | `podman inspect --format '{{.HostConfig.ReadonlyRootfs}}'` | `true` |
| Нет privileged | `podman inspect --format '{{.HostConfig.Privileged}}'` | `false` |
| Ограничены capabilities | `podman inspect --format '{{.HostConfig.CapAdd}}'` | Минимум |

### Типичные ошибки безопасности

| Ошибка | Решение |
|---|---|
| `--privileged` в production | Используйте `--cap-add` для конкретных capabilities |
| `--network host` | Используйте bridge сети с пробросом портов |
| `--security-opt seccomp=unconfined` | Всегда используйте seccomp профили |
| `root` внутри контейнера | Запускайте от непривилегированного пользователя |
| Секреты в ENV | Используйте `podman secrets` или volume mounts |

### Ссылки

- **[Rootless режим](./podman_rootless.md)** — детали rootless работы
- **[Linux Isolation](./linux_isolation.md)** — namespaces, cgroups, seccomp, SELinux
- **[Secrets](./podman_secrets.md)** — управление секретами
- **[CIS Docker Benchmark](../../Docker/Docker_security/host_daemon_hardening.md)** — CIS Docker
- **[Trivy](../../Security/Tools/security_tools.md)** — инструменты безопасности
- **[Cosign/Sigstore](../../Security/Tools/sigstore.md)** — подпись образов
- **[SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — анализ зависимостей
