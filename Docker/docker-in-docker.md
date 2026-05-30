# Docker-in-Docker (DinD): Запуск Docker внутри контейнера

## Определения

**Docker-in-Docker (DinD)** — подход, позволяющий запускать Docker-демон и управлять контейнерами внутри другого Docker-контейнера. Используется в CI/CD-пайплайнах для создания изолированных сред сборки и тестирования.

**Docker-out-of-Docker (DooD)** — альтернативный подход, при котором контейнер подключается к Docker-демону хоста через монтирование сокета (`/var/run/docker.sock`). Контейнеры создаются на уровне хоста, а не внутри контейнера.

## Основные концепции

### 1. Подход: Docker-in-Docker (официальный образ docker:dind)

Официальный образ `docker:dind` запускает полноценный Docker-демон внутри контейнера. Требует привилегированного режима (`--privileged`), так как демону нужен доступ к cgroups, namespaces и устройству `/dev/fuse`.

**Архитектура:**

```
Хост (dockerd)
 └── Контейнер (dockerd — привилегированный)
      ├── Контейнер A
      ├── Контейнер B
      └── Контейнер C
```

**Преимущества:**

- Полная изоляция: контейнеры DinD не видны демону хоста
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

- Равносильно root-доступу к хосту: через сокет можно смонтировать любую директорию хоста
- Нет изоляции: контейнеры соседствуют с основными на хосте
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

Важно: Монтирование с флагом `:ro` (read-only) не защищает — Docker API не является read-only API. Даже с `:ro` контейнер может создавать новые контейнеры, монтировать файловые системы хоста и выполнять команды. Подробнее см. в [Обзор безопасности Docker](./Docker_security/overview.md).

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
| **CI/CD пригодность** | Да | Да | Да |
| **Запуск контейнеров** | Да | Да | Нет (только сборка) |

### 4. Настройка прав доступа при монтировании директорий

При использовании DinD и DooD часто возникают сложности с правами доступа к файлам (UID/GID) при монтировании директорий с хоста или между контейнерами.

Подробные решения (именованные тома, совпадение UID/GID, entrypoint-скрипты) описаны в SSoT-файле: **[Настройка прав доступа при монтировании](./Docker_fs/docker_volumes.md#настройка-прав-доступа-при-монтировании-директорий)**.

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

Параметры:
- `DOCKER_TLS_CERTDIR` — включает TLS-аутентификацию между контейнером и DinD.
- `services` — GitLab CI запускает DinD как sidecar-контейнер.

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

Безопасность: Runner с доступом к сокету эквивалентен root-доступу. Используйте только для доверенных пайплайнов. Альтернатива — Kaniko.

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
      - postgres-data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d:ro,Z
    user: "999:999"  # UID/GID пользователя postgres в контейнере

volumes:
  postgres-data:
    driver: local
```

## Дополнительная информация

### Рекомендации по безопасности

1. **Избегайте DinD, если возможно:** Используйте Kaniko или Buildah для сборки образов.
2. **Ограничивайте доступ к сокету:** Никогда не монтируйте `/var/run/docker.sock` в недоверенные контейнеры.
3. **DinD только в изолированных CI/CD:** Привилегированный режим допустим только в эфемерных CI-раннерах.
4. **Используйте именованные тома:** Для данных приложений — избегайте bind mount в production.
5. **Настраивайте UID/GID явно:** Для bind mount — документируйте ожидаемые UID/GID в README.

### См. также

- **[Kaniko: Сборка без демона](./Dockerfile/dockerfile_kaniko.md)** — безопасная альтернатива DinD
- **[Обзор безопасности Docker](./Docker_security/overview.md)** — векторы атак через сокет
- **[Тома и персистентное хранение](./Docker_fs/docker_volumes.md)** — управление данными
