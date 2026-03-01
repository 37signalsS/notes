# Инструкции Dockerfile: Рабочий Контекст

## Определения

**WORKDIR** — инструкция Dockerfile, устанавливающая текущий рабочий каталог для всех последующих инструкций `RUN`, `CMD`, `ENTRYPOINT`, `COPY` и `ADD`.

**SHELL** — инструкция Dockerfile, определяющая оболочку по умолчанию для выполнения команд в инструкциях `RUN`, `CMD` и `ENTRYPOINT` в формате shell.

## Основные концепции

### WORKDIR

Устанавливает текущий рабочий каталог для всех последующих инструкций. Если каталог не существует, он будет создан.

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

Позволяет переопределить оболочку по умолчанию (`/bin/sh -c` для Linux, `powershell` или `cmd` для Windows).

**Синтаксис:**

```dockerfile
SHELL ["/bin/bash", "-c"]
SHELL ["/bin/sh", "-c"]
```

**Пример использования PowerShell на Windows:**

```dockerfile
SHELL ["powershell", "-Command"]
RUN Write-Host 'Hello, World!'
```

## Практические сценарии

### Сценарий: Создание рабочей директории для приложения

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["node", "index.js"]
```

### Сценарий: Использование SHELL для сложных команд

```dockerfile
SHELL ["/bin/bash", "-c"]
RUN echo "Hello" >> /file.txt && \
    cat /file.txt
```

## Дополнительная информация

- Рекомендуется всегда использовать `WORKDIR` вместо указания абсолютных путей в каждой инструкции `COPY` или `RUN`
- `WORKDIR` автоматически создает директорию, если она не существует
