# Отладка Distroless-контейнеров

## Определения

**Distroless-образы** — это минималистичные базовые образы, содержащие только приложение и его зависимости времени выполнения. В них отсутствуют оболочка (shell), менеджеры пакетов и стандартные Unix-утилиты.

**Проблема отладки:** Стандартный подход `docker exec -it <container> /bin/sh` завершается ошибкой, так как в образе нет ни `/bin/sh`, ни `/bin/bash`.

**Типичные представители:**
- `gcr.io/distroless/*` — классические образы от Google (Debian-based).
- `FROM scratch` — абсолютно пустой образ для статически скомпилированных бинарников (Go, Rust).
- `Chainguard / Wolfi` — современные безопасные образы ("un-distro"), ориентированные на 0 CVE. Включают `glibc` и менеджер пакетов `apk` (только в сборочных или dev-версиях).

## Основные концепции

### Почему distroless усложняют работу

| Характеристика | Стандартный образ (Debian/Alpine) | Distroless / Scratch |
| :--- | :--- | :--- |
| **Shell** | `/bin/sh`, `/bin/bash` | Отсутствует |
| **Утилиты** | `ls`, `ps`, `curl`, `netstat`, `ip` | Отсутствуют |
| **Менеджер пакетов** | `apt`, `apk`, `yum` | Отсутствует |
| **Поверхность атаки** | Большая (много лишнего ПО) | Минимальная |
| **Безопасность** | Часто запуск от `root` | Часто запуск от `non-root` (UID 65532) |

### Стратегии отладки в 2025-2026 гг.

1.  **Интерактивная среда (Docker Debug):** Нативный инструмент Docker для создания отладочного sidecar с Toolbox (на базе Nix).
2.  **Эфемерные контейнеры (Sidecars):** Запуск временного контейнера (например, `netshoot`), разделяющего namespaces с целью.
3.  **eBPF Трассировка:** Использование внешних инструментов (Inspektor Gadget, Parca) для анализа системных вызовов и сети без внедрения в контейнер.
4.  **Вход через namespaces (nsenter):** Прямое подключение к процессам через ядро Linux (требует привилегий хоста).
5.  **Удаленная отладка (Remote Debugging):** Подключение IDE напрямую к отладочному порту рантайма приложения (Delve, JDWP).

Подробно о пространствах имён: **[Namespaces](../../Linux/Core/namespaces.md)**.

## Практические сценарии

### Сценарий 1: Использование Docker Debug (Рекомендуемый)

С 2024 года `docker debug` является стандартом для локальной разработки и отладки distroless-контейнеров. Команда создает изолированную сессию с полноценным Toolbox (Nix), не внося изменений в исходный образ.

```bash
docker debug my-distroless-app
# → [info] Starting debug session for container "my-distroless-app"...
# → [root@docker-desktop /]# ls -l /app
```

**Преимущества:**
- **Toolbox:** Мгновенный доступ к `vim`, `curl`, `htop`, `ps` и `ip` в среде, где их нет.
- **Gordon AI:** Встроенный помощник (`docker ai`) для автоматического анализа логов и причин падения контейнера.
- **Безопасность:** Инструменты Nix физически изолированы от приложения.

Подробнее: **[Docker Debug](./docker_debug.md)**.

### Сценарий 2: Эфемерные отладочные контейнеры (Sidecars)

Если `docker debug` недоступен, используйте метод подключения к namespaces через `docker run`.

**Анализ сети (через Network Namespace):**
```bash
docker run --rm -it --network=container:target_app nicolaka/netshoot ss -tulpn
```

**Анализ процессов и ФС (через PID Namespace):**
```bash
docker run --rm -it --pid=container:target_app --privileged alpine sh
# Внутри можно видеть ФС цели через /proc/1/root
ls /proc/1/root/etc/
```

### Сценарий 3: Отладка в Kubernetes (kubectl debug)

Стандартный способ для кластеров — создание эфемерного контейнера внутри пода.

```bash
kubectl debug -it my-pod --image=nicolaka/netshoot --target=my-app-container
# / # curl localhost:8080/health
```

Подробнее: **[Ephemeral Containers](../../Kubernetes/Base/Pod/ephemeral_containers.md)**.

### Сценарий 4: Прямой вход через nsenter

Метод для глубокой диагностики, если есть доступ к хосту (требует `sudo`). Позволяет выполнять команды в контексте контейнера, используя бинарники хоста.

Подробное пошаговое руководство: **[Утилита nsenter](../../Linux/Diagnostics/Processes/nsenter.md)**.

Краткий пример получения PID:
```bash
PID=$(docker inspect -f '{{.State.Pid}}' my-container)
```

### Сценарий 5: Трассировка через eBPF (Inspektor Gadget)

Современный метод (2026), не требующий наличия shell или sidecar. Идеален для мониторинга системных вызовов в реальном времени.

```bash
# Отслеживание открываемых файлов в контейнере
ig trace open --container-name my-distroless-app

# Отслеживание DNS-запросов
ig trace dns --container-name my-distroless-app
```

### Сценарий 6: Удаленная отладка (Remote Debugging)

Применяется, когда нужно пошагово пройтись по коду, работающему в distroless.

1. **Go (Delve):**
   ```bash
   # Запуск скомпилированного с поддержкой отладки бинарника через dlv
   dlv --listen=:40000 --headless=true --api-version=2 exec ./app
   ```
2. **Подключение:** В IDE (VS Code/JetBrains) настройте Remote Debug на порт 40000.

## Дополнительная информация

### Сравнение методов отладки

| Метод | Плюсы | Минусы | Применимость |
| :--- | :--- | :--- | :--- |
| **`docker debug`** | Встроенный Nix, ИИ, простота | Нужен Docker CLI 27+ | Локально, Staging |
| **Sidecar (Netshoot)** | Огромный набор утилит | Нужно знать ID контейнера | Универсально |
| **eBPF (ig)** | 0 накладных расходов, безопасно | Нужен доступ к ядру хоста | Глубокая диагностика |
| **`kubectl debug`** | Нативно для K8s | Требует прав в RBAC | Production (K8s) |
| **[`nsenter`](../../Linux/Diagnostics/Processes/nsenter.md)** | Нет лишних контейнеров | Нужен `root` на хосте | Узлы инфраструктуры |
| **Remote Debug** | Пошаговая отладка кода | Требует спец. сборки и портов | Разработка / Тестирование |

### Профилактика и рекомендации

1.  **Debug-теги:** При использовании Google Distroless всегда имейте версию образа с тегом `:debug` (например, `nodejs:22-debug`) для быстрой подмены в случае ЧП.
2.  **Chainguard Dev:** Используйте `-dev` версии образов Chainguard на этапе тестирования — они содержат менеджер пакетов `apk` и shell.
3.  **Централизованное логирование:** Убедитесь, что все ошибки пишутся в `stdout` (Loki, ELK), так как "войти" в упавший контейнер часто невозможно.
4.  **Проверки здоровья:** Используйте **[HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)**, чтобы Docker мог автоматически перезапускать зависшие процессы.
5.  **Изоляция (Sandboxing):** Помните, что в **[Sandboxed Runtimes](../Docker_security/container_hardening.md)** (gVisor) метод [`nsenter`](../../Linux/Diagnostics/Processes/nsenter.md) может не работать напрямую из-за перехвата системных вызовов.

### См. также

- **[Docker Debug](./docker_debug.md)** — описание нативной команды.
- **[Ephemeral Containers](../../Kubernetes/Base/Pod/ephemeral_containers.md)** — отладка в Kubernetes.
- **[Утилита lsns](../../Linux/Diagnostics/Processes/lsns.md)** — поиск и инспекция пространств имен.
- **[Утилита nsenter](../../Linux/Diagnostics/Processes/nsenter.md)** — вход в изолированные окружения.
- **[Namespaces](../../Linux/Core/namespaces.md)** — основы изоляции в Linux.
- **[Коды завершения](./docker_exit_codes.md)** — понимание причин остановки distroless-контейнеров.
