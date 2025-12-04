# Docker Swarm - Remote Access with mTLS and GitLab CI Integration

## Настройка удаленного доступа по mTLS

Для интеграции с CI/CD системами, такими как GitLab CI, и для удаленного управления кластером без необходимости использовать SSH, можно настроить доступ к Docker Daemon по TCP с использованием mTLS (взаимной аутентификации по TLS).

**Процесс настройки:**

1.  **Генерация сертификатов:**

    *   Создается корневой сертификат (CA), которым будут подписываться все остальные сертификаты.
    *   Генерируется пара ключ/сертификат для сервера (Docker Daemon). В сертификате сервера в качестве `Common Name` (CN) или `Subject Alternative Name` (SAN) необходимо указать доменное имя или IP-адрес хоста.
    *   Генерируется пара ключ/сертификат для клиента (например, для GitLab Runner).

2.  **Настройка Docker Daemon:**

    *   Необходимо отредактировать конфигурацию systemd для сервиса Docker, чтобы он начал слушать TCP-порт (стандартно 2376 для mTLS) и использовал сгенерированные сертификаты.

    Пример конфигурации для `/etc/systemd/system/docker.service.d/override.conf`:
    ```ini
    [Service]
    ExecStart=
    ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2376 --tlsverify --tlscacert=/etc/docker/tls/ca.pem --tlscert=/etc/docker/tls/server-cert.pem --tlskey=/etc/docker/tls/server-key.pem
    ```

3.  **Перезапуск Docker:**

    ```sh
    sudo systemctl daemon-reload
    sudo systemctl restart docker
    ```

4.  **Настройка клиента:**

    *   На клиентской машине (или в CI/CD окружении) необходимо иметь файлы `ca.pem`, `cert.pem` (клиентский сертификат) и `key.pem` (клиентский ключ).
    *   Для удобства можно создать **Docker Context**.

### Использование Docker Context для удаленного управления

Docker Context позволяет легко переключаться между разными Docker-окружениями (локальным, удаленным dev, удаленным prod).

*   **Создание контекста:**

    ```sh
    docker context create prod-swarm \
      --docker "host=tcp://prod.example.com:2376,ca=/path/to/ca.pem,cert=/path/to/cert.pem,key=/path/to/key.pem"
    ```

*   **Переключение на контекст:**

    ```sh
    docker context use prod-swarm
    ```

*   После этого все команды `docker` (например, `docker ps`, `docker service ls`) будут выполняться на удаленном Swarm-кластере.

## Интеграция с GitLab CI для автоматического развертывания

Используя удаленный доступ по mTLS, можно построить эффективный CI/CD пайплайн для автоматического развертывания в Docker Swarm.

**Пример `.gitlab-ci.yml`:**

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
    # kaniko не требует Docker-in-Docker
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  only:
    - main
    - dev

deploy_prod:
  stage: deploy
  image: docker:latest
  script:
    # 1. Создаем Docker Context с помощью переменных GitLab CI
    - docker context create swarm-prod --docker "host=${PROD_DOCKER_HOST},ca=${PROD_CA_FILE},cert=${PROD_CERT_FILE},key=${PROD_KEY_FILE}"
    # 2. Переключаемся на созданный контекст
    - docker context use swarm-prod
    # 3. Развертываем стек
    - docker stack deploy -c docker-compose.prod.yml --with-registry-auth my-app
  environment:
    name: production
    url: https://prod.example.com
  only:
    - main

deploy_dev:
  stage: deploy
  image: docker:latest
  script:
    - docker context create swarm-dev --docker "host=${DEV_DOCKER_HOST},ca=${DEV_CA_FILE},cert=${DEV_CERT_FILE},key=${DEV_KEY_FILE}"
    - docker context use swarm-dev
    - docker stack deploy -c docker-compose.dev.yml --with-registry-auth my-app
  environment:
    name: development
    url: http://dev.example.com
  only:
    - dev
```

- **Ключевые моменты:**

**Сборка с Kaniko:** Для сборки Docker-образов используется [Kaniko](https://github.com/GoogleContainerTools/kaniko), что позволяет избежать сложностей и рисков безопасности, связанных Docker-in-Docker.                                                                                                                                                                         
**Переменные GitLab CI:** Все секреты (содержимое сертификатов, хосты) хранятся в переменных GitLab CI типа `File` и `Variable`. Это позволяет безопасно передавать их в сборочные задачи.
**`docker stack deploy --with-registry-auth`:** Эта опция автоматически передает учетные данные для доступа к приватному Docker Registry (в данном случае, GitLab Registry) на узлы Swarm, чтобы они могли скачать образ.                                                                                       
