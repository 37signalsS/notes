# Init Process в Docker: tini, PID 1, zombie reaping, signal forwarding

**Актуально для:** Tini v0.19.0

## Определения

**Init Process (PID 1)** — первый процесс в PID namespace контейнера, ответственный за обработку сигналов, пожинание завершившихся дочерних процессов и принятие сирот. В Linux ядро treats PID 1 specially: он не получает стандартных обработчиков сигналов (signal disposition) по умолчанию, обязан пожинать (reap) завершившиеся дочерние процессы и становиться adoptive parent для сирот (orphan processes). Если приложение с PID 1 не реализует обработку сигналов и reaping, контейнер будет некорректно завершаться при `docker stop`, а зомби-процессы будут накапливаться в таблице процессов.

**Tini** — легковесная утилита init (~20KB, статически скомпилированная), разработанная специально для контейнеров. Она берёт на себя роль PID 1, корректно пробрасывает сигналы (SIGTERM, SIGINT) к дочерним процессам и автоматически пожинает зомби через системные вызовы `wait()/waitpid()`. Tini не добавляет никакой логики — это максимально минималистичный init, который решает две проблемы: обработку сигналов и zombie reaping.

**Zombie Process (Зомбированный процесс)** — процесс, завершивший выполнение, но всё ещё имеющий запись в таблице процессов (process table), поскольку его родитель (parent) не вызвал `wait()/waitpid()` для получения статуса завершения. Зомби не потребляют CPU и память (кроме записи в process table), но при накоплении исчерпывают PID namespace и могут привести к отказу в создании новых процессов.

**Orphan Process (Сирота)** — процесс, чей родитель завершился. В обычной Linux-системе init (PID 1) автоматически adoptирует сирот и пожинает их. В контейнере без корректного init дочерние процессы сиротами остаются без adopter — их статус никогда не будет собран, и они превращаются в зомби навсегда.

**Signal Forwarding (Проброс сигналов)** — механизм, при котором init-процесс перенаправляет входящие сигналы (SIGTERM, SIGINT, SIGHUP) от ядра/dockerd к своим дочерним процессам. Без этого механизма сигнал SIGTERM от `docker stop` не дойдёт до приложения, если оно не зарегистрировало обработчик явно (а в PID 1 стандартные обработчики отключены ядром).

**Reaping (Пожинание)** — процесс сбора статуса завершения дочерних процессов через системные вызовы `wait()/waitpid()`. После вызова запись зомба удаляется из таблицы процессов. Для PID 1 это обязательная обязанность, инициируемая ядром Linux: если PID 1 не вызывает `wait()`, ядро не отправляет сигнал `SIGCHLD` повторно.

## Базовые концепции

### 1. Почему PID 1 особенный в Linux

В Linux ядро Treat PID 1 differently от всех остальных процессов:

**Default signal disposition:** Обычные процессы получают стандартные обработчики сигналов (например, `SIGTERM` приводит к завершению). Процесс PID 1 **не получает** этих обработчиков по умолчанию. Если приложение не зарегистрировало обработчик `SIGTERM` через `signal()` или `sigaction()`, ядро **не завершит** процесс — сигнал будет проигнорирован. Это сделано для того, чтобы init-процесс системы не был случайно завершён.

**Orphan adoption:** Когда родительский процесс завершается, ядро перепривязывает его дочерние процессы к PID 1 (init) в рамках PID namespace. В контейнере namespace init — это PID 1 контейнера, независимо от того, какое приложение его занимает.

В обычной системе PID 1 — это `init`/`systemd`. В контейнере им может оказаться что угодно:

```bash
$ docker run --rm alpine ps
PID   COMMAND
1     /app/server
7     worker
12    helper
```

Если дочерний процесс становится orphan, ядро перепривязывает его к PID 1. В контексте PID namespace это означает, что любая завершившаяся родительская ветка усыновляется namespace init:

```
# До: worker — родитель child
PID 1
└── worker
    └── child

# После завершения worker:
PID 1
└── child  # PPID изменён на 1
```

Специальное поведение PID 1 определяется ролью namespace init, а не числовым значением PID. Процессы, выступающие как init в своём PID namespace, становятся adoptive parent для всех orphan-процессов этого namespace.

**Zombie reaping:** Ядро отправляет `SIGCHLD` родителю при завершении дочернего процесса. Для PID 1 ядро не повторяет отправку `SIGCHLD` — если PID 1 не вызвал `wait()`/`waitpid()`, зомби-процесс остаётся в таблице процессов indefinitely. Для обычных процессов ядро повторно отправляет `SIGCHLD`, что обеспечивает eventual reaping.

```bash
# Проверка статуса процессов в контейнере
ps -eo pid,ppid,stat,comm

# Поиск процессов в состоянии Z (zombie)
grep -a '^State:' /proc/*/status 2>/dev/null | grep -w Z
```

Накопление зомби приводит к исчерпанию PID namespace (`/proc/sys/kernel/pid_max` по умолчанию ~32768), что блокирует создание новых процессов.

**Граница ответственности:** PID 1 контейнера отвечает только за процессы своего PID namespace. Он не является глобальным init хоста:

```
HOST PID namespace
systemd
└── container process
    └── ...

CONTAINER PID namespace
PID 1
├── app
├── worker
└── orphan → PID 1
```

**Практическое следствие:** Приложение, корректно работающее как обычный процесс на хосте, может накапливать зомби в контейнере, если оно запущено напрямую как PID 1 и не реализует обработку `SIGCHLD`/`wait()`. Для решения проблемы используется init-процесс:

```bash
# Встроенный init Docker
docker run --init myapp
# Вставляет /usr/bin/tini как PID 1 между runtime и приложением
```

### 2. Exec-form vs Shell-form: влияние на PID 1

Выбор формы записи инструкций `ENTRYPOINT` и `CMD` напрямую определяет, какой процесс получит PID 1:

| Exec-form (рекомендуется) | Shell-form |
| :--- | :--- |
| `ENTRYPOINT ["python", "app.py"]` | `ENTRYPOINT python app.py` |
| Процесс запускается напрямую через `execve()` | Запуск через `/bin/sh -c "..."` |
| **Приложение получает PID 1** | **`/bin/sh` получает PID 1** |
| Приложение получает сигналы напрямую | Shell перехватывает и игнорирует сигналы |
| Приложение должно обрабатывать `wait()` | Shell частично обрабатывает zombie reaping |

**Критическая проблема shell-form:** Оболочка `/bin/sh` (или `/bin/bash`) при запуске через shell-form становится PID 1. Большинство оболочек **не пробрасывают сигналы** к дочерним процессам. При `docker stop` оболочка получает `SIGTERM`, игнорирует его (не завершается), и Docker через 10 секунд принудительно убивает контейнер через `SIGKILL` (exit code 137).

```dockerfile
# ПЛОХО: /bin/sh -c получает PID 1, игнорирует сигналы
CMD node server.js

# ХОРОШО: node получает PID 1
CMD ["node", "server.js"]
```

### 3. Как работает tini

Tini реализует паттерн supervisor init через простой алгоритм:

1. **Fork himself:** Tini fork-ается и становится PID 1 в новом PID namespace.
2. **Spawn application:** Запускает указанное приложение как дочерний процесс.
3. **Signal forwarding:** Настраивает обработчик `SIGCHLD` и обработчики для `SIGTERM`, `SIGINT`, `SIGHUP` и других сигналов. При получении сигнала — перенаправляет его дочернему процессу.
4. **Zombie reaping:** В обработчике `SIGCHLD` вызывает `waitpid()` в цикле (с флагом `WNOHANG`), собирая всех завершившихся дочерних процессов.
5. **Exit forwarding:** При завершении дочернего процесса возвращает его exit code как собственный.

```bash
# Простой пример: tini fork-ается, становится PID 1, запускает python
$ docker run --rm alpine tini -- python -c "import os; print(os.getppid())"
1  # python видит tini как родителя (PID 1)
```

**Внутренний механизм tini:**

```
PID 1: tini -- python app.py
  └── PID 7: python app.py
       ├── PID 12: worker1 (дочерний поток/процесс)
       └── PID 15: worker2
```

При завершении worker1/worker2 — tini вызывает `waitpid()` и очищает запись из таблицы процессов. При `SIGTERM` от Docker — tini перенаправляет его к python.

### 4. Флаг -g: проброс сигналов в группы процессов (process groups)

По умолчанию tini отправляет сигнал только одному дочернему процессу (PID прямого потомка). Флаг `-g` (process group forwarding) расширяет это поведение — сигнал отправляется **всем процессам** в группе процессов (process group) приложения:

```bash
# Без -g: сигнал отправляется только PID дочернего процесса
tini -- python app.py

# С -g: сигнал отправляется всем процессам в группе (pgid)
tini -g -- bash -c "python app.py & python worker.py & wait"
```

Это критично для shell-скриптов, которые запускают несколько фоновых процессов. Без `-g` сигнал `SIGTERM` не дойдёт до фоновых воркеров.

**Когда использовать -g:**
- Entrypoint-скрипт запускает несколько процессов через `&` (backgrounding)
- Используется `wait` для ожидания нескольких фоновых процессов
- Нужно гарантировать Graceful Shutdown всех компонентов

### 4.5. Дополнительные флаги tini: subreaper, remapping, parent death signal

Tini предоставляет несколько флагов для продвинутых сценариев, которые не покрыты базовым набором.

**Subreaper mode (`-s` / `TINI_SUBREAPER`):**

По умолчанию tini должен быть PID 1, чтобы пожинать зомби. Если это невозможно (например, при использовании `shareProcessNamespace` в Kubernetes или запуске в уже существующем PID namespace), флаг `-s` регистрирует tini как subreaper через системный вызов `prctl(PR_SET_CHILD_SUBREAPER)`. Тогда все orphan-процессы будут перенаправляться tini, даже если он не PID 1.

```bash
# tini как subreaper (не PID 1)
tini -s -- python app.py

# Через переменную окружения
export TINI_SUBREAPER=1
tini -- python app.py
```

> **Примечание:** Subreaper работает только на ядрах Linux >= 3.4. Tini выводит предупреждение, если запущен не как PID 1 и не зарегистрирован как subreaper.

**Remapping exit code (`-e CODE`):**

Некоторые приложения завершаются с ненулевым exit code при получении сигнала завершения. Например, Java-приложения возвращают `143` (128 + 15 = SIGTERM), что нарушает контракт health check и orchestration. Флаг `-e` перезаписывает указанный exit code на `0`.

```bash
# Java-приложение: SIGTERM → exit 143, перезаписываем в 0
tini -e 143 -- java -jar app.jar
```

**Parent death signal (`-p SIGNAL`):**

Tini может быть сконфигурирован так, чтобы получать сигнал при смерти своего родителя. Это полезно для гарантированной каскадной остановки: если runtime убивает родителя, tini получает указанный сигнал и передаёт его дочернему приложению.

```bash
# Если родитель tini завершается, дочерний процесс получит SIGTERM
tini -p SIGTERM -- python app.py
```

### 5. dumb-init как альтернатива

**dumb-init** — ещё одна lightweight-утилита от Yelp, но с другим функциональным набором:

| Характеристика | tini | dumb-init |
| :--- | :--- | :--- |
| Zombie reaping | Да (waitpid в цикле) | **Нет** |
| Signal forwarding | Да (прямая пересылка) | Да (с возможностью перезаписи) |
| Перезапись сигналов (translation) | Нет | Да (например, SIGTERM->SIGQUIT для JVM) |
| Process group forwarding | Да (`-g`) | Нет |
| Subreaper mode | Да (`-s`) | Нет |
| Exit code remapping | Да (`-e`) | Частично |
| Parent death signal | Да (`-p`) | Нет |
| Размер | ~20KB | ~30KB |
| Встроен в Docker | Да (`--init`) | Нет |
| Установка | `apk add tini` | `apt-get install dumb-init` |

**Когда выбрать dumb-init:**
- Нужна перезапись сигналов (например, Java-приложение реагирует на `SIGQUIT`, а не `SIGTERM`)
- Нет дочерних процессов, которые могут стать зомби
- Нужна простая перезапись без проброса

```dockerfile
# Пример: Java/Gradle нужен SIGQUIT вместо SIGTERM
RUN apt-get update && apt-get install -y dumb-init
ENTRYPOINT ["dumb-init", "--rewrite", "15:3", "--", "java", "-jar", "app.jar"]
# SIGTERM (15) будет перезаписан в SIGQUIT (3)
```

### 6. s6-overlay и supervisord для multi-process контейнеров

Для контейнеров с несколькими долгоживущими процессами (front + back + cron) tini alone не достаточно. Рассмотрите:

**s6-overlay** (рекомендуется для контейнеров):
- Интегрируется с tini как PID 1 (или сам выступает init)
- Предоставляет сервис-менеджер с автоматическим перезапуском
- Поддерживает dependency injection между сервисами
- Минимальный overhead (~100KB)

```dockerfile
FROM alpine:3.21
RUN apk add --no-cache s6-overlay
COPY /etc/s6-overlay/s6-rc.d/ /etc/s6-overlay/s6-rc.d/
COPY init /etc/s6-overlay/init
ENTRYPOINT ["/init"]
```

**supervisord** (классический подход):
- Python-based process manager
-более тяжёлый (~5MB), но зрелый и гибкий
- Настройка через INI-файлы

```ini
# /etc/supervisor/conf.d/app.conf
[program:web]
command=python app.py
autostart=true
autorestart=true

[program:worker]
command=python worker.py
autostart=true
autorestart=true
```

```dockerfile
RUN pip install supervisor
COPY supervisord.conf /etc/supervisor/conf.d/
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```

**Важно:** Даже с supervisord/s6 рекомендуется использовать tini или --init как PID 1 для корректного zombie reaping и signal forwarding.

### 6.5. Оркестраторы и контейнерные runtime

Поведение init-процесса зависит от runtime и оркестратора. Ключевое правило: **Docker `--init` работает только в Docker**. В Kubernetes, Podman и других runtime init должен быть встроен в образ.

#### Kubernetes

Kubernetes **не поддерживает** флаг `--init` или аналогичный механизм runtime injection. Об этом известно открытой issue с 2019 года (kubernetes/kubernetes#84210). В Kubernetes tini/dumb-init/catatonit должны быть частью образа.

```dockerfile
# Правильно для Kubernetes: tini встроен в ENTRYPOINT
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
```

**Жизненный цикл завершения Pod в Kubernetes:**

1. Pod помечается как `Terminating` — удаляется из endpoints
2. Выполняется `preStop` hook (если определён)
3. В каждый контейнер отправляется `SIGTERM`
4. Запускается обратный отсчёт `terminationGracePeriodSeconds` (по умолчанию 30с)
5. После истечения grace period: `SIGKILL`

Если PID 1 не обрабатывает `SIGTERM`, grace period тратится впустую, после чего следует принудительное завершение. При частых деплоях это суммируется в значительные задержки.

```yaml
# docker-compose.yml с stop_grace_period
services:
  web:
    image: myapp
    init: true
    stop_grace_period: 30s
```

**Альтернатива: `shareProcessNamespace`:**

Kubernetes позволяет включить общий PID namespace для всех контейнеров в Pod через `shareProcessNamespace: true`. В этом случае pause-контейнер становится PID 1 для всего Pod и пожинает зомби. Однако:

- Signal handling остаётся ответственностью каждого контейнера отдельно
- Опция отключена по умолчанию с Kubernetes 1.8
- Изменяет видимость процессов (`/proc/1/cmdline` теперь указывает на pause)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app
spec:
  shareProcessNamespace: true
  containers:
  - name: app
    image: myapp
    # tini всё ещё рекомендуется для signal forwarding
```

> **Важно:** `initContainers` Kubernetes — это не init-процесс PID 1. Они выполняются последовательно перед основными контейнерами и завершаются. Их задача — подготовка окружения, а не обработка сигналов.

#### Podman

Podman включает встроенный init через флаг `--init`. В отличие от Docker (который использует tini), Podman по умолчанию использует **catatonit** — активно поддерживаемый форк от openSUSE. Catatonit последний релиз — декабрь 2024, имеет сигналы signal forwarding и zombie reaping, но не поддерживает signal rewriting и exit code remapping.

```bash
podman run --init myapp
```

#### Windows containers

Tini — это Linux-специфичная утилита, использующая системные вызовы Linux (`waitpid`, `prctl`). В Windows containers аналогичная проблема PID 1 решается иначе: Windows имеет встроенный процесс `csrss`/`wininit`, который обрабатывает orphan adoption, а signal forwarding реализован через Windows Events и Job Objects.

Для Windows контейнеров используйте:
- Встроенные механизмы Windows Service
- PowerShell `Register-ObjectEvent` для обработки остановки
- Docker HEALTHCHECK для мониторинга состояния

#### Shell-скрипты и `exec`

Entrypoint-скрипты на shell создают дополнительный процесс, который может стать источником проблем с сигналами. Правило: всегда используйте `exec "$@"` в конце скрипта, чтобы заменить shell-процесс на целевое приложение.

```bash
#!/bin/bash
# entrypoint.sh
set -euo pipefail

# Инициализация
python migrate.py

# КРИТИЧНО: exec заменяет shell на целевое приложение
exec "$@"
```

Без `exec` shell остаётся PID 1 (или родителем для tini), и сигналы могут обрабатываться неправильно. Tini пробросит сигнал shell-скрипту, но если скрипт не завершается, сигнал не дойдёт до приложения.

## Практические сценарии

### 1. Базовое использование tini в Dockerfile

Минимальная конфигурация для приложений с дочерними процессами.

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

USER 10001
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
```

**Проверка:**
```bash
docker build -t myapp .
docker run -d --name test myapp
docker exec test ps -p 1 -o pid,comm,args
# PID   COMMAND  COMMAND
#   1   tini     /usr/bin/tini -- python app.py
```

### 2. tini с argument forwarding (ENTRYPOINT + CMD)

Паттерн разделения init и аргументов приложения.

```dockerfile
FROM node:22-alpine
RUN apk add --no-cache tini
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production
COPY src/ ./src/

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "src/server.js", "--port", "3000"]
```

**Результат при разных запусках:**
```bash
docker run myapp                           # tini -- node src/server.js --port 3000
docker run myapp node src/worker.js        # tini -- node src/worker.js
docker run --entrypoint /bin/sh myapp      # tini -- /bin/sh (CMD игнорируется)
```

### 3. Демонстрация накопления зомби без tini

Сравнение поведения контейнеров с и без init.

**Dockerfile без tini (проблема):**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY zombie_demo.py .
CMD ["python", "zombie_demo.py"]
```

```python
# zombie_demo.py
import os, time, signal

def create_zombie():
    pid = os.fork()
    if pid == 0:
        # Дочерний процесс: немедленно завершается
        os._exit(0)
    else:
        # Родитель: НЕ вызывает waitpid() - процесс становится зомбом
        print(f"Created child PID {pid}, not reaping it")
        time.sleep(1)

if __name__ == "__main__":
    # Создаём 5 зомби
    for i in range(5):
        create_zombie()
    print("Zombies created, check 'ps aux | grep Z' in container")
    time.sleep(3600)
```

```bash
# Запуск без tini
docker run -d --name no-tini myapp-no-tini
docker exec no-tini ps aux | grep -w Z
# root  7  0.0  0.0  0  0 ? Z 10:05 0:00 [python] <defunct>
# root  8  0.0  0.0  0  0 ? Z 10:05 0:00 [python] <defunct>
# root  9  0.0  0.0  0  0 ? Z 10:05 0:00 [python] <defunct>
# root 10  0.0  0.0  0  0 ? Z 10:05 0:00 [python] <defunct>
# root 11  0.0  0.0  0  0 ? Z 10:05 0:00 [python] <defunct>

# С tini - зомби не накапливаются
docker run -d --name with-tini myapp-with-tini
docker exec with-tini ps aux | grep -w Z
# (пустой вывод)
```

### 4. Тест проброса сигналов: docker stop

Демонстрация разницы во времени завершения при использовании tini.

**Сценарий без tini:**
```bash
$ docker run -d --name no-signal myapp-no-tini
$ time docker stop no-signal
# (ожидание ~10 секунд)
# real 0m10.234s  - Docker отправил SIGKILL после таймаута

$ docker inspect --format='{{.State.ExitCode}}' no-signal
# 137 (128 + 9 = SIGKILL)
```

**Сценарий с tini:**
```bash
$ docker run -d --name with-signal myapp-with-tini
$ time docker stop with-signal
# (мгновенное завершение)
# real 0m0.512s  - приложение обработало SIGTERM и завершилось

$ docker inspect --format='{{.State.ExitCode}}' with-signal
# 0 (корректное завершение)
```

**Python-приложение с обработкой SIGTERM:**
```python
import signal, sys

def handle_sigterm(*args):
    print("Received SIGTERM, shutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

if __name__ == "__main__":
    import time
    print("Server running...")
    while True:
        time.sleep(1)
```

### 5. tini -g для multi-process контейнеров (shell script)

Shell-скрипт запускает несколько фоновых процессов — флаг `-g` гарантирует проброс сигналов ко всем.

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY entrypoint.sh .
COPY . .
RUN chmod +x entrypoint.sh
USER 10001
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["./entrypoint.sh"]
```

```bash
#!/bin/bash
# entrypoint.sh
set -euo pipefail

# Запуск нескольких процессов в фоне
python web_server.py &
python worker.py &
python scheduler.py &

# Ожидание завершения любого из процессов
# tini -g отправит SIGTERM ВСЕМ процессам в группе
wait
```

**Без `-g` при `docker stop`:**
```bash
$ docker exec multi-pg ps aux
# PID 1:  tini -- ./entrypoint.sh
# PID 7:  bash ./entrypoint.sh (PROCESS GROUP LEADER)
# PID 8:  python web_server.py   <- получает SIGTERM
# PID 12: python worker.py       <- НЕ получает SIGTERM (не в группе leader-а)
# PID 16: python scheduler.py    <- НЕ получает SIGTERM
```

**С `-g` при `docker stop`:**
```bash
# Все процессы получают SIGTERM одновременно
# Graceful shutdown всех компонентов
```

### 6. Compose: init: true

Docker Compose предоставляет встроенную поддержку tini через директиву `init`.

```yaml
# docker-compose.yml
services:
  web:
    build: .
    init: true
    command: python app.py
    stop_grace_period: 30s

  worker:
    build: .
    init: true
    command: python worker.py
```

**Эквивалентно:**
```bash
docker run --init myapp python app.py
# --init автоматически вставляет /usr/bin/tini как PID 1
```

**Проверка:**
```bash
$ docker compose up -d
$ docker compose exec web ps -p 1 -o pid,comm,args
# PID   COMMAND  COMMAND
#   1   tini     /usr/bin/tini -- python app.py
```

### 7. Отладка проблем с PID 1

Инструменты и команды для диагностики проблем с init process.

```bash
# Проверка PID 1 в запущенном контейнере
docker exec mycontainer ps -p 1 -o pid,comm,args
# PID   COMMAND  COMMAND
#   1   python   python app.py

# Поиск зомби-процессов
docker exec mycontainer ps aux | grep -w Z
# USER  PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
# root   7  0.0  0.0   0   0 ?   Z   10:05 0:00 [python] <defunct>

# Просмотр статуса PID 1
docker exec mycontainer cat /proc/1/status | head -5
# Name:   python
# State:  S (sleeping)
# Tgid:   1
# Ngid:   1
# Pid:    1

# Проверка обработчиков сигналов PID 1
docker exec mycontainer cat /proc/1/status | grep Sig
# SigPnd: 0000000000000000
# SigBlk: 0000000000000000
# SigIgn: 0000000000000000
# SigCgt: 0000000000000002

# Просмотр количества процессов в контейнере
docker exec mycontainer ps -e --no-headers | wc -l

# Просмотр дочерних процессов PID 1
docker exec mycontainer pstree -p 1

# Проверка exit code после остановки
docker inspect --format='{{.State.ExitCode}}' mycontainer
# 0   = корректное завершение
# 137 = SIGKILL (принудительное завершение)
# 143 = SIGTERM (только если обработан)
```

### 8. Когда НЕ нужно использовать tini

Однопроцессные Go/Rust-приложения с правильной обработкой сигналов могут работать без init.

```dockerfile
# Go-приложение без дочерних процессов
FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /server .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /server /server
USER nonroot:nonroot
ENTRYPOINT ["/server"]
# tini НЕ нужен: Go-приложение обрабатывает сигналы и нет дочерних процессов
```

**Приложение на Go с обработкой сигналов:**
```go
package main

import (
    "context"
    "log"
    "net/http"
    "os"
    "os/signal"
    "syscall"
)

func main() {
    srv := &http.Server{Addr: ":8080"}

    go func() {
        if err := srv.ListenAndServe(); err != http.ErrServerClosed {
            log.Fatalf("ListenAndServe: %v", err)
        }
    }()

    quit := make(chan os.Signal, 1)
    signal.Notify(quit, syscall.SIGTERM, syscall.SIGINT)
    <-quit

    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()
    srv.Shutdown(ctx)
}
```

**Критерии для использования tini:**
- Приложение порождает дочерние процессы (subprocess, fork, worker threads)
- Используется shell-скрипт как entrypoint без `exec "$@"`
- Контейнер запускает несколько процессов через shell
- Приложение не реализует обработку SIGTERM/SIGINT

**Когда tini НЕ нужен:**
- Однопроцессное Go/Rust-приложение без дочерних процессов
- Приложение реализует корректную обработку сигналов и zombie reaping
- Используется distroless/scratch образ с minimal PID 1

## Дополнительная информация

### Сравнительная таблица init-инструментов

| Инструмент | Zombie reaping | Signal forwarding | Process groups | Перезапись сигналов | Subreaper | Exit remap | Размер | Встроен в Docker |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **tini** | Да | Да | `-g` | Нет | Да (`-s`) | Да (`-e`) | ~20KB | Да (`--init`) |
| **dumb-init** | Нет | Да | Нет | Да (`--rewrite`) | Нет | Нет | ~30KB | Нет |
| **s6-overlay** | Да | Да | Да | Да | Да | Да | ~100KB | Нет |
| **supervisord** | Частично | Нет | Нет | Нет | Нет | Нет | ~5MB | Нет |
| **--init (Docker)** | Да | Да | Нет | Нет | Нет | Нет | N/A | Да |

### Размер и производительность overhead

Tini добавляет минимальный overhead:
- **Размер образа:** +20KB (statistically negligible)
- **Потребление памяти:** ~1MB resident memory
- **Время старта:** +1-2ms (fork overhead)
- **CPU:** пренебрежимо мало (только обработка SIGCHLD)

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Контейнер завершается с exit code 137 | Приложение не обрабатывает SIGTERM | Используйте tini или добавьте обработчик |
| Накопление зомби-процессов | PID 1 не вызывает wait() | Используйте tini для zombie reaping |
| `docker stop` занимает 10+ секунд | Shell-form игнорирует сигналы | Используйте exec-form или tini |
| Зомби накапливаются при fork | Нет init для reaping | Добавьте tini или --init |
| Сигнал не доходит до фоновых процессов | tini без `-g` для группы процессов | Используйте `tini -g` |
| OOM при большом количестве процессов | Исчерпание PID namespace зомбами | Используйте tini для автоматического reaping |
| Entrypoint-скрипт без `exec "$@"` | Shell остаётся между tini и приложением | Добавьте `exec "$@"` в конец скрипта |
| Java-приложение завершается с exit code 143 | SIGTERM возвращается как ненулевой код | Используйте `tini -e 143` |
| Tini предупреждает "not PID 1" | Запуск без subreaper в не-PID-1 | Добавьте `-s` или `TINI_SUBREAPER=1` |

### Установка tini в разных образах

```dockerfile
# Alpine Linux
RUN apk add --no-cache tini

# Debian/Ubuntu
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*

# RHEL/CentOS/Fedora
RUN yum install -y tini && yum clean all

# Arch Linux
RUN pacman -S --noconfirm tini

# Или статическая сборка (без пакетного менеджера)
RUN curl -fsSL -o /usr/local/bin/tini https://github.com/krallin/tini/releases/download/v0.19.0/tini-static && \
    chmod +x /usr/local/bin/tini
```

### Сценарии production

**Одинаковое поведение в Docker и Kubernetes:**

Если образ планируется использовать в Docker и Kubernetes, встраивайте tini в Dockerfile, а не полагайтесь на `docker run --init` или `init: true`. Kubernetes не поддерживает runtime injection.

```dockerfile
# Универсальный Dockerfile для Docker и K8s
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
```

**Distroless и scratch образы:**

Минимальные образы не содержат пакетного менеджера. Используйте статический бинарник tini:

```dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /server .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /usr/local/bin/tini-static /tini
COPY --from=builder /server /server
ENTRYPOINT ["/tini", "--"]
CMD ["/server"]
```

**Java-приложения с exit code 143:**

Java-приложения завершаются с exit code 143 при SIGTERM, так как JVM не перехватывает сигнал по умолчанию. Используйте remapping или dumb-init:

```dockerfile
# Вариант A: tini с remapping exit code
ENTRYPOINT ["/usr/bin/tini", "-e", "143", "--"]
CMD ["java", "-jar", "app.jar"]

# Вариант B: dumb-init с rewrite
ENTRYPOINT ["dumb-init", "--rewrite", "15:3", "--"]
CMD ["java", "-jar", "app.jar"]
```

**Multi-stage сборки с тINI:**

Если builder stage использует tini для health checks или скриптов, а final stage — нет, убедитесь, что бинарник tini копируется корректно:

```dockerfile
FROM alpine:3.21 AS builder
RUN apk add --no-cache tini

FROM alpine:3.21
COPY --from=builder /sbin/tini /sbin/tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "app.py"]
```

## Связанные документы

**См. также:**
- **[container_execution.md](./Docker_best_practices/container_execution.md)** — паттерны multi-process, Graceful Shutdown, OOM.
- **[health_signals.md](./Instructions/health_signals.md)** — инструкции HEALTHCHECK и STOPSIGNAL, проброс сигналов.
- **[runtime_execution.md](./Instructions/runtime_execution.md)** — инструкции CMD, ENTRYPOINT, USER и решение проблемы PID 1.
- **[docker_multi_process_logging.md](../../Docker_logs/docker_multi_process_logging.md)** — логирование multi-process контейнеров.
- **[linux_isolation.md](../../Docker/Concepts/linux_isolation.md)** — изоляция Linux: namespaces, cgroups, PID namespace.
- **[docker_exit_codes.md](../../Docker_troubleshooting/docker_exit_codes.md)** — справочник по exit code (137, 143 и др.).
- **[docker_compose_directives.md](../../Docker_compose/docker_compose_directives.md)** — директива `init:` в Docker Compose.
