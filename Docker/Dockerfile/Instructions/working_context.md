# Инструкции Dockerfile: Рабочий Контекст

## Определения

**WORKDIR** — инструкция Dockerfile, устанавливающая текущий рабочий каталог для всех последующих инструкций `RUN`, `CMD`, `ENTRYPOINT`, `COPY` и `ADD`.

**SHELL** — инструкция Dockerfile, определяющая оболочку по умолчанию для выполнения команд в инструкциях `RUN`, `CMD` и `ENTRYPOINT` в формате shell.

## Основные концепции

### WORKDIR

Устанавливает текущий рабочий каталог. Если каталог не существует, он будет создан.

**Синтаксис:**

```dockerfile
WORKDIR /path/to/directory
WORKDIR /app
WORKDIR /var/www/html
```

**Особенности:**

- Может использоваться несколько раз в Dockerfile
- Поддерживает как абсолютные, так и относительные пути
- Относительные пути разрешаются относительно предыдущего `WORKDIR`

**Пример:**

```dockerfile
WORKDIR /app
COPY . .
RUN npm install
WORKDIR /app/dist
RUN npm run build
```

### SHELL

Позволяет переопределить оболочку по умолчанию (`/bin/sh -c` для Linux).

**Синтаксис:**

```dockerfile
SHELL ["/bin/bash", "-c"]
SHELL ["/bin/sh", "-c"]
```

**Пример PowerShell на Windows:**

```dockerfile
SHELL ["powershell", "-Command"]
RUN Write-Host 'Hello, World!'
```

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

## Дополнительная информация

- Рекомендуется всегда использовать `WORKDIR` вместо абсолютных путей в `COPY` или `RUN`
- `WORKDIR` автоматически создаёт директорию, если она не существует
- Подробнее об оптимизации см. **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)**
