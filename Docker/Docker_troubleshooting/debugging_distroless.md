# Отладка Distroless-контейнеров

## Определения

**Distroless-образы** — это минималистичные базовые образы, содержащие только приложение и его зависимости времени выполнения. В них отсутствуют оболочка (shell), менеджеры пакетов и стандартные Unix-утилиты.

**Проблема отладки:** Стандартный подход `docker exec -it <container> /bin/sh` завершается ошибкой, так как в образе нет ни `/bin/sh`, ни `/bin/bash`.

Типичные представители:
- `gcr.io/distroless/*` (Google Distroless)
- `FROM scratch` (Абсолютно пустой образ)
- `Chainguard Images` / `Wolfi` (Современные безопасные минимальные образы)

## Основные концепции

### Почему distroless усложняют работу

| Характеристика | Стандартный образ (Debian/Alpine) | Distroless / Scratch |
| :--- | :--- | :--- |
| **Shell** | `/bin/sh`, `/bin/bash` | Отсутствует |
| **Утилиты** | `ls`, `ps`, `curl`, `netstat`, `ip` | Отсутствуют |
| **Менеджер пакетов** | `apt`, `apk`, `yum` | Отсутствует |
| **Поверхность атаки** | Большая (много лишнего ПО) | Минимальная |
| **Безопасность** | Часто запуск от `root` | Часто запуск от `non-root` |

### Стратегии отладки в 2025-2026 гг.

1.  **Интерактивная среда (Docker Debug):** Нативный инструмент Docker для создания отладочного sidecar с Toolbox.
2.  **Эфемерные контейнеры (Sidecars):** Запуск временного контейнера (например, `netshoot`), разделяющего namespaces с целью.
3.  **Вход через namespaces (nsenter):** Прямое подключение к процессам через ядро Linux (требует привилегий хоста).
4.  **Специальные образы (:debug):** Использование версий образов, содержащих `busybox` для экстренных случаев.

Подробно о пространствах имён: **[Namespaces](../../Linux/Core/namespaces.md)**.

## Практические сценарии

### Сценарий 1: Использование Docker Debug (Рекомендуемый)

С 2024 года `docker debug` является стандартом для локальной разработки. Команда создает сессию с набором инструментов (Nix), не изменяя сам образ.

```bash
docker debug my-distroless-app
# → [info] Starting debug session for container "my-distroless-app"...
# → [root@docker-desktop /]# ls -l /app
# → -rwxr-xr-x 1 root root 15728640 Jul 19 12:00 main
```

**Преимущества:** доступ к `vim`, `curl`, `htop` и ИИ-помощнику Gordon даже в пустом образе.
Подробнее: **[Docker Debug](./docker_debug.md)**.

### Сценарий 2: Эфемерные отладочные контейнеры (Sidecars)

Если `docker debug` недоступен (например, на старых серверах), используйте метод подключения к namespaces.

**Анализ сети (через Network Namespace):**

```bash
# Подключаемся к сети целевого контейнера
docker run --rm -it --network=container:target_app nicolaka/netshoot ss -tulpn
# → Netid  State  Recv-Q  Send-Q  Local Address:Port  Peer Address:Port
# → tcp    LISTEN 0       128     0.0.0.0:8080        0.0.0.0:*
```

**Анализ процессов и файлов (через PID Namespace):**

```bash
# Видим процессы приложения и его ФС через /proc
docker run --rm -it --pid=container:target_app --privileged alpine sh
# Внутри:
ps aux
# → PID   USER     TIME  COMMAND
# →    1 65532     0:05 /app/server
ls /proc/1/root/etc/configs
# → config.json
```

### Сценарий 3: Отладка в Kubernetes (kubectl debug)

Стандартный способ для кластеров — создание эфемерного контейнера внутри пода.

```bash
kubectl debug -it my-pod --image=nicolaka/netshoot --target=my-app-container
# → Defaulting debug container name to debugger-5v7z2.
# / # curl localhost:8080/health
# → {"status":"UP"}
```

Подробнее: **[Ephemeral Containers](../../Kubernetes/Base/Pod/ephemeral_containers.md)**.

### Сценарий 4: Прямой вход через nsenter

Метод для глубокой диагностики, если есть доступ к хосту (требует `sudo`).

```bash
# 1. Находим PID процесса контейнера
PID=$(docker inspect -f '{{.State.Pid}}' my-container) # → 12345

# 2. Входим в namespaces
sudo nsenter -t $PID -m -u -i -n -p sh
# # id
# → uid=0(root) gid=0(root) groups=0(root)
```

### Сценарий 5: Использование cdebug

Утилита **cdebug** — кроссплатформенная альтернатива для `containerd` и `Podman`.

```bash
cdebug exec -it --image nicolaka/netshoot my-container
# → [cdebug] Attaching to container...
# / # tcpdump -i eth0
```

## Дополнительная информация

### Сравнение методов

| Метод | Плюсы | Минусы | Применимость |
| :--- | :--- | :--- | :--- |
| **`docker debug`** | Встроенный Nix, ИИ | Нужен Docker CLI 27+ | Локально, Staging |
| **Sidecar (Netshoot)** | Огромный набор утилит | Нужно знать ID контейнера | Универсально |
| **`kubectl debug`** | Нативно для K8s | Требует прав в RBAC | Production (K8s) |
| **`nsenter`** | Нет лишних контейнеров | Нужен `root` на хосте | Debugging узла/хоста |
| **`docker cp`** | Самый простой способ | Только статический анализ | Извлечение логов/дампов |

### Профилактика и рекомендации

1.  **Debug-теги:** При использовании Google Distroless всегда имейте версию образа с тегом `:debug` (например, `nodejs:22-debug`) в реестре для быстрой подмены в случае ЧП.
2.  **Chainguard Dev:** Рассмотрите использование `-dev` версий образов Chainguard на этапе тестирования — они содержат удобные менеджеры пакетов (например, `apk`).
3.  **Централизованное логирование:** Поскольку войти в distroless сложно, убедитесь, что все ошибки пишутся в `stdout` и собираются системой (Loki, ELK).
4.  **Healthchecks:** Используйте `[HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)`, чтобы Docker мог автоматически перезапускать зависшие distroless-контейнеры.
5.  **Remote Debugging:** Для Go/Java/Node.js настройте удаленную отладку через порты (Delve, JDWP, Inspector), чтобы подключаться из IDE напрямую к коду.

### Связанные темы

- **[Docker Debug](./docker_debug.md)** — глубокое описание нативной команды.
- **[Ephemeral Containers](../../Kubernetes/Base/Pod/ephemeral_containers.md)** — отладка в Kubernetes.
- **[Namespaces](../../Linux/Core/namespaces.md)** — как работают пространства имен в Linux.
