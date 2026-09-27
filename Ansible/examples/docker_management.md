# Ansible: автоматизация управления Docker

## Определения

**Управление Docker через Ansible** — процесс декларативной автоматизации жизненного цикла контейнеров, образов, сетей, томов и кластеров Swarm на целевых хостах. Включает сборку через BuildKit/Buildx, дистрибуцию через реестры или tar-архивы, развертывание и системную настройку демона.

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса (например, `community.docker.docker_container`), гарантирующее вызов модуля из конкретной коллекции. Является обязательным стандартом в современном Ansible для предотвращения конфликтов имен.

**Идемпотентность** — свойство модулей проверять текущее состояние объекта и вносить изменения только при отклонении от целевой конфигурации. Коллекция `community.docker` 5.x учитывает breaking changes Docker Engine 29.x (например, формат вывода `docker version --format json` и обработка exposed port ranges).

**Docker Context** — механизм именования профилей подключения к различным движкам Docker (локальным, удаленным через SSH/TLS). Ansible позволяет переключать контексты через параметры `docker_host` или модуль `community.docker.docker_context_info`.

**containerd Image Store** — режим хранения образов, используемый по умолчанию в Docker Engine 29.1+. Вместо внутреннего хранилища Docker (`graphdriver`) используется нативный формат containerd, обеспечивающий совместимость с Kubernetes и ускорение операций с образами.

**Rootless Mode** — режим запуска демона и контейнеров от имени обычного пользователя без `root`-прав. В 2026 году является стандартом де-факто для production-сред, снижая поверхность атаки хоста.

## Базовые концепции

### Зависимости и инструментарий

Автоматизация Docker 29.x через Ansible требует актуальных версий Python-драйверов и инструментов на управляющем и целевых хостах.

| Компонент | Требование | Назначение |
|---|---|---|
| `community.docker` | 5.4.x | Коллекция модулей для управления Docker Engine, Swarm, Compose и образами. |
| `docker` (Python SDK) | 7.2+ | Python-библиотека для взаимодействия Ansible с Docker API. Заменила устаревшую `docker-py`. |
| `jsondiff` | любая | Сравнение конфигураций Swarm (обязательно для Swarm-сценариев). |
| `pyyaml` | любая | Работа с YAML-файлами Compose и Stack. |
| `docker compose` | V2 (встроен в Docker CLI) | Управление multi-container приложениями. |

Установка коллекции на управляющем узле:

```bash
ansible-galaxy collection install community.docker
# → Installing 'community.docker' to ...
```

### Предварительные требования (Prerequisites)

#### Управляющий узел (Control Node)

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible | 2.17+ (рекомендуется >= 2.21) | `ansible --version` |
| Python | 3.10+ | `python3 --version` |
| `community.docker` | 5.4.x | `ansible-galaxy collection list community.docker` |

#### Целевые хосты (Managed Nodes)

| Компонент | Минимальная версия | Назначение |
|---|---|---|
| Docker Engine | 29.x (28.x — EOL с мая 2026) | Целевая версия демона |
| Python 3 | 3.10+ | Модули Ansible работают через Python на целевом хосте |
| `docker` SDK | 7.2+ | Python-библиотека для взаимодействия с Docker API |
| `jsondiff` | любая | Сравнение конфигураций Swarm |
| `pyyaml` | любая | Работа с YAML-файлами Compose/Stack |
| Права `sudo` | Настроен `NOPASSWD` | Выполнение задач с `become: true` |
| SSH-доступ | Настроен и протестирован | Удаленное управление через Ansible |

**Проверка зависимостей на целевом хосте (однострочник):**

```bash
# Проверка Docker
docker --version 2>/dev/null || echo "Docker NOT installed"
# → Docker version 29.8.1, build ...

# Проверка Python SDK
python3 -c "import docker; print(f'docker SDK {docker.__version__}')" 2>/dev/null || echo "docker SDK NOT installed"
# → docker SDK 7.2.0

# Проверка jsondiff (для Swarm)
python3 -c "import jsondiff; print('jsondiff OK')" 2>/dev/null || echo "jsondiff NOT installed"
# → jsondiff OK
```

#### Аппаратные ограничения

| Требование | Минимум | Рекомендуется |
|---|---|---|
| CPU | 1 ядро | 2+ ядра (сборка образов — 4+) |
| RAM | 2 ГБ (демон) | 8+ ГБ (демон + контейнеры + сборка) |
| Диск | 20 ГБ SSD | 100+ ГБ SSD (образы, логи, тома) |

### Архитектура развертывания

При промышленной автоматизации роли хостов разделяются для оптимизации ресурсов и безопасности:

| Роль хоста | Назначение |
|---|---|
| **Build-host** | Сборка образов через BuildKit/Buildx. Требует значительных мощностей, Docker CLI и плагина `docker-buildx-plugin`. |
| **Run-host** | Целевой узел выполнения контейнеров или нода кластера Swarm. |
| **Control-node** | Управляющий узел Ansible, координирующий выполнение сценариев и доставку артефактов. |

### Жизненный цикл Build-Ship-Run

1. **Сборка (Build)** — создание образа. Стандартом является использование **BuildKit/Buildx** через модуль `community.docker.docker_image_build` для multi-arch сборок и продвинутого кэширования. BuildKit включен по умолчанию в Docker 23.0+.
2. **Доставка (Ship)** — передача образа.
   - **Registry-way (Рекомендуется):** Публикация в реестр (Harbor, GitLab Registry, Docker Hub) с помощью `community.docker.docker_image_push`.
   - **Tar-way (Air-gapped):** Экспорт в `.tar` архив через `archive_path` и передача на хосты без прямого доступа к сети.
3. **Запуск (Run)** — развертывание контейнера (`docker_container`), проекта Compose (`docker_compose_v2`) или стека Swarm (`docker_stack`).

### Зависимости на целевых хостах (PEP 668)

В современных дистрибутивах (Ubuntu 24.04+, Debian 12+) действует PEP 668, запрещающий прямую установку пакетов через `pip` в системную область Python.

| Пакет | Назначение | Требование |
| :--- | :--- | :--- |
| **`docker`** | Основная библиотека SDK (заменила `docker-py`) | v7.2+ |
| **`jsondiff`** | Сравнение конфигураций Swarm в формате JSON | Обязательно для Swarm |
| **`pyyaml`** | Работа с YAML-файлами (Compose и Stack) | Обязательно для Compose |

**Варианты установки:**

1. **Системные пакеты (Рекомендуется):** `python3-docker`, `python3-jsondiff`, `python3-yaml`.
2. **Pip (Workaround для PEP 668):**

```yaml
- name: Установка зависимостей Python для Docker
  ansible.builtin.pip:
    name:
      - docker
      - jsondiff
      - pyyaml
    state: present
    extra_args: --break-system-packages
```

### Делегирование задач

Использование `delegate_to: localhost` или `delegate_to: build_host` критически важно для сборки образов перед их отправкой на целевые серверы. Это позволяет не устанавливать Buildx, BuildKit и Git на все узлы инфраструктуры.

### Особенности Docker Engine 29.x

Docker Engine 29.x вносит breaking changes, требующие обновления `community.docker` до 5.0.2+:

- Формат вывода `docker version --format json` изменен, что сломало парсинг в CLI-based модулях. Исправлено в `community.docker` 5.0.2+.
- Exposed port ranges больше не передаются демону в недокументированном формате; модуль `docker_container` явно раскрывает диапазоны в список портов.
- `docker_image` и `docker_image_export`: идемпотентность архивации зависит от бэкенда хранения образов. containerd image store (Docker 29.1+) использует ID образов, не соответствующие `manifest.json` в tar-архивах.

## Практические сценарии

### Сценарий 1: Сборка через Buildx и отправка в Registry

Использование современных возможностей BuildKit для эффективной мультиплатформенной доставки.

```yaml
- name: Сборка и публикация приложения
  hosts: build_host
  tasks:
    - name: Авторизация в реестре
      community.docker.docker_login:
        registry_url: my-registry.internal
        username: "{{ vault_registry_user }}"
        password: "{{ vault_registry_password }}"
      no_log: true

    - name: Сборка и Push многоплатформенного образа
      community.docker.docker_image_build:
        name: my-registry.internal/my-app
        tag: "5.0"
        path: "./src"
        source: buildx
        buildx:
          platform: linux/amd64,linux/arm64
          push: true
          cache_from: "type=registry,ref=my-registry.internal/my-app:cache"
          cache_to: "type=inline,mode=max"
```

**Валидация:**

```bash
# Проверка публикации в реестре
docker manifest inspect my-registry.internal/my-app:5.0 | jq '.manifests[].platform'
# → { "architecture": "amd64", "os": "linux" }
# → { "architecture": "arm64", "os": "linux" }

# Проверка кэша BuildKit
docker buildx ls --format "{{.Driver}}"
# → docker-container
```

### Сценарий 2: Инициализация и управление кластером Swarm

**Инициализация первого менеджера:**

```yaml
- name: Инициализация Swarm
  community.docker.docker_swarm:
    state: present
    advertise_addr: "192.168.1.10"
  register: swarm_facts

- name: Сохранение токена
  ansible.builtin.set_fact:
    worker_token: "{{ swarm_facts.swarm_facts.JoinTokens.Worker }}"
```

**Присоединение Worker-ноды:**

```yaml
- name: Присоединение к кластеру
  community.docker.docker_swarm:
    state: join
    advertise_addr: "{{ ansible_host }}"
    join_token: "{{ hostvars['manager1']['worker_token'] }}"
    remote_addrs: ["192.168.1.10:2377"]
```

**Валидация Swarm:**

```bash
# Проверка статуса кластера (на менеджере)
docker node ls
# → ID            HOSTNAME   STATUS    AVAILABILITY   MANAGER STATUS   ENGINE VERSION
# → abc123 *      manager1   Ready     Active         Leader           29.8.1
# → def456        worker1    Ready     Active                          29.8.1

# Проверка кворума
docker info --format '{{.Swarm.Nodes}}'
# → 2

# Проверка доступности портов
for port in 2377 7946 7946/udp 4789/udp; do
  echo "Port $port: $(ss -tlnp | grep :${port%%/*} >/dev/null && echo 'OK' || echo 'BLOCKED')"
done
```

### Сценарий 3: Цикл Build-Ship-Run для изолированных сред (Tar)

Сценарий переноса образа без использования внешнего реестра.

```yaml
---
- name: Сборка и архивация (Build & Ship)
  hosts: build_server
  tasks:
    - name: Создание образа
      community.docker.docker_image:
        name: "local/app:latest"
        build:
          path: "./files/dockerfiles/app"
        source: build

    - name: Сохранение в .tar архив
      community.docker.docker_image:
        name: "local/app:latest"
        archive_path: "/tmp/app.tar"
        source: local

    - name: Загрузка на Control-node
      ansible.builtin.fetch:
        src: "/tmp/app.tar"
        dest: "./artifacts/app.tar"
        flat: yes

- name: Развертывание (Run)
  hosts: production_nodes
  tasks:
    - name: Копирование на целевой узел
      ansible.builtin.copy:
        src: "./artifacts/app.tar"
        dest: "/tmp/app.tar"

    - name: Загрузка образа
      community.docker.docker_image:
        name: "local/app"
        tag: "latest"
        load_path: "/tmp/app.tar"
        source: load

    - name: Запуск контейнера
      community.docker.docker_container:
        name: "my-app"
        image: "local/app:latest"
        state: started
        restart_policy: always
```

**Валидация Tar-цикла:**

```bash
# Проверка на целевом хосте
docker images | grep local/app
# → local/app    latest    abc123def456    5 minutes ago    125MB

docker ps | grep my-app
# → CONTAINER ID   IMAGE              STATUS          NAMES
# → abc123def456   local/app:latest   Up 5 minutes   my-app

# Очистка временных файлов (после проверки)
rm -f /tmp/app.tar ./artifacts/app.tar
```

**Очистка после сборки:**

```yaml
    - name: Очистка временного архива на Control-node
      ansible.builtin.file:
        path: "./artifacts/app.tar"
        state: absent
      delegate_to: localhost
      run_once: true
```

### Сценарий 4: Развертывание через Docker Compose V2

```yaml
- name: Управление стеком через Compose
  community.docker.docker_compose_v2:
    project_src: /opt/my-app
    project_name: production
    files:
      - docker-compose.yml
      - docker-compose.override.yml
    state: present
    wait: yes
```

**Валидация Compose:**

```bash
# Проверка запущенных сервисов
docker compose -p production ps
# → NAME                    SERVICE         STATUS          PORTS
# → production-web-1        web             running         0.0.0.0:8080->80/tcp
# → production-db-1         db              running         5432/tcp

# Проверка логов
docker compose -p production logs --tail=5 web
```

### Сценарий 5: Проверка состояния и Health Check

**Сбор информации о демоне:**

```yaml
- name: Проверка статуса Docker Engine
  ansible.builtin.command: docker info
  register: docker_info
  changed_when: false
  # → Позволяет проверить Storage Driver, Cgroup Version, режим Rootless и containerd image store.
```

**Ожидание готовности контейнера:**

```yaml
- name: Ожидание завершения Health Check
  community.docker.docker_container_info:
    name: "web-server"
  register: result
  until: result.container.State.Health.Status == "healthy"
  retries: 10
  delay: 5
```

**Валидация Health Check:**

```bash
# Проверка статуса здоровья
docker inspect --format='{{.State.Health.Status}}' web-server
# → healthy

# История проверок здоровья
docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' web-server
```

### Сценарий 6: Изменение конфигурации демона

Применение изменений в `daemon.json` требует использования `flush_handlers`.

```yaml
- name: Настройка параметров демона
  hosts: all
  tasks:
    - name: Конфигурация /etc/docker/daemon.json
      ansible.builtin.copy:
        dest: /etc/docker/daemon.json
        content: |
          {
            "log-driver": "json-file",
            "log-opts": { "max-size": "100m", "max-file": "3" },
            "live-restore": true,
            "features": { "containerd-snapshotter": true }
          }
      notify: Restart Docker

    - name: Немедленное применение изменений
      ansible.builtin.meta: flush_handlers

  handlers:
    - name: Restart Docker
      ansible.builtin.systemd:
        name: docker
        state: restarted
```

**Валидация конфигурации демона:**

```bash
# Проверка активных настроек
docker info --format '{{.LoggingDriver}}'
# → json-file

docker info --format '{{.LiveRestoreEnabled}}'
# → true

docker info --format '{{.DockerRootDir}}'
# → /var/lib/docker

# Проверка размера логов
docker inspect --format='{{.HostConfig.LogConfig.Config}}' $(docker ps -q | head -1)
# → map[max-file:3 max-size:100m]
```

### Сценарий 7: Работа в режиме Rootless

Для управления контейнерами от имени обычного пользователя необходимо правильно указать сокет.

```yaml
- name: Запуск контейнера в Rootless режиме
  community.docker.docker_container:
    name: my-rootless-app
    image: alpine
    state: started
    docker_host: "unix:///run/user/{{ ansible_user_uid }}/docker.sock"
```

**Валидация Rootless:**

```bash
# Проверка режима запуска
docker info --format '{{.SecurityOptions}}' | grep rootless
# → name=rootless

# Проверка сокета
ls -la /run/user/$(id -u)/docker.sock
# → srw-rw---- 1 user user 0 Aug 26 10:00 /run/user/1000/docker.sock
```

**Edge Case — Rootless + sysctl:**

В Rootless-режиме некоторые sysctl-параметры недоступны. Если контейнер требует `net.core.somaxconn`, необходимо настроить это на уровне хоста перед запуском:

```yaml
- name: Настройка sysctl для Rootless
  ansible.posix.sysctl:
    name: net.core.somaxconn
    value: "1024"
    state: present
    reload: yes
  become: true
  when: ansible_facts.virtualization_type != 'docker'
```

## Запуск и структура проекта

### Пример инвентаря (inventory)

**Файл `inventory.ini`:**

```ini
[build_host]
build-server ansible_host=10.0.5.10 ansible_user=deploy

[run_hosts]
web1 ansible_host=10.0.5.20 ansible_user=deploy
web2 ansible_host=10.0.5.21 ansible_user=deploy
db1  ansible_host=10.0.5.30 ansible_user=deploy

[swarm_managers]
manager1 ansible_host=10.0.5.100 ansible_user=deploy

[swarm_workers]
worker1 ansible_host=10.0.5.101 ansible_user=deploy
worker2 ansible_host=10.0.5.102 ansible_user=deploy

[all:vars]
ansible_become=true
ansible_become_method=sudo
```

### Команды запуска

```bash
# Полный запуск (с запросом пароля Vault)
ansible-playbook -i inventory.ini docker_management.yml --ask-vault-pass

# Только сборка образов
ansible-playbook -i inventory.ini docker_management.yml --limit "build_host" --tags "build"

# Только развертывание контейнеров
ansible-playbook -i inventory.ini docker_management.yml --limit "run_hosts" --tags "deploy"

# Проверка без выполнения (dry-run)
ansible-playbook -i inventory.ini docker_management.yml --check --diff

# Ограничение по конкретному хосту
ansible-playbook -i inventory.ini docker_management.yml --limit "web1"
```

### Чек-лист валидации после развертывания

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Docker запущен | `systemctl status docker` | `active (running)` |
| Docker SDK установлен | `python3 -c "import docker; print(docker.__version__)"` | `7.2.x` |
| containerd image store | `docker info --format '{{.DockerRootDir}}'` | `/var/lib/docker` (активен) |
| Образ собран | `docker images \| grep my-app` | Образ присутствует |
| Контейнер запущен | `docker ps \| grep my-app` | `Up ... minutes` |
| Compose-стек активен | `docker compose -p <name> ps` | Все сервисы `running` |
| Swarm инициализирован | `docker node ls` | Leader определен |
| Health check | `docker inspect --format='{{.State.Health.Status}}' <container>` | `healthy` |
| Логи ротируются | `docker inspect --format='{{.HostConfig.LogConfig}}' <container>` | `json-file` с `max-size` |
| Rootless (если применимо) | `docker info --format '{{.SecurityOptions}}'` | `name=rootless` |

## Операции и команды

### Основные модули community.docker

| Модуль | Назначение | Пример использования |
|---|---|---|
| `docker_container` | Управление контейнерами | Запуск, остановка, пересоздание контейнеров |
| `docker_image` | Управление образами | Сборка, загрузка, отправка, tagging |
| `docker_image_build` | Сборка через Buildx | Multi-arch, кэширование, секреты |
| `docker_image_push` | Публикация в реестр | Push образов с дайджестами |
| `docker_network` | Управление сетями | Создание bridge, overlay, macvlan сетей |
| `docker_volume` | Управление томами | Создание и монтирование томов |
| `docker_swarm` | Управление кластером | Инициализация и присоединение узлов |
| `docker_stack` | Развертывание стеков | Deploy/remove стеков в Swarm |
| `docker_compose_v2` | Управление Compose V2 | Multi-container приложения на single host |
| `docker_secret` | Управление секретами Swarm | Создание и доставка секретов |
| `docker_config` | Управление конфигами Swarm | Нечувствительные конфигурации |
| `docker_node` | Управление нодами Swarm | Промоут, демоут, обновление нод |
| `docker_prune` | Очистка объектов | Удаление неиспользуемых образов/контейнеров |
| `docker_login` | Авторизация в реестре | docker login с учетными данными |

### Команды запуска плейбуков

```bash
# Полный запуск
ansible-playbook -i inventory.ini docker_management.yml --ask-vault-pass

# Сборка образов
ansible-playbook -i inventory.ini docker_management.yml --limit "build_host" --tags "build"

# Развертывание
ansible-playbook -i inventory.ini docker_management.yml --limit "run_hosts" --tags "deploy"

# Dry-run
ansible-playbook -i inventory.ini docker_management.yml --check --diff

# Конкретный хост
ansible-playbook -i inventory.ini docker_management.yml --limit "web1"
```

### Docker CLI: основные команды

```bash
# Информация о демоне
docker info
# → Storage Driver: overlay2
# → Cgroup Version: 2
# → containerd image store: active

# Сборка образа
docker build -t my-app:1.0 ./src
# → Successfully built abc123def456
# → Successfully tagged my-app:1.0

# Публикация в реестр
docker push my-registry.internal/my-app:1.0
# → The push refers to repository [my-registry.internal/my-app]

# Запуск контейнера
docker run -d --name web -p 8080:80 --restart always my-app:1.0
# → abc123def456

# Просмотр логов
docker logs -f --tail=100 web
# → 2026-09-22 18:00:00 [INFO] Server started on port 80

# Очистка неиспользуемых объектов
docker system prune -a --volumes
# → Total reclaimed space: 2.1GB
```

## Устранение неисправностей

| Ошибка | Причина | Решение |
|---|---|---|
| `Library docker not found` | SDK установлен в другой интерпретатор Python. | Проверьте `ansible_python_interpreter`. |
| `Conflict: Name already in use` | Контейнер с таким именем уже существует. | Используйте `state: started` (обновит параметры) или `recreate: true`. |
| `Access denied (Rootless)` | Недостаточно прав на сокет. | Убедитесь, что `XDG_RUNTIME_DIR` настроена корректно. |
| `jsondiff not found` | Отсутствует зависимость для Swarm. | Установите пакет `python3-jsondiff`. |
| `Cannot connect to the Docker daemon` | Демон не запущен или сокет недоступен. | Проверьте `systemctl status docker` и права на `/var/run/docker.sock`. |
| `error during connect: Post http://%2F%2F.%2Fpipe%2Fdocker_engine` | Windows: Docker Desktop не запущен. | Запустите Docker Desktop и проверьте настройки Containers > Resources. |
| `manifest unknown` | Образ с указанным тегом не найден. | Проверьте имя реестра, тег и доступность образа. |
| `pool overlaps with other one` | Конфликт подсетей overlay-сети. | Укажите уникальную подсеть: `--subnet=10.10.0.0/16`. |
| `swarm mode already active` | Повторная инициализация Swarm. | Проверьте текущий статус: `docker info --format '{{.Swarm.LocalNodeState}}'`. |
| `failed to initialize raft node` | Проблемы с сетью между менеджерами. | Проверьте доступность портов 2377, 7946, 4789 и синхронизацию времени (NTP). |
| `no space left on device` | Закончилось дисковое пространство. | Очистите неиспользуемые образы: `docker system prune -a`. |
| `exec format error` | Несовпадение архитектуры образа и хоста. | Используйте multi-arch сборку: `--platform linux/amd64,linux/arm64`. |
| `Cannot locate specified Dockerfile` | Файл `Dockerfile` не найден или указан неверный путь. | Проверьте параметр `path` в модуле `docker_image_build`. |
| `idempotency broken after Docker 29 upgrade` | Breaking changes в формате вывода Docker CLI. | Обновите `community.docker` до 5.0.2+. |

### Краевые случаи (Edge Cases)

**1. Параллельная сборка образов:**
При одновременной сборке нескольких образов на одном build-хосте BuildKit может исчерпать оперативную память. Ограничьте параллелизм через `--parallel` или последовательно распределяйте сборки по узлам.

**2. Длинные имена контейнеров:**
Docker ограничивает имя контейнера 128 символами. При использовании динамических имен (составных из переменных) добавляйте валидацию:

```yaml
- name: Проверка длины имени
  ansible.builtin.assert:
    that: container_name | length <= 128
    fail_msg: "Имя контейнера '{{ container_name }}' превышает 128 символов"
```

**3. Docker Compose и профили:**
При использовании профилей Compose V2 модуль `docker_compose_v2` требует явного указания активных профилей:

```yaml
- name: Запуск с профилями
  community.docker.docker_compose_v2:
    project_src: /opt/my-app
    profiles:
      - monitoring
      - logging
    state: present
```

**4. Мультиплатформенная сборка без QEMU:**
Для сборки под архитектуру, отличную от хостовой, необходим QEMU:

```yaml
- name: Регистрация QEMU для multi-arch
  community.docker.docker_container:
    name: qemu-register
    image: tonistiigi/binfmt:latest
    privileged: yes
    command: "--install all"
    state: started
```

**5. Конфликт имен при recreation:**
При использовании `recreate: yes` происходит кратковременное окно, когда старый контейнер удален, а новый еще не создан. Для сервисов с `restart_policy: always` это может привести к потере трафика. Используйте `recreate: always` с `update_order: start-first` для zero-downtime.

**6. Ограничение ресурсов контейнера:**
Без явного указания лимитов контейнер может исчерпать ресурсы хоста:

```yaml
- name: Запуск с лимитами ресурсов
  community.docker.docker_container:
    name: my-app
    image: my-app:latest
    state: started
    memory: "512m"
    cpus: "0.5"
    pids_limit: 100
```

**7. Сетевые конфликты при масштабировании:**
При масштабировании Compose-проекта (`--scale web=3`) модуль `docker_compose_v2` может завершиться с ошибкой, если порты уже заняты. Убедитесь, что `ports` не указаны в YAML или используйте `host_port_range`.

**8. Обновление Docker Engine на production-хостах:**
При обновлении Docker Engine (`docker-ce`) через Ansible необходимо останавливать контейнеры или использовать `live-restore: true` в `daemon.json` для непрерывной работы.

**9. Cgroups v2 и лимиты ресурсов:**
На современных дистрибутивах (Ubuntu 22.04+, RHEL 9+) по умолчанию используется cgroups v2. Docker 29.x корректно работает с unified hierarchy, но параметры `--cpus` и `--memory` интерпретируются иначе, чем в cgroups v1. При миграции с v1 на v2 проверьте лимиты через `systemd-cgls` и `docker stats`.

## Рекомендации по безопасности

1.  **Ansible Vault:** Всегда шифруйте секреты реестра и пароли в Compose-файлах. Используйте `no_log: true` для задач, передающих пароли.
2.  **Rootless Mode:** Используйте режим без root-прав для сервисов, работающих с внешним трафиком. В 2026 году это стандарт де-факто для production.
3.  **Docker Content Trust (DCT):** Включите подпись образов через Cosign или Docker Content Trust для защиты от подмены. Проверка подписи: `export DOCKER_CONTENT_TRUST=1`.
4.  **Docker Contexts:** Для управления парком серверов с одной машины используйте контексты, чтобы минимизировать количество SSH-сессий.
5.  **Минимальные привилегии:** Не монтируйте Docker socket в контейнеры без крайней необходимости. Используйте сторонние API (Portainer, Docker API proxy) вместо прямого доступа к сокету.
6.  **Сетевая изоляция:** Разделяйте frontend и backend контейнеры через overlay-сети. Не используйте сеть `host` для приложений.
7.  **Ротация логов:** Настройте `log-driver: json-file` с `max-size` и `max-file` для предотвращения заполнения диска.
8.  **Image Pruning:** Регулярно очищайте неиспользуемые образы и слои: `docker image prune -a --filter "until=720h"` (старше 30 дней).
9.  **SBOM и сканирование:** Интегрируйте генерацию SBOM и сканирование уязвимостей (Trivy, Grype) в пайплайн сборки образов.

## Дополнительная информация

### Связанные документы

- **[Настройка Docker Swarm: Конфиги и секреты](../../Docker_swarm/swarm_secrets_configs.md)** — механизмы секретов и конфигураций в Swarm.
- **[Безопасность Docker: Rootless и Hardening](../../Docker/Docker_security/overview.md)** — hardening демона, контейнеров и хоста.
- **[Реестры образов (Registry)](../../Docker/docker_registries.md)** — хранение, промоушн и безопасность реестров.
- **[Docker Buildx](../../Docker/Dockerfile/docker_buildx.md)** — мультиплатформенная сборка и кэширование.
- **[Тома и персистентное хранилище](../../Docker/Docker_fs/docker_volumes.md)** — управление томами, bind mounts и tmpfs.

## Смотрите также

- **[Настройка Docker Swarm: Конфиги и секреты](../../Docker_swarm/swarm_secrets_configs.md)**
- **[Безопасность Docker: Rootless и Hardening](../../Docker/Docker_security/overview.md)**
- **[Реестры образов (Registry)](../../Docker/docker_registries.md)**
