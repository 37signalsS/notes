# Инструкции Dockerfile: Выполнение Команд При Запуске

## Определения

**`CMD`** — инструкция, задающая команду по умолчанию, выполняемую при запуске контейнера без аргументов.

**`ENTRYPOINT`** — инструкция, настраивающая контейнер как исполняемый файл. Аргументы из командной строки **добавляются** к ENTRYPOINT.

## Основные концепции

### CMD vs ENTRYPOINT

Обе инструкции задают команду при запуске, но работают по-разному:

- **`CMD`:** Команда по умолчанию. Если контейнер запускается с аргументами, `CMD` игнорируется.
- **`ENTRYPOINT`:** Контейнер работает как исполняемый файл. Аргументы из `docker run` **добавляются** к `ENTRYPOINT`.

**Взаимодействие:**

```dockerfile
ENTRYPOINT ["/bin/echo", "Hello"]
CMD ["world"]
```

- `docker run <image>` → `Hello world`
- `docker run <image> John` → `Hello John`

### Формы записи: Shell vs Exec

| Форма | Синтаксис | Особенности |
| :--- | :--- | :--- |
| Shell | `CMD myapp --config prod.yaml` | Выполняется через `/bin/sh -c`. Поддерживает переменные `$VAR`. |
| Exec | `CMD ["/myapp", "--config", "prod.yaml"]` | Выполняется напрямую через `execve`. Работает в `distroless`/`scratch`. |

> ⚠️ **Важно:** В образах `gcr.io/distroless/static` и `FROM scratch` **отсутствует `/bin/sh`**. Shell-форма приведёт к ошибке.

### Запуск в режиме Foreground

Docker отслеживает процесс PID 1. Когда он завершается — контейнер останавливается.

| Режим | Пример | Проблема |
| :--- | :--- | :--- |
| Foreground | `CMD ["nginx", "-g", "daemon off;"]` | ✅ Правильно |
| Background (daemon) | `CMD ["nginx"]` | ❌ Контейнер сразу завершится |

## Практические сценарии

### Сценарий 1: Python-приложение

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
```

### Сценарий 2: Go-бинарник (exec form)

```dockerfile
FROM scratch
COPY app /app
ENTRYPOINT ["/app"]
```

### Сценарий 3: Nginx

```dockerfile
FROM nginx:alpine
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Сценарий 4: Скрипт-обёртка для подстановки переменных

```dockerfile
FROM alpine
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD []
```

```bash
#!/bin/sh
echo "Starting $APP_NAME"
exec "$@"
```

## Дополнительная информация

- Подробнее о переопределении CMD/ENTRYPOINT см. **[Практические сценарии](./practical_scenarios.md)**
- Подробнее об оптимизации образов (distroless, scratch) см. **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)**
- Подробнее об отладке distroless см. **[Отладка distroless-контейнеров](../../Docker_troubleshooting/debugging_distroless.md)**
