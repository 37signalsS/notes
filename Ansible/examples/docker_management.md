# Ansible: Управление Docker

## Определения

**Управление Docker через Ansible** — процесс автоматизации жизненного цикла контейнеров, включающий сборку образов, их дистрибуцию, управление сетями, томами и оркестрацию (Swarm) на целевых хостах с использованием декларативных сценариев.

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса (например, `community.docker.docker_container`), которое гарантирует вызов модуля из конкретной коллекции и является обязательным стандартом в современном Ansible.

**Идемпотентность** — свойство модулей проверять текущее состояние объекта и вносить изменения только при отклонении от целевой конфигурации. В версиях Docker Engine v27/v28+ модули Ansible учитывают новые параметры изоляции (Rootless) и сетевые стандарты (Secure Bridge).

## Базовые концепции

### Архитектура развертывания

При промышленной автоматизации роли хостов разделяются для оптимизации ресурсов и безопасности:

| Роль хоста | Назначение |
|---|---|
| **Build-host** | Сборка образов через Buildx. Требует значительных вычислительных мощностей и установленного Docker CLI. |
| **Run-host** | Целевой узел, на котором запускаются контейнеры или сервисы Swarm. |
| **Control-node** | Узел управления Ansible, координирующий передачу артефактов и конфигураций. |

### Жизненный цикл Build-Ship-Run (Состояние на 2026 г.)

1.  **Сборка (Build)** — создание образа. В 2026 году стандартом является использование **BuildKit/Buildx** через модуль `docker_image_build` для multi-arch сборок и продвинутого кэширования.
2.  **Доставка (Ship)** — передача образа.
    *   *Registry-way (Рекомендуется):* Публикация в реестр (Docker Hub, GitLab Registry, Harbor) с помощью `community.docker.docker_image_push`.
    *   *Tar-way (Air-gapped):* Экспорт в `.tar` архив через `archive_path` и передача на хосты без прямого доступа к сети.
3.  **Запуск (Run)** — развертывание контейнера (`docker_container`), проекта Compose (`docker_compose_v2`) или стека Swarm (`docker_stack`).

### Зависимости на целевых хостах (PEP 668)

С 2024 года в дистрибутивах (Ubuntu 24.04+, Debian 12+) действует PEP 668, запрещающий прямую установку пакетов через `pip` в системную область Python без специальных флагов.

| Пакет | Назначение | Требование |
| :--- | :--- | :--- |
| **`docker`** | Основная библиотека SDK (заменила `docker-py`) | v7.0+ |
| **`jsondiff`** | Сравнение конфигураций Swarm в формате JSON | Обязательно для Swarm |
| **`pyyaml`** | Работа с YAML-файлами (Compose и Stack) | Обязательно для Compose |

**Практическая установка (Workaround для PEP 668):**

```yaml
- name: Установка зависимостей Python для Docker
  ansible.builtin.pip:
    name:
      - docker
      - jsondiff
      - pyyaml
    state: present
    extra_args: --break-system-packages # Для обхода ограничений на системный Python (PEP 668)
```
*Примечание: В производственных средах предпочтительнее использовать системные пакеты `python3-docker`, `python3-jsondiff`, `python3-yaml` или изолированные виртуальные окружения.*

### Делегирование задач

Подробности механизма описаны в разделе **[Делегирование задач](../PlaybookStructure/advanced.md#делегирование-задач)**. `delegate_to: localhost` критически важен для сборки образов на Control-node или выделенных билдерах перед их отправкой на целевые серверы.

---

## Практические сценарии

### Сценарий 1: Сборка через Buildx и отправка в Registry

Использование современных возможностей BuildKit для эффективной доставки.

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
        tag: "4.0"
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

Сценарий переноса образа без использования Docker Registry.

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

### Сценарий 4: Проверка состояния и Health Check

**Сбор информации о демоне:**
```yaml
- name: Проверка статуса Docker Engine
  ansible.builtin.command: docker info
  register: docker_info
  changed_when: false
  # → Выводит детали: Storage Driver, Cgroup Version, Rootless status.
```

**Ожидание Health Check контейнера:**
```yaml
- name: Ожидание готовности сервиса
  community.docker.docker_container_info:
    name: "web-server"
  register: result
  until: result.container.State.Health.Status == "healthy"
  retries: 10
  delay: 5
```

### Сценарий 5: Изменение конфигурации демона

Применение `daemon.json` требует `flush_handlers` для корректной последовательности.

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
            "live-restore": true
          }
      notify: Restart Docker

    - name: Применение изменений немедленно
      ansible.builtin.meta: flush_handlers

  handlers:
    - name: Restart Docker
      ansible.builtin.systemd:
        name: docker
        state: restarted
```

---

## Дополнительная информация

### Типичные ошибки

*   **`Library docker not found`**: Проблема интерпретатора. SDK должен быть установлен именно в тот Python, который указан в `ansible_python_interpreter`.
*   **`Conflict: Name already in use`**: Имя контейнера занято. Используйте `state: started` (обновит параметры) или `recreate: true`.
*   **Ошибки в Rootless режиме**: Убедитесь, что `docker_host` указывает на сокет пользователя в `/run/user/`.

## Смотрите также

- [Настройка Docker Swarm: Конфиги и секреты](../../Docker_swarm/swarm_secrets_configs.md)
- [Безопасность Docker: Rootless и Hardening](../../Docker/Docker_security/overview.md)
- [Реестры образов (Registry)](../../Docker/docker_registries.md)
- [Установка и настройка Docker Swarm (SSoT)](../../Docker_swarm/docker_swarm_overview.md)
