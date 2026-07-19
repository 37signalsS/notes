# Управление Docker с помощью Ansible

## Определения

**Управление Docker через Ansible** — процесс автоматизации жизненного цикла контейнеров, включающий сборку образов, их дистрибуцию и запуск на целевых хостах с использованием декларативных плейбуков.

**Идемпотентность** — ключевое свойство модулей коллекции `community.docker`, позволяющее Ansible проверять текущее состояние контейнера или образа и вносить изменения только в случае отклонения от описанной конфигурации (например, при изменении параметров портов или версии образа).

## Базовые концепции

### Архитектура развертывания

| Роль хоста | Назначение |
|---|---|
| `build-host` | Сборка Docker-образов из Dockerfile (требуется Docker Software Development Kit (SDK — комплект разработки программного обеспечения)) |
| `run-host` | Запуск контейнеров на основе готовых образов |
| `control-node` | Узел Ansible: координация, хранение артефактов |

### Жизненный цикл сборки, доставки и запуска (Build-Ship-Run)

1. **Сборка (Build)** — создание образа из Dockerfile на специализированном хосте (`build-host`).
2. **Доставка (Ship)** — сохранение образа в архив `.tar` (Tape Archive) и его передача на целевые узлы через контрольную ноду или реестр (Registry).
3. **Запуск (Run)** — загрузка образа из архива и старт контейнера на конечном хосте (`run-host`).

### Ключевые модули

Основным инструментом является коллекция `community.docker`.

| Модуль | Назначение | Параметры |
|---|---|---|
| `community.docker.docker_image` | Управление образами | `source: build` (сборка), `source: load` (загрузка), `archive_path` (экспорт в tar) |
| `community.docker.docker_container` | Управление контейнерами | `state: started/stopped/absent`, `restart_policy`, `ports`, `env` |
| `community.docker.docker_compose_v2` | Работа с Docker Compose | `project_src`, `state: present/absent` |
| `community.docker.docker_swarm` | Кластер Swarm | `state: present` (init), `state: join`, `advertise_addr` |
| `community.docker.docker_stack` | Деплой стеков | `name`, `compose_file`, `state: present` |

> **Примечание по архивации:** Параметры `archive_path` и `load_path` используются для переноса образов без Registry. `archive_path` экспортирует образ в файл на целевом хосте, а `load_path` импортирует его из файла в локальное хранилище Docker.

### Зависимости на целевых хостах

Для работы модулей требуется наличие Docker SDK for Python на целевой машине.

| Пакет | Назначение |
| :--- | :--- |
| `docker` | Основная библиотека SDK (рекомендуется версия 6.x и выше) |
| `jsondiff` | Сравнение конфигураций Swarm в формате JSON (JavaScript Object Notation) |
| `pyyaml` | Работа с YAML-файлами (стеки и компоуз) |

В современных дистрибутивах (Ubuntu 23.04+, Debian 12+) действует PEP 668. Установка через `pip` может потребовать флага `--break-system-packages`, если не используется виртуальное окружение.

Пример подготовки хоста:

```yaml
- name: Установка зависимостей Python для Docker
  ansible.builtin.pip:
    name:
      - docker
      - jsondiff
      - pyyaml
    state: present
    extra_args: --break-system-packages # Для обхода ограничений на системный Python
```

### Делегирование задач

Подробности механизма описаны в разделе **[Делегирование задач](../PlaybookStructure/advanced.md#делегирование-задач)**. `delegate_to: localhost` часто применяется для сборки образов или подготовки конфигов на контрольном узле перед их отправкой на серверы.

---

## Практические сценарии

### Сценарий: Инициализация и управление Swarm-кластером

**Инициализация первого менеджера:**

```yaml
- name: Инициализация Docker Swarm на менеджере
  community.docker.docker_swarm:
    state: present
    advertise_addr: "192.168.77.11"
```

**Добавление worker-ноды:**

Для этого требуется токен, который можно получить динамически через `hostvars` (если менеджер в том же плейбуке) или через модуль `community.docker.docker_swarm_info`.

```yaml
- name: Присоединение к Swarm как worker
  community.docker.docker_swarm:
    state: join
    advertise_addr: "192.168.77.12"
    join_token: "{{ hostvars['manager1']['swarm_worker_token'] }}"
    remote_addrs: ["192.168.77.11:2377"]
```

### Сценарий: Полный цикл сборки и развертывания (Build-Ship-Run)

Плейбук демонстрирует перенос образов без использования внешнего Docker Registry.

```yaml
---
- name: Сборка и архивация образов
  hosts: build-host
  tasks:
    - name: Создание образа из Dockerfile
      community.docker.docker_image:
        name: "my-app/web"
        tag: "1.0"
        build:
          path: "./files/dockerfiles/webapp"
        source: build

    - name: Сохранение образа в .tar архив
      community.docker.docker_image:
        name: "my-app/web:1.0"
        archive_path: "/tmp/webapp_1.0.tar"
        source: local # Берем образ из локального демона

    - name: Копирование архива на контрольный узел
      ansible.builtin.fetch:
        src: "/tmp/webapp_1.0.tar"
        dest: "./artifacts/webapp_1.0.tar"
        flat: yes

- name: Развертывание контейнеров
  hosts: run-host
  tasks:
    - name: Копирование архива на целевой хост
      ansible.builtin.copy:
        src: "./artifacts/webapp_1.0.tar"
        dest: "/tmp/webapp_1.0.tar"

    - name: Загрузка образа из архива
      community.docker.docker_image:
        name: "my-app/web"
        tag: "1.0"
        load_path: "/tmp/webapp_1.0.tar"
        source: load

    - name: Запуск контейнера
      community.docker.docker_container:
        name: "web-app"
        image: "my-app/web:1.0"
        state: started
        restart_policy: always
        ports:
          - "8080:80"
```

### Сценарий: Проверка состояния (Health Check)

**Проверка работы Docker-демона:**

```yaml
- name: Проверка активности Docker
  ansible.builtin.command: docker info
  register: docker_info
  changed_when: false
  # → вывод детальной информации о демоне (Containers, Images, Storage Driver)
```

**Проверка доступности веб-сервиса:**

```yaml
- name: Проверка эндпоинта приложения
  ansible.builtin.uri:
    url: "http://{{ ansible_host }}:8080"
  register: result
  until: result.status == 200
  retries: 5
  delay: 5
```

### Сценарий: Изменение конфигурации демона

Использование `flush_handlers` гарантирует перезапуск Docker до того, как начнутся задачи, требующие его работы.

```yaml
- name: Настройка Docker daemon
  hosts: all
  tasks:
    - name: Конфигурация /etc/docker/daemon.json
      ansible.builtin.copy:
        dest: /etc/docker/daemon.json
        content: |
          {
            "log-driver": "json-file",
            "log-opts": { "max-size": "10m", "max-file": "3" }
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

---

## Дополнительная информация

### Типичные ошибки

- **Библиотека docker не найдена:** Убедитесь, что `pip install docker` выполнен для того же интерпретатора Python, который использует Ansible (`ansible_python_interpreter`).
- **Ошибка прав доступа:** Пользователь, под которым работает Ansible, должен входить в группу `docker` или задачи должны запускаться с `become: true`.

## Смотрите также

- [Настройка Docker Swarm: Конфиги и секреты](../../Docker_swarm/swarm_secrets_configs.md)
- [Безопасность Docker-контейнеров](../../Docker/Docker_security/overview.md)
- [Реестры образов (Registry)](../../Docker/docker_registries.md)
