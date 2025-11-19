# Полное руководство: CI/CD с Docker Swarm, GitLab и Traefik

Это руководство объединяет несколько концепций для создания простого, но мощного и безопасного CI/CD процесса для развертывания приложений. Мы будем использовать Docker Swarm для оркестрации, Traefik в качестве reverse proxy и Let's Encrypt для SSL, а GitLab CI/CD для полной автоматизации сборок и развертываний.

Такой подход является отличной, легковесной альтернативой Kubernetes для небольших и средних проектов, где важна простота, скорость развертывания и низкий порог входа.

## Часть 1: Настройка кластера Docker Swarm

### Шаг 1.1: Инициализация Swarm

Для создания кластера понадобится как минимум один узел-менеджер.

1.  **Инициализация менеджера:**
    На главном узле выполните команду, указав IP-адрес, по которому другие узлы смогут к нему подключиться.

    ```bash
    # Замените <MANAGER-IP> на реальный IP вашего узла
    docker swarm init --advertise-addr <MANAGER-IP>
    ```

    После выполнения Docker выведет команду для присоединения рабочих узлов, включающую токен.

2.  **Присоединение рабочих узлов (опционально):**
    На каждом рабочем узле выполните команду, полученную на предыдущем шаге, чтобы расширить кластер.

    ```bash
    docker swarm join --token <TOKEN> <MANAGER-IP>:<PORT>
    ```

3.  **Проверка состояния кластера:**
    На узле-менеджере можно посмотреть список всех узлов.

    ```bash
    docker node ls
    ```

### Шаг 1.2: Защита Docker Daemon с помощью mTLS

Чтобы GitLab Runner мог удаленно и безопасно управлять Docker Swarm, необходимо настроить Docker daemon на прием команд только от клиентов, предоставивших валидный TLS-сертификат.

1.  **Генерация сертификатов с помощью `openssl`:**
    На узле-менеджере Swarm выполните следующие команды.

    ```bash
    # Создайте директорию для сертификатов
    mkdir -p ~/docker-certs && cd ~/docker-certs

    # 1. Генерируем ключ и сертификат для Центра Сертификации (CA)
    openssl genrsa -aes256 -out ca-key.pem 4096
    openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem
    # (В процессе нужно будет ввести информацию и пароль для CA)

    # 2. Генерируем ключ и сертификат для сервера (Docker Daemon)
    # ВАЖНО: В поле "Common Name (CN)" укажите IP-адрес или доменное имя вашего менеджера Swarm
    openssl genrsa -out server-key.pem 4096
    openssl req -subj "/CN=$(hostname -f)" -sha256 -new -key server-key.pem -out server.csr
    echo "subjectAltName = DNS:$(hostname -f),IP:$(hostname -I | awk '{print $1}')" > extfile.cnf
    openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
      -CAcreateserial -out server-cert.pem -extfile extfile.cnf

    # 3. Генерируем ключ и сертификат для клиента (GitLab Runner)
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
    Создайте файл `/etc/docker/daemon.json` (или отредактируйте существующий) со следующим содержимым:

    ```json
    {
      "tls": true,
      "tlscert": "/etc/docker/certs/server-cert.pem",
      "tlskey": "/etc/docker/certs/server-key.pem",
      "tlscacert": "/etc/docker/certs/ca.pem",
      "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
    }
    ```

3.  **Скопируйте сертификаты и перезапустите Docker:**

    ```bash
    sudo mkdir -p /etc/docker/certs
    sudo cp ~/docker-certs/{ca,server-cert,server-key}.pem /etc/docker/certs/
    sudo systemctl restart docker
    ```

## Часть 2: Развертывание инфраструктурных сервисов

Создадим отдельный репозиторий в GitLab (например, `infra`) для управления общими сервисами, такими как Traefik и базы данных.

### Шаг 2.1: `docker-compose.yml` для Traefik и PostgreSQL

В репозитории `infra` создайте файл `docker-compose.yml`:

```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v2.11 # Рекомендуется использовать актуальную версию
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

  postgres:
    image: postgres:16
    volumes:
      - "postgres-data:/var/lib/postgresql/data"
    environment:
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD} # Переменная GitLab
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

### Шаг 2.2: Настройка GitLab CI для `infra`

1.  **Добавьте переменные в GitLab CI/CD:**
    Перейдите в **Settings -> CI/CD -> Variables**. Создайте переменные:
    *   `DOCKER_HOST`: `tcp://your-swarm-manager.com:2376`
    *   `POSTGRES_DB`: `shared_db`
    *   `POSTGRES_USER`: `shared_user`
    *   `POSTGRES_PASSWORD` (Masked): `your_secure_password`
    *   `ACME_EMAIL`: `your-email@example.com`
    *   `CA_PEM` (File): Содержимое `ca.pem`
    *   `CERT_PEM` (File): Содержимое `cert.pem`
    *   `KEY_PEM` (File): Содержимое `key.pem`

2.  **Создайте `.gitlab-ci.yml`:**

```yaml
stages:
  - deploy

deploy_infra:
  stage: deploy
  image: docker:24
  before_script:
    - mkdir -p ~/.docker
    - cp "$CA_PEM" ~/.docker/ca.pem
    - cp "$CERT_PEM" ~/.docker/cert.pem
    - cp "$KEY_PEM" ~/.docker/key.pem
    - docker context create swarm --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm
  script:
    - docker info
    - docker stack deploy -c docker-compose.yml shared-infra
  when: manual
```

Теперь, запустив этот пайплайн вручную, вы развернете Traefik и PostgreSQL в вашем кластере.

## Часть 3: Автоматическое развертывание приложения

Создадим второй репозиторий для нашего приложения (например, `my-app`), настроив CI/CD для двух окружений: `development` (из ветки `dev`) и `production` (из ветки `main`).

### Шаг 3.1: `Dockerfile` и `docker-compose` файлы

*   **`Dockerfile`** (пример для Node.js, остается без изменений):
    ```Dockerfile
    FROM node:18-alpine
    WORKDIR /app
    COPY package*.json ./
    RUN npm install
    COPY . .
    EXPOSE 3000
    CMD ["node", "server.js"]
    ```

*   **`docker-compose.prod.yml`** для production-окружения:
    ```yaml
    version: '3.8'

    services:
      app:
        image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
        networks:
          - public
        deploy:
          replicas: 3 # Больше реплик для стабильности
          labels:
            - "traefik.enable=true"
            - "traefik.http.routers.my-app-prod.rule=Host(`app.your-domain.com`)"
            - "traefik.http.routers.my-app-prod.entrypoints=websecure"
            - "traefik.http.routers.my-app-prod.tls.certresolver=myresolver"
            - "traefik.http.services.my-app-prod.loadbalancer.server.port=3000"
            - "traefik.docker.network=public"

    networks:
      public:
        external: true
    ```

*   **`docker-compose.dev.yml`** для development-окружения:
    ```yaml
    version: '3.8'

    services:
      app:
        image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
        networks:
          - public
        deploy:
          replicas: 1 # Достаточно одной реплики для разработки
          labels:
            - "traefik.enable=true"
            - "traefik.http.routers.my-app-dev.rule=Host(`dev.app.your-domain.com`)"
            - "traefik.http.routers.my-app-dev.entrypoints=websecure"
            - "traefik.http.routers.my-app-dev.tls.certresolver=myresolver"
            - "traefik.http.services.my-app-dev.loadbalancer.server.port=3000"
            - "traefik.docker.network=public"

    networks:
      public:
        external: true
    ```

### Шаг 3.2: Настройка переменных CI/CD для окружений

В настройках GitLab CI/CD (**Settings -> CI/CD -> Variables**) необходимо определить переменные для каждого окружения, используя **Environment scope**. Это позволяет пайплайну автоматически использовать правильные креды для нужного кластера.

Создайте следующие переменные **дважды**: один раз со скоупом `production`, второй раз — `development`.

*   `DOCKER_HOST`: `tcp://prod-manager.your-domain.com:2376` (для `production`) и `tcp://dev-manager.your-domain.com:2376` (для `development`).
*   `CA_PEM` (File): Содержимое `ca.pem` для соответствующего кластера.
*   `CERT_PEM` (File): Содержимое `cert.pem` для соответствующего кластера.
*   `KEY_PEM` (File): Содержимое `key.pem` для соответствующего кластера.

### Шаг 3.3: `.gitlab-ci.yml` с использованием шаблонов и окружений

Этот пайплайн использует YAML-якоря (`&`) для переиспользования кода и `rules` для запуска задач только на определенных ветках.

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
    # Переменные CA_PEM, CERT_PEM, KEY_PEM, DOCKER_HOST будут выбраны GitLab
    # в зависимости от окружения (environment scope)
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - docker context create swarm --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker info
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

## Заключение

Теперь ваш CI/CD процесс полностью настроен для работы с несколькими окружениями:
1.  **Коммит в `dev`**: Запускается сборка и развертывание на `development` окружение.
2.  **Коммит в `main`**: Запускается сборка и развертывание на `production` окружение.

Этот процесс полностью автоматизирован, безопасен и легко масштабируется для новых приложений и окружений.
