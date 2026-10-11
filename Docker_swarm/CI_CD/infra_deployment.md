> **Статус:** Docker Swarm не развивается. Применяется только для поддержки существующих
> развёртываний; для новых — Kubernetes.

**Актуально для:** Docker Engine 29.x+, Compose file v3.8+, Traefik v3.7.x

# Развертывание инфраструктуры Docker Swarm через CI/CD

## Определения

- **Инфраструктурный стек (Infrastructure Stack):** Логическая группа общекластерных сервисов (Ingress-прокси, мониторинг, логирование, UI-портал), управляемая как единый объект. Служит фундаментом для запуска прикладных приложений.
- **Общие сервисы (Shared Services):** Компоненты, предоставляющие функциональность нескольким стекам одновременно (Traefik для маршрутизации, Loki для агрегации логов, общий Redis кэш).
- **Внешняя оверлейная сеть (External Overlay Network):** Сеть Swarm, создаваемая вне жизненного цикла конкретного приложения. Позволяет сервисам из разных стеков взаимодействовать друг с другом.
- **Socket Proxy:** Вспомогательный сервис (`tecnativa/docker-socket-proxy`), ограничивающий доступ Traefik к Docker API только необходимыми операциями чтения вместо монтирования `/var/run/docker.sock` напрямую.
- **[Traefik](../swarm_ingress_traefik.md):** Edge-прокси с нативной поддержкой Docker Swarm. Автоматически обнаруживает новые сервисы через Docker API и настраивает маршрутизацию на основе меток (labels).
- **[Docker Context](./docker_context_setup.md):** Абстракция CLI Docker, инкапсулирующая параметры подключения (адрес менеджера и пути к TLS-ключам) под коротким именем для переключения между кластерами.
- **Swarm Autolock:** Функция шифрования ключей TLS и логов Raft на диске менеджеров. Требует ввода ключа разблокировки после перезагрузки демона Docker.
- **Raft Consensus:** Алгоритм консенсуса менеджеров для поддержания согласованного состояния кластера (TCP 2377). Требует нечетного числа менеджеров и синхронизации времени (NTP).

## Базовые концепции

### Архитектура инфраструктурного слоя

Вынос базовых компонентов в отдельный репозиторий (`infra-stack`) реализует принцип **Infrastructure as Code (IaC)** и обеспечивает:

1. **Изоляцию критических изменений:** Обновление версии Traefik или конфигурации Prometheus не затрагивает прикладные пайплайны.
2. **Централизованное сетевое управление:** Все общие сети (`public`, `monitoring`, `db_net`) создаются и описываются в одном месте.
3. **Безопасность (POLP):** Доступ к репозиторию инфраструктуры ограничивается узким кругом SRE/системных администраторов.
4. **Preservation of Source IP:** Использование режима `mode: host` для портов 80/443 позволяет Traefik видеть реальные IP-адреса клиентов, что критично для логирования и систем защиты (WAF/Fail2Ban).

### Сетевые требования

Для корректной работы Swarm и Remote API необходимо открыть порты в Firewall на всех узлах:

| Порт / Протокол | Назначение |
|:---|:---|
| **2376 / TCP** | Docker TLS API (удаленное управление из CI/CD) |
| **2377 / TCP** | Коммуникации между менеджерами (Raft) |
| **7946 / TCP + UDP** | Обнаружение узлов и Gossip |
| **4789 / UDP** | Трафик Overlay (VXLAN) |

> **Важно:** Синхронизация времени (NTP) критически важна для Raft. Разница более чем в несколько секунд приводит к потере кворума. Используйте `chrony` или `systemd-timesyncd`. Детали см. в **[swarm_setup.md](./swarm_setup.md)**.

### Overlay-сети и MTU

Overlay-сети создают виртуальную L2-сеть между хостами:

- **VXLAN-инкапсуляция:** Добавляет 50-байтовый заголовок. Рекомендуемое значение MTU для интерфейса `docker0` — **1450** (вместо стандартных 1500).
- **Шифрование:** При создании сети с флагом `--opt encrypted` трафик шифруется через IPSec (mTLS между узлами), что добавляет нагрузку на CPU.
- **Attachable:** Флаг `--attachable` позволяет standalone-контейнерам подключаться к Overlay-сети для отладки.

### Secrets и конфигурации

- **Immutable:** Секреты неизменяемы. Для обновления создается новый секрет с новым именем.
- **Хранение:** Секреты хранятся в зашифрованном Raft-логе менеджеров (AES-256). Никогда не записываются на диск воркеров.
- **Монтирование:** В контейнере монтируются в `/run/secrets/<имя>` как tmpfs.

### Наблюдаемость как часть инфраструктуры

Инфраструктурный стек обязан включать компоненты мониторинга и логирования:

- **Метрики узлов:** `node_exporter` (порт 9100) для сбора метрик хоста (CPU, память, диск, сеть).
- **Метрики контейнеров:** `cAdvisor` (порт 8080) для сбора метрик Docker Engine и контейнеров.
- **Сбор метрик:** `Prometheus` (порт 9090) для агрегации метрик со всех узлов и сервисов.
- **Визуализация:** `Grafana` (порт 3000) для дашбордов.
- **Логирование:** `Loki` (порт 3100) для агрегации логов со всех узлов через `promtail` или `fluentd`.

## Практические сценарии

### Сценарий 1: Подготовка кластера и менеджеров

Перед развертыванием инфраструктуры инициализируйте Swarm и подготовьте менеджерские узлы. Pre-flight проверки и детали инициализации см. в **[swarm_setup.md](./swarm_setup.md)**.

Рекомендуемые параметры Docker Daemon на менеджерах (`/etc/docker/daemon.json`):

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "metrics-addr": "0.0.0.0:9323",
  "experimental": false,
  "live-restore": true,
  "storage-driver": "overlay2"
}
```

- **log-opts:** Защита от заполнения диска.
- **metrics-addr:** Включение метрик Docker Engine (порт 9323) для `node_exporter`.
- **live-restore:** Ускоряет восстановление после перезагрузки узла.

### Сценарий 2: Создание общих Overlay-сетей

Общие сети должны существовать до того, как стеки попытаются к ним подключиться.

```bash
# Создание публичной сети с шифрованием и корректным MTU
docker network create \
  --driver overlay \
  --attachable \
  --opt encrypted \
  --opt mtu=1450 \
  public_net

# Создание внутренней сети для мониторинга
docker network create \
  --driver overlay \
  --internal \
  --attachable \
  monitoring_net

# Проверка
docker network ls --filter driver=overlay
```

### Сценарий 3: Развертывание Traefik (Ingress)

Traefik развертывается как сервис в Swarm с привязкой к менеджерским узлам. Используется `socket-proxy` для ограничения доступа к Docker API.

Структура стека `infra-stack/traefik/`:

```yaml
# docker-compose.yml
version: '3.8'

configs:
  traefik-config:
    file: ./traefik.yml

services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    networks:
      - traefik-internal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - SERVICES=1
      - TASKS=1
      - NETWORKS=1
      - NODES=1
      - SWARM=1
    deploy:
      placement:
        constraints: [node.role == manager]
      resources:
        limits:
          cpus: '0.1'
          memory: 64M

  traefik:
    image: traefik:v3.7
    configs:
      - source: traefik-config
        target: /etc/traefik/traefik.yml
    ports:
      - target: 80
        published: 80
        mode: host
      - target: 443
        published: 443
        mode: host
    volumes:
      - letsencrypt-data:/letsencrypt
    networks:
      - traefik-public
      - traefik-internal
    healthcheck:
      test: ["CMD", "traefik", "healthcheck"]
      interval: 10s
      timeout: 5s
      retries: 3
    deploy:
      replicas: 1
      placement:
        constraints: [node.role == manager]
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.api.rule=Host(`traefik.example.com`)"
        - "traefik.http.routers.api.service=api@internal"
        - "traefik.http.routers.api.entrypoints=websecure"
        - "traefik.http.routers.api.tls=true"
        - "traefik.http.routers.api.middlewares=auth"
        - "traefik.http.middlewares.auth.basicauth.users=admin:$$apr1$$..."

networks:
  traefik-public:
    external: true
  traefik-internal:
    driver: overlay

volumes:
  letsencrypt-data:
```

Статическая конфигурация `traefik.yml`:

```yaml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@example.com
      storage: /letsencrypt/acme.json
      httpChallenge:
        entryPoint: web

providers:
  swarm:
    endpoint: "tcp://socket-proxy:2375"
    exposedByDefault: false

api:
  dashboard: true
```

### Сценарий 4: Развертывание стека мониторинга и логирования

Инфраструктурный стек должен включать полный цикл сбора метрик и логов.

```yaml
# docker-compose.yml (фрагмент)
version: '3.8'

services:
  node-exporter:
    image: prom/node-exporter:v1.8
    networks:
      - monitoring_net
    deploy:
      mode: global
      resources:
        limits:
          cpus: '0.1'
          memory: 128M

  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.6
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    networks:
      - monitoring_net
    deploy:
      mode: global
      resources:
        limits:
          cpus: '0.5'
          memory: 512M

  prometheus:
    image: prom/prometheus:v2.48
    volumes:
      - prometheus-data:/prometheus
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    networks:
      - monitoring_net
      - traefik-public
    deploy:
      replicas: 1
      placement:
        constraints: [node.role == manager]
      resources:
        limits:
          memory: 1G

  grafana:
    image: grafana/grafana:10.4
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GF_ADMIN_PASSWORD}
    networks:
      - monitoring_net
      - traefik-public
    deploy:
      replicas: 1
      placement:
        constraints: [node.role == manager]
      resources:
        limits:
          memory: 256M

  loki:
    image: grafana/loki:2.9
    volumes:
      - loki-data:/loki
    command: -config.file=/etc/loki/local-config.yaml
    networks:
      - monitoring_net
    deploy:
      replicas: 1
      placement:
        constraints: [node.role == manager]

volumes:
  prometheus-data:
  grafana-data:
  loki-data:

networks:
  monitoring_net:
    external: true
  traefik-public:
    external: true
```

### Сценарий 5: Развертывание UI-портала управления (Portainer)

Portainer предоставляет веб-интерфейс для управления Swarm-кластером без использования CLI.

```yaml
services:
  portainer:
    image: portainer/portainer-ce:latest
    command: -H unix:///var/run/docker.sock
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - portainer-data:/data
    networks:
      - traefik-public
      - monitoring_net
    deploy:
      replicas: 1
      placement:
        constraints: [node.role == manager]
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.portainer.rule=Host(`portainer.example.com`)"
        - "traefik.http.routers.portainer.entrypoints=websecure"
        - "traefik.http.routers.portainer.tls.certresolver=letsencrypt"
      resources:
        limits:
          memory: 128M

volumes:
  portainer-data:

networks:
  traefik-public:
    external: true
```

### Сценарий 6: CI/CD пайплайн для инфраструктуры

Пайплайн использует Docker Context для переключения между кластерами и деплоит инфраструктурный стек с ручным подтверждением.

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - deploy

variables:
  COMPOSE_FILE: docker-compose.yml
  DOCKER_IMAGE: docker:29

before_script:
  - docker context rm -f ${CONTEXT_NAME} || true
  - docker context create ${CONTEXT_NAME} \
      --docker "host=${DOCKER_HOST},ca=${DOCKER_CA},cert=${DOCKER_CERT},key=${DOCKER_KEY}"
  - docker context use ${CONTEXT_NAME}

validate:
  stage: validate
  image: ${DOCKER_IMAGE}
  script:
    - docker compose config > /dev/null

deploy_infra:
  stage: deploy
  image: ${DOCKER_IMAGE}
  script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
    - docker stack deploy -c ${COMPOSE_FILE} infra --with-registry-auth --prune
    - docker service ls --filter name=infra
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

### Сценарий 7: Мультиокружение (dev/staging/prod)

Разделение инфраструктуры по окружениям через Docker Context:

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
│       ├── docker-compose.yml      # 3+ replicas
│       └── context.env
└── .gitlab-ci.yml
```

```yaml
# .gitlab-ci.yml
.deploy_template: &deploy_template
  stage: deploy
  image: docker:29
  before_script:
    - docker context rm -f ${CONTEXT_NAME} || true
    - docker context create ${CONTEXT_NAME} \
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

### Сценарий 8: Автоматизация TLS через ACME (Let's Encrypt)

Traefik v3.7 поддерживает автоматическое получение и обновление SSL-сертификатов через ACME-протокол.

```yaml
services:
  traefik:
    command:
      - "--certificatesresolvers.letsencrypt.acme.email=admin@example.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
      - "--certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web"
    volumes:
      - "letsencrypt-data:/letsencrypt"
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

> **Важно:** Let's Encrypt имеет Rate Limit (50 сертификатов на домен в неделю). На dev/staging используйте staging-сервер ACME или self-signed сертификаты.

### Сценарий 9: Rolling Update инфраструктурных сервисов

Инфраструктурные сервисы обновляются через `docker stack deploy` с особыми ограничениями:

```yaml
deploy:
  update_config:
    parallelism: 1
    delay: 30s
    order: start-first
    failure_action: rollback
    monitor: 60s
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

1. **Сети** — проверьте создание новых overlay-сетей (`docker network ls`).
2. **Traefik** — обновите первым, так как он маршрутизирует трафик ко всем сервисам.
3. **Prometheus/Grafana** — обновите вторыми для контроля метрик.
4. **Логирование** — обновите последним, чтобы не потерять логи во время обновления.

**Принудительный откат:**

```bash
docker service rollback infra_traefik
docker service inspect --format '{{.UpdateStatus.State}} {{.UpdateStatus.Message}}' infra_traefik
```

### Сценарий 10: Бэкап и восстановление Raft-логов и секретов

Регулярный бэкап критичен для восстановления кластера после сбоя менеджеров.

```bash
# На менеджере (с включенным Swarm Autolock)
tar -czf /backup/swarm-raft-$(date +%Y%m%d).tar.gz /var/lib/docker/swarm/raft/

# Экспорт секретов
docker secret ls --format "{{.Name}}" | while read secret; do
  docker secret inspect --format '{{printf "%s %s" .Name .ID}}' "$secret" >> /backup/secrets-manifest-$(date +%Y%m%d).txt
done

# Бэкап метаданных стеков
docker stack ls
```

**Восстановление:**

```bash
# Остановка демона Docker на целевом менеджере
systemctl stop docker

# Восстановление Raft-логов
tar -xzf /backup/swarm-raft-20241001.tar.gz -C /var/lib/docker/swarm/

# Запуск и разблокировка (если включен Autolock)
systemctl start docker
docker swarm unlock

# Воссоздание секретов из манифеста
while read name id; do
  docker secret create "$name" /path/to/secret-file
done < secrets-manifest-20241001.txt
```

## Операции и команды

### Управление стеками

```bash
# Развертывание стека
docker stack deploy -c docker-compose.yml infra --with-registry-auth --prune

# Список сервисов в стеке
docker stack services infra
# → ID            NAME           MODE        REPLICAS  IMAGE

# Задачи сервиса (с отображением узлов)
docker stack ps infra --no-trunc

# Удаление стека
docker stack rm infra
```

### Управление сетями

```bash
# Создание сети
docker network create --driver overlay --attachable --opt encrypted --opt mtu=1450 public_net

# Список сетей
docker network ls --filter driver=overlay

# Удаление сети (только если нет сервисов в ней)
docker network rm public_net
```

### Управление секретами

```bash
# Создание секрета
echo "password" | docker secret create mysecret -

# Список секретов
docker secret ls

# Удаление секрета
docker secret rm mysecret
```

### Диагностика

```bash
# Статус узлов
docker node ls

# Статус сервисов
docker service ls

# Логи сервиса (последние 100 строк)
docker service logs --tail 100 infra_traefik

# Инспекция задачи
docker service inspect --format '{{.UpdateStatus.State}}' infra_traefik
```

## Диагностика типовых проблем

| Проблема | Причина | Решение |
|:---|:---|:---|
| `network public_net not found` | Сеть не создана вручную | Запустите Сценарий 2 на одном из менеджеров. |
| `context already exists` | Повторный запуск `create` без очистки | Добавьте `docker context rm -f` в `before_script`. |
| Traefik не видит сервисы | Ошибка в `constraints` | Проверьте, что Traefik запущен на узле с ролью `manager`. |
| SSL не работает | Порт 443 закрыт или лимит LE | Проверьте Firewall и логи Traefik. |
| 502 Bad Gateway | Приложение не в сети `public_net` | Проверьте секцию `networks` в Compose-файле. |
| `No manager nodes are currently reachable` | Потеря кворума | Проверьте NTP на менеджерах. При необходимости используйте `docker swarm init --force-new-cluster`. |
| `failed to initialize raft node` | Проблемы с сетью | Проверьте доступность портов 2377, 7946, 4789 между менеджерами. |
| `service not found in DNS` | DNS-проблема | Проверьте, что контейнер находится в overlay-сети и имя сервиса указано без домена. |
| `image not found` | Отсутствие registry auth | Используйте флаг `--with-registry-auth` при деплое. |
| `secret not found` | Секрет не создан | Создайте секрет на менеджере: `echo "password" \| docker secret create mysecret -`. |

## Best Practices

### Безопасность инфраструктуры

- **Никогда не открывайте порт 2375:** Используйте только 2376 с mTLS для удаленного доступа.
- **Ограничьте firewall:** Порт 2376 разрешайте только с IP-адресов CI-раннеров (`ufw allow from <CI_IP> to any port 2376`).
- **Swarm Autolock:** Включите `docker swarm update --autolock=true` для защиты данных Raft при перезагрузке менеджеров.
- **Socket Proxy:** Запускайте Traefik через `socket-proxy`, а не через прямой монтинг `/var/run/docker.sock`.
- **Хранилище секретов:** Никогда не храните `ca-key.pem` или пароли в репозитории. Используйте GitLab Secrets, GitHub Secrets или HashiCorp Vault.

### Надежность

- **Нечетное количество менеджеров:** Используйте 3 (tolerates 1 failure) или 5 (tolerates 2 failures) менеджеров.
- **Drain менеджеров в HA:** В production переводите менеджеров в режим `drain`, чтобы они занимались только управлением.
- **NTP-синхронизация:** Обязательно настройте `chrony` или `systemd-timesyncd` на всех узлах.
- **MTU 1450 для Overlay:** Установите MTU интерфейса `docker0` в 1450 (VXLAN добавляет 50 байт заголовка).
- **Health Checks:** Настройте `HEALTHCHECK` в каждом инфраструктурном сервисе.

### Производительность

- **Resource Limits:** Всегда указывайте `resources.limits` и `resources.reservations` для каждого сервиса.
- **Log rotation:** Настройте `log-opts` в `daemon.json` (`max-size: 10m`, `max-file: 3`).
- **Иммутабельность образов:** Никогда не используйте тег `:latest` в production. Используйте конкретные версии или SHA256.
- **--with-registry-auth:** Всегда используйте флаг при деплое стека с приватным registry.

### Эксплуатация

- **Мониторинг:** Разверните Prometheus + Grafana + cAdvisor для мониторинга состояния кластера, узлов и сервисов.
- **Бэкапы:** Регулярно бэкапите Raft-лог менеджеров (`/var/lib/docker/swarm/raft/`) и данные секретов. Храните бэкапы вне кластера.
- **Idempotent операции:** Все скрипты деплоя и CI/CD должны быть идемпотентными.
- **Валидация перед деплоем:** В CI/CD добавляйте стадию валидации Compose-файлов (`docker compose config`).
- **Post-deploy verification:** После каждого деплоя проверяйте статус сервисов (`docker service ls`, `docker service ps`).
- **Документация:** Ведите актуальный инвентарь узлов (IP, роль, метки) и токенов присоединения.

## Дополнительная информация

### Связанные документы

- **[Подготовка кластера (mTLS)](./swarm_setup.md)** — генерация сертификатов и инициализация Swarm.
- **[Docker Context](./docker_context_setup.md)** — управление подключениями к кластерам.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — детальная настройка маршрутизации и middleware.
- **[Секреты и конфиги Swarm](../swarm_secrets_configs.md)** — безопасная доставка данных в контейнеры.
- **[Лучшие практики CI/CD](./best_practices.md)** — стандарты безопасности и оптимизации.
- **[Развертывание стеков](../swarm_stack_deployment.md)** — детальное использование `docker stack`.
- **[Основные концепции Docker Swarm](../swarm_core_concepts.md)** — теория Raft, кворум и жизненный цикл задач.
- **[Сетевое взаимодействие в Swarm](../swarm_networking.md)** — Routing Mesh и Overlay.
