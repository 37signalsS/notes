# Ansible: Модули управления контейнерами

## Определения

**Модули управления контейнерами** — группа декларативных инструментов Ansible из коллекций `community.docker` и `containers.podman`, предназначенных для автоматизации сборки, публикации и управления жизненным циклом контейнеров OCI без необходимости использования прямых вызовов `docker`/`podman` CLI.

**OCI-образ (Open Container Initiative Image)** — стандартизированный формат контейнерного образа, совместимый с Docker, Podman, CRI-O и другими runtime. Ansible-модули работают с OCI-образами независимо от используемого runtime.

**Container runtime** — исполняющая среда для контейнеров. В контексте модулей:
- **Docker** — классический runtime, требует запущенного демона `dockerd`.
- **Podman** — daemonless runtime, поддерживает rootless-режим, рекомендуется для production сред, где требуется отсутствие центрального демона.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имен и коллекцию (например, `community.docker.docker_container`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен.

**Идемпотентность** — свойство модулей проверять текущее состояние объекта и вносить изменения только при отклонении от целевой конфигурации. Это фундаментальное отличие Ansible от скриптового подхода: повторный запуск плейбука не изменяет систему, если она уже находится в желаемом состоянии.

**Docker Context** — механизм именования профилей подключения к различным движкам Docker. В Ansible передается через параметр `docker_host` или переменную окружения `DOCKER_HOST`.

**containerd Image Store** — режим хранения образов, используемый по умолчанию при свежей установке Docker Engine 29.0+. При обновлении с более ранних версий демон продолжает использовать классические драйверы (overlay2) до ручного включения. Обеспечивает совместимость с Kubernetes и ускоряет операции с образами.

**Rootless Mode** — режим запуска демона и контейнеров от имени обычного пользователя без `root`-прав. В 2026 году является стандартом де-факто для production-сред, снижая поверхность атаки хоста.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.17+ | 2.21+ |
| **community.docker** | 5.0+ | 5.4.x |
| **containers.podman** | 1.9+ | 1.20.2 |
| **containers.common** | 1.0+ | Актуальная |
| **Docker Engine** | 24.0+ | 29.8.x |
| **Podman** | 4.9+ | 5.x |
| **Python** (control node) | 3.10+ | 3.12+ |
| **Python** (managed node) | 3.10+ | 3.12+ |
| **docker** (Python SDK) | 7.0+ | 7.2+ |

**Установка коллекций:**
```bash
ansible-galaxy collection install community.docker
ansible-galaxy collection install containers.podman
ansible-galaxy collection install containers.common
```

**Проверка окружения:**
```bash
docker --version
# → Docker version 29.8.0, build ...

podman --version
# → podman version 5.2.1

ansible-doc -l community.docker | head -20
```

## Основные концепции

### Архитектура модулей

Модули управления контейнерами работают через API соответствующего runtime:

1. **Docker:** модули `community.docker` используют Python SDK (`docker` package) для взаимодействия с Docker Engine API через сокет `/var/run/docker.sock` или удаленный хост (`docker_host`).
2. **Podman:** модули `containers.podman` взаимодействуют с Podman через REST API (флаг `--listen`) или через podman CLI, когда API недоступен.

Модули не требуют установки `docker`/`podman` CLI на управляемом узле — достаточно Python SDK и доступности демона.

### Жизненный цикл Build-Ship-Run

1. **Сборка (Build)** — создание образа через `docker_image_build` (BuildKit/Buildx) или `docker_image` с `source: build`.
2. **Доставка (Ship)** — передача образа через реестр (`docker_image_push`) или tar-архив (`docker_image_export`/`docker_image_load`) для air-gapped сред.
3. **Запуск (Run)** — развертывание контейнера (`docker_container`/`podman_container`), проекта Compose (`docker_compose_v2`/`podman_play`) или стека Swarm (`docker_stack`).

### Модель идемпотентности

Каждый модуль:
- Читает текущее состояние объекта через info-модуль (`docker_container_info`, `podman_container_info`).
- Сравнивает с целевым состоянием из параметров задачи.
- Выполняет только delta-изменения (создание, обновление, удаление).
- Возвращает `changed: true` только при фактическом изменении.

### Зависимости на целевых хостах (PEP 668)

В современных дистрибутивах (Ubuntu 24.04+, Debian 12+) действует PEP 668, запрещающий прямую установку пакетов через `pip` в системную область Python.

| Пакет | Назначение | Вариант установки |
| :--- | :--- | :--- |
| **`docker`** | SDK для Docker Engine | `python3-docker` (системный пакет) или `pip install --break-system-packages docker` |
| **`jsondiff`** | Сравнение JSON-конфигураций Swarm | `python3-jsondiff` |
| **`pyyaml`** | Работа с Compose/Stack YAML | `python3-yaml` |

### Особенности Docker Engine 29.x

- Формат вывода `docker version --format json` изменен; требует `community.docker` 5.0.2+.
- Exposed port ranges явно раскрываются в список портов модулем `docker_container`.
- `containerd image store` использует ID образов, не соответствующие `manifest.json` в tar-архивах; идемпотентность архивации зависит от бэкенда.

### Rootless Mode

Запуск контейнеров от имени обычного пользователя. В managed node требуется:
- Установленный Podman/Docker в rootless режиме.
- Корректная переменная `XDG_RUNTIME_DIR`.
- Передача сокета: `docker_host: "unix:///run/user/{{ ansible_user_uid }}/docker.sock"`.

### Модули community.docker (Docker)

| Модуль | Назначение |
| :--- | :--- |
| `community.docker.docker_container` | Управление жизненным циклом контейнеров |
| `community.docker.docker_container_info` | Получение информации о контейнерах |
| `community.docker.docker_container_copy_into` | Копирование файлов в контейнер |
| `community.docker.docker_container_exec` | Выполнение команд в контейнере |
| `community.docker.docker_image` | Управление образами (build/pull/load/push/remove/tag) |
| `community.docker.docker_image_info` | Инспекция образов |
| `community.docker.docker_image_build` | Сборка через BuildKit/Buildx |
| `community.docker.docker_image_export` | Экспорт образа в tar-архив |
| `community.docker.docker_image_load` | Загрузка образа из tar-архива |
| `community.docker.docker_image_push` | Публикация в реестр |
| `community.docker.docker_image_remove` | Удаление образов |
| `community.docker.docker_image_tag` | Тегирование образов |
| `community.docker.docker_network` | Управление сетями Docker |
| `community.docker.docker_network_info` | Получение информации о сетях |
| `community.docker.docker_volume` | Управление томами |
| `community.docker.docker_volume_info` | Получение информации о томах |
| `community.docker.docker_compose_v2` | Управление Compose V2 проектами |
| `community.docker.docker_compose_v2_exec` | Выполнение команд в сервисе Compose |
| `community.docker.docker_compose_v2_pull` | Pull образов Compose проекта |
| `community.docker.docker_compose_v2_run` | Запуск одноразовых задач в Compose |
| `community.docker.docker_swarm` | Управление кластером Swarm |
| `community.docker.docker_swarm_info` | Получение информации о Swarm |
| `community.docker.docker_swarm_service` | Управление сервисами Swarm |
| `community.docker.docker_swarm_service_info` | Получение информации о сервисах Swarm |
| `community.docker.docker_stack` | Развертывание стеков Swarm |
| `community.docker.docker_stack_info` | Получение информации о стеках |
| `community.docker.docker_stack_task_info` | Получение информации о задачах стеков |
| `community.docker.docker_node` | Управление нодами Swarm |
| `community.docker.docker_node_info` | Получение информации о нодах Swarm |
| `community.docker.docker_secret` | Управление секретами Swarm |
| `community.docker.docker_config` | Управление конфигами Swarm |
| `community.docker.docker_plugin` | Управление плагинами Docker |
| `community.docker.docker_prune` | Очистка неиспользуемых объектов |
| `community.docker.docker_login` | Авторизация в реестре |
| `community.docker.docker_logout` | Выход из реестра |
| `community.docker.docker_host_info` | Получение информации о демоне Docker |
| `community.docker.current_container_facts` | Факты о контейнере, в котором выполняется модуль |

### Модули containers.podman (Podman)

| Модуль | Назначение |
| :--- | :--- |
| `containers.podman.podman_container` | Управление контейнерами Podman |
| `containers.podman.podman_container_info` | Получение информации о контейнерах |
| `containers.podman.podman_container_copy` | Копирование файлов в/из контейнера |
| `containers.podman.podman_container_exec` | Выполнение команд в контейнере |
| `containers.podman.podman_containers` | Пакетное управление контейнерами |
| `containers.podman.podman_image` | Управление образами Podman |
| `containers.podman.podman_image_info` | Получение информации об образах |
| `containers.podman.podman_network` | Управление сетями Podman |
| `containers.podman.podman_network_info` | Получение информации о сетях |
| `containers.podman.podman_volume` | Управление томами Podman |
| `containers.podman.podman_volume_info` | Получение информации о томах |
| `containers.podman.podman_pod` | Управление поды (pods) Podman |
| `containers.podman.podman_secret` | Управление секретами Podman |
| `containers.podman.podman_quadlet` | Управление Quadlet unit-файлами |
| `containers.podman.podman_generate_systemd` | Генерация systemd unit-файлов |
| `containers.podman.podman_login` | Авторизация в реестре |
| `containers.podman.podman_logout` | Выход из реестра |
| `containers.podman.podman_system_connection` | Управление системными подключениями |
| `containers.podman.podman_system_connection_info` | Получение информации о подключениях |
| `containers.podman.podman_system_info` | Получение системной информации Podman |

### Ключевые параметры

**`docker_container` / `podman_container`:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `name` | str | Имя контейнера |
| `image` | str | OCI-образ и тег (например, `nginx:1.25`) |
| `state` | str | Целевое состояние (`present`, `absent`, `started`, `stopped`, `restarted`) |
| `ports` | list | Маппинг портов (например, `["80:80", "443:443"]`) |
| `volumes` | list | Монтирования томов (например, `["nginx_data:/usr/share/nginx/html"]`) |
| `env` | dict | Переменные окружения |
| `restart_policy` | str | Политика перезапуска (`no`, `on-failure`, `always`, `unless-stopped`) |
| `command` | list | Переопределение команды запуска |
| `entrypoint` | str | Переопределение entrypoint |
| `user` | str | Пользователь для запуска процесса |
| `privileged` | bool | Привилегированный режим |
| `capabilities` | dict | Linux capabilities |
| `security_opts` | list | Параметры безопасности (SELinux, AppArmor) |
| `healthcheck` | dict | Проверка здоровья контейнера |
| `docker_host` | str | Путь к сокету или URL удаленного демона |

**`docker_image` / `podman_image`:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `name` | str | Имя образа с тегом |
| `tag` | str | Тег образа |
| `source` | str | Источник (`build`, `pull`, `load`, `local`) |
| `build` | dict | Параметры сборки (`path`, `dockerfile`, `args`, `platform`) |
| `push` | bool | Публиковать образ после сборки |
| `archive_path` | str | Путь к tar-архиву для экспорта/загрузки |

### Сравнение подходов

| Критерий | Docker CLI | Podman CLI | Ansible Docker Module | Ansible Podman Module |
| :--- | :--- | :--- | :--- | :--- |
| Идемпотентность | Нет | Нет | Да | Да |
| Управление состоянием | Нет | Нет | Да | Да |
| Интеграция с inventory | Нет | Нет | Да | Да |
| Rootless | Нет | Да | Да | Да |
| Systemd integration | Нет | Да | Да | Да |
| Batch operations | Нет | Нет | Да | Да (podman_containers) |

## Практические сценарии

### Сценарий 1: Полный цикл развертывания Nginx через Docker

```yaml
- name: "Создание Docker сети"
  community.docker.docker_network:
    name: proxy_net
    driver: bridge
    ipam:
      config:
        - subnet: "10.0.0.0/24"

- name: "Создание Docker тома"
  community.docker.docker_volume:
    name: nginx_data
    driver: local

- name: "Запуск Nginx"
  community.docker.docker_container:
    name: nginx
    image: nginx:1.25-alpine
    state: started
    restart_policy: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - nginx_data:/usr/share/nginx/html
      - /etc/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    env:
      NGINX_HOST: "example.com"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 30s
      timeout: 5s
      retries: 3
  register: nginx_container

- name: "Проверка статуса контейнера"
  ansible.builtin.assert:
    that:
      - nginx_container.container.State.Health.Status == "healthy"
      - nginx_container.container.State.Running
    fail_msg: "Nginx контейнер не запущен или не здоров"
    success_msg: "Nginx контейнер работает"
```

### Сценарий 2: Сборка и публикация образа через Docker

```yaml
- name: "Сборка Docker образа"
  community.docker.docker_image:
    name: myapp
    tag: "{{ app_version }}"
    source: build
    build:
      path: ./app
      dockerfile: Dockerfile.prod
      args:
        BUILD_DATE: "{{ lookup('pipe', 'date -u +%Y-%m-%dT%H:%M:%SZ') }}"
        VCS_REF: "{{ lookup('env', 'GITHUB_SHA') }}"
    state: present

- name: "Публикация образа в registry"
  community.docker.docker_image:
    name: registry.example.com/myapp
    tag: "{{ app_version }}"
    source: push
    push:
      registry_url: https://registry.example.com
      username: "{{ vault_registry_user }}"
      password: "{{ vault_registry_password }}"
```

### Сценарий 3: Развертывание через Podman с systemd

```yaml
- name: "Создание Podman контейнера"
  containers.podman.podman_container:
    name: myapp
    image: quay.io/myapp:latest
    state: started
    restart_policy: always
    ports:
      - "8080:8080"
    volumes:
      - /opt/myapp/data:/app/data:Z
    user: "1000:1000"
    annotation:
      com.example.description: "MyApp container"
    security_opt:
      - label=type:container_runtime_t

- name: "Генерация systemd unit"
  containers.podman.podman_generate_systemd:
    name: myapp
    dest: /etc/systemd/system/
    restart_policy: always
    container_name: myapp

- name: "Перезагрузка systemd и запуск сервиса"
  ansible.builtin.systemd:
    name: container-myapp.service
    state: started
    enabled: yes
    daemon_reload: yes
```

### Сценарий 4: Управление Compose-проектом

```yaml
- name: "Развертывание стека через Docker Compose"
  community.docker.docker_compose_v2:
    project_src: ./myproject
    files:
      - docker-compose.yml
      - docker-compose.prod.yml
    state: present
    pull: yes
    build: yes
    recreate: always
    stop_grace_period: 30s
  register: compose_result

- name: "Проверка сервисов"
  ansible.builtin.uri:
    url: "http://localhost:{{ item.port }}"
    status_code: 200
  loop:
    - { port: 80 }
    - { port: 8080 }
```

### Сценарий 5: Drift detection и верификация состояния

Для SRE-сценариев критично обнаруживать drift (отклонение фактического состояния от желаемого).

```yaml
- name: "Сбор фактического состояния контейнеров"
  community.docker.docker_container_info:
    name: "{{ item }}"
  loop:
    - web
    - api
    - worker
  register: actual_state

- name: "Верификация конфигурации"
  ansible.builtin.assert:
    that:
      - actual_state.results | map(attribute='container.State.Running') | unique | first
    fail_msg: "Обнаружен drift: не все контейнеры запущены"
    success_msg: "Состояние соответствует желаемому"
```

### Сценарий 6: Air-gapped среда (tar-цикл)

Развертывание в изолированной среде без доступа к registry.

```yaml
- name: "Сборка образа"
  community.docker.docker_image:
    name: "local/app:latest"
    build:
      path: "./src"
    source: build

- name: "Экспорт в tar"
  community.docker.docker_image:
    name: "local/app:latest"
    archive_path: "/tmp/app.tar"
    source: local

- name: "Загрузка на целевой узел"
  ansible.builtin.copy:
    src: "/tmp/app.tar"
    dest: "/tmp/app.tar"

- name: "Загрузка образа из tar"
  community.docker.docker_image:
    name: "local/app"
    tag: "latest"
    load_path: "/tmp/app.tar"
    source: load
```

### Сценарий 7: CI/CD pipeline интеграция

```yaml
- name: "Сборка и Push многоплатформенного образа"
  hosts: build_host
  vars:
    build_timestamp: "{{ lookup('pipe', 'date -u +%Y-%m-%dT%H:%M:%SZ') }}"
  tasks:
    - name: "Авторизация в registry"
      community.docker.docker_login:
        registry_url: registry.internal
        username: "{{ vault_registry_user }}"
        password: "{{ vault_registry_password }}"
      no_log: true

    - name: "Сборка образа"
      community.docker.docker_image_build:
        name: registry.internal/myapp
        tag: "{{ build_timestamp }}"
        path: "./src"
        source: buildx
        buildx:
          platform: linux/amd64,linux/arm64
          push: true
          cache_from: "type=registry,ref=registry.internal/myapp:cache"
          cache_to: "type=inline,mode=max"
        state: present

    - name: "Запуск на production"
      community.docker.docker_container:
        name: myapp
        image: registry.internal/myapp:{{ build_timestamp }}
        state: started
        restart_policy: always
        pull: yes
```

## Операции и команды

### Основные модули community.docker

| Модуль | Назначение | Пример использования |
| :--- | :--- | :--- |
| `docker_container` | Управление контейнерами | Запуск, остановка, пересоздание контейнеров |
| `docker_container_info` | Информация о контейнерах | Верификация состояния, drift detection |
| `docker_image` | Управление образами | Сборка, загрузка, отправка, tagging |
| `docker_image_build` | Сборка через Buildx | Multi-arch, кэширование |
| `docker_image_push` | Публикация в реестр | Push образов |
| `docker_image_load` | Загрузка из tar | Air-gapped развертывание |
| `docker_network` | Управление сетями | Создание bridge, overlay, macvlan |
| `docker_volume` | Управление томами | Создание и монтирование томов |
| `docker_compose_v2` | Compose V2 | Multi-container приложения |
| `docker_swarm` | Управление кластером | Инициализация Swarm |
| `docker_stack` | Развертывание стеков | Deploy стеков в Swarm |
| `docker_secret` | Секреты Swarm | Управление секретами |
| `docker_prune` | Очистка | Удаление неиспользуемых объектов |

### Основные модули containers.podman

| Модуль | Назначение | Пример использования |
| :--- | :--- | :--- |
| `podman_container` | Управление контейнерами | Запуск, остановка, пересоздание |
| `podman_container_info` | Информация о контейнерах | Верификация состояния |
| `podman_image` | Управление образами | Pull, build, tag |
| `podman_network` | Управление сетями | Создание сетей Podman |
| `podman_volume` | Управление томами | Создание томов |
| `podman_generate_systemd` | Systemd интеграция | Генерация unit-файлов |
| `podman_quadlet` | Quadlet integration | Управление Quadlet unit-файлами |
| `podman_containers` | Пакетное управление | Массовые операции с контейнерами |

### Docker CLI: основные команды (для диагностики)

```bash
# Информация о демоне
docker info
# → Storage Driver: overlay2
# → Cgroup Version: 2
# → containerd image store: active

# Сборка образа
docker build -t my-app:1.0 ./src
# → Successfully built abc123def456

# Запуск контейнера
docker run -d --name web -p 8080:80 --restart always my-app:1.0
# → abc123def456

# Просмотр логов
docker logs -f --tail=100 web

# Очистка неиспользуемых объектов
docker system prune -a --volumes
# → Total reclaimed space: 2.1GB
```

### Podman CLI: основные команды (для диагностики)

```bash
# Информация о системе
podman info

# Сборка образа
podman build -t my-app:1.0 ./src

# Запуск контейнера
podman run -d --name web -p 8080:80 my-app:1.0

# Генерация systemd unit
podman generate systemd --name myapp --files

# Очистка
podman system prune -a --volumes
```

## Устранение неисправлений

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Library docker not found` | SDK установлен в другой интерпретатор Python | Проверьте `ansible_python_interpreter` |
| `Conflict: Name already in use` | Контейнер с таким именем уже существует | Используйте `state: started` или `recreate: true` |
| `Access denied (Rootless)` | Недостаточно прав на сокет | Проверьте `XDG_RUNTIME_DIR` и права на сокет |
| `Cannot connect to the Docker daemon` | Демон не запущен или сокет недоступен | Проверьте `systemctl status docker` и права на `/var/run/docker.sock` |
| `manifest unknown` | Образ с указанным тегом не найден | Проверьте имя реестра, тег и доступность образа |
| `no space left on device` | Закончилось дисковое пространство | Очистите неиспользуемые образы: `docker system prune -a` |
| `exec format error` | Несовпадение архитектуры образа и хоста | Используйте multi-arch сборку: `--platform linux/amd64,linux/arm64` |
| `Cannot locate specified Dockerfile` | Файл `Dockerfile` не найден | Проверьте параметр `path` в модуле сборки |
| `idempotency broken after Docker 29 upgrade` | Breaking changes в формате вывода Docker CLI | Обновите `community.docker` до 5.0.2+ |
| `pool overlaps with other one` | Конфликт подсетей overlay-сети | Укажите уникальную подсеть: `--subnet=10.10.0.0/16` |
| `swarm mode already active` | Повторная инициализация Swarm | Проверьте статус: `docker info --format '{{.Swarm.LocalNodeState}}'` |
| `failed to initialize raft node` | Проблемы с сетью между менеджерами | Проверьте порты 2377, 7946, 4789 и NTP |

## Рекомендации

### Безопасность

1. **Ansible Vault:** Всегда шифруйте секреты реестра и пароли. Используйте `no_log: true` для задач с учетными данными.
2. **Rootless Mode:** Используйте режим без root-прав для сервисов с внешним трафиком.
3. **Минимальные привилегии:** Не монтируйте Docker socket в контейнеры без крайней необходимости. Используйте Docker API proxy или Portainer.
4. **Сетевая изоляция:** Разделяйте frontend и backend через overlay-сети. Не используйте сеть `host` для приложений.
5. **Ротация логов:** Настройте `log-driver: json-file` с `max-size` и `max-file` для предотвращения заполнения диска.
6. **Очистка:** Регулярно удаляйте неиспользуемые образы: `docker image prune -a --filter "until=720h"`.

### Надежность (SRE)

1. **Идемпотентность:** Каждая задача должна быть безопасна для повторного запуска. Используйте `changed_when` и `failed_when` для точного контроля.
2. **Health checks:** Всегда определяйте `healthcheck` для production контейнеров и используйте `until`/`retries` для ожидания готовности.
3. **Restart policies:** Используйте `restart_policy: unless-stopped` для критичных сервисов.
4. **Resource limits:** Всегда ограничивайте `memory`, `cpus`, `pids_limit` для предотвращения DoS хоста.
5. **Drift detection:** Периодически запускайте info-модули и сравнивайте факты с желаемым состоянием.
6. **Air-gapped readiness:** Для критичных сред проектируйте пайплайн с tar-архивами, а не внешними registry.
7. **Secrets management:** Храните registry-учетные данные в Ansible Vault, Never в plaintext vars.

### Производительность

1. **Delegate to localhost:** Сборку образов делегируйте на `build_host`, чтобы не устанавливать Buildx на все узлы.
2. **BuildKit кэширование:** Используйте `cache_from` и `cache_to` для ускорения повторных сборок.
3. **Multi-arch:** Для mixed-парка (amd64/arm64) используйте `platform` в `docker_image_build`.
4. **Parallelism:** Ограничьте параллельную сборку через `--parallel` или распределение по build-узлам.

## Дополнительная информация

- **[Docker Management Guide](../examples/docker_management.md)** — подробное руководство по автоматизации Docker: Swarm, edge cases, безопасность, эксплуатация.
- **[Docker Documentation](https://docs.docker.com/engine/reference/commandline/cli/)** — официальная документация Docker CLI.
- **[Podman Documentation](https://docs.podman.io/)** — документация Podman.
- **[Ansible Docker Collection](https://docs.ansible.com/ansible/latest/collections/community/docker/)** — документация модулей `community.docker`.
- **[Ansible Podman Collection](https://docs.ansible.com/ansible/latest/collections/containers/podman/)** — документация модулей `containers.podman`.
- **[OCI Image Specification](https://github.com/opencontainers/image-spec)** — спецификация OCI-образов.
- **[Buildah](https://buildah.io/)** — инструмент для сборки OCI-образов без демона.
