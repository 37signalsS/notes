# Гайд: Развертывание Spring Boot-приложения с помощью GitLab CI и Docker

В данном руководстве подробно рассматривается процесс настройки CI/CD-пайплайна в GitLab для сборки, тестирования и развертывания Java Spring Boot-приложения с использованием Docker.

Для понимания основных концепций, таких как Pipeline, Stage, Job, Runner и Artifact, обратитесь к базовому документу [Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md).

## Схема работы

Алгоритм развертывания следующий:
1.  Разработчик отправляет код в GitLab-репозиторий.
2.  GitLab обнаруживает файл `.gitlab-ci.yml` и запускает пайплайн.
3.  **Этап `build`**:
    *   Запускается задача сборки Docker-образа с помощью [Kaniko](https://docs.gitlab.com/ee/ci/docker/using_kaniko.html), что позволяет избежать использования Docker-in-Docker.
    *   Собранный образ помещается в [GitLab Container Registry](../../../Docker/docker_registries.md).
4.  **Этап `deploy`**:
    *   Задача запускается **вручную** для контроля над развертыванием в production-окружении.
    *   GitLab Runner подключается к удаленному серверу по SSH.
    *   С помощью `docker compose` скачивается новый образ из GitLab Registry и перезапускается контейнер с приложением.

---

## 1. Настройка виртуального сервера

### Шаг 1: Установка Docker

Для быстрой установки Docker на тестовом или рабочем окружении можно использовать официальный скрипт.

```bash
# Скачиваем скрипт установки
curl -fsSL https://get.docker.com -o get-docker.sh

# Запускаем скрипт для установки Docker и его зависимостей
sudo sh ./get-docker.sh
```

### Шаг 2: Запуск GitLab Runner в Docker

В данном примере используется собственный Runner, развернутый на том же сервере, где будет работать приложение.

```bash
# Запускаем контейнер с GitLab Runner
docker run -d --name gitlab-runner --restart always 
  -v /srv/gitlab-runner/config:/etc/gitlab-runner 
  -v /var/run/docker.sock:/var/run/docker.sock 
  gitlab/gitlab-runner:alpine
```
*   `-v /var/run/docker.sock:/var/run/docker.sock`: Пробрасываем сокет Docker внутрь контейнера, чтобы Runner мог управлять Docker-демоном на хост-машине.

### Шаг 3: Регистрация Runner в проекте

Для привязки Runner к вашему проекту его необходимо зарегистрировать.
Перейдите в репозиторий проекта: `Settings > CI/CD > Runners`. Скопируйте токен регистрации.

```bash
# Запускаем команду регистрации в интерактивном режиме
docker run --rm -it -v /srv/gitlab-runner/config:/etc/gitlab-runner gitlab/gitlab-runner:alpine register 
  --non-interactive 
  --url "https://gitlab.com/" 
  --registration-token <ВАШ_REGISTRATION_TOKEN> 
  --executor docker 
  --description "Docker Runner для Spring Boot проекта" 
  --tag-list "docker" 
  --docker-image alpine:latest 
  --docker-privileged 
  --docker-volumes "/certs/client"
```
После выполнения в UI GitLab появится новый "Project runner".

### Шаг 4: Аутентификация Docker на сервере

Чтобы сервер мог скачивать образы из приватного GitLab Container Registry, необходимо выполнить вход.
1.  Создайте Personal Access Token: `User Profile > Access Tokens`. Дайте ему права `read_registry` и `write_registry`.
2.  На сервере выполните команду:

```bash
# registry.gitlab.com - для облачной версии GitLab
docker login registry.gitlab.com -u <ВАШ_USERNAME> -p <ВАШ_ACCESS_TOKEN>
```

### Шаг 5: Настройка SSH-доступа для деплоя

GitLab CI будет использовать SSH для подключения к серверу на этапе развертывания.

```bash
# 1. Генерируем SSH-ключ на сервере
ssh-keygen -t rsa -b 4096 -C "gitlab-ci-deploy"

# 2. Добавляем публичный ключ в список авторизованных
cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys

# 3. Выводим приватный ключ, чтобы скопировать его в переменные CI/CD
cat ~/.ssh/id_rsa
```

### Шаг 6: Настройка переменных в GitLab CI/CD

Перейдите в `Settings > CI/CD > Variables` и добавьте переменные:

*   **`SSH_PRIVATE_KEY`**:
    *   **Type**: `File`
    *   **Value**: Вставьте содержимое приватного ключа (`id_rsa`), скопированное на предыдущем шаге.
*   **`SERVER_USER`**:
    *   **Type**: `Variable`
    *   **Value**: Имя пользователя для SSH-подключения (например, `root` или другой).
*   **`SERVER_HOST`**:
    *   **Type**: `Variable`
    *   **Value**: IP-адрес вашего сервера.
*   **`ENV_FILE`**:
    *   **Type**: `File`
    *   **Value**: Содержимое файла с переменными окружения для `docker-compose`. Например:
        ```
        TEST_SERVICE_PORT=8080
        OPEN_API_TITLE=My Spring App
        ```

---

## 2. Конфигурация файлов проекта

### `docker-compose.yml`

```yaml
version: '3.9'
services:
  core:
    container_name: spring-application
    image: ${CI_REGISTRY_IMAGE}:latest # Используем предопределенную переменную GitLab
    environment:
      TEST_SERVICE_PORT: ${TEST_SERVICE_PORT}
      OPEN_API_TITLE: ${OPEN_API_TITLE}
    ports:
      - "8081:${TEST_SERVICE_PORT}" # Пробрасываем порт 8081 хоста на порт приложения
    logging:
      driver: 'json-file'
      options:
        max-size: '100m'
        max-file: '3'
```

### `Dockerfile`

```dockerfile
FROM maven:3.8-openjdk-17-slim

RUN mkdir -p /home/app
WORKDIR /home/app

ADD pom.xml /home/app
ADD src /home/app/src

RUN mvn clean package

CMD ["java", "-jar", "/home/app/target/test-0.0.1-SNAPSHOT.jar"]
```

### `.gitlab-ci.yml`

```yaml
stages:
  - build
  - deploy

build-only-MR:
  stage: build
  tags:
    - docker # Указываем, что задача должна выполняться на Runner'е с этим тегом
  image:
    name: gcr.io/kaniko-project/executor:v1.9.2-debug
    entrypoint: [ "" ]
  script:
    - /kaniko/executor
      --context "${CI_PROJECT_DIR}"
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
      --no-push # Не отправляем образ в Registry
  only:
    - merge_requests

build:
  stage: build
  tags:
    - docker
  image:
    name: gcr.io/kaniko-project/executor:v1.9.2-debug
    entrypoint: [ "" ]
  script:
    - /kaniko/executor
      --context "${CI_PROJECT_DIR}"
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
      --destination "${CI_REGISTRY_IMAGE}:latest" # Отправляем образ в Registry проекта
  only:
    - main

deploy:
  stage: deploy
  image: docker:20.10-git
  tags:
    - gitlab-org-docker # Используем общий Runner от GitLab.com для деплоя
  variables:
    DOCKER_HOST: "ssh://${SERVER_USER}@${SERVER_HOST}"
  before_script:
    - mkdir -p ~/.ssh
    - chmod 700 ~/.ssh
    - eval $(ssh-agent -s)
    - echo "${SSH_PRIVATE_KEY}" | tr -d '' | ssh-add -
    - '[[ -f /.dockerenv || -d /run/secrets/kubernetes.io/serviceaccount ]] && echo -e "Host *
	StrictHostKeyChecking no

" > ~/.ssh/config'
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker compose --env-file $ENV_FILE pull
    - docker compose --env-file $ENV_FILE down --timeout=60 --remove-orphans
    - docker compose --env-file $ENV_FILE up --build --detach
    - docker image prune -f || true
  only:
    - main
  when: manual # Запускать задачу только вручную
```

---

## 3. Анализ `.gitlab-ci.yml`

*   **`stages`**: Определены два этапа: `build` и `deploy`.
*   **`build-only-MR`**: Собирает Docker-образ для Merge Request'ов, но не публикует его (`--no-push`). Это позволяет проверить, что проект успешно собирается, не загрязняя Registry.
*   **`build`**: Собирает образ при коммите в `main` и публикует его в GitLab Container Registry с тегом `latest`.
*   **`deploy`**:
    *   Выполняется вручную (`when: manual`) для контроля релиза.
    *   Использует стандартный образ `docker:20.10-git`.
    *   В `before_script` настраивается SSH-соединение с удаленным сервером с использованием переменных `SSH_PRIVATE_KEY`, `SERVER_USER`, `SERVER_HOST`.
    *   `DOCKER_HOST` перенаправляет команды локального Docker CLI на Docker-демон удаленного сервера.
    *   В `script` происходит обновление и перезапуск сервисов через `docker compose`.
