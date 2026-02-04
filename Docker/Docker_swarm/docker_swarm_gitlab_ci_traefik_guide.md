# CI/CD с Docker Swarm, GitLab и Traefik

## Определения

- **[Docker Swarm](../docker_swarm_overview.md):** Нативная система оркестровки контейнеров от Docker, позволяющая объединять несколько хостов в единый виртуальный Docker-хост (кластер). Используется для развертывания и масштабирования сервисов.
- **[GitLab CI/CD](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md):** Встроенный в GitLab инструмент для автоматизации сборки, тестирования и развертывания приложений (CI/CD). Пайплайны описываются в файле `.gitlab-ci.yml`.
- **[Traefik](../../WebServers/Traefik/traefik_overview.md):** Современный обратный прокси и балансировщик нагрузки, который автоматически обнаруживает сервисы (Service Discovery) и управляет маршрутизацией трафика к ним, включая автоматическое управление SSL-сертификатами.

## Базовые концепции

### Архитектура решения

Предлагаемая архитектура представляет собой полный CI/CD-процесс, где **GitLab CI** выступает в роли системы автоматизации, **Docker Swarm** — в качестве платформы для выполнения приложений, а **Traefik** — как точка входа для внешнего трафика (Ingress).

Ключевые принципы:

1.  **Удаленное и безопасное управление Swarm:** GitLab Runner не устанавливается напрямую на узлы кластера. Вместо этого он взаимодействует с Docker Engine удаленно по TCP, используя **[mTLS (mutual TLS)](../../WebServers/Nginx/Security/nginx_tls_ssl_configuration.md)**. И клиент (GitLab Runner), и сервер (Docker Daemon) проверяют сертификаты друг друга, что обеспечивает безопасное соединение.
2.  **Динамическая маршрутизация с Traefik:** Traefik отслеживает Docker API. Когда в Swarm запускается новый сервис с определенными метками (`labels`), Traefik автоматически создает для него маршрут и может выпустить SSL-сертификат от Let's Encrypt. Это устраняет необходимость ручной настройки reverse proxy.
3.  **Разделение инфраструктуры и приложений:** Общие сервисы (Traefik, базы данных) выносятся в отдельный "инфраструктурный" стек (например, `shared-infra`), управляемый из своего репозитория. Приложения развертываются независимо, используя общую сетевую инфраструктуру.
4.  **Управление окружениями в GitLab CI:** Используя **[переменные с привязкой к окружению (environment scope)](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**, один и тот же пайплайн может развертывать приложение на разные кластеры (например, `development` и `production`), автоматически подставляя нужные адреса (`DOCKER_HOST`) и учетные данные.

## Практические сценарии

### Сценарий: Настройка полного CI/CD-пайплайна

#### Шаг 1: Настройка кластера Docker Swarm

1.  **Инициализация Swarm:**
    На узле, который будет менеджером, выполните:
    ```bash
    # Замените <MANAGER-IP> на реальный IP вашего узла
    docker swarm init --advertise-addr <MANAGER-IP>
    ```
    Сохраните команду `docker swarm join` с токеном для подключения рабочих узлов.

2.  **Проверка кластера:**
    ```bash
    docker node ls
    ```

#### Шаг 2: Защита Docker Daemon с помощью mTLS

Эта настройка позволяет GitLab Runner'у безопасно управлять Docker Swarm.

1.  **Генерация сертификатов (`openssl`):**
    На узле-менеджере Swarm:
    ```bash
    # Создание директории для сертификатов
    mkdir -p ~/docker-certs && cd ~/docker-certs

    # 1. Генерация ключа и сертификата для Центра Сертификации (CA)
    openssl genrsa -aes256 -out ca-key.pem 4096
    openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem

    # 2. Генерация ключа и сертификата для сервера (Docker Daemon)
    # ВАЖНО: В поле "Common Name (CN)" укажите IP или FQDN вашего менеджера Swarm
    openssl genrsa -out server-key.pem 4096
    openssl req -subj "/CN=$(hostname -f)" -sha256 -new -key server-key.pem -out server.csr
    echo "subjectAltName = DNS:$(hostname -f),IP:$(hostname -I | awk '{print $1}')" > extfile.cnf
    openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
      -CAcreateserial -out server-cert.pem -extfile extfile.cnf

    # 3. Генерация ключа и сертификата для клиента (GitLab Runner)
    openssl genrsa -out key.pem 4096
    openssl req -subj "/CN=client" -new -key key.pem -out client.csr
    echo "extendedKeyUsage = clientAuth" > extfile-client.cnf
    openssl x509 -req -days 3650 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem \
      -CAcreateserial -out cert.pem -extfile extfile-client.cnf

    # 4. Очистка и установка прав
    rm -v *.csr *.srl *.cnf
    chmod -v 0400 ca-key.pem key.pem server-key.pem
    chmod -v 0444 ca.pem server-cert.pem cert.pem
    ```

2.  **Настройка Docker Daemon:**
    Создайте или отредактируйте `/etc/docker/daemon.json`:
    ```json
    {
      "tls": true,
      "tlscert": "/etc/docker/certs/server-cert.pem",
      "tlskey": "/etc/docker/certs/server-key.pem",
      "tlscacert": "/etc/docker/certs/ca.pem",
      "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
    }
    ```

    В качестве альтернативы, можно использовать `systemd` для переопределения команды запуска сервиса. Этот способ считается более гибким.

    Пример конфигурации для `/etc/systemd/system/docker.service.d/override.conf`:
    ```ini
    [Service]
    ExecStart=
    ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2376 --tlsverify --tlscacert=/etc/docker/certs/ca.pem --tlscert=/etc/docker/certs/server-cert.pem --tlskey=/etc/docker/certs/server-key.pem
    ```
    После создания файла необходимо выполнить `sudo systemctl daemon-reload`.

3.  **Копирование сертификатов и перезапуск Docker:**
    ```bash
    sudo mkdir -p /etc/docker/certs
    sudo cp ~/docker-certs/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/
    sudo systemctl restart docker
    ```

#### Шаг 2.1: Упрощение удаленного доступа с Docker Context

После настройки mTLS, вместо того чтобы каждый раз указывать хост и ключи в командной строке или использовать переменные окружения, можно использовать **Docker Context**. Это позволяет легко переключаться между разными Docker-окружениями (локальным, удаленным dev, удаленным prod).

*   **Создание контекста:**

    На вашей локальной машине или в окружении, откуда вы будете управлять кластером, выполните команду. У вас должны быть файлы сертификатов клиента (`ca.pem`, `cert.pem`, `key.pem`), полученные на предыдущем шаге.

    ```sh
    docker context create prod-swarm \
      --docker "host=tcp://prod.example.com:2376,ca=/path/to/ca.pem,cert=/path/to/cert.pem,key=/path/to/key.pem"
    ```
    Где `prod.example.com` — это доменное имя вашего Swarm менеджера.

*   **Переключение на контекст:**

    ```sh
    docker context use prod-swarm
    ```

*   После этого все команды `docker` (например, `docker ps`, `docker service ls`) будут выполняться на удаленном Swarm-кластере. Чтобы вернуться к локальному окружению, выполните `docker context use default`.

Этот механизм используется в CI/CD пайплайнах для удобного и безопасного взаимодействия с кластером.

#### Шаг 3: Развертывание инфраструктурных сервисов (Traefik)

В отдельном репозитории GitLab (`infra-stack`) создайте файлы для управления общими сервисами.

1.  **`docker-compose.yml` для Traefik и общей сети:**
    ```yaml
    version: '3.8'

    services:
      traefik:
        image: traefik:v2.11
        command:
          - "--log.level=INFO"
          - "--api.dashboard=true"
          - "--providers.docker=true"
          - "--providers.docker.exposedbydefault=false"
          - "--providers.docker.swarmmode=true"
          - "--entrypoints.web.address=:80"
          - "--entrypoints.websecure.address=:443"
          - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
          - "--certificatesresolvers.myresolver.acme.email=${ACME_EMAIL}" # Переменная GitLab
          - "--certificatesresolvers.myresolver.acme.storage=/certificates/acme.json"
        ports:
          - "80:80"
          - "443:443"
        volumes:
          - "/var/run/docker.sock:/var/run/docker.sock:ro"
          - "traefik-certs:/certificates"
        networks:
          - public
        deploy:
          placement:
            constraints:
              - "node.role==manager"

    volumes:
      postgres-data:
      traefik-certs:

    networks:
      public:
        driver: overlay
        name: public
    ```
    > Этот файл также может содержать другие общие сервисы, например, базы данных (PostgreSQL, MariaDB).

2.  **Настройка `.gitlab-ci.yml` для `infra-stack`:**
    *   **Переменные в GitLab CI/CD (`Settings -> CI/CD -> Variables`):**
        *   `DOCKER_HOST`: `tcp://your-swarm-manager.com:2376`
        *   `POSTGRES_DB`: `shared_db`
        *   `POSTGRES_USER`: `shared_user`
        *   `POSTGRES_PASSWORD` (Masked): `your_secure_password`
        *   `ACME_EMAIL`: `your-email@example.com`
        *   `CA_PEM` (File): Содержимое `ca.pem`
        *   `CERT_PEM` (File): Содержимое `cert.pem` (сертификат клиента)
        *   `KEY_PEM` (File): Содержимое `key.pem` (ключ клиента)

    *   **Код `.gitlab-ci.yml`:**
```yaml
    stages:
      - deploy

deploy_infra:
  stage: deploy
  image: docker:24
  before_script:
    - mkdir -p ~/.docker
    # Переменные типа File лучше всего записывать через echo
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - docker context create swarm --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm
  script:
    - docker stack deploy -c docker-compose.yml shared-infra --with-registry-auth
  when: manual
```

#### Шаг 4: Автоматическое развертывание приложения

В репозитории приложения (`my-app`) настроим пайплайн для сборки и развертывания в `dev` и `prod` окружения.

1.  **`Dockerfile` приложения (пример):**
    ```Dockerfile
    FROM node:18-alpine
    WORKDIR /app
    COPY package*.json ./
    RUN npm install
    COPY . .
    EXPOSE 3000
    CMD ["node", "server.js"]
    ```

2.  **Файлы `docker-compose` для окружений:**
    *   `docker-compose.prod.yml`:
    ```yaml
    version: '3.8'
    services:
      app:
        image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
        networks:
          - public
        deploy:
          replicas: 3
          labels:
            - "traefik.enable=true"
            - "traefik.http.routers.my-app-prod.rule=Host(\`app.your-domain.com`)"
            - "traefik.http.routers.my-app-prod.entrypoints=websecure"
            - "traefik.http.routers.my-app-prod.tls.certresolver=myresolver"
            - "traefik.http.services.my-app-prod.loadbalancer.server.port=3000"
            - "traefik.docker.network=public"
    networks:
      public:
        external: true
    ```
    *   `docker-compose.dev.yml` (аналогично, но с `replicas: 1` и `rule=Host(\`dev.app.your-domain.com`)").

3.  **Настройка переменных CI/CD с `Environment scope`:**

В настройках GitLab CI/CD (**Settings -> CI/CD -> Variables**) необходимо определить переменные для каждого окружения, используя **Environment scope**. Это позволяет пайплайну автоматически использовать правильные креды для нужного кластера.

Создайте следующие переменные **дважды**: один раз со скоупом `production`, второй раз — `development`.

*   `DOCKER_HOST`: `tcp://prod-manager.your-domain.com:2376` (для `production`) и `tcp://dev-manager.your-domain.com:2376` (для `development`).
*   `CA_PEM` (File): Содержимое `ca.pem` для соответствующего кластера.
*   `CERT_PEM` (File): Содержимое `cert.pem` для соответствующего кластера.
*   `KEY_PEM` (File): Содержимое `key.pem` для соответствующего кластера.

4.  **Файл `.gitlab-ci.yml` для приложения:**
    ```yaml
    stages:
      - build
      - deploy

    build:
      stage: build
      image:
        name: gcr.io/kaniko-project/executor:v1.9.0-debug
        entrypoint: [""]
      script:
        - mkdir -p /kaniko/.docker
        - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_JOB_USER\",\"password\":\"$CI_JOB_TOKEN\"}}}" > /kaniko/.docker/config.json
        - /kaniko/executor
          --context $CI_PROJECT_DIR
          --dockerfile $CI_PROJECT_DIR/Dockerfile
          --destination ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
      rules:
        - if: '$CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "dev"'

    # Шаблон для задачи развертывания
    .deploy_template: &deploy_template
      stage: deploy
      image: docker:24
      before_script:
        - mkdir -p ~/.docker
        # Переменные CA_PEM, CERT_PEM, KEY_PEM, DOCKER_HOST выбираются GitLab в зависимости от окружения
        - echo "$CA_PEM" > ~/.docker/ca.pem
        - echo "$CERT_PEM" > ~/.docker/cert.pem
        - echo "$KEY_PEM" > ~/.docker/key.pem
        - docker context create swarm --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
        - docker context use swarm
        - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
      script:
        - docker stack deploy -c $COMPOSE_FILE my-app --with-registry-auth

deploy_prod:
  <<: *deploy_template
  environment:
    name: production
    url: https://app.your-domain.com
  variables:
    COMPOSE_FILE: docker-compose.prod.yml
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy_dev:
  <<: *deploy_template
  environment:
    name: development
    url: http://dev.app.your-domain.com
  variables:
    COMPOSE_FILE: docker-compose.dev.yml
  rules:
    - if: '$CI_COMMIT_BRANCH == "dev"'
    ```

## Дополнительная информация

- **Сборка образов без Docker-in-Docker:** В примере используется **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md)** для сборки Docker-образов. Это предпочтительный способ в CI/CD, так как он не требует привилегированного доступа к Docker-демону, что повышает безопасность.
- **`--with-registry-auth`:** Этот флаг в команде `docker stack deploy` критически важен. Он заставляет узел-менеджер Swarm передать учетные данные для доступа к Docker Registry всем узлам кластера, чтобы они могли скачать приватный образ.
- **Результат:** Коммит в ветку `dev` автоматически развертывает приложение в `development` окружение, а коммит в `main` — в `production`.