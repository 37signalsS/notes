# CI/CD с Docker Swarm: Развертывание инфраструктуры

## Шаг 3: Развертывание инфраструктурных сервисов (Traefik)

> **Важно:** В примере используется Traefik v3.x. При миграции с v2.x учитыйте [отличия в конфигурации](https://doc.traefik.io/traefik/v3.0/migration/v2-to-v3/).

В отдельном репозитории GitLab (`infra-stack`) создайте файлы для управления общими сервисами.

1. **`docker-compose.yml` для Traefik и общей сети:**

    ```yaml
    version: '3.8'

    services:
      traefik:
        image: traefik:v3.6
        command:
          - "--log.level=INFO"
          - "--api.dashboard=true"
          - "--providers.docker=true"
          - "--providers.docker.exposedbydefault=false"
          - "--providers.swarm=true"
          - "--providers.swarm.endpoint=unix:///var/run/docker.sock"
          - "--entrypoints.web.address=:80"
          - "--entrypoints.websecure.address=:443"
          - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
          - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
          - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
          - "--certificatesresolvers.myresolver.acme.email=${ACME_EMAIL}" # Переменная GitLab
          - "--certificatesresolvers.myresolver.acme.storage=/certificates/acme.json"
        ports:
          - "80:80"
          - "443:443"
          - "8080:8080"
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

2. **Настройка `.gitlab-ci.yml` для `infra-stack`:**
    - **Переменные в GitLab CI/CD (`Settings -> CI/CD -> Variables`):**
        - `DOCKER_HOST`: `tcp://your-swarm-manager.com:2376`
        - `POSTGRES_DB`: `shared_db`
        - `POSTGRES_USER`: `shared_user`
        - `POSTGRES_PASSWORD` (Masked): `your_secure_password`
        - `ACME_EMAIL`: `your-email@example.com`
        - `CA_PEM` (File): Содержимое `ca.pem`
        - `CERT_PEM` (File): Содержимое `cert.pem` (сертификат клиента)
        - `KEY_PEM` (File): Содержимое `key.pem` (ключ клиента)

    - **Код `.gitlab-ci.yml`:**

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
