# Docker Exit Codes

## Определения

**Exit Code** — целочисленное значение (0–255), которое возвращает главный процесс контейнера (PID 1) после завершения. Docker транслирует код процесса без изменений.

- **`0`** — успешное завершение
- **`1–255`** — завершение с ошибкой

Общие коды Linux описаны в **[Exit Codes](../../Linux/Shell/exit_codes.md)**.

## Основные концепции

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
| **130** | SIGINT (2) | Прерывание | Ctrl+C, `docker kill -s SIGINT` |
| **137** | SIGKILL (9) | Принудительное завершение | OOM kill, `docker kill` |
| **139** | SIGSEGV (11) | Ошибка сегментации | Баг в приложении (C/C++, native extensions) |
| **143** | SIGTERM (15) | Запрос завершения | `docker stop`, оркестратор |

### OOMKilled

**OOMKilled** — специальный флаг в состоянии контейнера, указывающий на завершение из-за нехватки памяти.

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

**Причина:** Исполняемый файл отсутствует в PATH или не существует.

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
