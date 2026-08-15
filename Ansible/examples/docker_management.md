# Ansible: автоматизация управления Docker

## Определения

**Управление Docker через Ansible** — процесс декларативной автоматизации жизненного цикла контейнеров, образов, сетей и томов на целевых хостах. Включает в себя сборку, дистрибуцию, оркестрацию (Swarm) и системную настройку демона.

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса (например, `community.docker.docker_container`), гарантирующее вызов модуля из конкретной коллекции. Является обязательным стандартом в современном Ansible для предотвращения конфликтов имен.

**Идемпотентность** — свойство модулей проверять текущее состояние объекта и вносить изменения только при отклонении от целевой конфигурации. В версиях Docker Engine v27/v28+ модули Ansible учитывают новые параметры изоляции (Rootless) и сетевые стандарты.

**Docker Context** — механизм именования профилей подключения к различным движкам Docker (локальным, удаленным через SSH/TLS). Ansible позволяет переключать контексты через специализированные модули или параметры подключения.

## Базовые концепции

### Архитектура развертывания

При промышленной автоматизации роли хостов разделяются для оптимизации ресурсов и безопасности:

| Роль хоста | Назначение |
|---|---|
| **Build-host** | Сборка образов через BuildKit/Buildx. Требует значительных мощностей и установленного Docker CLI. |
| **Run-host** | Целевой узел выполнения контейнеров или нода кластера Swarm. |
| **Control-node** | Управляющий узел Ansible, координирующий выполнение сценариев и доставку артефактов. |

### Жизненный цикл Build-Ship-Run (Состояние на 2026 г.)

1.  **Сборка (Build)** — создание образа. Стандартом является использование **BuildKit/Buildx** через модуль `docker_image_build` для multi-arch сборок и продвинутого кэширования.
2.  **Доставка (Ship)** — передача образа.
    *   **Registry-way (Рекомендуется):** Публикация в реестр (Harbor, GitLab Registry, Docker Hub) с помощью `community.docker.docker_image_push`.
    *   **Tar-way (Air-gapped):** Экспорт в `.tar` архив через `archive_path` и передача на хосты без прямого доступа к сети.
3.  **Запуск (Run)** — развертывание контейнера (`docker_container`), проекта Compose (`docker_compose_v2`) или стека Swarm (`docker_stack`).

### Зависимости на целевых хостах (PEP 668)

В современных дистрибутивах (Ubuntu 24.04+, Debian 12+) действует PEP 668, запрещающий прямую установку пакетов через `pip` в системную область Python.

| Пакет | Назначение | Требование |
| :--- | :--- | :--- |
| **`docker`** | Основная библиотека SDK (заменила `docker-py`) | v7.0+ |
| **`jsondiff`** | Сравнение конфигураций Swarm в формате JSON | Обязательно для Swarm |
| **`pyyaml`** | Работа с YAML-файлами (Compose и Stack) | Обязательно для Compose |

**Варианты установки:**

1.  **Системные пакеты (Рекомендуется):** `python3-docker`, `python3-jsondiff`, `python3-yaml`.
2.  **Pip (Workaround для PEP 668):**
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

Использование `delegate_to: localhost` или `delegate_to: build_host` критически важно для сборки образов перед их отправкой на целевые серверы. Это позволяет не устанавливать инструментарий сборки (Buildx, Git) на все узлы инфраструктуры.

---

## Практические сценарии

### Сценарий 1: Сборка через Buildx и отправка в Registry

Использование современных возможностей BuildKit для эффективной мультиплатформенной доставки.

```yaml
- name: Сборка и публикация приложения
  hosts: build_host
  tasks:
    - name: Авторизация в реестре
      community.docker.docker_login:
        registry_url: my-registry.com
        username: "{{ vault_registry_user }}"
        password: "{{ vault_registry_password }}"

    - name: Сборка и Push многоплатформенного образа
      community.docker.docker_image_build:
        name: my-registry.com/my-app
        tag: "5.0"
        path: "./src"
        source: buildx
        buildx:
          platform: linux/amd64,linux/arm64
          push: true
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

### Сценарий 5: Проверка состояния и Health Check

**Сбор информации о демоне:**
```yaml
- name: Проверка статуса Docker Engine
  ansible.builtin.command: docker info
  register: docker_info
  changed_when: false
  # → Позволяет проверить Storage Driver, Cgroup Version и режим Rootless.
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

---

## Дополнительная информация

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Library docker not found` | SDK установлен в другой интерпретатор Python. | Проверьте `ansible_python_interpreter`. |
| `Conflict: Name already in use` | Контейнер с таким именем уже существует. | Используйте `state: started` (обновит параметры) или `recreate: true`. |
| `Access denied (Rootless)` | Недостаточно прав на сокет или не установлена переменная окружения. | Убедитесь, что `XDG_RUNTIME_DIR` настроена корректно. |
| `jsondiff not found` | Отсутствует зависимость для Swarm. | Установите пакет `python3-jsondiff`. |

### Рекомендации по безопасности

1.  **Ansible Vault:** Всегда шифруйте секреты реестра и пароли в Compose-файлах.
2.  **Rootless Mode:** Используйте режим без root-прав для сервисов, работающих с внешним трафиком.
3.  **Docker Contexts:** Для управления парком серверов с одной машины используйте контексты, чтобы минимизировать количество SSH-сессий.

## Смотрите также

- **[Настройка Docker Swarm: Конфиги и секреты](../../Docker_swarm/swarm_secrets_configs.md)**
- **[Безопасность Docker: Rootless и Hardening](../../Docker/Docker_security/overview.md)**
- **[Реестры образов (Registry)](../../Docker/docker_registries.md)**
- **[Установка и настройка Docker Swarm (базовый обзор)](../../Docker_swarm/docker_swarm_overview.md)**
- **[Docker Context: управление профилями подключения](../../Docker/docker_context.md)**
