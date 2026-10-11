# GitLab Runner в Docker Swarm: деплой и автокеллинг

> **Статус:** Docker Swarm не развивается. Применяется только для поддержки существующих
> развёртываний; для новых — Kubernetes.

**Актуально для:** Docker Engine 29.x+, Docker Swarm mode (Compose file v3.8+), GitLab Runner v19.x

## Определения

- **[GitLab Runner](https://docs.gitlab.com/runner/):** Агент (приложение на Go), который опрашивает GitLab по API, получает задания и исполняет их в изолированной среде. В данном сценарии используется режим **docker executor** с монтированием сокета Docker или подключением к Docker-демону через TCP для управления контейнерами на swarm-нодах.
- **[Runner Authentication Token](https://docs.gitlab.com/runner/register/#register-with-a-runner-authentication-token):** Токен формата `glrt-`, заменяющий устаревший registration token. Используется для связывания раннера с инстансом GitLab. Имеет область видимости (instance/group/project) и набор тегов.
- **[Docker Executor](https://docs.gitlab.com/runner/executors/docker/):** Режим исполнения, при котором каждый джоб запускается в отдельном контейнере. Обеспечивает изоляцию и позволяет использовать Docker-in-Docker (DinD) или прямой доступ к Docker-демону через сокет/TCP.
- **[Docker Swarm Mode](../docker_swarm_overview.md):** Встроенный механизм оркестрации Docker. В контексте раннеров используется режим развертывания **global** (аналог DaemonSet в Kubernetes), который запускает один экземпляр контейнера на каждой ноде кластера.
- **[Autoscaling (автокеллинг):** Способность системы автоматически увеличивать количество исполнительных ресурсов при росте очереди заданий. В связке GitLab Runner + Swarm автокеллинг достигается за счет того, что каждый раннер на ноде может создавать новые контейнеры через локальный Docker-демон.
- **[Docker Socket Proxy](../swarm_ingress_traefik.md):** Вспомогательный сервис (`tecnativa/docker-socket-proxy`), ограничивающий доступ к Docker API только необходимыми операциями чтения вместо прямого монтирования `/var/run/docker.sock` в контейнер раннера.
- **[Rootless Docker](../docker_swarm_overview.md):** Режим работы Docker-демона от имени обычного пользователя, минимизирующий риски "побега" из контейнера на хост-систему. Применим и для раннеров, требующих привилегированного доступа.

## Базовые концепции

### Архитектура решения

При использовании Kubernetes для CI/CD-раннеров требуется полноценный кластер, что добавляет операционную сложность. Docker Swarm позволяет запускать раннеры на тех же нодах, где выполняются приложения, без выделения отдельного кластера.

Ключевые компоненты архитектуры:

1. **GitLab Runner Manager (контейнер на каждой swarm-ноде):**
   - Запускается в режиме `deploy.mode: global` — один экземпляр на узел.
   - Монтирует `/var/run/docker.sock` хоста или подключается к `docker-socket-proxy` для управления локальным Docker-демоном.
   - Читает конфигурацию из `/etc/gitlab-runner/config.toml`, смонтированного из bind-mount.

2. **Конфигурационный файл (`config.toml`):**
   - Хранится на каждой ноде (раздается через Ansible или config-сервис).
   - Содержит `executor = "docker"`, токен аутентификации, настройки volumes и привилегий.

3. **Swarm-кластер:**
   - Менеджер-ноды управляют состоянием стека.
   - Воркер-ноды принимают задачи (контейнеры джобов), созданные раннерами.

### Почему Swarm вместо Kubernetes

| Критерий | Docker Swarm | Kubernetes |
|:---|:---|:---|
| Порог вхождения | Низкий (стандартный Compose YAML) | Высокий (Manifests, Helm, Operators) |
| Операционная сложность | Один бинарник `dockerd` на каждом хосте | Отдельные control plane, etcd, CNI, CSI |
| Режим развертывания раннеров | `global` в stack-файле | DaemonSet / Deployment + HPA |
| Автокеллинг | Через локальный docker.sock на каждой ноде | Через Fleeting / Taskscaler (16.0+) |
| Подходит для | Средних команд, существующих Swarm-инфраструктур | Крупных организаций, cloud-native стеков |

### Безопасность монтирования Docker Socket

Проброс `/var/run/docker.sock` в контейнер раннера дает ему права суперпользователя на хост-системе (практически эквивалент `root`).

- **В производственной среде Swarm:** это стандартная практика для docker-executor, так как раннер должен создавать контейнеры джобов. Риск митигируется изоляцией swarm-нод (раннер видит только свой узел) и использованием привилегированных контейнеров только где необходимо.
- **Альтернатива:** использовать `docker-socket-proxy` для ограничения доступа только к необходимым API-операциям. Детали см. в **[swarm_ingress_traefik.md](../swarm_ingress_traefik.md)**.
- **Альтернатива:** использовать **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md)** для сборки образов и ограничить раннеры shell/docker-executor без privileged. Однако Kaniko не подходит для сценариев, где джобы требуют запуска произвольных контейнеров (интеграционные тесты, testcontainers). Детали см. в **[best_practices.md](./best_practices.md)**.
- **Rootless-подход:** запуск раннера в контейнере с подключением к rootless Docker-демону на хосте. Минимизирует риски, но требует дополнительной настройки UID-маппинга и subuid/subgid. Общая концепция описана в **[docker_swarm_overview.md](../docker_swarm_overview.md)**.

### Ресурсы и планирование

Глобальный режим развертывания создает один контейнер раннера на каждой ноде. При проектировании пропускной способности учитывайте:

- `concurrent` в `config.toml` — лимит джобов на **одном** раннере (ноде).
- `deploy.resources.limits` — квоты CPU/RAM для контейнера раннера, чтобы он не потреблял весь бюджет ноды.
- `check_interval` — интервал опроса GitLab API. `0` означает агрессивный поллинг; для средних нагрузок используйте `5–10` секунд.

### Синхронизация времени

NTP критически важен для корректной работы Swarm-кластера и регистрации раннеров. Расхождение более чем в несколько секунд приводит к ошибкам TLS-рукопожатий и проблемам с кворумом Raft. Используйте `chrony` или `systemd-timesyncd` на всех нодах.

## Предварительные требования

Перед развертыванием GitLab Runner в Swarm убедитесь, что инфраструктура соответствует следующим критериям:

- **Версия Docker:** Docker Engine 29.x+ на всех узлах кластера.
- **Сетевая доступность:** Раннеры имеют доступ к GitLab API (порт 443/TCP) и реестру образов.
- **Синхронизация времени:** На всех нодах настроен NTP.
- **Сертификаты:** При использовании mTLS подготовлен CA и клиентские сертификаты для CI-раннеров (порт 2376/TCP).
- **Реестр:** Swarm-менеджеры и воркеры имеют сетевой доступ к реестру образов.
- **Secrets management:** Для хранения токена раннера настроен Ansible Vault или HashiCorp Vault. Никогда не храните токены в Git-репозитории.

## Практические сценарии

### Сценарий 1: Получение Runner Authentication Token

Устаревший `registration token` (просто длинная строка) заменен на **Runner Authentication Token** (начинается с `glrt-`). Новый токен создается в интерфейсе GitLab и сразу привязан к области видимости и тегам.

1. Перейдите в **Admin Area → CI/CD → Runners** (или в настройки группы/проекта).
2. Нажмите **New instance runner** (или **New group runner** / **New project runner**).
3. Укажите теги (tags), по которым пайплайны будут выбирать этот флот раннеров. Например: `swarm`.
4. На следующей странице скопируйте токен (сохраните его в защищенном хранилище: Ansible Vault или HashiCorp Vault).
5. GitLab перейдет в состояние ожидания регистрации раннера с этим токеном.

### Сценарий 2: Подготовка конфигурации `config.toml`

Файл конфигурации создается один раз и разкладывается на все swarm-ноды. Ниже минимальный рабочий шаблон:

```toml
concurrent = 5
check_interval = 5

[[runners]]
  name = "docker-swarm-runner"
  url = "https://<YOUR-GITLAB-INSTANCE>/"
  token = "<GITLAB AUTHENTICATION TOKEN>"
  executor = "docker"
  [runners.custom_build_dir]
  [runners.docker]
    tls_verify = false
    image = "alpine:latest"
    privileged = true
    disable_entrypoint_overwrite = false
    oom_kill_disable = false
    disable_cache = false
    volumes = ["/cache"]
    shm_size = 0
    allowed_pull_policies = ["always", "if-not-present", "never"]
  [runners.cache]
    [runners.cache.s3]
```

**Важные параметры:**
- `concurrent` — максимальное количество одновременно выполняемых джобов на **одном** раннере (ноде). При 5 нодах и `concurrent = 5` общая пропускная способность — 25 джобов.
- `check_interval` — интервал опроса GitLab API в секундах. Значение `0` означает максимально частый поллинг; для большинства сред recommended `5–10`.
- `privileged = true` — требуется для Docker-in-Docker и запуска привилегированных контейнеров. Если джобы не требуют сборки образов, установите `false`.
- `volumes = ["/cache"]` — кэш зависимостей (например, `node_modules`, `~/.m2`), сохраняемый между джобами на ноде.
- `shm_size = 0` — отключает разделяемую память; при проблемах с памятью в джобах установите `shm_size = "2gb"`.

### Сценарий 3: Распределение конфигурации по нодам (Ansible)

Хранить токен в Git-репозитории небезопасно. Используйте Ansible Vault или внешние секрет-хранилища.

**Шаблон `templates/config.toml.j2`:**

```jinja
concurrent = 5
check_interval = 5

[[runners]]
  name = "docker-swarm-runner"
  url = "{{ gitlab_instance_url }}"
  token = "{{ gitlab_runner_swarm_auth_token.value }}"
  executor = "docker"
  [runners.custom_build_dir]
  [runners.docker]
    tls_verify = false
    image = "alpine:latest"
    privileged = true
    disable_entrypoint_overwrite = false
    oom_kill_disable = false
    disable_cache = false
    volumes = ["/cache"]
    shm_size = 0
    allowed_pull_policies = ["always", "if-not-present", "never"]
  [runners.cache]
    [runners.cache.s3]
```

**Задача `tasks/main.yml`:**

```yaml
- name: Create directories
  ansible.builtin.file:
    path: /etc/gitlab-runner/config
    state: directory
    recurse: true

- name: Copy config file
  ansible.builtin.template:
    src: config.toml.j2
    dest: /etc/gitlab-runner/config/config.toml
```

Конфигурационный файл должен присутствовать на **всех** swarm-нодах (менеджерах и воркерах), так как раннер может быть запланирован на любой узел.

### Сценарий 4: Деплой стека раннеров

Swarm работает с docker-compose файлами версии 3.8+. Создайте стек для развертывания раннеров:

```yaml
services:
  gitlab-runner:
    image: gitlab/gitlab-runner:ubuntu-v19.3.1
    deploy:
      mode: global
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 256M
      restart_policy:
        condition: any
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/gitlab-runner/config:/etc/gitlab-runner
    networks:
      - gitlab-net

networks:
  gitlab-net:
    external: false
```

**Параметры:**
- `deploy.mode: global` — гарантирует запуск одного контейнера на каждой ноде кластера. Аналог Kubernetes DaemonSet.
- `deploy.resources.limits` — жесткие лимиты CPU и RAM для контейнера раннера, защищающие ноду от исчерпания ресурсов.
- `volumes`:
  - `/var/run/docker.sock` — дает раннеру доступ к Docker-демону ноды для создания контейнеров джобов (автокеллинг).
  - `/etc/gitlab-runner/config` — смонтированный конфиг с токеном и настройками.
- `image` — используйте фиксированную версию образа, соответствующую версии GitLab. Актуальные теги: [Docker Hub](https://hub.docker.com/r/gitlab/gitlab-runner/tags).

**Распределение stack-файла через Ansible:**

```yaml
- name: Copy compose file
  ansible.builtin.template:
    src: docker-compose.yml.j2
    dest: /etc/gitlab-runner/docker-compose.yml
```

**Запуск стека (с менеджер-ноды):**

```bash
docker stack deploy -c /etc/gitlab-runner/docker-compose.yml gitlab-runner
```

### Сценарий 5: Валидация deployments

Проверка состояния задач в стеке:

```bash
docker stack ps gitlab-runner
# →
# ID             NAME                                              IMAGE                                 NODE           DESIRED STATE   CURRENT STATE        ERROR     PORTS
# pnkxq7yf3wm3   gitlab-runner.1tlong-name   gitlab/gitlab-runner:ubuntu-v19.3.1   swarm-node01   Running         Running 2 days ago
# ih4822qch9ew   gitlab-runner.3tlong-name   gitlab/gitlab-runner:ubuntu-v19.3.1   swarm-node03   Running         Running 2 days ago
# xzj5yt1cv5ae   gitlab-runner.2tlong-name   gitlab/gitlab-runner:ubuntu-v19.3.1   swarm-node02   Running         Running 2 days ago
```

В интерфейсе GitLab (Admin Area → CI/CD → Runners) должен появиться зарегистрированный раннер с соответствующими тегами.

### Сценарий 6: Проверка работы автокеллинга

Создайте тестовый пайплайн, запускающий несколько параллельных джобов:

```yaml
stages:
  - test

parallel-jobs:
  stage: test
  tags:
    - swarm
  script:
    - echo "Starting sleep for 600 seconds"
    - sleep 600
  parallel:
    matrix:
      - JOB_NAME: "job1"
      - JOB_NAME: "job2"
      - JOB_NAME: "job3"
      - JOB_NAME: "job4"
      - JOB_NAME: "job5"
      - JOB_NAME: "job6"
      - JOB_NAME: "job7"
      - JOB_NAME: "job8"
      - JOB_NAME: "job9"
      - JOB_NAME: "job10"
```

Ожидаемый результат:
- На разных swarm-нодах появятся контейнеры с джобами.
- Контейнеры gitlab-runner (по одному на ноду) опрашивают GitLab и создают динамические контейнеры под джобы.
- Метрики cAdvisor в Grafana покажут параллельные контейнеры на разных нодах. Детали см. в **[infra_deployment.md](./infra_deployment.md)**.

Проверка через Docker CLI на нодах:

```bash
docker ps --filter "name=gitlab-runner"
docker ps --filter "label=com.gitlab.runner.job"
```

### Сценарий 7: Ограничение ресурсов и размещение

Указывайте лимиты ресурсов для контейнеров раннеров, чтобы защитить ноды от исчерпания:

```yaml
services:
  gitlab-runner:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
      placement:
        constraints:
          - node.labels.ci_worker == true
```

- `constraints` — ограничивает запуск раннеров только нодами с определенным лейблом. Это позволяет отделить CI-инфраструктуру от продакшн-сервисов.
- `reservations` — гарантирует минимальный объем ресурсов для раннера.
- `limits` — жесткий потолок, при превышении которого Docker применяет OOM Kill или throttling CPU.

### Сценарий 8: Управление контекстами для мультиокружения

Используйте Docker Context для переключения между кластерами dev/stage/prod в пайплайнах:

```bash
docker context rm -f ${CONTEXT_NAME} || true
docker context create ${CONTEXT_NAME} \
  --docker "host=tcp://${MANAGER_IP}:2376,ca=ca.pem,cert=cert.pem,key=key.pem"
docker context use ${CONTEXT_NAME}
```

**Интеграция с GitLab CI:**

```yaml
deploy_to_swarm:
  stage: deploy
  image: docker:29
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  before_script:
    - docker context rm -f ${CONTEXT_NAME} || true
    - docker context create ${CONTEXT_NAME} \
        --docker "host=tcp://${MANAGER_IP}:2376,ca=ca.pem,cert=cert.pem,key=key.pem"
    - docker context use ${CONTEXT_NAME}
  script:
    - docker stack deploy -c docker-compose.yml my-app --with-registry-auth --prune
  after_script:
    - docker context use default
    - docker context rm -f ${CONTEXT_NAME} || true
```

Детали работы с Docker Context см. в **[docker_context_setup.md](./docker_context_setup.md)**.

### Сценарий 9: Rootless Runner

Для сценариев, где требуется минимизировать привилегированный доступ, разверните раннер с подключением к rootless Docker-демону на хосте:

1. Настройте rootless Docker на каждой ноде согласно **[docker_swarm_overview.md](../docker_swarm_overview.md)**.
2. Создайте сервис раннера с переменной окружения `DOCKER_HOST=unix:///run/user/999/docker.sock`.
3. Убедитесь, что UID/GID раннера совпадает с владельцем rootless-сокета.

```yaml
services:
  gitlab-runner:
    image: gitlab/gitlab-runner:ubuntu-v19.3.1
    deploy:
      mode: global
    environment:
      - DOCKER_HOST=unix:///run/user/999/docker.sock
    volumes:
      - /etc/gitlab-runner/config:/etc/gitlab-runner
```

**Ограничения rootless-подхода:**
- Нет поддержки привилегированных контейнеров (privileged mode).
- Ограниченная производительность по сравнению с стандартным Docker.
- Требует настройки UID-маппинга (`/etc/subuid`, `/etc/subgid`).

## Справочная информация

### Сравнение подходов к развертыванию GitLab Runner

| Подход | Масштабирование | Изоляция | Сложность |
|:---|:---|:---|:---|
| **Static runner (VM)** | Вертикальное (добавление машин) | Средняя (systemd, процессы) | Средняя |
| **Docker Executor + docker.sock (Swarm)** | Горизонтальное (по нодам Swarm) | Высокая (каждый джоб в контейнере) | Низкая |
| **Docker Executor + socket-proxy (Swarm)** | Горизонтальное (по нодам Swarm) | Высокая (ограниченный API) | Низкая |
| **Kubernetes Executor + Fleeting** | Горизонтальное (Pods + VM pool) | Высокая (Pod per job) | Высокая |
| **Kaniko / Rootless Docker** | Ограниченное (нет произвольных контейнеров) | Высокая (userspace) | Средняя |

### Типичные проблемы и решения

| Симптом | Причина | Диагностика | Решение |
|:---|:---|:---|:---|
| Раннер не появляется в GitLab | Неверный токен или URL | Логи контейнера: `docker service logs gitlab-runner` | Проверьте `url` и `token` в `config.toml` |
| Джоб висит в `pending` | Нет свободных слотов на ноде | `docker node inspect <node>`; метрики | Увеличьте `concurrent` или добавьте ноды |
| `Cannot connect to Docker daemon` | `/var/run/docker.sock` не смонтирован | `docker service inspect gitlab-runner` | Проверьте `volumes` в stack-файле |
| OOM-kill джоба | Недостаточно RAM на ноде | `dmesg \| grep -i oom` | Увеличьте `deploy.resources.limits.memory` или добавьте ноды |
| `privileged` не работает | Секция `[runners.docker]` отсутствует в `config.toml` | `docker exec <runner> cat /etc/gitlab-runner/config.toml` | Добавьте блок с `privileged = true` |
| Джоб падает с `Docker-in-Docker` ошибкой | Недостаточно shared memory | Логи джоба в GitLab | Увеличьте `shm_size` до `"2gb"` в `config.toml` |
| Раннер регистрируется, но не подхватывает джобы | Несовпадение тегов | Проверьте теги раннера в GitLab UI и `tags` в `.gitlab-ci.yml` | Убедитесь, что теги совпадают |

### Лучшие практики

1. **Версионирование образа:** никогда не используйте `:latest` для `gitlab/gitlab-runner` в продакшене. Фиксируйте версию, соответствующую версии GitLab.
2. **Хранение токенов:** используйте Ansible Vault или HashiCorp Vault. Никогда не коммитьте `config.toml` с токеном в Git.
3. **Ограничение привилегий:** если джобы не требуют DinD, установите `privileged = false`. Для сборки образов используйте Kaniko или rootless-подход. Детали см. в **[best_practices.md](./best_practices.md)**.
4. **Квотирование ресурсов:** указывайте `deploy.resources.limits` для сервисов на swarm-нодах, чтобы раннеры не потребляли весь RAM/CPU.
5. **Мониторинг:** экспортируйте метрики раннеров (`:9252/metrics`) в Prometheus. Ключевые метрики: `gitlab_runner_jobs_total`, Queue Time, Runner Saturation. Детали см. в **[infra_deployment.md](./infra_deployment.md)**.
6. **Чистка:** настройте `docker system prune` через `systemd.timer` на нодах для предотвращения переполнения диска старыми образами джобов.
7. **Сокет Docker:** предпочитайте `docker-socket-proxy` прямому монтированию `/var/run/docker.sock` там, где это возможно. Детали см. в **[swarm_ingress_traefik.md](../swarm_ingress_traefik.md)**.
8. **Изоляция нод:** используйте лейблы `node.labels.ci_worker == true` для размещения раннеров на выделенных нодах, отделенных от продакшн-нагрузки.
9. **Ротация токенов:** периодически обновляйте Runner Authentication Token и переразворачивайте стек. Настройте уведомление об истечении срока действия токена.
10. **Health Checks:** добавьте healthcheck в stack-файл для раннера, чтобы Swarm мог автоматически перезапускать упавшие экземпляры.

### Связанные документы

- **[Обзор Docker Swarm](../docker_swarm_overview.md)** — архитектура кластера, менеджеры и воркеры, rootless режим.
- **[CI/CD в Docker Swarm: Обзор](./overview.md)** — архитектурные концепции конвейера доставки.
- **[Docker Context в CI/CD](./docker_context_setup.md)** — управление подключениями к кластерам.
- **[Развертывание приложения через GitLab CI](./app_deployment.md)** — пайплайны деплоя в Swarm.
- **[Лучшие практики CI/CD в Swarm](./best_practices.md)** — безопасность, Kaniko, ротация секретов.
- **[Развертывание инфраструктуры (Traefik, Portainer, Monitoring)](./infra_deployment.md)** — инфраструктурный стек, мониторинг, docker-socket-proxy.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — детальная настройка маршрутизации и docker-socket-proxy.
- **[Основные концепции Docker Swarm](../swarm_core_concepts.md)** — теория Raft, кворум и жизненный цикл задач.
