# Развертывание инфраструктуры Docker Swarm через CI/CD

## Определения

- **Инфраструктурный стек (Infrastructure Stack):** Логическая группа общекластерных сервисов (Ingress-прокси, мониторинг, логирование), управляемая как единый объект. Служит фундаментом для запуска прикладных приложений.
- **Общие сервисы (Shared Services):** Компоненты, предоставляющие функциональность нескольким стекам одновременно (например, Traefik для маршрутизации или Redis как общий кэш).
- **Внешняя оверлейная сеть (External Overlay Network):** Сеть Swarm, создаваемая вне жизненного цикла конкретного приложения. Позволяет сервисам из разных стеков взаимодействовать друг с другом.
- **[Traefik](../swarm_ingress_traefik.md):** Cloud Native Ingress-прокси. В Swarm-кластере автоматически обнаруживает новые сервисы через Docker API и настраивает маршрутизацию на основе меток (labels).

## Базовые концепции

### Архитектура системного слоя кластера

Вынос базовых компонентов в отдельный репозиторий (`infra-stack`) реализует принцип **Infrastructure as Code (IaC)** и обеспечивает:

1. **Изоляцию критических изменений:** Обновление версии Traefik или конфигурации Prometheus не требует перезапуска прикладных пайплайнов.
2. **Централизованное сетевое управление:** Все общие сети (`public`, `monitoring`, `db_net`) создаются и описываются в одном месте.
3. **Безопасность (POLP):** Доступ к репозиторию инфраструктуры ограничивается узким кругом системных администраторов/SRE.
4. **Preservation of Source IP:** Использование режима `mode: host` для портов 80/443 позволяет Traefik видеть реальные IP-адреса клиентов, что критично для логирования и систем защиты (WAF/Fail2Ban).

### Механизм автоматизации деплоя

1. **Декларативность:** Вся структура инфраструктуры описана в `docker-compose.yml` (v3.8+).
2. **Безопасное соединение:** Использование порта 2376 с **mTLS** аутентификацией для удаленного управления менеджерами.
3. **Docker Context:** Позволяет пайплайну переключаться между кластерами (staging/production) без изменения скриптов деплоя.

## Практические сценарии

### Сценарий 1: Автоматизация подготовки сетей

Общие сети должны существовать *до* того, как прикладные стеки попытаются к ним подключиться.

```bash
# Создание сети с поддержкой шифрования трафика и корректным MTU
docker network create \
  --driver overlay \
  --attachable \
  --opt encrypted \
  --opt mtu=1450 \
  public_net
```
# Результат: Сеть доступна на всех узлах Swarm для динамического подключения контейнеров.

### Сценарий 2: Конфигурация Ingress-слоя (Traefik v3)

Пример оптимального `docker-compose.yml` для высокодоступного Ingress:

```yaml
version: '3.8'
services:
  traefik:
    image: traefik:v3.1 # Используйте фиксированные версии
    command:
      - "--providers.swarm=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Редирект на HTTPS на уровне Entrypoint
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      # Включение Dashboard
      - "--api.dashboard=true"
    ports:
      - target: 80
        published: 80
        mode: host # Важно для сохранения Client IP
      - target: 443
        published: 443
        mode: host
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro" # Доступ только на чтение
    networks:
      - public_net
    deploy:
      replicas: 3
      placement:
        constraints:
          - "node.role==manager" # Traefik должен быть там, где есть Docker API
      update_config:
        parallelism: 1
        order: start-first
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 128M
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.api.rule=Host(`traefik.example.com`)"
        - "traefik.http.routers.api.service=api@internal"
        - "traefik.http.routers.api.entrypoints=websecure"
        - "traefik.http.routers.api.tls=true"
        # Middleware для защиты Dashboard (требует создания секрета)
        - "traefik.http.routers.api.middlewares=auth"
        - "traefik.http.middlewares.auth.basicauth.users=admin:$$apr1$$..."

networks:
  public_net:
    external: true
```

### Сценарий 3: Переменные GitLab CI для инфраструктуры

Для безопасного управления кластером настройте следующие переменные (тип **File**):

| Переменная | Назначение | Описание |
|:---|:---|:---|
| `DOCKER_CA` | File | Содержимое `ca.pem` |
| `DOCKER_CERT` | File | Содержимое `cert.pem` |
| `DOCKER_KEY` | File | Содержимое `key.pem` |
| `DOCKER_HOST` | Variable | Строка вида `tcp://<MANAGER_IP>:2376` |

### Сценарий 4: Пайплайн доставки инфраструктуры

Пример `.gitlab-ci.yml`, реализующий чистый деплой через Docker Context:

```yaml
deploy_infra:
  stage: deploy
  image: docker:27.x
  before_script:
    # Удаление старого контекста, если он остался от прошлых запусков
    - docker context rm swarm-prod -f || true
    - docker context create swarm-prod \
      --docker "host=$DOCKER_HOST,ca=$DOCKER_CA,cert=$DOCKER_CERT,key=$DOCKER_KEY"
    - docker context use swarm-prod
  script:
    # Авторизация в Registry для скачивания образов мониторинга/прокси
    - echo "$CI_REGISTRY_PASSWORD" | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
    # Развертывание стека
    - docker stack deploy -c docker-compose.yml infra --with-registry-auth --prune
    # Верификация деплоя
    - docker service ls --filter name=infra
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual # Инфраструктурные изменения требуют ручного подтверждения
```

### Сценарий 5: Подготовка нод через IaC (Ansible + Terraform)

Прежде чем развернуть Swarm-кластер, необходимо подготовить виртуальные или физические сервера. Рекомендуемый стек: **Terraform** (провижининг инфраструктуры) + **Ansible** (настройка ОС и Docker).

**Terraform (минимальный пример для AWS EC2):**

```hcl
# main.tf — развертывание 3 менеджеров + 3 воркеров
resource "aws_instance" "swarm_manager" {
  count         = 3
  ami           = "ami-0c55b159cbfafe1f0"  # Ubuntu 22.04
  instance_type = "t3.medium"
  key_name      = var.ssh_key_name
  vpc_security_group_ids = [aws_security_group.swarm.id]

  tags = {
    Name = "swarm-manager-${count.index}"
    Role = "manager"
  }
}

resource "aws_instance" "swarm_worker" {
  count         = 3
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.large"
  key_name      = var.ssh_key_name
  vpc_security_group_ids = [aws_security_group.swarm.id]

  tags = {
    Name = "swarm-worker-${count.index}"
    Role = "worker"
  }
}
```

**Ansible (настройка Docker и инициализация Swarm):**

```yaml
# playbooks/swarm_init.yml
- hosts: managers[0]
  become: yes
  tasks:
    - name: Install Docker
      apt:
        name: [docker.io, docker-compose-plugin]
        state: present
        update_cache: yes

    - name: Initialize Swarm cluster
      command: docker swarm init --advertise-addr {{ ansible_host }}
      register: init_result
      changed_when: "'Swarm initialized' in init_result.stdout"

    - name: Get worker join token
      command: docker swarm join-token worker -q
      register: worker_token
      changed_when: false

    - name: Join workers to cluster
      hosts: workers
      become: yes
      tasks:
        - name: Join Swarm
          command: >
            docker swarm join
            --token {{ hostvars['managers[0]'].worker_token.stdout }}
            {{ hostvars['managers[0]'].ansible_host }}:2377

- hosts: managers
  become: yes
  tasks:
    - name: Configure Docker daemon
      template:
        src: daemon.json.j2
        dest: /etc/docker/daemon.json
      notify: restart docker

  handlers:
    - name: restart docker
      systemd:
        name: docker
        state: restarted
```

**Важно:** Не храните IP-адреса и токены в Playbook напрямую — используйте Ansible Inventory и переменные окружения.

### Сценарий 6: Мультиокружение (dev/staging/prod)

Разделение кластеров по окружениям через Docker Context и отдельные Compose-файлы:

```yaml
# Структура репозитория
infra-stack/
├── envs/
│   ├── dev/
│   │   ├── docker-compose.yml      # 1 replica, без TLS
│   │   └── context.env             # DOCKER_HOST=...
│   ├── staging/
│   │   ├── docker-compose.yml      # 2 replicas, self-signed TLS
│   │   └── context.env
│   └── prod/
│       ├── docker-compose.yml      # 3+ replicas, Let's Encrypt
│       └── context.env
└── .gitlab-ci.yml
```

```yaml
# .gitlab-ci.yml — деплой в dev/staging/prod
.deploy_template: &deploy_template
  stage: deploy
  image: docker:27.x
  before_script:
    - docker context rm -f ${CONTEXT_NAME} || true
    - docker context create ${CONTEXT_NAME}
        --docker "host=${DOCKER_HOST},ca=${DOCKER_CA},cert=${DOCKER_CERT},key=${DOCKER_KEY}"
    - docker context use ${CONTEXT_NAME}
  script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
    - docker stack deploy -c envs/${ENVIRONMENT}/docker-compose.yml infra-${ENVIRONMENT} --with-registry-auth --prune

deploy_dev:
  <<: *deploy_template
  variables:
    ENVIRONMENT: dev
    CONTEXT_NAME: swarm-dev
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
      when: manual

deploy_staging:
  <<: *deploy_template
  variables:
    ENVIRONMENT: staging
    CONTEXT_NAME: swarm-staging
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual

deploy_prod:
  <<: *deploy_template
  variables:
    ENVIRONMENT: prod
    CONTEXT_NAME: swarm-prod
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
      allow_failure: false
```

**Отличия окружений:**

| Параметр | dev | staging | prod |
|:---|:---|:---|:---|
| Реплики | 1 | 2 | 3+ |
| TLS | Нет | Self-signed | Let's Encrypt |
| Ресурсы (limits) | Минимальные | Средние | Production |
| Мониторинг | Не обязателен | Обязателен | Обязателен + алертинг |
| Ручной подтверждение | Да | Да | Да |

### Сценарий 7: Автоматизация TLS через Let's Encrypt (Traefik ACME)

Traefik встроенно поддерживает автоматическое получение и обновление SSL-сертификатов через ACME-протокол (Let's Encrypt). Это исключает необходимость ручного управления сертификатами:

```yaml
# Дополнение к docker-compose.yml (Сценарий 2)
services:
  traefik:
    command:
      - "--certificatesresolvers.letsencrypt.acme.email=admin@example.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
      # HTTP-01 Challenge (требует порта 80)
      - "--certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web"
      # Для тестирования (чтобы не попасть в Rate Limit)
      # - "--certificatesresolvers.letsencrypt.acme.caserver=https://acme-staging-v02.api.letsencrypt.org/directory"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "letsencrypt:/letsencrypt"

  # Сервис для wildcard-сертификатов (DNS-01 Challenge)
  # Требует DNS-провайдера (Cloudflare, Route53 и т.д.)
  # traefik:
  #   command:
  #     - "--certificatesresolvers.letsencrypt.acme.dnschallenge=true"
  #     - "--certificatesresolvers.letsencrypt.acme.dnschallenge.provider=cloudflare"

volumes:
  letsencrypt:
    driver: local
```

**Метки сервиса для автоматического TLS:**

```yaml
services:
  my-app:
    deploy:
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.my-app.rule=Host(`app.example.com`)"
        - "traefik.http.routers.my-app.entrypoints=websecure"
        - "traefik.http.routers.my-app.tls.certresolver=letsencrypt"
```

**Важно:** Let's Encrypt имеет Rate Limit (50 сертификатов на домен в неделю). На dev/staging используйте staging-сервер или self-signed сертификаты.

### Сценарий 8: Rolling Update инфраструктурных сервисов

Инфраструктурные сервисы (Traefik, Prometheus) обновляются через тот же механизм `docker stack deploy`, но с особыми ограничениями:

```yaml
# Ключевые параметры для инфраструктурных сервисов
deploy:
  update_config:
    parallelism: 1        # Одна реплика за раз
    delay: 30s            # Долгая задержка для инициализации
    order: start-first    # Сначала новая, потом старая
    failure_action: rollback
    monitor: 60s          # Долгий мониторинг (Traefik может долго стартовать)
  rollback_config:
    parallelism: 1
    delay: 10s
    order: start-first
  restart_policy:
    condition: any
    delay: 5s
    max_attempts: 3
    window: 120s
```

**Порядок обновления инфраструктуры:**

1. **Сети** — проверьте, что новые overlay-сети созданы (`docker network ls`).
2. **Traefik** — обновите первым, так как он маршрутизирует трафик ко всем сервисам.
3. **Prometheus/Grafana** — обновите вторыми для контроля метрик.
4. **Логирование** — обновите последним, чтобы не потерять логи во время обновления.

**Команда принудительного отката:**

```bash
# Если новая версия Traefik вызвала ошибки
docker service rollback infra_traefik

# Проверка статуса отката
docker service inspect --format '{{.UpdateStatus.State}} {{.UpdateStatus.Message}}' infra_traefik
```

## Дополнительная информация

### Безопасность инфраструктурного слоя

- **Защита сокета:** Использование `:ro` (read-only) для проброса `/var/run/docker.sock` в Traefik.
- **Firewall:** Ограничение доступа к порту 2376 (API) и портам управления Swarm (2377, 7946, 4789) только для доверенных сетей.
- **Секреты:** Используйте `docker secret` для хранения SSL-сертификатов (если они не управляются Traefik) и паролей БД.

### Диагностика типовых проблем

| Проблема | Причина | Решение |
|:---|:---|:---|
| `network public_net not found` | Сеть не была создана вручную | Запустите Сценарий 1 на одном из менеджеров. |
| `context already exists` | Повторный запуск `create` без очистки | Добавить `docker context rm -f` в `before_script`. |
| Traefik не видит сервисы | Ошибка в `constraints` | Проверьте, что Traefik запущен на узле с ролью `manager`. |
| SSL не работает | Порт 443 закрыт или лимит LE | Проверьте Firewall и логи Traefik (`docker service logs`). |
| 502 Bad Gateway | Приложение не в сети `public_net` | Проверьте секцию `networks` в Compose-файле приложения. |

### Связанные документы

- **[Подготовка кластера (mTLS)](./swarm_setup.md)** — генерация сертификатов и инициализация Swarm.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — детальная настройка маршрутизации и middleware.
- **[Лучшие практики CI/CD](./best_practices.md)** — стандарты безопасности и оптимизации.
