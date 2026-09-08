# GitLab Runner в Docker Swarm: деплой и автокеллинг

## Определения

- **[GitLab Runner](https://docs.gitlab.com/runner/):** Агент (приложение на Go), который опрашивает GitLab по API, получает задания и исполняет их в изолированной среде. В данном сценарии используется режим **docker executor** с монтированием сокета Docker для управления контейнерами на swarm-нодах.
- **[Runner Authentication Token](https://docs.gitlab.com/runner/register/#register-with-a-runner-authentication-token):** Токен формата `glrt-`, заменяющий устаревший registration token. Используется для связывания раннера с инстансом GitLab. Имеет область видимости (instance/group/project) и набор тегов.
- **[Docker Executor](https://docs.gitlab.com/runner/executors/docker/):** Режим исполнения, при котором каждый джоб запускается в отдельном контейнере. Обеспечивает изоляцию и позволяет использовать Docker-in-Docker (DinD) или прямой доступ к Docker-демону через сокет.
- **[Docker Swarm Mode](../docker_swarm_overview.md):** Встроенный механизм оркестрации Docker. В контексте раннеров используется режим развертывания **global** (аналог DaemonSet в Kubernetes), который запускает один экземпляр контейнера на каждой ноде кластера.
- **[Autoscaling (автокеллинг):** Способность системы автоматически увеличивать количество исполнительных ресурсов при росте очереди заданий. В связке GitLab Runner + Swarm автокеллинг достигается за счет того, что каждый раннер на ноде может создавать новые контейнеры через локальный Docker-демон.

## Базовые концепции

### Архитектура решения

При использовании Kubernetes для CI/CD-раннеров требуется полноценный кластер, что добавляет операционную сложность. Docker Swarm позволяет запускать раннеры на тех же нодах, где выполняются приложения, без выделения отдельного кластера.

Ключевые компоненты архитектуры:

1. **GitLab Runner Manager (контейнер на каждой swarm-ноде):**
   - Запускается в режиме `deploy.mode: global` — один экземпляр на узел.
   - Монтирует `/var/run/docker.sock` хоста для управления локальным Docker-демоном.
   - Читает конфигурацию из `/etc/gitlab-runner/config.toml`, смонтированного из swarm-secret или bind-mount.

2. **Конфигурационный файл (`config.toml`):**
   - Хранится на каждой ноде (раздается через Ansible).
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
- **Альтернатива:** использовать Kaniko для сборки образов и ограничить раннеры shell/docker-executor без privileged. Однако Kaniko не подходит для сценариев, где джобы требуют запуска произвольных контейнеров (интеграционные тесты, testcontainers).

## Практические сценарии

### Сценарий 1: Получение Runner Authentication Token

Устаревший `registration token` (просто длинная строка) заменен на **Runner Authentication Token** (начинается с `glrt-`). Новый токен создается в интерфейсе GitLab и сразу привязан к области видимости и тегам.

1. Перейдите в **Admin Area → CI/CD → Runners** (или в настройки группы/проекта).
2. Нажмите **New instance runner** (или **New group runner** / **New project runner**).
3. Укажите теги (tags), по которым пайплайны будут выбирать этот флот раннеров. Например: `swarm`.
4. На следующей странице скопируйте токен (сохраните его в защищенном хранилище: Ansible Vault, HashiCorp Vault, Sber Vault).
5. GitLab перейдет в состояние ожидания регистрации раннера с этим токеном.

### Сценарий 2: Подготовка конфигурации `config.toml`

Файл конфигурации создается один раз и разкладывается на все swarm-ноды. Ниже минимальный рабочий шаблон:

```toml
concurrent = 5
check_interval = 0

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
    [runners.cache.gcs]
```

**Важные параметры:**
- `concurrent` — максимальное количество одновременно выполняемых джобов на **одном** раннере (ноде). При 5 нодах и `concurrent = 5` общая пропускная способность — 25 джобов.
- `privileged = true` — требуется для Docker-in-Docker и запуска привилегированных контейнеров. Если джобы не требуют сборки образов, установите `false`.
- `volumes = ["/cache"]` — кэш зависимостей (например, `node_modules`, `~/.m2`), сохраняемый между джобами на ноде.
- `shm_size = 0` — отключает разделяемую память; при проблемах с памятью в джобах установите `shm_size = "2gb"`.

### Сценарий 3: Распределение конфигурации по нодам (Ansible)

Хранить токен в Git-репозитории небезопасно. Используйте Ansible Vault или внешние секрет-хранилища.

**Шаблон `templates/config.toml.j2`:**

```jinja
concurrent = 5
check_interval = 0

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
    [runners.cache.gcs]
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

Swarm работает с docker-compose файлами версии 3.x. Создайте стек для развертывания раннеров:

```yaml
services:
  gitlab-runner:
    image: gitlab/gitlab-runner:<VERSION>
    deploy:
      mode: global
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
- `volumes`:
  - `/var/run/docker.sock` — дает раннеру доступ к Docker-демону ноды для создания контейнеров джобов (автокеллинг).
  - `/etc/gitlab-runner/config` — смонтированный конфиг с токеном и настройками.
- `image` — используйте фиксированную версию образа (например, `gitlab/gitlab-runner:ubuntu-v17.3.0`). Актуальные теги: [Docker Hub](https://hub.docker.com/r/gitlab/gitlab-runner/tags).

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
# pnkxq7yf3wm3   gitlab-runner.1tlong-name   gitlab/gitlab-runner:ubuntu-v17.3.0   swarm-node01   Running         Running 2 days ago
# ih4822qch9ew   gitlab-runner.3tlong-name   gitlab/gitlab-runner:ubuntu-v17.3.0   swarm-node03   Running         Running 2 days ago
# xzj5yt1cv5ae   gitlab-runner.2tlong-name   gitlab/gitlab-runner:ubuntu-v17.3.0   swarm-node02   Running         Running 2 days ago
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
- Три верхних контейнера — это основные процессы gitlab-runner (по одному на ноду), которые опрашивают GitLab и создают динамические контейнеры под джобы.
- Метрики cAdvisor в Grafana покажут параллельные контейнеры на разных нодах.

Проверка через Docker CLI на нодах:

```bash
docker ps --filter "name=gitlab-runner"
docker ps --filter "label=com.gitlab.runner.job"
```

## Справочная информация

### Сравнение подходов к развертыванию GitLab Runner

| Подход | Масштабирование | Изоляция | Сложность |
|:---|:---|:---|:---|
| **Static runner (VM)** | Вертикальное (добавление машин) | Средняя (systemd, процессы) | Средняя |
| **Docker Executor + docker.sock (Swarm)** | Горизонтальное (по нодам Swarm) | Высокая (каждый джоб в контейнере) | Низкая |
| **Kubernetes Executor + Fleeting** | Горизонтальное (Pods + VM pool) | Высокая (Pod per job) | Высокая |
| **Kaniko / Rootless Docker** | Ограниченное (нет произвольных контейнеров) | Высокая (userspace) | Средняя |

### Типичные проблемы и решения

| Симптом | Причина | Диагностика | Решение |
|:---|:---|:---|:---|
| Раннер не появляется в GitLab | Неверный токен или URL | Логи контейнера: `docker service logs gitlab-runner` | Проверьте `url` и `token` в `config.toml` |
| Джоб висит в `pending` | Нет свободных слотов на ноде | `docker node inspect <node>`; метрики | Увеличьте `concurrent` или добавьте ноды |
| `Cannot connect to Docker daemon` | `/var/run/docker.sock` не смонтирован | `docker service inspect gitlab-runner` | Проверьте `volumes` в stack-файле |
| OOM-kill джоба | Недостаточно RAM на ноде | `dmesg \| grep -i oom` | Увеличьте `deploy.resources.limits.memory` для сервисов или добавьте ноды |
| `privileged` не работает | Секция `[runners.docker]` отсутствует в `config.toml` | `docker exec <runner> cat /etc/gitlab-runner/config.toml` | Добавьте блок с `privileged = true` |

### Лучшие практики

1. **Версионирование образа:** никогда не используйте `:latest` для `gitlab/gitlab-runner` в продакшене. Фиксируйте версию, соответствующую версии GitLab.
2. **Хранение токенов:** используйте Ansible Vault, HashiCorp Vault или Sber Vault. Никогда не коммитьте `config.toml` с токеном в Git.
3. **Ограничение привилегий:** если джобы не требуют DinD, установите `privileged = false`. Для сборки образов используйте Kaniko или rootless-подход.
4. **Квотирование ресурсов:** указывайте `deploy.resources.limits` для сервисов на swarm-нодах, чтобы раннеры не потребляли весь RAM/CPU.
5. **Мониторинг:** экспортируйте метрики раннеров (`:9252/metrics`) в Prometheus. Ключевые метрики: `gitlab_runner_jobs_total`, Queue Time, Runner Saturation.
6. **Чистка:** настройте `docker system prune` через `systemd.timer` на нодах для предотвращения переполнения диска старыми образами джобов.

### Связанные документы

- **[Обзор Docker Swarm](../docker_swarm_overview.md)** — архитектура кластера, менеджеры и воркеры.
- **[CI/CD в Docker Swarm: Обзор](./overview.md)** — архитектурные концепции конвейера доставки.
- **[Развертывание приложения через GitLab CI](./app_deployment.md)** — пайплайны деплоя в Swarm.
- **[Лучшие практики CI/CD в Swarm](./best_practices.md)** — безопасность и оптимизация.
- **[Обзор Runner'ов и Executor'ов](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_runners_executors.md)** — типы исполнителей и их характеристики.
