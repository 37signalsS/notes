# CI/CD с Docker Swarm: Развертывание приложения

## Шаг 4: Автоматическое развертывание приложения

В репозитории приложения (`my-app`) настроим пайплайн для сборки и развертывания в `dev` и `prod` окружения.

1. **`Dockerfile` приложения (пример):**

    ```Dockerfile
    FROM node:18-alpine
    WORKDIR /app
    COPY package*.json ./
    RUN npm install
    COPY . .
    EXPOSE 3000
    CMD ["node", "server.js"]
    ```

2. **Файлы `docker-compose` для окружений:**
    - `docker-compose.prod.yml`:

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
            - "traefik.http.routers.my-app-prod.rule=Host(`app.your-domain.com`)"
            - "traefik.http.routers.my-app-prod.entrypoints=websecure"
            - "traefik.http.routers.my-app-prod.tls.certresolver=myresolver"
            - "traefik.http.services.my-app-prod.loadbalancer.server.port=3000"
            - "traefik.docker.network=public"
    networks:
      public:
        external: true
    ```

    - `docker-compose.dev.yml` (аналогично, но с `replicas: 1` и `rule=Host(`dev.app.your-domain.com`)").

3. **Настройка переменных CI/CD с `Environment scope`:**

В настройках GitLab CI/CD (**Settings -> CI/CD -> Variables**) необходимо определить переменные для каждого окружения, используя **Environment scope**. Это позволяет пайплайну автоматически использовать правильные креды для нужного кластера.

Создайте следующие переменные **дважды**: один раз со скоупом `production`, второй раз — `development`.

- `DOCKER_HOST`: `tcp://prod-manager.your-domain.com:2376` (для `production`) и `tcp://dev-manager.your-domain.com:2376` (для `development`).
- `CA_PEM` (File): Содержимое `ca.pem` для соответствующего кластера.
- `CERT_PEM` (File): Содержимое `cert.pem` для соответствующего кластера.
- `KEY_PEM` (File): Содержимое `key.pem` для соответствующего кластера.

1. **Файл `.gitlab-ci.yml` для приложения:**

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
        - echo "{"auths":{"$CI_REGISTRY":{"username":"$CI_JOB_USER","password":"$CI_JOB_TOKEN"}}}" > /kaniko/.docker/config.json
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
    url: <https://app.your-domain.com>
  variables:
    COMPOSE_FILE: docker-compose.prod.yml
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy_dev:
  <<: *deploy_template
  environment:
    name: development
    url: <http://dev.app.your-domain.com>
  variables:
    COMPOSE_FILE: docker-compose.dev.yml
  rules:
    - if: '$CI_COMMIT_BRANCH == "dev"'
    ```
