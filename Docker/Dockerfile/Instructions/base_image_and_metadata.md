# Инструкции Dockerfile: Базовый Образ и Метаданные

## Определения

**Базовый образ** — начальный образ системы, от которого наследуется новый образ. Определяется инструкцией `FROM`.

**Метаданные образа** — информация об образе (автор, версия, описание), добавляемая через инструкции `LABEL`.

## Основные концепции

### `FROM`

Определяет базовый образ для сборки нового образа. Для повышения безопасности от подмены образа (например, на Docker Hub) рекомендуется указывать хэш образа (`FROM <image>@sha256:<digest>`). Дайджест (хэш) образа можно получить из вывода команды `docker pull my-image:tag`.

> Подробнее о верификации образов см. **[Подпись и верификация образов](../../Docker_security/image_signature_and_verification.md)**

Если тег не указан (например, `FROM debian`), Docker по умолчанию использует тег `latest`. **Важно:** При изменении образа, на который указывает тег `latest`, образ будет пересобираться.

### Метаданные

#### `MAINTAINER` (Устаревшая инструкция)

Инструкция `MAINTAINER` использовалась для указания автора образа.

```dockerfile
FROM ubuntu:14.04
MAINTAINER "Вася Пупкин <vasya@example.com>"
RUN apt-get update
```

**Важно:** Эта директива была помечена как устаревшая (`deprecated`) в Docker-версии 1.13 и её использование не рекомендуется. Причина в том, что `MAINTAINER` была слишком специфичной и позволяла указать только автора.

#### `LABEL`

Используется для добавления метаданных (меток) к образу. Это современный и гибкий подход по сравнению с `MAINTAINER`. `LABEL` позволяет добавлять любую информацию в формате `ключ-значение`.

**Пример использования метаданных (включая OCI-стандарт):**

```dockerfile
FROM ubuntu:22.04
LABEL maintainer="vasya@example.com"
LABEL version="1.0.0"
LABEL description="Мой крутой микросервис"
LABEL org.opencontainers.image.title="My Application"
LABEL org.opencontainers.image.description="Description of my application"
LABEL org.opencontainers.image.source="https://github.com/vasya/my-app"
LABEL org.opencontainers.image.authors="Vasya Pupkin <vasya@example.com>"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.licenses="MIT"
```

> **Примечание:** Использование префикса `org.opencontainers.image.*` обеспечивает совместимость с OCI (Open Container Initiative) и поддерживается большинством современных registry.

## Практические сценарии

### Пример: Использование digest для безопасности

```dockerfile
# Вместо FROM ubuntu:22.04 (тег может измениться)
FROM ubuntu@sha256:1408f3f47e7d2fec5c1a5b6b8c8e5c8b8c8e5c8b8c8e5c8b8c8e5c8b8c8e5c
```

## Дополнительная информация

- Инструкция `FROM` должна быть первой в Dockerfile (после обязательных комментариев и директив)
- Рекомендуется использовать конкретные теги версий вместо `latest` для воспроизводимости сборок
- Для языковых образов (Node.js, Python, Go) существуют официальные образы с оптимизированными дистрибутивами (например, `node:alpine`)
- Подробнее об оптимизации размера образов см. **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)**
