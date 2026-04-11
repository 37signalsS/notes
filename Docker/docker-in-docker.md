# Docker-in-Docker (DinD): Запуск Docker внутри контейнера

## Определения

**Docker-in-Docker (DinD)** — подход, позволяющий запускать Docker-демон и управлять контейнерами внутри другого Docker-контейнера. Используется в CI/CD-пайплайнах, для создания изолированных сред сборки и тестирования.

**Docker-out-of-Docker (DooD)** — альтернативный подход, при котором контейнер подключается к Docker-демону хоста через монтирование сокета (`/var/run/docker.sock`). Контейнеры создаются на уровне хоста, а не внутри контейнера.

## Основные концепции

### 1. Подход: Docker-in-Docker (официальный образ `docker:dind`)

Официальный образ `docker:dind` запускает полноценный Docker-демон внутри контейнера. Требует **привилегированного режима** (`--privileged`), так как демону нужен доступ к cgroups, namespaces и устройству `/dev/fuse`.

**Архитектура:**
```
Хост (dockerd)
 └── Контейнер (dockerd — привилегированный)
      ├── Контейнер A
      ├── Контейнер B
      └── Контейнер C
```

**Преимущества:**
- Полная изоция: контейнеры DinD не видны демону хоста
- Чистая среда: каждый запуск начинает с нуля
- Идеально для CI/CD: воспроизводимые сборки

**Недостатки и риски:**
- Требует `--privileged` — полный доступ к хосту (риск контейнер-эксплойта)
- Вложенная виртуализация: производительность ниже на 10–30%
- Двойное хранение: образы и слои дублируются на хосте и внутри DinD
- Сложность отладки: логи и артефакты внутри вложенного демона

**Пример запуска:**
```bash
docker run --privileged -d --name dind docker:27-dind
docker exec -it dind docker run --rm hello-world
```

### 2. Подход: Docker-out-of-Docker (монтирование сокета)

Контейнер получает доступ к Docker API хоста через Unix-сокет. Docker CLI внутри контейнера отправляет команды демону на хосте.

**Архитектура:**
```
Хост (dockerd)
 ├── Контейнер A (с доступом к /var/run/docker.sock)
 ├── Контейнер B (создан через сокет)
 └── Контейнер C (создан через сокет)
```

**Преимущества:**
- Нет привилегированного режима — безопаснее
- Образы хранятся на хосте — экономия места и кэширование
- Простая отладка: все контейнеры видны через `docker ps` на хосте

**Недостатки и риски:**
- **Равносильно root-доступу к хосту:** через сокет можно смонтировать любую директорию хоста
- Нет изоляции: контейнеры "соседствуют" с основными на хосте
- Конфликты имён: несколько пайплайнов могут создать контейнеры с одинаковыми именами

**Пример с docker-compose:**
```yaml
services:
  builder:
    image: docker:27-cli
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: docker build -t myapp .
```

> **Важно:** Монтирование с флагом `:ro` (read-only) **не защищает** — Docker API не является readOnly API. Даже с `:ro` контейнер может создавать новые контейнеры, монтировать файловые системы хоста и выполнять команды.

### 3. Подход: Kaniko (сборка без демона)

**[Kaniko](./Dockerfile/dockerfile_kaniko.md)** — альтернатива DinD для сборки образов. Выполняет сборку в userspace без Docker-демона.

**Сравнение подходов:**

| Критерий | DinD (`docker:dind`) | DooD (socket mount) | Kaniko |
| :--- | :--- | :--- | :--- |
| **Изоляция** | Полная | Отсутствует | Полная |
| **Привилегии** | `--privileged` | Нет | Нет |
| **Безопасность** | Низкая | Низкая | Высокая |
| **Производительность** | Средняя (-10–30%) | Высокая | Высокая |
| **Кэширование образов** | Внутреннее | На хосте | В реестре |
| **CI/CD пригодность** | Да | Да | Да (рекомендуется) |
| **Запуск контейнеров** | Да | Да | Нет (только сборка) |

### 4. Настройка прав доступа при монтировании директорий

При использовании bind mount (монтирование директории хоста) возникают проблемы с правами доступа.

#### Проблема UID/GID

Процессы внутри контейнера работают под определёнными UID/GID. Если UID контейнера не совпадает с владельцем файлов на хосте, возникают ошибки `Permission Denied`.

**Пример проблемы:**
```bash
# На хосте файл принадлежит пользователю 1000
ls -ln /srv/data/config.yml
# -rw-r--r-- 1 1000 1000 1234 Apr 10 12:00 config.yml

# В контейнере процесс работает под UID 1001
docker run --rm -v /srv/data:/data alpine ls -la /data/config.yml
# -rw-r--r-- 1 1000 1000 1234 Apr 10 12:00 config.yml (владелец не совпадает)

# Попытка записи приведёт к Permission Denied
```

#### Решение 1: Именованные тома (рекомендуется)

Именованные тома управляются Docker и автоматически решают проблему прав:

```bash
# Создание тома
docker volume create app-config

# Монтирование — Docker сам управляет правами
docker run -d --name myapp \
  --mount type=volume,source=app-config,target=/etc/config \
  myapp:latest
```

**Преимущества:**
- Не нужно управлять UID/GID вручную
- Изоляция от файловой системы хоста
- Автоматическое создание с правильными правами

**Недостатки:**
- Путь на хосте управляется Docker (`/var/lib/docker/volumes/`)
- Сложнее прямой доступ к файлам с хоста

#### Решение 2: Bind mount с настройкой прав

Когда нужен прямой доступ к конкретной директории на хосте:

**Вариант A — совпадение UID/GID:**
```bash
# Узнать UID процесса в контейнере
docker run --rm myapp id
# uid=1000(appuser) gid=1000(appuser)

# Изменить владельца файлов на хосте
sudo chown -R 1000:1000 /srv/data

# Запустить с bind mount
docker run -d --name myapp \
  -v /srv/data:/data \
  myapp:latest
```

**Вариант B — запуск с нужным UID:**
```bash
# Запустить контейнер с UID, совпадающим с владельцем файлов
docker run -d --name myapp \
  --user 1000:1000 \
  -v /srv/data:/data \
  myapp:latest
```

**Вариант C — `docker-compose.yml` с инициализацией прав:**
```yaml
services:
  app:
    image: myapp:latest
    user: "1000:1000"
    volumes:
      - ./data:/data
    # Контейнер выполнит chown при старте
    command: >
      sh -c "chown -R 1000:1000 /data && exec /app/start.sh"
```

**Вариант D — использование флагов SELinux `:z` и `:Z`:**
```bash
# :z — общий доступ для нескольких контейнеров
docker run -v /srv/data:/data:z myapp:latest

# :Z — эксклюзивный доступ для одного контейнера (меняет контекст)
docker run -v /srv/data:/data:Z myapp:latest
```

> **Примечание:** Флаги `:z`/`:Z` работают только на системах с SELinux. На системах без SELinux они игнорируются.

#### Решение 3: Инициализация через entrypoint

Для сложных сценариев создают entrypoint-скрипт, который настраивает права при старте:

```bash
#!/bin/sh
# entrypoint.sh

# Если передан UID/GID — применяем
if [ -n "$APP_UID" ] && [ -n "$APP_GID" ]; then
  chown -R "${APP_UID}:${APP_GID}" /data
fi

# Переключаемся на нужного пользователя
exec gosu "${APP_UID:-1000}:${APP_GID:-1000}" "$@"
```

```dockerfile
# Dockerfile
FROM alpine:3.20
RUN apk add --no-cache gosu
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/app/start.sh"]
```

```bash
# Запуск
docker run -d --name myapp \
  -e APP_UID=1000 -e APP_GID=1000 \
  -v /srv/data:/data \
  myapp:latest
```

## Практические сценарии

### Сценарий 1: CI/CD с DinD (GitLab CI)

Используется для сборки и тестирования в изолированной среде:

```yaml
build:
  stage: build
  image: docker:27
  services:
    - docker:27-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker build -t myapp:${CI_COMMIT_SHA} .
    - docker push myapp:${CI_COMMIT_SHA}
```

**Параметры:**
- `DOCKER_TLS_CERTDIR` — включает TLS-аутентификацию между контейнером и DinD
- `services` — GitLab CI запускает DinD как sidecar-контейнер

### Сценарий 2: Тестирование с DooD (монтирование сокета)

Для локальной разработки, когда нужен доступ к образам хоста:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd):/workspace \
  docker:27-cli \
  sh -c "cd /workspace && docker build -t test:local ."
```

### Сценарий 3: GitLab Runner с доступом к сокету

Регистрация Runner'а с монтированием сокета для сборки образов:

```bash
docker run -d --name gitlab-runner \
  --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:latest
```

> **Безопасность:** Runner с доступом к сокету эквивалентен root-доступу. Используйте только для доверенных пайплайнов. Альтернатива — Kaniko (см. [Сценарий 4](#сценарий-4-cicd-с-kaniko-без-dind)).

### Сценарий 4: CI/CD с Kaniko (без DinD)

Рекомендуемый подход для сборки образов в Kubernetes/GitLab CI:

```yaml
build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.24.0-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor \
        --context "${CI_PROJECT_DIR}" \
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile" \
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}"
```

Подробнее: **[Kaniko: Сборка без демона](./Dockerfile/dockerfile_kaniko.md)**.

### Сценарий 5: kind (Kubernetes in Docker) с DinD

Локальный Kubernetes-кластер в Docker-контейнере:

```bash
kind create cluster --name local-dev
# kind использует DinD для создания нод как Docker-контейнеров
```

Подробнее: **[kind: Практические сценарии](../Kubernetes/Installation/kind/kind_practical_scenarios.md)**.

### Сценарий 6: Монтирование директории с настройкой прав (compose)

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: secret
    volumes:
      # Именованный том — права управляются автоматически
      - postgres-data:/var/lib/postgresql/data
      # Bind mount для инициализации — с флагом :Z для SELinux
      - ./init-scripts:/docker-entrypoint-initdb.d:ro,Z
    user: "999:999"  # UID/GID пользователя postgres в контейнере

volumes:
  postgres-data:
    driver: local
```

## Дополнительная информация

### Рекомендации по безопасности

1. **Избегайте DinD, если возможно:** Используйте Kaniko или Buildah для сборки образов
2. **Ограничивайте доступ к сокету:** Никогда не монтируйте `/var/run/docker.sock` в недоверенные контейнеры
3. **DinD только в изолированных CI/CD:** Привилегированный режим допустим только в эфемерных CI-раннерах
4. **Используйте именованные тома:** Для данных приложений — избегайте bind mount в production
5. **Настраивайте UID/GID явно:** Для bind mount — документируйте ожидаемые UID/GID в README

### См. также

- **[Kaniko: Сборка без демона](./Dockerfile/dockerfile_kaniko.md)** — безопасная альтернатива DinD
- **[Обзор безопасности Docker](./Docker_security/overview.md)** — векторы атак через сокет
- **[Тома и персистентное хранение](./Docker_fs/docker_volumes.md)** — управление данными
- **[Защита хоста и демона](./Docker_security/host_daemon_hardening.md)** — userns-remap, Rootless
- **[kind: Практические сценарии](../Kubernetes/Installation/kind/kind_practical_scenarios.md)** — Kubernetes в Docker
