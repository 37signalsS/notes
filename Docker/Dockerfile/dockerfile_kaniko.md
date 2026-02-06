# Сборка Docker-образов без демона с помощью Kaniko

## Определения

**Kaniko** — это инструмент от Google для сборки образов контейнеров из `Dockerfile` **без зависимости от Docker-демона**. Он выполняет каждую команду `Dockerfile` полностью в пользовательском пространстве (userspace) внутри контейнера, что делает его идеальным для сред с повышенными требованиями к безопасности, таких как CI/CD пайплайны.

### Основные концепции

#### Проблема: Зависимость от Docker-демона

В некоторых окружениях, особенно в CI/CD-пайплайнах (GitLab CI, Jenkins) или внутри Kubernetes-подов, доступ к сокету Docker-демона (`/var/run/docker.sock`) ограничен или отсутствует по соображениям безопасности. Использование подхода "Docker-in-Docker" (`dind`) решает эту проблему, но является сложным в настройке, небезопасным (требует привилегированного режима) и ресурсоемким.

#### Решение: Kaniko

1. Запускается в виде обычного, непривилегированного контейнера.
2. Извлекает файловую систему базового образа.
3. Выполняет каждую команду `Dockerfile`, создавая слои в userspace.
4. Делает снапшот файловой системы после каждой команды и формирует слои на основе разницы снапшотов.
5. Отправляет собранный образ в указанный реестр контейнеров.

#### Преимущества

- **Безопасность:** Не требует привилегированного доступа или монтирования Docker-сокета.
- **Простота:** Легко интегрируется в существующие пайплайны, так как запускается как обычный контейнер.
- **Совместимость с Kubernetes:** Идеально подходит для сборки образов непосредственно в кластере.

### Практические сценарии

#### Сценарий: Сборка образа в GitLab CI

```yaml
build-image:
  stage: build
  image:
    # Рекомендуется использовать debug-образ, так как он содержит shell
    name: gcr.io/kaniko-project/executor:v1.21.0-debug
    entrypoint: [""]
  script:
    # 1. Создание файла конфигурации для аутентификации в реестре
    # Kaniko ожидает найти credentials в /kaniko/.docker/config.json
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    # 2. Запуск сборки и отправка образа
    - /kaniko/executor
        --context "${CI_PROJECT_DIR}"
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}"
```

- **`--context`**: Путь к исходным файлам для сборки.
- **`--dockerfile`**: Путь к `Dockerfile`.
- **`--destination`**: Имя и тег итогового образа.

### Дополнительная информация

#### Кэширование с Kaniko для ускорения сборок

Для ускорения повторных сборок в CI/CD Kaniko поддерживает кэширование слоев в удаленном реестре. Это особенно эффективно для распределенных и эфемерных `runners`.

- **`--cache=true`**: Включает механизм кэширования.
- **`--cache-repo`**: Указывает репозиторий для хранения кэшированных слоев. Если не указан, Kaniko использует репозиторий из `--destination`, добавляя к нему суффикс (например, `/cache`).

**Пример использования с кэшированием в GitLab CI:**

```yaml
build-image-with-cache:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.21.0-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
        --context "${CI_PROJECT_DIR}"
        --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
        --destination "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}"
        --cache=true
        --cache-repo "${CI_REGISTRY_IMAGE}/cache"
```

В этом примере кэшированные слои будут храниться в отдельном образе `${CI_REGISTRY_IMAGE}/cache` в том же реестре.
