# Сборка OCI-образов с помощью Ansible и Buildah

## Определения

**Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, полностью соответствующих стандартам **OCI (Open Container Initiative)**. Он спроектирован для работы без фонового демона (**daemonless**) и поддерживает полноценный безрутовый режим (**rootless**).

**Плагин соединения buildah (`containers.podman.buildah`)** — современный и официально поддерживаемый способ использования Ansible для сборки образов. Он позволяет Ansible "монтировать" рабочий контейнер Buildah и выполнять в нем задачи напрямую через драйвер файловой системы, обходясь без SSH-сервера или установленного Python внутри образа.

**Ansible-builder** — специализированный инструмент для сборки **[Execution Environments (EE)](./ansible-execution-environments.md)**.

**Ansible-bender** — устаревшая утилита-мост (legacy). Проект признан архивным и не рекомендуется для новых разработок. Для сборки образов на базе плейбуков следует использовать плагин соединения `buildah`.

**Containerfile** — файл описания сборки, синтаксически совместимый с `Dockerfile`. Buildah автоматически ищет `Containerfile`, а при его отсутствии — `Dockerfile`. Поддерживает heredoc-синтаксис и файл исключений `.containerignore`.

**Build context (Контекст сборки)** — каталог, из которого инструкции `COPY`/`ADD` получают исходные файлы; исключаемые файлы задаются в `.dockerignore`/`.containerignore`.

**Working Container (Рабочий контейнер)** — временная сущность в локальном хранилище, представляющая собой распакованную файловую систему базового образа с записываемым слоем. Buildah манипулирует этим слоем и позволяет "закоммитить" его в итоговый образ в любой момент.

## Основные концепции

### Предварительные требования

Для автоматизации сборки образов через Ansible + Buildah необходимы:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | Ядро Ansible (рекомендуется 2.17+) |
| **Python** | 3.8+ | Совместимость с ansible-core |
| **Buildah** | 1.35+ | Сборщик образов (рекомендуется 1.45+) |
| **containers.podman** | latest | Коллекция модулей Ansible для Podman/Buildah |
| **containers.common** | latest | Общие зависимости коллекции containers |
| **Podman** (опционально) | 4.0+ | Управление контейнерами (сборка через `podman_image`) |
| **overlay-utils** | latest | Драйвер `overlay` для rootfs (обычно предустановлен) |

**Установка Buildah:**
```bash
# Fedora / RHEL / CentOS
sudo dnf install -y buildah

# Ubuntu / Debian
sudo apt update && sudo apt install -y buildah

# macOS (через Homebrew)
brew install buildah
```

**Установка коллекций Ansible:**
```bash
# Основные коллекции
ansible-galaxy collection install containers.podman containers.common

# Или через requirements.yml
cat > requirements.yml << 'EOF'
collections:
  - name: containers.podman
  - name: containers.common
EOF

ansible-galaxy collection install -r requirements.yml
```

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.17.x]

buildah --version
# → buildah version 1.45.0 (image-spec 1.1.0, runtime-spec 1.2.0)

ansible-galaxy collection list | grep containers
# → containers.podman    1.x.x
# → containers.common    1.x.x
```

### Преимущества Ansible + Buildah перед Dockerfile

Использование Ansible в связке с Buildah предоставляет критические преимущества перед классическими `Dockerfile`:

*   **Идемпотентность** — гарантия того, что повторный запуск сборки не внесет изменений в слои, если целевое состояние конфигурации уже достигнуто. В отличие от `RUN` в Dockerfile (который всегда выполняется), Ansible-задачи проверяют состояние перед изменением.
*   **Переиспользование кода** — возможность применять одни и те же проверенные роли Ansible (например, по харденингу ОС или настройке мониторинга) как для инфраструктуры (ВМ, Bare Metal), так и для сборки неизменяемых (immutable) контейнеров.
*   **Безопасность секретов** — использование **Ansible Vault** позволяет передавать пароли, ключи и сертификаты в процессе сборки без их сохранения в метаданных или слоях итогового образа. Никогда не используйте `ENV` или `ARG` для передачи паролей — они остаются в метаданных образа.
*   **Сложная логика сборки** — использование циклов, условий, шаблонов Jinja2 и динамического получения данных из внешних API (например, NetBox или Vault) на этапе генерации образа. В Dockerfile такая логика реализуется только через shell-скрипты.
*   **Управление слоями** — Buildah позволяет создавать образы с минимальным количеством слоев (один слой на весь плейбук), что повышает производительность при скачивании и уменьшает размер образа.
*   **Монтирование ФС** — `buildah mount` позволяет модифицировать файловую систему образа как обычный каталог на хосте, используя инструменты хоста (установка пакетов, копирование файлов) без необходимости иметь пакетный менеджер внутри образа.

### Rootless-режим

При запуске без прав root необходимо учитывать особенности работы с user namespaces:

*   **`buildah unshare`** — команда, создающая новый User Namespace, в котором текущий пользователь получает права root внутри этого пространства имен. Это необходимо для корректной работы драйверов файловой системы (например, `overlay`).
*   **Когда требуется `buildah unshare`:** При использовании `buildah mount`, `buildah config`, и любых операций, требующих привилегий root в User Namespace (монтирование, изменение прав доступа, установка пакетов через `dnf`/`apt`).
*   **Когда `buildah unshare` не нужен:** При простых командах `buildah from`, `buildah run` (с выполняемой командой), `buildah commit`, `buildah rm` — эти операции работают в rootless-режиме без дополнительной обертки.
*   **Ограничения rootless:** Не поддерживаются привилегированные порты (<1024), некоторые драйверы файловой системы (privileged overlay), и😴ерархические cgroups (в старых ядрах).

**Команда запуска:**
```bash
buildah unshare ansible-playbook build_image.yml
```

### Плагины подключения

Для работы Ansible с Buildah используются специализированные плагины соединения:

*   **`containers.podman.buildah`** — основной плагин. Позволяет Ansible "подключиться" к рабочему контейнеру Buildah через драйвер файловой системы (обходясь без SSH или Python внутри образа). Используйте для максимального контроля и идемпотентности.
*   **`containers.podman.podman`** — плагин для Podman. Работает через SSH или podman API. Используйте, если Podman уже настроен как основной runtime.
*   **`ansible.builtin.command` / `ansible.builtin.shell`** — прямое выполнение команд `buildah` на хосте. Простейший метод, но не дает идемпотентности на уровне Ansible.

### Жизненный цикл сборки через Buildah

```
from → run/copy/config → mount/unmount → commit → rm
  │         │                  │            │       │
  │         │                  │            │       └─ Очистка рабочего контейнера
  │         │                  │            └─ Фиксация в OCI-образ
  │         │                  └─ Монтирование ФС для редактирования на хосте
  │         └─ Модификация ФС (установка, копирование, настройка)
  └─ Создание рабочего контейнера из базового образа
```

**Важно:** рабочий контейнер не предназначен для запуска долгоживущих процессов — `buildah run` выполняет команду и завершается, изменения остаются в записываемом слое.

### Параметры buildah config

Модуль `buildah config` устанавливает метаданные образа. Вот основные параметры:

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--author` | Автор образа | `--author "DevOps Team"` |
| `--entrypoint` | Точка входа (JSON-массив) | `--entrypoint '["nginx", "-g", "daemon off;"]'` |
| `--cmd` | Команда по умолчанию | `--cmd '["/app/start.sh"]'` |
| `--port` | Раскрываемый порт | `--port 8080` |
| `--env` | Переменная окружения | `--env APP_ENV=production` |
| `--label` | Метка OCI | `--label version=1.5.0` |
| `--volume` | Точка монтирования | `--volume /data` |
| `--user` | Пользователь UID:GID | `--user 1000:1000` |
| `--workingdir` | Рабочая директория | `--workingdir /app` |
| `--hostname` | Имя хоста контейнера | `--hostname web-server` |
| `--stop-signal` | Сигнал остановки | `--stop-signal SIGTERM` |
| `--healthcheck` | Проверка состояния | `--healthcheck "curl -f http://localhost/" --healthcheck-interval 30s` |

## Практические сценарии

### 1. Использование плагина соединения Buildah

Это наиболее гибкий и мощный метод. Ansible подключается к рабочему контейнеру Buildah так же, как к удаленному хосту по SSH, но использует для этого механизмы `buildah mount`.

#### Работа в Rootless-режиме
При запуске без прав root необходимо использовать команду `buildah unshare`. Она создает новый User Namespace, в котором текущий пользователь получает права root внутри этого пространства имен, что необходимо для корректной работы драйверов файловой системы (например, `overlay`).

**Команда запуска:**
```bash
buildah unshare ansible-playbook build_image.yml
```

**Плейбук (`build_image.yml`):**
```yaml
---
- name: Подготовка рабочего контейнера
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Создать рабочий контейнер из базового образа
      ansible.builtin.command: buildah from alpine:3.20
      register: build_container
      changed_when: false

    - name: Добавить контейнер во временный инвентарь
      ansible.builtin.add_host:
        name: "oci_target"
        ansible_connection: containers.podman.buildah
        ansible_buildah_container: "{{ build_container.stdout }}"

- name: Настройка образа
  hosts: oci_target
  tasks:
    - name: Установка необходимых пакетов
      ansible.builtin.apk:
        name: 
          - nginx
          - curl
        state: present

    - name: Копирование конфигурации (использование Vault для секретов)
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        owner: nginx
        group: nginx
        mode: '0644'

- name: Фиксация и очистка
  hosts: localhost
  tasks:
    - name: Установка метаданных образа
      ansible.builtin.command: >
        buildah config 
        --author "DevOps Team" 
        --entrypoint '["nginx", "-g", "daemon off;"]'
        {{ hostvars['oci_target']['ansible_buildah_container'] }}
      changed_when: false

    - name: Сохранение изменений в новый OCI-образ
      ansible.builtin.command: >
        buildah commit {{ hostvars['oci_target']['ansible_buildah_container'] }} my-nginx:v1
      
    - name: Удаление временного рабочего контейнера
      ansible.builtin.command: >
        buildah rm {{ hostvars['oci_target']['ansible_buildah_container'] }}
      changed_when: false
```

#### Установка метаданных образа (Labels, Ports, Env)

Полноценная настройка образа перед фиксацией:

```yaml
- name: Установка полного набора метаданных
  hosts: localhost
  tasks:
    - name: Установка author, labels, ports, env, entrypoint
      ansible.builtin.command: >
        buildah config
        --author "DevOps Team"
        --label "version={{ app_version }}"
        --label "build-date={{ ansible_date_time.iso8601_basic_short }}"
        --label "maintainer=devops@example.com"
        --port 8080
        --env APP_ENV=production
        --env LOG_LEVEL=info
        --entrypoint '["/app/server"]'
        --cmd '["--config", "/etc/app/config.yml"]'
        --user 1000:1000
        --workingdir /app
        --stop-signal SIGTERM
        --healthcheck "curl -f http://localhost:8080/health || exit 1"
        --healthcheck-interval 30s
        --healthcheck-timeout 5s
        --healthcheck-retries 3
        {{ container_id }}
      changed_when: false
      vars:
        app_version: "1.5.0"
```

### 2. Многоэтапная сборка (Multi-stage) средствами Ansible

В отличие от `Dockerfile`, где перенос файлов между этапами ограничен инструкцией `COPY --from`, Ansible позволяет копировать данные между любыми контейнерами, смонтированными в текущей сессии.

```yaml
- name: Многоэтапная сборка артефакта
  hosts: localhost
  tasks:
    - name: Создать сборочный контейнер (Builder)
      ansible.builtin.command: buildah from golang:1.22-alpine
      register: builder_raw
      
    - name: Создать финальный контейнер (Runtime)
      ansible.builtin.command: buildah from alpine:latest
      register: runtime_raw

    - name: Монтирование контейнеров
      ansible.builtin.command: "buildah mount {{ item }}"
      loop:
        - "{{ builder_raw.stdout }}"
        - "{{ runtime_raw.stdout }}"
      register: mounts

    - name: Сборка и копирование бинарника
      vars:
        builder_path: "{{ mounts.results[0].stdout }}"
        runtime_path: "{{ mounts.results[1].stdout }}"
      ansible.builtin.shell: |
        # Сборка внутри builder
        go build -o {{ builder_path }}/app/server main.go
        # Копирование в runtime средствами хоста
        cp {{ builder_path }}/app/server {{ runtime_path }}/usr/bin/server

    - name: Установка метаданных runtime-контейнера
      ansible.builtin.command: >
        buildah config
        --entrypoint '["/usr/bin/server"]'
        --port 8080
        --user 1000:1000
        {{ runtime_raw.stdout }}
      changed_when: false

    - name: Финальный коммит
      ansible.builtin.command: >
        buildah commit --rm {{ runtime_raw.stdout }} my-app-prod:latest
```

### 3. Сборка из Containerfile через podman_image

Если проект уже содержит готовые `Dockerfile` или `Containerfile`, используйте модуль `podman_image` из коллекции `containers.podman`. Этот метод проще, но не дает доступа к идемпотентности на уровне отдельных задач Ansible.

```yaml
- name: Сборка образа из Containerfile
  containers.podman.podman_image:
    name: my-application
    path: ./src/
    dockerfile: Containerfile
    build_args:
      APP_VERSION: "1.5.0"
    state: build
```

**Сборка с дополнительными параметрами:**
```yaml
- name: Сборка образа с тегами и build-args
  containers.podman.podman_image:
    name: "{{ registry }}/{{ app_name }}"
    tag: "{{ app_version }}"
    path: "{{ context_dir }}"
    dockerfile: "{{ dockerfile_path | default('Containerfile') }}"
    build_args:
      PYTHON_VERSION: "3.12"
      APP_ENV: "{{ target_env }}"
    build_cache: true
    push: "{{ push_after_build | default(false) }}"
    push_args: "--tls-verify={{ tls_verify | default(true) }}"
    state: build
  vars:
    registry: "registry.example.com/team"
    app_name: "my-app"
    app_version: "1.5.0"
    target_env: "production"
```

### 4. Создание Execution Environments (EE)

Для специализированной сборки сред выполнения Ansible рекомендуется использовать утилиту **ansible-builder**. Она автоматизирует создание образов с учетом зависимостей коллекций, Python и системных пакетов.

Подробное руководство: **[Ansible Execution Environments — глубокое погружение](./ansible-execution-environments.md)**.

### 5. Публикация образов в реестр

После сборки образа необходимо опубликовать его в container registry для использования в продакшене.

```yaml
---
- name: Сборка и публикация образа
  hosts: localhost
  gather_facts: false
  vars:
    registry: "registry.example.com"
    repo: "team/my-app"
    tag: "1.5.0"
    container_id: ""

  tasks:
    - name: Создание рабочего контейнера
      ansible.builtin.command: buildah from alpine:3.20
      register: container
      changed_when: false

    - name: Сохранение ID контейнера
      ansible.builtin.set_fact:
        container_id: "{{ container.stdout }}"

    - name: Установка пакетов
      ansible.builtin.command: "buildah run {{ container_id }} -- apk add --no-cache python3"
      changed_when: true

    - name: Копирование приложения
      ansible.builtin.command: "buildah copy {{ container_id }} ./app /app"
      changed_when: true

    - name: Настройка метаданных
      ansible.builtin.command: >
        buildah config
        --author "DevOps Team"
        --label "version={{ tag }}"
        --label "registry={{ registry }}"
        --entrypoint '["python3", "/app/main.py"]'
        --port 8080
        {{ container_id }}
      changed_when: false

    - name: Фиксация образа
      ansible.builtin.command: >
        buildah commit {{ container_id }} {{ registry }}/{{ repo }}:{{ tag }}
      register: commit_result

    - name: Логин в реестр
      ansible.builtin.shell: |
        echo "{{ registry_password }}" | buildah login {{ registry }} \
          --username {{ registry_user }} --password-stdin
      no_log: true

    - name: Публикация образа
      ansible.builtin.command: >
        buildah push {{ registry }}/{{ repo }}:{{ tag }}
        docker://{{ registry }}/{{ repo }}:{{ tag }}
      register: push_result

    - name: Очистка рабочего контейнера
      ansible.builtin.command: "buildah rm {{ container_id }}"
      changed_when: false
      when: cleanup | default(true)

    - name: Вывод результата
      ansible.builtin.debug:
        msg: "Образ опубликован: {{ registry }}/{{ repo }}:{{ tag }}"
```

### 6. Проверка и верификация образа

После сборки необходимо проверить корректность образа перед деплоем.

```yaml
---
- name: Верификация собранного образа
  hosts: localhost
  gather_facts: false
  vars:
    image_name: "my-app"
    image_tag: "1.5.0"

  tasks:
    - name: Проверка существования образа
      ansible.builtin.command: "buildah inspect {{ image_name }}:{{ image_tag }}"
      register: inspect_result
      failed_when: inspect_result.rc != 0

    - name: Проверка размера образа
      ansible.builtin.command: "buildah images {{ image_name }}:{{ image_tag }} --format '{{{{.Size}}}}'"
      register: image_size
      changed_when: false

    - name: Проверка labels
      ansible.builtin.command: "buildah inspect --format '{{{{index .Labels \"version\"}}}}' {{ image_name }}:{{ image_tag }}"
      register: version_label
      changed_when: false
      failed_when: version_label.stdout != image_tag

    - name: Проверка entrypoint
      ansible.builtin.command: "buildah inspect --format '{{{{.OCIv1.Config.Entrypoint}}}}' {{ image_name }}:{{ image_tag }}"
      register: entrypoint_check
      changed_when: false

    - name: Проверка портов
      ansible.builtin.command: "buildah inspect --format '{{{{.OCIv1.Config.ExposedPorts}}}}' {{ image_name }}:{{ image_tag }}"
      register: ports_check
      changed_when: false

    - name: Вывод результатов верификации
      ansible.builtin.debug:
        msg: |
          Размер: {{ image_size.stdout }}
          Версия: {{ version_label.stdout }}
          Entrypoint: {{ entrypoint_check.stdout }}
          Порты: {{ ports_check.stdout }}
```

### 7. Интеграция с CI/CD (GitLab CI)

Пример полного пайплайна сборки и публикации образа:

```yaml
# .gitlab-ci.yml
---
stages:
  - build
  - test
  - publish

variables:
  IMAGE_NAME: "${CI_REGISTRY_IMAGE}"
  IMAGE_TAG: "${CI_COMMIT_SHORT_SHA}"

build:
  stage: build
  image: quay.io/buildah/stable:v1.45
  script:
    - ansible-playbook build_image.yml
      -e "image_tag=${IMAGE_TAG}"
      -e "registry=${CI_REGISTRY}"
  artifacts:
    paths:
      - build.log

test:
  stage: test
  image: "${IMAGE_NAME}:${IMAGE_TAG}"
  script:
    - python3 /app/test_suite.py
  services:
    - name: "${IMAGE_NAME}:${IMAGE_TAG}"
      alias: app-under-test

publish:
  stage: publish
  image: quay.io/buildah/stable:v1.45
  only:
    - main
    - tags
  script:
    - echo "${CI_REGISTRY_PASSWORD}" | buildah login ${CI_REGISTRY}
      --username ${CI_REGISTRY_USER} --password-stdin
    - buildah push ${IMAGE_NAME}:${IMAGE_TAG} docker://${IMAGE_NAME}:latest
    - buildah push ${IMAGE_NAME}:${IMAGE_TAG} docker://${IMAGE_NAME}:${CI_COMMIT_TAG}
  when: on_success
```

### 8. Полный плейбук: сборка с зависимостями и кэшированием

```yaml
---
- name: Сборка production-образа с кэшированием
  hosts: localhost
  gather_facts: false
  vars:
    base_image: "python:3.12-slim"
    app_name: "data-pipeline"
    app_version: "2.3.0"
    registry: "registry.example.com"
    cache_dir: "/tmp/buildah-cache"

  tasks:
    - name: Создание рабочего контейнера
      ansible.builtin.command: "buildah from {{ base_image }}"
      register: container
      changed_when: false

    - name: Монтирование контейнера
      ansible.builtin.command: "buildah mount {{ container.stdout }}"
      register: mount
      changed_when: false

    - name: Установка системных зависимостей
      ansible.builtin.shell: |
        {{ mount.stdout }}/usr/bin/apt-get update
        {{ mount.stdout }}/usr/bin/apt-get install -y --no-install-recommends \
          build-essential \
          libpq-dev \
          curl
      changed_when: true

    - name: Кэширование pip-зависимостей
      ansible.builtin.shell: |
        {{ mount.stdout }}/usr/local/bin/pip install --cache-dir={{ cache_dir }} \
          -r requirements.txt
      changed_when: true

    - name: Копирование кода приложения
      ansible.builtin.command: "buildah copy {{ container.stdout }} ./src /app/src"
      changed_when: true

    - name: Копирование конфигурации
      ansible.builtin.template:
        src: config.yml.j2
        dest: "{{ mount.stdout }}/app/config.yml"
        mode: '0644'

    - name: Очистка кэша сборки
      ansible.builtin.file:
        path: "{{ mount.stdout }}/var/cache/apt"
        state: absent

    - name: Размонтирование
      ansible.builtin.command: "buildah unmount {{ container.stdout }}"
      changed_when: false

    - name: Установка метаданных
      ansible.builtin.command: >
        buildah config
        --author "Data Engineering Team"
        --label "version={{ app_version }}"
        --label "build={{ ansible_date_time.iso8601_basic_short }}"
        --entrypoint '["python3", "/app/src/main.py"]'
        --port 8000
        --user 1000:1000
        --workingdir /app
        {{ container.stdout }}
      changed_when: false

    - name: Фиксация образа
      ansible.builtin.command: >
        buildah commit {{ container.stdout }} {{ app_name }}:{{ app_version }}
      register: commit_result

    - name: Очистка рабочего контейнера
      ansible.builtin.command: "buildah rm {{ container.stdout }}"
      changed_when: false

    - name: Верификация образа
      ansible.builtin.command: "buildah images {{ app_name }}:{{ app_version }}"
      register: image_info
      changed_when: false

    - name: Вывод информации
      ansible.builtin.debug:
        msg: "Образ собран: {{ app_name }}:{{ app_version }} | {{ image_info.stdout_lines }}"
```

## Устранение типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `error creating buildah container` | Недостаточно прав в rootless-режиме | Используйте `buildah unshare` перед запуском |
| `overlay mount fails` | Драйвер `overlay` не поддерживается | Установите `fuse-overlayfs` или используйте `vfs` драйвер |
| `no such file or directory` | Неверный путь к файлу в `buildah copy` | Проверьте контекст сборки и пути в плейбуке |
| `unable to find user` | UID:GID не существует в образе | Убедитесь, что пользователь создан в образе |
| `permission denied` | Rootless-режим ограничивает операции | Используйте `buildah unshare` или `sudo` |
| `manifest list not found` | Multi-arch образ не собран | Используйте `buildah manifest create` перед пушем |
| `buildah from: image not known` | Образ не найден в локальном хранилище | Проверьте имя образа, выполните `buildah pull` |
| `error committing container` | Конфликт слоев или нехватка места | Проверьте `df -h` и выполните `buildah rm` для очистки |
| `Ansible module not found` | Коллекция `containers.podman` не установлена | `ansible-galaxy collection install containers.podman` |
| `timeout waiting for connection` | Контейнер не смонтирован или удалён | Проверьте `buildah containers` и пересоздайте контейнер |

**Диагностика:**
```bash
# Проверка доступных образов
buildah images

# Просмотр рабочих контейнеров
buildah containers

# Просмотр деталей образа
buildah inspect my-image:latest

# Проверка слоев образа
buildah inspect --format '{{range .LayerDiffIDs}}{{println .}}{{end}}' my-image:latest

# Тестирование плейбука (dry-run)
ansible-playbook build_image.yml --check --diff

# Просмотр команд без выполнения
ansible-playbook build_image.yml -vvv

# Проверка синтаксиса
ansible-playbook build_image.yml --syntax-check
```

## Контрольный список: лучшие практики

- [ ] **Безопасность секретов:** Пароли и ключи хранятся в `ansible-vault`, передаются через `template`/`copy`, удаляются перед `commit`
- [ ] **Идемпотентность:** Используйте ресурсные модули `containers.podman` вместо `command` там, где это возможно
- [ ] **Минимизация слоев:** Фиксируйте изменения одним `buildah commit` в конце плейбука
- [ ] **Тегирование:** Всегда указывайте версию и дату сборки в labels (`version`, `build-date`)
- [ ] **Кэширование:** Монтируйте кэш пакетного менеджера с хоста для ускорения сборок в CI/CD
- [ ] **Верификация:** Проверяйте образ после сборки (размер, labels, entrypoint, порты)
- [ ] **Cleanup:** Удаляйте рабочие контейнеры после фиксации (`buildah rm`)
- [ ] **Пиннинг версий:** Указывайте конкретную версию базового образа (`alpine:3.20`, не `alpine:latest`)
- [ ] **Linting:** Проходите `ansible-lint` перед коммитом плейбуков
- [ ] **Check mode:** Проверяйте `--check --diff` перед реальными изменениями
- [ ] **Кроссплатформенность:** Используйте.roles для разделения логики по типам ОС
- [ ] **Документация:** Описывайте назначение каждого образа через labels и README

## Дополнительная информация

### Оптимизация и кэширование
1.  **Слои:** При использовании плагина `buildah` изменения фиксируются только при вызове `buildah commit`. Это позволяет создавать образы с минимальным количеством слоев (один слой на весь плейбук), что повышает производительность при скачивании.
2.  **Кэш пакетов:** Для ускорения сборок в CI/CD рекомендуется монтировать кэш пакетного менеджера (например, `/var/cache/apk` или `/var/cache/dnf`) с хоста в рабочий контейнер через параметры `buildah run`.
3.  **Кэширование pip/npm:** Используйте `--cache-dir` при установке зависимостей для повторного использования кэша между сборками.
4.  **Распределенный кэш:** В CI/CD используйте `--cache-from`/`--cache-to` для распределенного кэширования слоев через registry.

### Защита секретов
Никогда не используйте `ENV` или `ARG` в `Dockerfile` для передачи паролей. При использовании Ansible:
1.  Храните секреты в `ansible-vault`.
2.  Используйте модуль `ansible.builtin.template` для генерации конфигурационных файлов "на лету" внутри контейнера.
3.  Если секрет нужен только в процессе установки (например, ключ SSH для доступа к приватному репозиторию), передавайте его как переменную и удаляйте временные файлы перед фиксацией образа (`buildah commit`).
4.  Используйте `no_log: true` в задачах Ansible для скрытия секретов в логах.

### Сравнение подходов

| Критерий | Podman Build (Dockerfile) | Ansible + Buildah Plugin | Ansible-builder (EE) | Ansible + command/shell |
| :--- | :--- | :--- | :--- | :--- |
| **Гибкость логики** | Низкая (Shell скрипты) | Высокая (Модули, YAML) | Средняя (Конфиг YAML) | Средняя (Shell) |
| **Идемпотентность** | На уровне слоев | На уровне каждой задачи | На уровне сборки целиком | Нет |
| **Слои образа** | Много (на каждую команду) | Минимум (ручной коммит) | Много | Минимум |
| **Контроль слоев** | Автоматический | Ручной (commit) | Автоматический | Ручной |
| **Секреты** | ENV/ARG (небезопасно) | Vault + template (безопасно) | Vault (безопасно) | Переменные |
| **Применение** | Стандартные приложения | Сложная инфраструктура | Инфраструктура Ansible | Простые сборки |
| **Требования** | Podman/Docker | Buildah + Ansible | Ansible-builder | Buildah CLI |
| **CI/CD** | Container registry | SSH / Ansible Runner | AAP/AWX | Прямые команды |

### Смотрите также

*   **[Buildah: Концепции и практика](../Podman/buildah_overview.md)** — подробный разбор CLI-команд Buildah и механизмов монтирования.
*   **[Кроссплатформенные плейбуки Ansible](./CrossPlatform/concepts.md)** — стратегии написания ролей для разных типов таргетов.
