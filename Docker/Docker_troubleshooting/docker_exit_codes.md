# Коды завершения Docker (Exit Codes)

## Определения

**Exit Code (Код завершения)** — целочисленное значение (0–255), которое возвращает главный процесс контейнера (**PID 1 — Process Identifier 1**) после завершения. Docker транслирует код процесса операционной системе без изменений.

- **`0`** — успешное завершение
- **`1–255`** — завершение с ошибкой

Общие коды Linux описаны в **[Exit Codes](../../Linux/Shell/exit_codes.md)**.

## Базовые концепции

### Категории кодов

| Диапазон | Причина | Источник |
| :--- | :--- | :--- |
| **0** | Успех | Приложение |
| **1–125** | Ошибка приложения | Приложение |
| **125** | Ошибка `docker run` | Docker |
| **126** | Нет прав на исполнение | Shell |
| **127** | Команда не найдена | Shell |
| **128+N** | Завершение по сигналу | Ядро Linux |

### Коды сигналов (формула `128 + N`)

| Код | Сигнал | Описание | Типичная причина |
| :--- | :--- | :--- | :--- |
| **130** | **SIGINT (Signal Interrupt — прерывание)** | Прерывание с клавиатуры | Ctrl+C, `docker kill -s SIGINT` |
| **137** | **SIGKILL (Signal Kill — принудительное завершение)** | Принудительное завершение | **OOM kill (Out of Memory — нехватка памяти)**, `docker kill` |
| **139** | **SIGSEGV (Signal Segmentation Violation — ошибка сегментации)** | Ошибка сегментации | Баг в приложении (C/C++, native extensions) |
| **143** | **SIGTERM (Signal Terminate — запрос завершения)** | Запрос корректного завершения | `docker stop`, оркестратор |

### OOMKilled

**OOMKilled** — специальный флаг в состоянии контейнера, указывающий на завершение из-за нехватки оперативной памяти.

```bash
# Проверка OOMKilled
docker inspect <container> --format '{{.State.OOMKilled}}'

# Полный вывод состояния
docker inspect <container> --format '{{json .State}}'
```

**Диагностика:**

- `OOMKilled: true` → контейнер превысил лимит памяти
- `OOMKilled: false` + код 137 → внешнее вмешательство (`docker kill`, системный монитор)

## Практические сценарии

### Сценарий 1: Диагностика по коду завершения

```bash
# Получить код завершения
docker inspect <container> --format '{{.State.ExitCode}}'

# Получить причину ошибки
docker inspect <container> --format '{{.State.Error}}'

# Проверить OOMKilled
docker inspect <container> --format '{{.State.OOMKilled}}'
```

### Сценарий 2: Код 137 (SIGKILL) — OOM kill

**Симптомы:** Контейнер завершается с кодом 137.

```bash
# Проверка OOMKilled
docker inspect <container> --format 'OOMKilled: {{.State.OOMKilled}}'

# Проверка лимитов памяти
docker inspect <container> --format 'Memory: {{.HostConfig.Memory}}'

# Просмотр логов ядра
dmesg | grep -i "killed process"
```

**Решение:**

1. Увеличить лимит памяти: `docker run -m 512m ...`
2. Оптимизировать потребление памяти приложением
3. Проверить утечки памяти (memory leaks)

### Сценарий 3: Код 143 (SIGTERM) — Graceful Shutdown

**Симптомы:** Контейнер завершается с кодом 143 после `docker stop`.

**Причина:** Приложение не обрабатывает SIGTERM корректно.

**Решение:**

```dockerfile
# Dockerfile — правильная обработка сигналов
FROM node:20-alpine
WORKDIR /app
COPY . .

# SIGTERM handler в приложении
# process.on('SIGTERM', () => {
#   server.close(() => process.exit(0));
# });

CMD ["node", "server.js"]
```

**Проверка:**

```bash
# Запуск контейнера
docker run -d --name myapp myimage

# Отправка SIGTERM
docker stop myapp

# Проверка кода
docker inspect myapp --format '{{.State.ExitCode}}'
# Ожидается: 0 (если graceful shutdown реализован)
```

### Сценарий 4: Код 126 — Нет прав на исполнение

**Симптомы:** Exit code 126 сразу после старта.

**Причина:** У entrypoint/cmd скрипта нет прав на исполнение.

**Решение:**

```dockerfile
# Неправильно
COPY entrypoint.sh /entrypoint.sh
CMD ["/entrypoint.sh"]

# Правильно
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
```

### Сценарий 5: Код 127 — Команда не найдена

**Симптомы:** Exit code 127, контейнер не стартует.

**Причина:** Исполняемый файл отсутствует в **PATH (переменная окружения со списком путей к исполняемым файлам)** или не существует.

**Решение:**

```dockerfile
# Проверка существования файла
RUN ls -la /app/myapp

# Использование абсолютного пути
CMD ["/app/myapp"]

# Или добавление в PATH
ENV PATH="/app/bin:$PATH"
CMD ["myapp"]
```

### Сценарий 6: Код 139 (SIGSEGV) — Ошибка сегментации

**Симптомы:** Exit code 139, приложение падает без логов.

**Причина:** Обращение к невалидной памяти (баги C/C++, native extensions).

**Диагностика:**

```bash
# Включение core dump
docker run --ulimit core=-1 myapp

# Анализ core dump
gdb /app/myapp core
```

**Решение:** Отладка приложения, обновление зависимостей, отчёт разработчику.

### Сценарий 7: Exited сразу после запуска

**Симптомы:** Контейнер уходит в `Exited` мгновенно или через секунду после `docker run`.

**Причина:** **PID 1** (процесс из `ENTRYPOINT`/`CMD`) завершается — контейнер жив, пока жив PID 1.

**Алгоритм диагностики:**

```bash
# 1. Логи — что процесс успел выдать до смерти
docker logs <container-id>

# 2. Состояние контейнера — ExitCode, OOMKilled, Error
docker inspect <container-id> --format '{{json .State}}'
```

**Быстрая интерпретация ExitCode:**

| Код | Значение | Действие |
| :--- | :--- | :--- |
| **0** | Штатное завершение | Процесс выполнил работу и вышел (однократная задача, job) |
| **1** | Ошибка приложения | Смотреть `docker logs` (конфиг, БД, переменные окружения) |
| **137** | SIGKILL | Проверить `OOMKilled: true` — нехватка памяти |
| **139** | SIGSEGV (segfault) | Баг в C/C++, native-расширениях |

**Частые причины и их диагностика:**

1. **Приложение — демон (background process):** Процесс отсоединяется от терминала, PID 1 завершается, контейнер падает. Решение — `daemon off;` (Nginx), `--foreground` (Apache) или просто не демонизировать. Подробнее: [Выполнение приложений в контейнере](../Dockerfile/Docker_best_practices/container_execution.md).

2. **Бинарь несовместим с базовым образом (musl vs glibc):** `ldd` показывает зависимости от **glibc (GNU C Library — стандартная библиотека языка C)**, а образ на `alpine` (**musl libc**). Ошибка: `exec format error` или `/bin/sh: not found`. Решение — **CGO_ENABLED=0 (инструмент Go для вызова функций C)** + статическая линковка для Go, либо использовать `debian:bookworm-slim`. Подробнее: [Проблема несовместимости libc (Alpine)](./alpine_glibc_compatibility.md).

3. **Конфиг не найден / невалидный:** Приложение не может прочитать конфигурационный файл или переменные окружения не заданы. Проверка: `docker logs`, `docker inspect` → `Error` поле.

4. **OOMKilled:** Контейнер убит за превышение лимита памяти. Проверка: `docker inspect` → `OOMKilled: true`. Подробнее: [Сценарий 2: Код 137](#сценарий-2-код-137-sigkill-oom-kill).

## Дополнительная информация

### Быстрая справка

| Код | Действие |
| :--- | :--- |
| **1–125** | Изучить логи приложения: `docker logs <container>` |
| **126** | Проверить права: `chmod +x` в Dockerfile |
| **127** | Проверить PATH и существование файла |
| **137** | Проверить OOMKilled, увеличить память |
| **139** | Debug приложения, core dump |
| **143** | Реализовать graceful shutdown |

### Связанные темы

- **[Exit Codes](../../Linux/Shell/exit_codes.md)** — общие коды Linux
- **[Health Signals](../Dockerfile/Instructions/health_signals.md)** — сигналы остановки
- **[Debugging with Events](./debugging_with_docker_events.md)** — события Docker

### Примечания

- Коды 1–125 зависят от приложения — сверяйтесь с документацией
- Docker отправляет SIGTERM при `docker stop`, затем SIGKILL через 10с
- Для изменения сигнала остановки используйте `STOPSIGNAL` в Dockerfile
