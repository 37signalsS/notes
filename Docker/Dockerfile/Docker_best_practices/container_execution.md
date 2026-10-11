# Выполнение приложений в контейнере

**Актуально для:** Docker 24.0+ / BuildKit включён по умолчанию

## Определения

- **PID (Process Identifier) 1:** Первый процесс в пространстве имен (Namespace), обладающий особыми полномочиями и обязанностями в Linux. Он отвечает за управление сигналами и очистку «процессов-сирот» (reaping). В контейнере PID 1 — это основной процесс, определяемый инструкцией `ENTRYPOINT` или `CMD`.
- **Форма записи Exec (JSON form):** Синтаксис `CMD ["executable", "param1"]`, запускающий процесс напрямую через системный вызов `execve` без участия командной оболочки. Это единственный надежный способ сделать процесс PID 1 и обеспечить корректный проброс сигналов.
- **Форма записи Shell:** Синтаксис `CMD executable param1`, запускающий процесс как дочерний для `/bin/sh -c`. Оболочка становится PID 1 и часто блокирует проброс сигналов приложению. Использование shell-form для основных процессов считается антипаттерном.
- **Процесс-зомби (Zombie Process):** Завершенный процесс, который уже не выполняется, но запись о нем остается в таблице процессов (task list), так как родитель (PID 1) не выполнил системный вызов `wait()` для сбора статуса завершения. Зомби не потребляют ресурсы (CPU, память), но занимают запись в таблице процессов. При переполнении таблицы (typically ~32768 записей в Linux по умолчанию) невозможно создать новые процессы, что приводит к отказу системы. **Зомби нельзя «убить» напрямую** через `SIGKILL` — единственное решение это либо корректная обработка `SIGCHLD` родительским процессом, либо использование init-системы. Подробности см. в [Руководстве по отладке процессов](../../../Linux/Core/processes/Troubleshooting/debugging.md#устранение-зомби-и-сирот).
- **Сигнал SIGCHLD:** Специальный сигнал, который ядро отправляет родительскому процессу при завершении дочернего процесса. Процесс PID 1 обязан перехватывать этот сигнал и выполнять `wait()` или `waitpid()` для освобождения ресурсов. Если обработчик `SIGCHLD` не зарегистрирован, дочерние процессы превращаются в зомби.
- **Graceful Shutdown (Плавное завершение):** Паттерн, при котором приложение при получении сигнала остановки прекращает прием новых запросов, завершает текущие транзакции, сохраняет состояние и только после этого закрывается. Типичная реализация: перехват `SIGTERM`, установка флага «не принимать новые соединения», ожидание завершения активных операций с таймаутом, вызов `server.shutdown()` и выход.
- **STOPSIGNAL:** Инструкция Dockerfile, задающая конкретный системный сигнал (например, `SIGTERM`, `SIGQUIT`, `SIGINT`), который Docker будет отправлять процессу PID 1 при выполнении команды `docker stop`. Использование имен сигналов предпочтительнее числовых значений, так как числа могут различаться в зависимости от архитектуры процессора.
- **Init-система (Tini / dumb-init):** Легковесные менеджеры процессов, которые берут на себя роль PID 1, корректно пробрасывают сигналы дочерним процессам и очищают зомби. Разница: `tini` ( (~20KB) ) является стандартом для Docker, поддерживает process groups (`-g`), тогда как `dumb-init` предоставляет возможность перезаписи сигналов (например, SIGTERM → SIGQUIT для Java).
- **Stop Timeout (Таймаут остановки):** Временной интервал (по умолчанию 10 секунд для Linux-контейнеров), в течение которого Docker ожидает завершения процесса после отправки сигнала из STOPSIGNAL. По истечении таймаута Docker отправляет SIGKILL (сигнал 9), который невозможно перехватить.

## Предварительные требования

Для корректного выполнения и управления контейнерами необходимо:

- **Docker Engine** версии 24.0 или новее (Cgroups v2, BuildKit включён по умолчанию, улучшенная обработка сигналов).
- **Docker Compose** версии 2.x (для управления жизненным циклом, `stop_grace_period`, `security_opt`).
- **Linux Kernel** версии 5.19+ (полная поддержка cgroups v2, User Namespaces, Landlock).
- **Rootless Docker** (опционально, рекомендуется): требует ядро >= 5.11 и настройки `userns-remap`.
- **ОС хоста:** Ubuntu 22.04+/Debian 12+ (AppArmor), RHEL 9+/Fedora 40+ (SELinux enforcing).
- Понимание базовых концепций: **[CMD и ENTRYPOINT](../Instructions/runtime_execution.md)** (exec-form vs shell-form), **[HEALTHCHECK и STOPSIGNAL](../Instructions/health_signals.md)**.
- Базовое понимание Linux-процессов: PID, сигналы (SIGTERM, SIGKILL, SIGCHLD), процессы-зомби, дерево процессов.
- Утилиты для диагностики: `docker exec`, `docker top`, `docker events`, `docker inspect`, `docker stats`, `ps`, `strace` (в debugging образах).

## Базовые концепции

### Проблема PID 1 и систем инициализации

В стандартной ОС за очистку ресурсов и управление процессами отвечает полноценная система инициализации (`systemd`, `OpenRC`, `sysvinit`). В контейнере роль PID 1 ложится на ваше приложение, что порождает две критические проблемы:

1.  **Игнорирование сигналов:** Процесс PID 1 в Linux является особенным. Он не имеет обработчиков сигналов по умолчанию (default signal disposition). Если приложение (например, на Python, Node.js, Java) не зарегистрировало обработчик `SIGTERM` явно через `signal.signal()` или `process.on()`, ядро не применит стандартное поведение "завершиться", и сигнал будет проигнорирован. Docker будет ждать 10 секунд (stop timeout) и отправит `SIGKILL`, что приведет к немедленному завершению без возможности корректного закрытия ресурсов.
2.  **Накопление зомби:** Если приложение порождает дочерние процессы (например, через `shell_exec`, `subprocess.Popen()`, `worker_threads` в Node.js, или `fork()` в Go), и они завершаются, PID 1 обязан «пожинать» их, вызывая `wait()`. Если этого не происходит, записи о завершенных процессах остаются в таблице процессов. При переполнении таблицы ядро отказывает в создании новых процессов (`fork()` возвращает `EAGAIN`), что критически для приложений, динамически порождающих воркеров.

### Exec Form против Shell Form

Выбор формы записи в `Dockerfile` (для `CMD` и `ENTRYPOINT`) критически влияет на жизненный цикл приложения, проброс сигналов и возможность отладки.

| Характеристика | Exec Form (`["app", "arg"]`) | Shell Form (`app arg`) |
| :--- | :--- | :--- |
| **Системный вызов** | `execve("app", ["app", "arg"], envp)` | `execve("/bin/sh", ["sh", "-c", "app arg"], envp)` |
| **PID процесса** | Приложение получает PID 1 | `/bin/sh` получает PID 1, приложение — случайный PID |
| **Проброс сигналов** | Напрямую приложению (SIGTERM, SIGINT) | Блокируется оболочкой — сигнал доходит только до sh |
| **Зомби-процессы** | Не обрабатываются (требует init-систему или явный `wait()`) | Оболочка частично обрабатывает (но не полностью) |
| **Переменные окружения** | Не подставляются автоматически (нужен `/bin/sh -c`) | Подставляются через обработку `/bin/sh` |
| **Доступ к shell-утилитам** | Нет (только статические бинарники) | Да (pipe, переменные, команды shell) |
| **Размер процесса** | Минимальный (нет overhead оболочки) | +~1MB для экземпляра sh |
| **Отладка** | Сложнее (нет shell) | Проще (можно войти через `docker exec sh`) |

**Рекомендация:** Всегда используйте **Exec Form**. Если приложению нужны переменные окружения или pipe, используйте явный вызов оболочки с `exec`:
```dockerfile
CMD ["/bin/sh", "-c", "echo $DATABASE_URL && exec /app/bin/start"]
```
Использование `exec` в конце команды `sh` заменит процесс оболочки вашим приложением, сохраняя за ним PID 1 и возможность получения сигналов.

**Антипаттерн — shell-form для CMD:**
```dockerfile
# ПЛОХО: sh станет PID 1, SIGTERM не дойдет до приложения
CMD node server.js

# ХОРОШО: node становится PID 1 напрямую
CMD ["node", "server.js"]
```

### Механизм STOPSIGNAL

По умолчанию `docker stop` отправляет `SIGTERM`, ждет stop timeout (по умолчанию 10 секунд для Linux, 30 для Windows-контейнеров) и, если контейнер не остановился, отправляет `SIGKILL`. Однако некоторым приложениям требуются другие сигналы для корректного завершения:

| Приложение | Рекомендуемый сигнал | Причина |
| :--- | :--- | :--- |
| **Nginx** | `SIGQUIT` | Graceful shutdown — завершает обработку текущих запросов и закрывает listener |
| **PostgreSQL** | `SIGINT` | Fast Shutdown — немедленно завершает все сессии (Smart Shutdown через SIGTERM часто приводит к таймауту) |
| **Redis** | `SIGTERM` | Стандартный graceful shutdown с сохранением RDB-снапшота |
| **Java/Spring Boot** | `SIGTERM` | Spring Boot Actuator перехватывает и выполняет graceful shutdown |
| **Sidekiq** | `SIGQUIT` | Завершает текущие job'ы и выходит |
| **RabbitMQ** | `SIGTERM` | Стандартный graceful shutdown |

```dockerfile
# Установка правильного сигнала в Dockerfile
STOPSIGNAL SIGQUIT
```

**Важно:** Использование `--stop-signal` в `docker run` или `stop_signal` в `compose.yml` переопределяет инструкцию `STOPSIGNAL`. Однако `--stop-signal` не работает с shell-form CMD — это еще одна причина использовать exec-form.

### Механизм docker stop: пошагово

```
docker stop mycontainer
    │
    ▼
1. Docker отправляет SIGTERM (или сигнал из STOPSIGNAL) процессу PID 1
    │
    ▼
2. Docker ожидает stop timeout (по умолчанию 10 секунд)
    │
    ├── Процесс завершился → Контейнер остановлен (exit code 0 или код приложения)
    │
    ▼ (процесс не завершился)
3. Docker отправляет SIGKILL (сигнал 9) — невозможно перехватить
    │
    ▼
4. Контейнер принудительно завершен (exit code 137 = 128 + 9)
```

Настройка таймаута:

```bash
# Ожидание 30 секунд перед SIGKILL
docker stop --timeout 30 my-container

# В docker-compose.yml
services:
  app:
    stop_grace_period: 30s

# В Kubernetes манифесте
spec:
  terminationGracePeriodSeconds: 60
```

### Флаг --init

Если образ не содержит `tini`, но вам нужно решить проблему PID 1, Docker предоставляет встроенную поддержку:

- **CLI:** `docker run --init ...`
- **Compose:** `init: true`

Это автоматически вставляет `tini` как PID 1 внутрь контейнера. Механизм: Docker монтирует статически скомпилированный бинарник `tini` из собственного образа и запускает его вместо вашего приложения. `tini` становится PID 1 и передает все сигналы вашему приложению (которое теперь его дочерний процесс).

**Когда использовать `--init`:**
- При отладке — не нужно пересобирать образ с tini
- Когда нет возможности изменить Dockerfile
- Для быстрого исправления в production (но лучше исправить образ)

**Когда НЕ использовать `--init`:**
- Приложение уже само корректно обрабатывает PID 1 (например, Go без дочерних процессов)
- Дополнительный процесс tini накладывает минимальные, но ненужные накладные расходы

### Принцип одного процесса

Контейнер спроектирован для изоляции одной функциональной единицы (functional unit). Это не жесткое ограничение, а архитектурная рекомендация:

- **Масштабируемость:** Микросервисы должны масштабироваться независимо. Если в одном контейнере Nginx и PHP-FPM, их нельзя масштабировать по отдельности.
- **Логирование:** Docker агрегирует `stdout/stderr` PID 1. Несколько процессов в одном контейнере перемешивают логи, затрудняя фильтрацию и агрегацию (ELK, Loki).
- **Мониторинг:** Если упадет второстепенный процесс, а основной (PID 1) останется жив, оркестратор не узнает о сбое. Контейнер будет помечен как «running», хотя часть функциональности недоступна.
- **Управление жизненным циклом:** Один процесс = один стоп-сигнал. С несколькими процессами возникает конфликт: кому отправлять SIGTERM?

**Исключения (когда multi-process допустим):**
- **Sidecar-контейнеры в Kubernetes:** Логирование (fluentd), мониторинг (prometheus-exporter), проксирование (envoy) запускаются отдельно.
- **Init-контейнеры:** Выполняют одноразовую задачу (миграции БД) и завершаются до старта основного процесса.
- **Легковесные менеджеры:** `supervisord`, `s6-overlay` — если процессы неразрывно связаны (например, `Nginx + PHP-FPM` в legacy-приложениях) и их разделение требует рефакторинга архитектуры.

### Сравнение tini и dumb-init

Оба инструмента решают проблему PID 1, но имеют ключевые отличия:

| Характеристика | tini | dumb-init |
| :--- | :--- | :--- |
| **Размер** | ~20KB (statically linked) | ~30KB |
| **Встроен в Docker** | Да (`docker run --init`) | Нет |
| **Process Groups** | Поддержка `-g` (forward signals to process group) | Не поддерживает |
| **Перезапись сигналов** | Нет (пробрасывает как есть) | Да (`--rewrite SIGTERM:SIGQUIT`) |
| **Файловые дескрипторы** | Закрывает FD при завершении | Не закрывает |
| **Рекомендация** | Стандарт для Docker, рекомендуется по умолчанию | Полезен когда нужна трансляция сигналов (Java, Nginx) |

**Пример перезаписи сигналов через dumb-init:**
```bash
# Java не обрабатывает SIGTERM напрямую, но понимает SIGQUIT
dumb-init --rewrite SIGTERM:SIGQUIT java -jar app.jar
```

**Пример tini с process groups:**
```bash
# Пересылает сигналы всей группе процессов (полезно для shell-скриптов с фоновыми задачами)
tini -g -- sh -c "python worker.py & python scheduler.py"
```

### Мониторинг жизненного цикла и процессов (DevOps/SRE)

Для управления контейнерами в production необходим набор инструментов наблюдения за состоянием процессов и событиями.

#### События контейнера (`docker events`)

Docker Engine генерирует события для каждого изменения состояния: `start`, `stop`, `die`, `kill`, `oom`, `pause`, `unpause`, `exec-create`, `exec-start`. Эти события критичны для построения пайплайнов реагирования (например, автоматический перезапуск, оповещение в Slack/PagerDuty, запись в SIEM).

```bash
# Подписка на все события в реальном времени
docker events --filter event=die --filter event=oom --format '{{.Time}} {{.Action}} {{.ID}}'

# Фильтр по контейнеру
docker events --filter id=abc123 --filter event=die

# Выходные коды и их причины:
# die    exit_code=137 → OOM Kill или docker stop timeout
# die    exit_code=0   → нормальное завершение
# oom    → OOM Killer убил контейнер (cgroups)
# kill   → SIGKILL отправлен явно
```

**SRE-практика:** В production-средах все события контейнера должны стекаться в централизованный лог (Loki, ELK, Splunk). Это позволяет диагностировать инциденты постфактум: какой контейнер умер, с каким кодом, в какое время.

#### Инспекция процессов внутри контейнера (`docker top`)

`docker top` показывает дерево процессов внутри running-контейнера, аналогично `ps aux` на хосте. Это первичный инструмент диагностики при проблемах с потреблением CPU, памятью или зависаниями.

```bash
# Полный список процессов
docker top mycontainer -eo pid,user,pri,ni,vsize,rsize,etime,args

# Фильтр по имени процесса
docker top mycontainer | grep python

# Проверка зомби-процессов
docker top mycontainer -o stat | grep -w Z
# → Если есть вывод — проблема с PID 1 (см. Раздел "Проблема PID 1")
```

**Важно:** `docker top` работает через встроенный criu/procfs-механизм. Если контейнер остановлен — команда вернет ошибку. Для stopped-контейнеров используйте `docker inspect --format='{{.State.ExitCode}}'` и логи.

#### Живое обновление ресурсов (`docker update`)

Docker позволяет изменять лимиты CPU, памяти и количество процессов без перезапуска контейнера. Это критично для SRE: можно среагировать на деградацию производительности без даунтайма.

```bash
# Увеличение лимита CPU с 0.5 до 2.0 ядер "на лету"
docker update --cpus=2.0 mycontainer

# Увеличение лимита памяти с 512m до 1g
docker update --memory=1g --memory-swap=1g mycontainer

# Ограничение количества процессов (защита от fork-бомб)
docker update --pids-limit=128 mycontainer

# Привязка к конкретным ядрам CPU (для latency-sensitive приложений)
docker update --cpuset-cpus="0,1" mycontainer

# Проверка применённых лимитов
docker inspect mycontainer --format='{{.HostConfig.CpuShares}} {{.HostConfig.Memory}} {{.HostConfig.PidsLimit}}'
```

**Ограничения:**
- Уменьшение лимита памяти (`--memory`) принудительно завершит контейнер с кодом 137, если текущее потребление превышает новый лимит. Всегда проверяйте `docker stats` перед уменьшением.
- `--cpuset-cpus` может быть только **сужен**, но не расширен. Если контейнер уже привязан к ядрам 0,1 — нельзя добавить ядро 2 без перезапуска.

#### Интеграция с systemd

Запуск Docker Engine и контейнеров через systemd-юниты — стандарт для production Linux-хостов. Неправильная конфигурация systemd приводит к проблемам с сигналами и управлением ресурсами.

```ini
# /etc/systemd/system/docker.service.d/delegate.conf
# Делегирование cgroups контейнерам (обязательно для корректных лимитов)
[Service]
Delegate=yes

# Проверка
systemctl daemon-reload && systemctl restart docker
```

**Управление контейнером как systemd-юнитом (Podman-стиль):**

В Docker 24+ доступен экспериментальный режим `--sdnotify`, позволяющий контейнеру интегрироваться с systemd через D-Bus. Это позволяет:
- Автоматически запускать контейнер при старте systemd.
- Получать статус `active`/`inactive` через `systemctl status mycontainer`.
- Автоматически перезапускать контейнер при падении (аналог `restart: always`).

```bash
# Запуск с интеграцией systemd
docker run -d --name myservice --sdnotify=conmon nginx:alpine
```

**Критично:** При запуске Docker внутри systemd-контейнера (Docker-in-Docker) убедитесь, что хост-юнит содержит `Delegate=yes` и `TasksMax=infinity`, иначе воркеры DinD не смогут создавать дочерние контейнеры.

#### Паттерны process supervision

Помимо `tini` и `dumb-init`, в production-средах применяются полноценные менеджеры процессов для multi-process-контейнеров (legacy-приложения, Nginx + PHP-FPM):

- **s6-overlay:** Минималистичный init-система с зависимостями между сервисами, долгоживущими процессами и oneshot-задачами. Подходит для Alpine-образов.
- **supervisord:** Классический Python-менеджер процессов с веб-интерфейсом, перезапуском и логированием. Требует установки `supervisor` пакета, увеличивает размер образа.
- **runit:** Очень легковесный (single-binary), поддерживает параллельный запуск сервисов и автоматический перезапуск.

**Рекомендация:** Для микросервисов (один процесс на контейнер) используйте `tini`. Для legacy-моноролитов, где разделение на микросервисы требует рефакторинга — `s6-overlay`. `supervisord` и `runit` применяйте только при обоснованной необходимости.

## Практические сценарии

### Сценарий 1: Корректный Graceful Shutdown (Go)

Приложение должно перехватывать сигналы, чтобы не прерывать активные соединения и корректно завершать работу.

```go
package main

import (
    "context"
    "log"
    "net/http"
    "os"
    "os/signal"
    "syscall"
    "time"
)

func main() {
    srv := &http.Server{Addr: ":8080"}

    go func() {
        if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            log.Fatalf("ListenAndServe: %v", err)
        }
    }()

    // Ожидание сигнала SIGTERM или SIGINT
    quit := make(chan os.Signal, 1)
    signal.Notify(quit, syscall.SIGTERM, syscall.SIGINT)
    <-quit
    log.Println("Получен сигнал завершения, остановка сервера...")

    // Контекст с таймаутом дает время на закрытие активных соединений
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()

    if err := srv.Shutdown(ctx); err != nil {
        log.Printf("Принудительная остановка: %v", err)
    }
    log.Println("Сервер остановлен")
}
```

**Валидация:**
```bash
# Запуск контейнера
docker run -d --name go-app mygo:latest

# Проверка PID 1
docker exec go-app ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
#   1   mygo     /app/server

# Отправка SIGTERM и проверка логов
docker stop go-app && docker logs go-app
# → Получен сигнал завершения, остановка сервера...
# → Сервер остановлен

# Проверка exit code (должен быть 0, не 137)
docker inspect go-app --format='{{.State.ExitCode}}'
# → 0
```

### Сценарий 2: Использование Tini (рекомендуемый подход)

Для приложений на Node.js, Java или Python, которые не умеют корректно работать как PID 1 или порождают дочерние процессы.

```dockerfile
FROM node:22-alpine
RUN apk add --no-cache tini

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production
COPY src/ ./src/

# Tini становится PID 1, приложение — его прямым потомком
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "src/server.js"]
```

**Сигнал в Node.js:**
```javascript
const http = require('http');
const server = http.createServer((req, res) => res.end('OK'));
server.listen(3000);

const shutdown = (signal) => {
  console.log(`Received ${signal}, shutting down...`);
  server.close(() => process.exit(0));
  // Принудительный выход через 30 секунд, если graceful shutdown завис
  setTimeout(() => process.exit(1), 30000);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
```

**Валидация:**
```bash
# Проверка что tini — PID 1
docker exec node-app ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
#   1   tini     /sbin/tini -- node src/server.js

# Поиск зомби-процессов (должно быть пусто)
docker exec node-app ps aux | grep -w Z
# → (нет вывода — зомби не накапливаются)
```

### Сценарий 3: Python multiprocessing

Python multiprocessing порождает дочерние процессы (spawning/forking). Без tini зомби накапливаются, а SIGTERM не достигает воркеров.

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

USER 10001
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "multiprocessing_spawn", "app.py"]
```

**Код приложения:**
```python
import multiprocessing
import signal
import sys
import time

def worker():
    """Рабочий процесс, который обрабатывает задачи."""
    while True:
        time.sleep(1)
        # Обработка задач...

def shutdown_handler(signum, frame):
    """Обработчик SIGTERM для корректного завершения."""
    print(f"Получен сигнал {signum}, завершение воркеров...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Запуск воркеров
    processes = []
    for _ in range(4):
        p = multiprocessing.Process(target=worker)
        p.start()
        processes.append(p)

    # Ожидание завершения (или сигнала через main process)
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()
```

**Валидация:**
```bash
# Проверка что tini — PID 1, python — дочерний
docker exec python-app ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
#   1   tini     /usr/bin/tini -- python -m multiprocessing_spawn app.py

# Проверка воркеров
docker exec python-app ps aux | grep python
# → root         1  0.0  0.0  ...  tini -- python -m multiprocessing_spawn app.py
# → root         7  0.0  0.1  ...  python -m multiprocessing_spawn app.py
# → root         8  0.0  0.1  ...  python worker.py
# → root         9  0.0  0.1  ...  python worker.py
# → root        10  0.0  0.1  ...  python worker.py
# → root        11  0.0  0.1  ...  python worker.py

# Зомби отсутствуют
docker exec python-app ps aux | grep -w Z | wc -l
# → 0
```

### Сценарий 4: Java/Spring Boot

JVM не обрабатывает `SIGTERM` по умолчанию. Spring Boot Actuator предоставляет graceful shutdown через `server.shutdown=graceful`, но для этого сигнал должен достичь процесса Java.

```dockerfile
FROM eclipse-temurin:21-jre-alpine
RUN apk add --no-cache tini

WORKDIR /app
COPY target/app.jar .

# JVM требует больше памяти для метасPACE и кода — MaxRAMPercentage вместо фиксированного -Xmx
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["java", \
     "-XX:MaxRAMPercentage=80.0", \
     "-XX:+UseG1GC", \
     "-Dserver.shutdown=graceful", \
     "-jar", "app.jar"]
```

**application.yml (Spring Boot):**
```yaml
server:
  shutdown: graceful

spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s
```

**Валидация:**
```bash
# Проверка PID 1
docker exec java-app ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
#   1   tini     /sbin/tini -- java -XX:MaxRAMPercentage=80.0 ... -jar app.jar

# Проверка graceful shutdown (должен завершиться с кодом 0)
docker stop --timeout 60 java-app
docker inspect java-app --format='{{.State.ExitCode}}'
# → 0

# Логи должны содержать:
# → Commencing graceful shutdown. Waiting for active requests to complete
# → Graceful shutdown complete
```

### Сценарий 5: Graceful Shutdown воркеров (Consumer Pattern)

Для приложений, разбирающих очереди (RabbitMQ, Kafka, Redis), простого перехвата `SIGTERM` недостаточно. При резком переключении трафика (например, при миграции между серверами) важно не допустить потери или дублирования неидемпотентных задач.

**Алгоритм:**

1.  **Обработка сигнала:** При получении `SIGTERM` воркер переходит в режим «завершения».
2.  **Флаг готовности:** Устанавливается внутренний флаг (например, `is_accepting = false`).
3.  **Перераспределение:** Все новые сообщения, приходящие из очереди, воркер возвращает обратно (`nack` или `reject` с параметром `requeue=true`), чтобы их подхватили другие активные инстансы (например, на новом сервере).
4.  **Завершение текущих задач:** Воркер продолжает обрабатывать те задачи, которые уже взял в работу, до их полного выполнения.
5.  **Таймаут:** В `compose.yml` или манифесте Pod необходимо увеличить `stop_grace_period` до времени выполнения самой долгой задачи.

**Пример на Python:**
```python
import pika
import signal
import sys

is_accepting = True
connection = None
channel = None

def shutdown_handler(signum, frame):
    global is_accepting
    print("SIG получен, остановка приема новых сообщений...")
    is_accepting = False

def callback(ch, method, properties, body):
    if not is_accepting:
        # Возвращаем сообщение обратно в очередь
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        return

    try:
        process_task(body)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
channel = connection.channel()
channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue='tasks', on_message_callback=callback)

print("Ожидание сообщений...")
channel.start_consuming()
```

**Конфигурация Docker Compose:**
```yaml
services:
  worker:
    image: myworker:latest
    stop_grace_period: 120s  # Увеличен для длинных задач
    stop_signal: SIGTERM
```

### Сценарий 6: Entrypoint-скрипт с сохранением сигналов

Типичный сценарий для подготовки окружения перед запуском (миграции БД, проверка зависимостей, настройка переменных).

**Dockerfile:**
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y tini && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
COPY . .

USER 10001
ENTRYPOINT ["/usr/bin/tini", "--", "./entrypoint.sh"]
CMD ["python", "app.py"]
```

**entrypoint.sh:**
```bash
#!/bin/bash
set -euo pipefail

echo "Ожидание готовности БД..."
./wait-for-it.sh db:5432 --timeout=30

echo "Выполнение миграций..."
python manage.py migrate --no-input

echo "Запуск приложения..."
# exec заменяет текущую оболочку (PID 1) приложением
# Без exec оболочка останется PID 1 и будет блокировать сигналы
exec "$@"
```

**Валидация:**
```bash
# Проверка что приложение, а не shell — PID 1
docker exec django-app ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
#   1   python   python app.py

# Если бы exec "$@" отсутствовал:
#   1   bash     /bin/bash ./entrypoint.sh  ← ПЛОХО: shell блокирует сигналы
```

### Сценарий 7: Ограничения ресурсов и OOM

Процесс в контейнере жестко ограничен лимитами Docker/Kubernetes. Непонимание этих ограничений приводит к неожиданным завершениям.

**CPU Throttling:**
Если лимит процессора превышен (например, `--cpus=1.0`), ядро ограничивает кванты времени (throttling). Приложение не завершается, но резко замедляется. Это особенно критично для latency-sensitive приложений и часто ошибочно диагностируется как «сбой сети» или «проблема с БД».

```bash
# Диагностика throttling
docker stats --no-stream
# → CPU% показывает использование относительно лимита

# В Kubernetes: метрики CPU throttling доступны через cAdvisor
# mcpu_usage_seconds_total / mcpu_cfs_throttled_seconds_total
```

**OOM Kill (Exit Code 137):**
Если приложение превышает лимит памяти (RSS), ядро отправляет `SIGKILL`. Приложение **не может** перехватить этот сигнал и завершается мгновенно. Контейнер завершается с кодом 137 (128 + 9).

```bash
# Проверка OOM
docker inspect mycontainer --format='{{.State.OOMKilled}}'
# → true если killed by OOM

# Проверка лимитов
docker inspect mycontainer --format='{{.HostConfig.Memory}}'
# → 0 = без лимита

# Рекомендация: всегда задавайте лимит памяти
docker run -m 512m --memory-swap 512m myapp:latest
```

**Тихий OOM (Silent OOM):**
Особенно опасный случай — когда OOM убивает только дочерний процесс, а PID 1 (например, tini или shell) остается жив. Контейнер продолжает работать, но функциональность нарушена.

```bash
# Симуляция тихого OOM
docker run -d --name test -m 64m python:3.12-slim python -c "
import sys
data = []
while True:
    data.append('x' * 1024 * 1024)  # Утечка памяти ~1MB/итерация
"
# → Контейнер продолжает работать, но python завершился

# Проверка
docker exec test ps aux
# → PID 1: tini (жив), python (мёртв)
# → Функциональность нарушена, но контейнер "Up"
```

## Валидация и диагностика

### Проверка PID 1 в запущенном контейнере

```bash
# Проверка кто является PID 1
docker exec mycontainer ps -p 1 -o pid,comm,args
# → Ожидаемый результат: tini, node, python, java (exec-form)

# Проверка дерева процессов
docker exec mycontainer ps aux --forest
# → PID 1: tini
#   └── PID 7: node server.js
#       ├── PID 12: worker.js (дочерний)
#       └── PID 15: worker.js (дочерний)
```

### Поиск зомби-процессов

```bash
# Поиск зомби (STAT = Z или Z+)
docker exec mycontainer ps aux | grep -w Z
# → root         7  0.0  0.0      0     0 ?        Z    10:05   0:00 [python] <defunct>

# Подсчет количества зомби
docker exec mycontainer ps aux | grep -c -w Z
# → 0 (в норме)

# Если зомби накапливаются — проблема с PID 1
# Решение: добавить tini или исправить обработку SIGCHLD
```

### Проверка exit code контейнера

```bash
# Проверка кода завершения
docker inspect mycontainer --format='{{.State.ExitCode}}'

# Расшифровка кодов:
# 0   — нормальное завершение
# 1   — общая ошибка приложения
# 126 — команда не может быть выполнена (permission denied)
# 127 — команда не найдена (command not found)
# 130 — завершен по SIGINT (Ctrl+C)
# 137 — завершен по SIGKILL (OOM, docker stop timeout)
# 143 — завершен по SIGTERM (нормальное завершение)
```

### Проверка graceful shutdown

```bash
# Запуск с логированием
docker run -d --name test myapp:latest

# Остановка с наблюдением за логами
docker stop test && docker logs -f test
# → Ожидаемый вывод: "SIGTERM получен", "Завершение активных соединений", "Готово"

# Проверка что завершение было graceful (exit code 0)
docker inspect test --format='{{.State.ExitCode}}'
# → 0 (graceful) или 137 (принудительное завершение)
```

### Диагностика STOP timeout

```bash
# Проверка текущего таймаута
docker inspect mycontainer --format='{{.HostConfig.StopTimeout}}'
# → 10 (по умолчанию, секунды)

# Если контейнер завершается с 137 — увеличьте таймаут
docker stop --timeout 60 mycontainer

# Мониторинг времени завершения
time docker stop mycontainer
# → real    0m10.03s  (таймаут по умолчанию)
# → real    0m3.21s   (graceful shutdown за 3 секунды)
```

## Типичные ошибки и их решение

### Ошибка 1: Контейнер не останавливается при docker stop (exit code 137)

**Причина:** Приложение не обрабатывает SIGTERM или обрабатывает слишком долго.

```bash
# Диагностика
docker inspect --format='{{.State.ExitCode}}' mycontainer
# → 137 = 128 + 9 (SIGKILL)

# Проверка PID 1 — возможно shell-blocked
docker exec mycontainer ps -p 1 -o pid,comm,args
# → Если sh/bash — сигнал не доходит до приложения
```

**Решение:**
1. Добавьте обработку SIGTERM в приложение
2. Используйте tini для проброса сигналов
3. Увеличьте `stop_grace_period`
4. Используйте exec-form в CMD/ENTRYPOINT

### Ошибка 2: exec "$@" не заменяет shell

**Причина:** `exec "$@"` используется в entrypoint-скрипте, но shell не завершается.

```bash
# Диагностика
docker exec mycontainer ps aux
# → PID 1: /bin/bash /entrypoint.sh
# → PID 7: python app.py
# → shell всё ещё PID 1!
```

**Решение:** Убедитесь, что `exec "$@"` — последняя команда в скрипте:

```bash
#!/bin/bash
set -euo pipefail
# ... настройка ...
exec "$@"  # ОБЯЗАТЕЛЬНО последней командой
```

### Ошибка 3: Зомби накапливаются

**Причина:** Приложение порождает дочерние процессы, но PID 1 не вызывает `wait()`.

```bash
# Диагностика
docker exec mycontainer ps aux | grep -w Z
# → [python] <defunct>  ← зомби

# Проверка количества
docker exec mycontainer ps aux | grep -c -w Z
# → > 0
```

**Решение:**
1. Установите tini как PID 1
2. Или исправьте приложение: добавьте обработчик `SIGCHLD` с вызовом `wait()`
3. Для Python: `signal.signal(signal.SIGCHLD, lambda s, f: os.waitpid(-1, os.WNOHANG))`

### Ошибка 4: Контейнер завершается сразу (exit code 0)

**Причина:** CMD не определён или нет долгоживущего процесса.

```bash
# Диагностика
docker inspect --format='{{.Config.Cmd}}' myimage
# → null или ["echo", "hello"]

# Проверка entrypoint
docker inspect --format='{{.Config.Entrypoint}}' myimage
```

**Решение:** Определите долгоживущий процесс:

```dockerfile
# ПЛОХО: нет долгоживущего процесса
CMD ["echo", "hello"]

# ХОРОШО: долгоживущий процесс
CMD ["python", "app.py"]
```

## Граничные случаи и ограничения

### Air-gapped среды

В изолированных инфраструктурах (нет доступа в интернет) требуется предварительная подготовка:
- Все базовые образы и зависимости загружаются во внутренний registry.
- Утилиты для отладки (`tini`, `curl`, `procps`) должны присутствовать в образе заранее.
- Сканеры уязвимостей (Trivy, Grype) работают с локальной базой CVE.

**Проверка:**
```bash
# В air-gapped среде docker events недоступен
# Используйте docker logs и docker inspect для диагностики
docker inspect mycontainer --format='{{.State.ExitCode}} {{.State.OOMKilled}}'
```

### Rootless Docker

Rootless Docker запускает демон и контейнеры от непривилегированного пользователя хоста. Это влияет на execution:
- Некоторые системные вызовы (например, `CAP_SYS_ADMIN`) ограничены. `docker exec` работает, но `strace` может требовать дополнительных прав.
- User Namespaces (userns-remap) меняют UID/GID маппинг. `USER 10001` внутри контейнера маппируется на `100000+` на хосте.
- Сеть rootless-контейнера работает через `slirp4netns` или `rootlesskit` с более низкой производительностью, чем `bridge` с правами root.

**Проверка:**
```bash
# Проверка режима
docker info --format '{{.SecurityOptions}}'
# → containerd, userns, rootless ...

# Проверка UID внутри контейнера
docker exec mycontainer id -u
# → 10001 (внутри контейнера), но на хосте это 100000+
```

### Distroless и отладка

В distroless/chiseled образах (`gcr.io/distroless/...`, `chainguard`) нет shell, поэтому `docker exec` стандартными утилитами недоступен.

**Решение:**
- Используйте debug-версии образов только для отладки, не для production: Google Distroless — тег `:debug` (BusyBox); Chainguard — `-dev`-вариант (например, `cgr.dev/chainguard/static:latest-dev`).
- Добавьте временную отладочную стадию в Dockerfile для сбора артефактов.
- Используйте `kubectl debug` (Kubernetes) или `ctr tasks exec` (containerd) с предустановленными утилитами.

```bash
# Ошибка: нет sh в distroless
docker exec mycontainer sh
# → docker: Error response from daemon:OCI runtime exec failed: exec failed: container_linux.go:380: ...

# Решение 1: debug-образ
docker run -it --rm gcr.io/distroless/java21-debian12:debug bash

# Решение 2: kubectl debug (Kubernetes)
kubectl debug -it pod/myapp --image=busybox --target=myapp
```

### Read-only rootfs и временные файлы

Запуск с `--read-only` блокирует запись в корневую ФС. Приложение не сможет создавать временные файлы, сокеты, PID-файлы или логи.

```bash
docker run -d --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m myapp:latest
```

**Ограничения:**
- Все временные директории должны быть явно смонтированы через `--tmpfs`.
- Логирование в файлы внутри контейнера невозможно. Используйте stdout/stderr и Docker logging drivers.
- Некоторые приложения пишут PID-файлы в `/var/run/` — потребуется `--tmpfs /var/run:rw,noexec,nosuid`.

### Multi-platform и эмуляция

Сборка и запуск контейнеров под архитектуру, отличную от архитектуры хоста (например, `linux/arm64` на `linux/amd64`), требует:
- Включенной поддержки QEMU/binfmt_misc: `docker run --rm --privileged multiarch/qemu-user-static --reset -p yes`.
- Учета производительности эмуляции: запуск под QEMU в 5-10 раз медленнее нативного.

```bash
# Проверка поддерживаемых архитектур
docker buildx inspect --bootstrap
# → Platforms: linux/amd64, linux/arm64, linux/riscv64

# Запуск arm64-контейнера на amd64-хосте (с эмуляцией)
docker run --platform linux/arm64 myapp:latest
```

### Потребление ресурсов и cgroups v2

Все ограничения Docker (CPU, память, I/O, PIDs) реализованы через cgroups v2 (Docker 24+). Понимание этих ограничений критично для SRE:

- **CPU Throttling:** При превышении `--cpus` лимита, ядро ограничивает кванты времени. Приложение не завершается, но замедляется. Диагностика: `docker stats` показывает `CPU %` относительно лимита.
- **OOM Kill:** При превышении `--memory` (RSS), ядро отправляет `SIGKILL`. Контейнер завершается с кодом 137. Включите `--memory-swap` равным `--memory` для отключения свопа и предсказуемой производительности.
- **PIDs Limit:** Защита от fork-бомб. `--pids-limit` ограничивает количество процессов в контейнере. Слишком низкое значение (< 50) может сломать приложения с пулом потоков.
- **I/O Throttling:** `--device-read-bps`, `--device-write-bps` ограничивают скорость чтения/записи на блочные устройства.

**SRE-практика:** Все production-контейнеры должны иметь явные лимиты `--cpus`, `--memory`, `--memory-swap` и `--pids-limit`. Без лимитов один контейнер может исчерпить все ресурсы хоста.

### Сигналы и Windows-контейнеры

Windows-контейнеры обрабатывают сигналы иначе, чем Linux:
- Stop timeout по умолчанию: **30 секунд** (вместо 10 секунд в Linux).
- Некоторые сигналы (например, `SIGKILL`) не поддерживаются в Windows-контейнерах. Docker использует `TerminateProcess` для принудительного завершения.
- `docker exec` в Windows-контейнерах работает только через `powershell` или `cmd`, но не поддерживает интерактивный `bash`.

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Форма CMD/ENTRYPOINT** | Всегда exec-form (`["app", "arg"]`) | Обеспечивает прямой PID 1 и проброс сигналов |
| **Init-система** | tini для приложений с дочерними процессами | Обработка зомби и корректный проброс сигналов |
| **Stop Signal** | Явно указывайте в Dockerfile | Приложение может требовать специфический сигнал |
| **Stop Timeout** | Настройте под время graceful shutdown | Избегайте принудительного SIGKILL |
| **Entrypoint скрипт** | Заканчивайте `exec "$@"` | Заменяет shell приложением, PID 1 переходит к приложению |
| **Лимиты ресурсов** | Всегда задавайте `-m` и `--cpus` | Защита от OOM и CPU starvation |
| **Один процесс** | Одна функциональная единица на контейнер | Масштабируемость, мониторинг, логирование |

### Порядок инструкций в Dockerfile

```dockerfile
# 1. FROM
FROM node:22-alpine

# 2. SHELL (если нужен pipefail)
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# 3. WORKDIR
WORKDIR /app

# 4. Системные зависимости (tini)
RUN apk add --no-cache tini

# 5. Кэширование зависимостей
COPY package.json package-lock.json ./
RUN npm ci --production

# 6. Исходный код
COPY src/ ./src/

# 7. Пользователь (безопасность)
USER node

# 8. Entrypoint и команда
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "src/server.js"]
```

### Чек-лист перед деплоем

- [ ] CMD/ENTRYPOINT используют exec-form
- [ ] tini установлен (если есть дочерние процессы)
- [ ] STOPSIGNAL установлен корректно (если отличается от SIGTERM)
- [ ] stop_grace_period настроен под время graceful shutdown
- [ ] Entrypoint-скрипт заканчивается `exec "$@"`
- [ ] Лимиты памяти и CPU заданы
- [ ] Приложение перехватывает SIGTERM и выполняет graceful shutdown
- [ ] Зомби-процессы не накапливаются (проверка через `ps aux | grep Z`)

## Дополнительная информация

### Взаимодействие с Kubernetes

Kubernetes игнорирует `HEALTHCHECK` и `STOPSIGNAL` из Dockerfile. Все параметры управления жизненным циклом задаются в манифесте Pod:

- `terminationGracePeriodSeconds`: Время на завершение (аналог таймаута `docker stop`). По умолчанию 30 секунд. Должно быть больше времени graceful shutdown приложения.
- `preStop hook`: Команда, выполняемая **до** отправки `SIGTERM`. Полезна для задержки (например, `sleep 5` для завершения in-flight запросов до отключения от балансировщика).
- `livenessProbe` / `readinessProbe`: Нативные пробы, заменяющие `HEALTHCHECK`.

```yaml
apiVersion: v1
kind: Pod
spec:
  terminationGracePeriodSeconds: 60
  containers:
  - name: app
    image: myapp:latest
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 5"]
    readinessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 5
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
```

**Важно:** Если `preStop` hook выполняется дольше `terminationGracePeriodSeconds`, контейнер будет принудительно завершен. Убедитесь, что суммарное время `preStop` + graceful shutdown < `terminationGracePeriodSeconds`.

### Смотрите также

- **[Инструкции Dockerfile: Выполнение команд при запуске](../Instructions/runtime_execution.md)** — детальный разбор `CMD` и `ENTRYPOINT`, exec-form vs shell-form, USER.
- **[Инструкции Dockerfile: Сигналы и остановка](../Instructions/health_signals.md)** — использование `STOPSIGNAL`, `HEALTHCHECK`, таблица сигналов.
- **[Коды завершения контейнеров](../../Docker_troubleshooting/docker_exit_codes.md)** — справочник по причинам падения процессов (137, 143 и др.).
- **[Паттерн Multi-Process в Docker](../../Docker_logs/docker_multi_process_logging.md)** — использование `supervisord`, `s6-overlay`, логирование.
- **[Graceful Shutdown в Kubernetes](../../../Kubernetes/Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md)** — специфика оркестрации.
- **[Init Process и tini](../init_process_tini.md)** — подробный разбор tini, dumb-init, интеграция и best practices.
- **[Безопасность в Dockerfile](./security.md)** — `USER`, read-only rootfs, tmpfs, `--security-opt`, capabilities, cgroups v2.
- **[Изоляция Linux](../../Concepts/linux_isolation.md)** — namespaces, cgroups, capabilities, rootfs.
- **[Производительность Docker](../../Docker_performance_tuning.md)** — `docker update`, `docker stats`, лимиты ресурсов, диагностика throttling.
- **[Политики перезапуска и Autoheal](../../Docker_troubleshooting/docker_autoheal.md)** — `restart: always/on-failure`, самовосстановление `unhealthy`-контейнеров.
- **[Лимиты ресурсов — Deep Dive](../../Docker_security/resource_limits.md)** — `--memory`, `--cpus`, `--pids-limit`, cgroups v1/v2, диагностика OOM и throttling.
- **[Конфигурация демона daemon.json](../../docker_daemon_config.md)** — `live-restore`, `log-driver`, `storage-driver`, `registry-mirrors`.
- **[Продвинутые возможности Docker Compose](../../Docker_compose/docker_compose_advanced_topics.md)** — `stop_grace_period`, `init: true`, `healthcheck`, `deploy.resources` в production.
- **[Rolling Update в Docker Swarm](../../../Docker_swarm/swarm_stack_advanced.md)** — стратегии обновления стеков и авто-откат.
- **[Деплой cAdvisor и сбор метрик](../../Docker_metrics/docker_cadvisor_deployment.md)** — per-container метрики CPU, RAM, Network, I/O для Prometheus.
- **[Обзор системы логирования](../../Docker_logs/docker_logging_drivers_overview.md)** — лог-драйверы (`json-file`, `loki`, `gelf`, `fluentd`), ротация.
- **[Паттерны Sidecar в Kubernetes](../../../Kubernetes/Base/Pod/pod_sidecar_patterns.md)** — Sidecar, Ambassador, Adapter — многоконтейнерные паттерны.
- **[Отладка контейнеров](../../Docker_troubleshooting/docker_debug.md)** — `docker exec`, `docker diff`, диагностика внутри контейнера.
- **[Антипаттерны Dockerfile](../dockerfile-anti-patterns.md)** — каталог антипаттернов: shell-form CMD, отсутствие init, секреты в слоях.
