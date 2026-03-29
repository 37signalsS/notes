# Инструкции Dockerfile: Рабочий Контекст

## Определения

**`WORKDIR`** — инструкция Dockerfile, устанавливающая текущий рабочий каталог для всех последующих инструкций `RUN`, `CMD`, `ENTRYPOINT`, `COPY` и `ADD`.

**`SHELL`** — инструкция Dockerfile, определяющая оболочку по умолчанию для выполнения команд в инструкциях `RUN`, `CMD` и `ENTRYPOINT` в формате shell.

## Основные концепции

### `WORKDIR`

Устанавливает текущий рабочий каталог. Если каталог не существует, он будет создан автоматически.

**Синтаксис:**

```dockerfile
WORKDIR /path/to/directory
```

**Поведение:**

| Характеристика | Описание |
| :--- | :--- |
| **Создание директории** | Автоматически создаёт, если не существует |
| **Количество использований** | Может использоваться несколько раз в Dockerfile |
| **Типы путей** | Поддерживает абсолютные и относительные пути |
| **Разрешение относительных путей** | Относительно предыдущего `WORKDIR` |
| **Переменные окружения** | Поддерживает подстановку `$VAR` и `${VAR}` |

**Пример с последовательными `WORKDIR`:**

```dockerfile
WORKDIR /a
WORKDIR b
WORKDIR c
RUN pwd  # Вывод: /a/b/c
```

**Пример с переменными окружения:**

```dockerfile
ENV DIRPATH=/path
ENV DIRNAME=app
WORKDIR $DIRPATH/$DIRNAME
RUN pwd  # Вывод: /path/app
```

> **Важно:** По умолчанию рабочая директория — `/`. Всегда явно устанавливайте `WORKDIR` для предсказуемости сборки.

### `SHELL`

Позволяет переопределить оболочку по умолчанию (`/bin/sh -c` для Linux).

**Синтаксис:**

```dockerfile
SHELL ["/bin/bash", "-c"]
```

**Поведение:**

| Характеристика | Описание |
| :--- | :--- |
| **Формат** | Требует JSON array (exec form) |
| **Применение** | К последующим инструкциям в shell form |
| **Не влияет на** | Инструкции в exec form (`CMD ["..."]`, `ENTRYPOINT ["..."]`) |
| **По умолчанию** | `/bin/sh -c` (Linux), `cmd /S /C` (Windows) |

**Пример PowerShell на Windows:**

```dockerfile
SHELL ["powershell", "-Command"]
RUN Write-Host 'Hello, World!'
```

**Пример с bash-специфичными конструкциями:**

```dockerfile
SHELL ["/bin/bash", "-c"]
RUN if [[ -f /etc/os-release ]]; then \
      cat /etc/os-release; \
    fi
```

> **Важно:** `SHELL` влияет только на shell form инструкций. Exec form (`["command", "arg"]`) выполняется напрямую без оболочки.

## Практические сценарии

### Сценарий 1: Node.js приложение

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["node", "index.js"]
```

### Сценарий 2: Многоэтапная сборка Go

```dockerfile
FROM golang:1.22 AS builder
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 go build -o main .

FROM scratch
WORKDIR /
COPY --from=builder /app/main .
ENTRYPOINT ["/main"]
```

### Сценарий 3: Использование SHELL для сложных команд

```dockerfile
SHELL ["/bin/bash", "-c"]
RUN echo "Hello" >> /file.txt && \
    cat /file.txt
```

### Сценарий 4: Python-приложение с виртуальным окружением

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install -r requirements.txt
ENV PATH="/opt/venv/bin:$PATH"
COPY . .
CMD ["python", "app.py"]
```

### Сценарий 5: Windows-контейнер с PowerShell

```dockerfile
FROM mcr.microsoft.com/windows/nanoserver:ltsc2022
SHELL ["powershell", "-Command"]
RUN New-Item -Path C:\app -ItemType Directory -Force
WORKDIR C:\app
COPY . .
CMD ["pwsh", "-File", "app.ps1"]
```

### Сценарий 6: Организация структуры проекта

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
WORKDIR /app/src
COPY src/ ./src
WORKDIR /app/tests
COPY tests/ ./tests
CMD ["npm", "test"]
```

## Дополнительная информация

Рекомендуется всегда использовать `WORKDIR` вместо абсолютных путей в `COPY` или `RUN` — это делает Dockerfile более читаемым и переносимым. `WORKDIR` автоматически создаёт директорию, если она не существует. Подробнее об оптимизации см. **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)**.
