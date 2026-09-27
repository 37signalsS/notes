# Сборка OCI-образов с помощью Ansible и Buildah

## Определения

**Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, полностью соответствующих стандартам **OCI (Open Container Initiative)**. Он спроектирован для работы без фонового демона (**daemonless**) и поддерживает полноценный безрутовый режим (**rootless**).

**Плагин соединения buildah (`containers.podman.buildah`)** — современный и официально поддерживаемый способ использования Ansible для сборки образов. Он позволяет Ansible "монтировать" рабочий контейнер Buildah и выполнять в нем задачи напрямую через драйвер файловой системы, обходясь без SSH-сервера или установленного Python внутри образа.

**Ansible-builder** — специализированный инструмент для сборки **[Execution Environments (EE)](./ansible-execution-environments.md)**.

**Ansible-bender** — устаревшая утилита-мост (legacy). Проект признан архивным и не рекомендуется для новых разработок. Для сборки образов на базе плейбуков следует использовать плагин соединения `buildah`.

**Containerfile** — файл описания сборки, синтаксически совместимый с `Dockerfile`. Buildah автоматически ищет `Containerfile`, а при его отсутствии — `Dockerfile`. Поддерживает heredoc-синтаксис и файл исключений `.containerignore`.

**Build context (Контекст сборки)** — каталог, из которого инструкции `COPY`/`ADD` получают исходные файлы; исключаемые файлы задаются в `.dockerignore`/`.containerignore`.

**Working Container (Рабочий контейнер)** — временная сущность в локальном хранилище, представляющая собой распакованную файловую систему базового образа с записываемым слоем. Buildah манипулирует этим слоем и позволяет "закоммитить" его в итоговый образ в любой момент.

**Daemonless** — архитектура без постоянно запущенного фонового процесса. Buildah работает по модели fork-exec: процесс запускается, выполняет конкретную операцию и немедленно завершается. Это снижает поверхность атаки и потребление ресурсов на хосте.

**Rootless mode (Безрутовый режим)** — режим работы, при котором пользователь не имеет прав root в хост-системе. Buildah использует user namespaces для эмуляции прав root внутри изолированного пространства имен.

**SBOM (Software Bill of Materials)** — инвентаризационный список компонентов ПО, входящих в образ. Используется для отслеживания зависимостей и управления уязвимостями.

**Image Signing (Подпись образа)** — процесс цифровой подписи образа для подтверждения его происхождения и целостности. Инструменты: `cosign`, `notation`.

## Основные концепции

### Архитектура и принцип работы

Buildah — это не демон и не runtime. Это набор Unix-утилит, которые работают напрямую с ядром Linux через библиотеку `containers/storage`:

1. **Namespaces:** при создании рабочего контейнера Buildah настраивает mount, UTS и IPC namespace. PID и network namespace не создаются, так как контейнер не запускается как сервис.

2. **Стораж:** Buildah использует драйвер `containers-storage:` (библиотека `containers/storage`) для управления слоями образов. Это тот же бэкенд, что и у Podman/CRI-O, что позволяет разделять локальные образы между инструментами без повторной выгрузки.

3. **Storage drivers (Драйверы хранилища):**
   - **overlay / overlay2** — наиболее производительный, требует поддержки ядром OverlayFS. Рекомендуется для продакшн-сборок.
   - **fuse-overlayfs** — реализация OverlayFS в userspace. Работает в rootless-режиме без прав root. Рекомендуется для rootless-сборок на хостах без поддержки kernel overlay.
   - **vfs** — полная копия файлов для каждого слоя. Низкая производительность, но максимальная совместимость. Используется как fallback.
   - **devicemapper** — legacy-драйвер. Не рекомендуется для новых сборок.

4. **OCI runtime:** Buildah **не использует** OCI runtime (crun/runc) для сборки. Он работает напрямую с файловой системой. Это снижает накладные расходы и сложность привилегий по сравнению с Podman/Docker, которые вызывают `conmon` → `crun`.

5. **Общее хранилище:** образы, созданные Buildah, немедленно доступны для `podman run` через транспорт `containers-storage:`. Не требуется `buildah push` в реестр для локального использования.

### Предварительные требования

Для автоматизации сборки образов через Ansible + Buildah необходимы:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | Ядро Ansible (рекомендуется 2.17+) |
| **Python** | 3.8+ | Совместимость с ansible-core |
| **Buildah** | 1.41+ | Сборщик образов (стабильная версия на июль 2026 — 1.45.0) |
| **containers.podman** | latest | Коллекция модулей Ansible для Podman/Buildah |
| **containers.common** | latest | Общие зависимости коллекции containers |
| **Podman** (опционально) | 4.6+ | Управление контейнерами (сборка через `podman_image`) |
| **fuse-overlayfs** | latest | Драйвер хранилища для rootless-режима (рекомендуется) |
| **overlay-utils** | latest | Драйвер overlay для rootfs (обычно предустановлен) |
| **Ядро Linux** | 4.18+ | Поддержка OverlayFS, user namespaces, cgroups v2 |

**Требования к ядру:**
- **OverlayFS** — требуется для драйверов `overlay` и `fuse-overlayfs`
- **User namespaces** — требуется для rootless-режима
- **cgroups v2** — рекомендуется (cgroups v1 удалены в Buildah 1.44.0)
- **FUSE** — требуется для `fuse-overlayfs`

**Проверка поддержки:**
```bash
# Проверка поддержки OverlayFS
cat /proc/filesystems | grep overlay
# → nodev   overlay

# Проверка поддержки user namespaces
sysctl user.max_user_namespaces
# → user.max_user_namespaces = 28633

# Проверка версии ядра
uname -r
# → 5.15.0-78-generic
```

**Установка Buildah:**
```bash
# Fedora / RHEL / CentOS Stream
sudo dnf install -y buildah fuse-overlayfs

# Ubuntu / Debian (Bookworm и новее)
sudo apt update && sudo apt install -y buildah fuse-overlayfs

# openSUSE / SLES
sudo zypper install -y buildah fuse-overlayfs

# macOS (через Homebrew)
brew install buildah
# → Примечание: Buildah работает только на Linux-хостах. На macOS используется Colima/Lima с Linux-VM.
```

**Установка коллекций Ansible:**
```bash
# Основные коллекции
ansible-galaxy collection install containers.podman containers.common

# Или через requirements.yml
cat > requirements.yml << 'EOF'
collections:
  - name: containers.podman
    version: ">=1.0.0"
  - name: containers.common
    version: ">=1.0.0"
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

# Проверка доступных драйверов хранилища
buildah info --format '{{.Store.VolumeDriver}}'
# → overlay (или fuse-overlayfs)
```

### Преимущества Ansible + Buildah перед Dockerfile

Использование Ansible в связке с Buildah предоставляет критические преимущества перед классическими `Dockerfile`:

*   **Идемпотентность** — гарантия того, что повторный запуск сборки не внесет изменений в слои, если целевое состояние конфигурации уже достигнуто. В отличие от `RUN` в Dockerfile (который всегда выполняется), Ansible-задачи проверяют состояние перед изменением.
*   **Переиспользование кода** — возможность применять одни и те же проверенные роли Ansible (например, по харденингу ОС или настройке мониторинга) как для инфраструктуры (ВМ, Bare Metal), так и для сборки неизменяемых (immutable) контейнеров.
*   **Безопасность секретов** — использование **Ansible Vault** позволяет передавать пароли, ключи и сертификаты в процессе сборки без их сохранения в метаданных или слоях итогового образа. Никогда не используйте `ENV` или `ARG` для передачи паролей — они остаются в метаданных образа.
*   **Сложная логика сборки** — использование циклов, условий, шаблонов Jinja2 и динамического получения данных из внешних API (например, из NetBox или Vault) на этапе генерации образа. В Dockerfile такая логика реализуется только через shell-скрипты.
*   **Управление слоями** — Buildah позволяет создавать образы с минимальным количеством слоев (один слой на весь плейбук), что повышает производительность при скачивании и уменьшает размер образа.
*   **Монтирование ФС** — `buildah mount` позволяет модифицировать файловую систему образа как обычный каталог на хосте, используя инструменты хоста (установка пакетов, копирование файлов) без необходимости иметь пакетный менеджер внутри образа.
*   **Отсутствие демона** — Buildah не требует постоянно запущенного демона, что снижает поверхность атаки и потребление ресурсов на хосте.
*   **Rootless-сборки в CI/CD** — Buildah позволяет собирать образы без привилегированного контейнера (Docker-in-Docker), используя user namespaces и fuse-overlayfs.

### Rootless-режим

При запуске без прав root необходимо учитывать особенности работы с user namespaces:

*   **`buildah unshare`** — команда, создающая новый User Namespace, в котором текущий пользователь получает права root внутри этого пространства имен. Это необходимо для корректной работы драйверов файловой системы (например, `overlay`, `fuse-overlayfs`).
*   **Когда требуется `buildah unshare`:** При использовании `buildah mount`, `buildah config`, `buildah commit`, и любых операций, требующих привилегий root в User Namespace (монтирование, изменение прав доступа, установка пакетов через `dnf`/`apt`).
*   **Когда `buildah unshare` не нужен:** При простых командах `buildah from`, `buildah run` (с выполняемой командой), `buildah rm` — эти операции работают в rootless-режиме без дополнительной обертки.
*   **Ограничения rootless:** Не поддерживаются привилегированные порты (<1024), драйвер `overlay` без fuse-overlayfs (требует прав root), и иерархические cgroups в старых ядрах.
*   **Storage driver в rootless-режиме:** По умолчанию Buildah использует `vfs` в rootless-режиме, что дает низкую производительность. Для работы с `fuse-overlayfs` настройте `containers.conf`:

```bash
mkdir -p ~/.config/containers
cat > ~/.config/containers/storage.conf << 'EOF'
[storage]
driver = "fuse-overlayfs"
runroot = "/run/user/1000/containers"
graphroot = "/home/user/.local/share/containers/storage"
EOF
```

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
| `--annotation` | Аннотация OCI (ключ=значение) | `--annotation "org.opencontainers.image.created=2026-09-24T10:00:00Z"` |
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
| `--os-version` | Версия ОС образа | `--os-version "9"` |
| `--label` | Метка образа | `--label maintainer="devops@example.com"` |
| `--arch` | Архитектура процессора | `--arch amd64` |

## Операции и команды

### Справочник команд Buildah

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `buildah from` | Создание рабочего контейнера из базового образа | `buildah from alpine:3.20` |
| `buildah run` | Выполнение команды внутри контейнера | `buildah run alpine -- apk add --no-cache nginx` |
| `buildah copy` | Копирование файлов/папок в контейнер | `buildah copy alpine /local/app /app` |
| `buildah add` | Добавление файлов с поддержкой symlinks | `buildah add --no-follow-symlinks alpine /local/app.tar /app` |
| `buildah mount` | Монтирование ФС рабочего контейнера | `buildah mount alpine` |
| `buildah unmount` | Размонтирование рабочего контейнера | `buildah unmount alpine` |
| `buildah config` | Установка метаданных образа | `buildah config --author "DevOps Team" alpine` |
| `buildah commit` | Фиксация рабочего контейнера в образ | `buildah commit alpine my-nginx:1.5.0` |
| `buildah rm` | Удаление рабочего контейнера | `buildah rm alpine` |
| `buildah inspect` | Просмотр метаданных образа | `buildah inspect my-nginx:1.5.0` |
| `buildah images` | Список локальных образов | `buildah images --format '{{.Name}}:{{.Tag}} {{.Size}}'` |
| `buildah containers` | Список рабочих контейнеров | `buildah containers --format '{{.ContainerID}} {{.ContainerName}}'` |
| `buildah login` | Авторизация в registry | `buildah login registry.example.com --username user` |
| `buildah push` | Публикация образа в registry | `buildah push my-nginx:1.5.0 docker://registry.example.com/my-nginx:1.5.0` |
| `buildah tag` | Создание тега образа | `buildah tag my-nginx:1.5.0 my-nginx:latest` |
| `buildah manifest` | Управление multi-arch манифестами | `buildah manifest create my-nginx:1.5.0 --arch amd64 --arch arm64` |
| `buildah bud` | Сборка из Containerfile (альтернатива build) | `buildah bud -t my-nginx:1.5.0 -f Containerfile ./` |
| `buildah unshare` | Запуск команды в user namespace | `buildah unshare ansible-playbook build_image.yml` |
| `buildah rmi` | Удаление локального образа | `buildah rmi my-nginx:1.5.0` |
| `buildah history` | Просмотр истории слоев образа | `buildah history my-nginx:1.5.0` |
| `buildah diff` | Просмотр изменений в рабочем контейнере | `buildah diff alpine --name --size --type` |
| `buildah umount` | Размонтирование контейнера (алиас unmount) | `buildah umount alpine` |

### Новые возможности Buildah 1.44.0–1.45.0

| Версия | Возможность | Описание |
| :--- | :--- | :--- |
| 1.45.0 | `--no-follow-symlinks` | Копирование symlinks вместо dereferencing в `buildah add`/`copy` |
| 1.45.0 | `--timestamp 0` | Фиксированный timestamp для reproducible builds в `buildah manifest push` |
| 1.44.0 | `--metadata-file` | Экспорт метаданных образа в JSON-файл при `buildah build`/`commit` |
| 1.44.0 | `--valid-exit-codes` | Принятие конкретных non-zero exit codes как успешных в `buildah run` |
| 1.41.0 | `ADD/COPY --link` | Создание hard links вместо копирования для экономии места |
| 1.41.0 | `zstd` commit | Сжатие слоев zstd при `buildah commit` для уменьшения размера |
| 1.41.0 | `--unsetannotation` | Удаление аннотаций из образа |
| 1.41.0 | `--inherit-annotations` | Наследование аннотаций от базового образа |

## Практические сценарии

### 1. Использование плагина соединения Buildah

Это наиболее гибкий и мощный метод. Ansible подключается к рабочему контейнеру Buildah так же, как к удаленному хосту по SSH, но использует для этого механизмы `buildah mount`.

#### Работа в Rootless-режиме
При запуске без прав root необходимо использовать команду `buildah unshare`. Она создает новый User Namespace, в котором текущий пользователь получает права root внутри этого пространства имен, что необходимо для корректной работы драйверов файловой системы (например, `overlay`, `fuse-overlayfs`).

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
        --label "version={{ app_version | default('1.5.0') }}"
        --label "build-date={{ ansible_date_time.iso8601_basic_short }}"
        --port 80
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

#### Установка метаданных образа (Labels, Ports, Env, Annotations)

Полноценная настройка образа перед фиксацией:

```yaml
- name: Установка полного набора метаданных
  hosts: localhost
  tasks:
    - name: Установка author, labels, ports, env, entrypoint, annotations
      ansible.builtin.command: >
        buildah config
        --author "DevOps Team"
        --annotation "org.opencontainers.image.created={{ ansible_date_time.iso8601 }}"
        --annotation "org.opencontainers.image.revision={{ git_sha | default('dev') }}"
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
        cd {{ builder_path }}/src && go build -o {{ builder_path }}/app/server main.go
        # Копирование в runtime средствами хоста
        cp {{ builder_path }}/app/server {{ runtime_path }}/usr/bin/server

    - name: Установка метаданных runtime-контейнера
      ansible.builtin.command: >
        buildah config
        --entrypoint '["/usr/bin/server"]'
        --port 8080
        --user 1000:1000
        --label "build-tool=golang"
        {{ runtime_raw.stdout }}
      changed_when: false

    - name: Очистка рабочего контейнера сборки
      ansible.builtin.command: "buildah rm {{ builder_raw.stdout }}"
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
        --annotation "org.opencontainers.image.source=https://github.com/example/my-app"
        --entrypoint '["python3", "/app/main.py"]'
        --port 8080
        --user 1000:1000
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

    - name: Проверка пользователя
      ansible.builtin.command: "buildah inspect --format '{{{{.OCIv1.Config.User}}}}' {{ image_name }}:{{ image_tag }}"
      register: user_check
      changed_when: false
      failed_when: user_check.stdout | length == 0

    - name: Проверка слоев образа
      ansible.builtin.command: "buildah inspect --format '{{{{range .LayerDiffIDs}}}{{{println .}}}{{{end}}}}' {{ image_name }}:{{ image_tag }}"
      register: layers_check
      changed_when: false

    - name: Вывод результатов верификации
      ansible.builtin.debug:
        msg: |
          Размер: {{ image_size.stdout }}
          Версия: {{ version_label.stdout }}
          Entrypoint: {{ entrypoint_check.stdout }}
          Порты: {{ ports_check.stdout }}
          Пользователь: {{ user_check.stdout }}
          Количество слоев: {{ layers_check.stdout_lines | length }}
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
  image: quay.io/buildah/stable:latest
  script:
    - ansible-playbook build_image.yml \
      -e "image_tag=${IMAGE_TAG}"" \
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
  image: quay.io/buildah/stable:latest
  only:
    - main
    - tags
  script:
    - echo "${CI_REGISTRY_PASSWORD}" | buildah login ${CI_REGISTRY} \
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
    build_user: "1000"
    build_group: "1000"

  tasks:
    - name: Создание рабочего контейнера
      ansible.builtin.command: "buildah from {{ base_image }}"
      register: container
      changed_when: false

    - name: Монтирование контейнера
      ansible.builtin.command: "buildah mount {{ container.stdout }}"
      register: mount
      changed_when: false

    - name: Создание группы и пользователя для приложения
      ansible.builtin.command: "groupadd -g {{ build_group }} appuser"
      register: group_create
      changed_when: group_create.rc == 4 # уже существует

    - name: Создание пользователя для приложения
      ansible.builtin.command: "useradd -u {{ build_user }} -g {{ build_group }} -m -s /bin/sh appuser"
      register: user_create
      changed_when: user_create.rc == 4 # уже существует

    - name: Установка системных зависимостей
      ansible.builtin.shell: |
        {{ mount.stdout }}/usr/bin/apt-get update
        {{ mount.stdout }}/usr/bin/apt-get install -y --no-install-recommends \
          build-essential \
          libpq-dev \
          curl
      changed_when: true

    - name: Создание директории для кэша
      ansible.builtin.file:
        path: "{{ cache_dir }}"
        state: directory
        mode: '0755'

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
        owner: "{{ build_user }}"
        group: "{{ build_group }}"

    - name: Очистка кэша сборки
      ansible.builtin.file:
        path: "{{ mount.stdout }}/var/cache/apt"
        state: absent

    - name: Установка прав доступа для приложения
      ansible.builtin.file:
        path: "/app"
        state: directory
        recurse: yes
        owner: "{{ build_user }}"
        group: "{{ build_group }}"

    - name: Размонтирование
      ansible.builtin.command: "buildah unmount {{ container.stdout }}"
      changed_when: false

    - name: Установка метаданных
      ansible.builtin.command: >
        buildah config
        --author "Data Engineering Team"
        --label "version={{ app_version }}"
        --label "build={{ ansible_date_time.iso8601_basic_short }}"
        --label "maintainer=devops@example.com"
        --annotation "org.opencontainers.image.source=https://github.com/example/data-pipeline"
        --annotation "org.opencontainers.image.description=Production data pipeline image"
        --entrypoint '["python3", "/app/src/main.py"]'
        --port 8000
        --user {{ build_user }}:{{ build_group }}
        --workingdir /app
        --stop-signal SIGTERM
        --healthcheck "curl -f http://localhost:8000/health || exit 1"
        --healthcheck-interval 30s
        --healthcheck-timeout 5s
        --healthcheck-retries 3
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

## Безопасность и хардениг

### Хардениг образов в контексте SRE

Для продакшн-образов критично придерживаться следующих принципов:

1. **Не-root пользователь:** Всегда используйте `--user 1000:1000` или создайте dedicated-пользователя в образе. Никогда не запускайте приложение от root.

2. **Минимальные базовые образы:** Используйте `alpine:3.20`, `python:3.12-slim`, `distroless` или `scratch` вместо `ubuntu:latest`. Меньше пакетов — меньше поверхность атаки.

3. **Очистка кэша пакетного менеджера:** Удаляйте `/var/cache/apk`, `/var/cache/dnf`, `/var/cache/apt` после установки пакетов.

4. **Удаление временных файлов:** Удаляйте ключи SSH, кэш pip/npm и временные файлы перед `buildah commit`.

5. **Подпись образа:** Используйте `cosign` или `notation` для цифровой подписи образа перед публикацией.

6. **Сканирование уязвимостей:** Интегрируйте Trivy или Grype в CI/CD для сканирования образа перед деплоем.

7. **SBOM генерация:** Генерируйте Software Bill of Materials для каждого образа.

```yaml
- name: Хардениг production-образа
  hosts: localhost
  tasks:
    - name: Создание non-root пользователя в образе
      ansible.builtin.command: "buildah run {{ container }} -- useradd -m -u 1000 appuser"
      changed_when: true

    - name: Установка прав на директорию приложения
      ansible.builtin.command: "buildah run {{ container }} -- chown -R appuser:appuser /app"

    - name: Установка метаданных с non-root пользователем
      ansible.builtin.command: >
        buildah config
        --user 1000:1000
        --stop-signal SIGTERM
        --no-new-privileges
        {{ container }}
      changed_when: false

    - name: Удаление временных файлов перед коммитом
      ansible.builtin.shell: |
        # Удаление ключей SSH
        rm -f {{ mount }}/root/.ssh/*
        # Удаление кэша pip
        rm -rf {{ mount }}/root/.cache/pip/*
        # Удаление кэша apt
        rm -rf {{ mount }}/var/cache/apt/*
      changed_when: true
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
| `seccomp profile rejected` | Явный seccomp профиль без поддержки | Уберите `--security-opt seccomp=profile` или соберите Buildah с seccomp |
| `failed to copy symlink` | Symlink не разрешен | Используйте `buildah add --no-follow-symlinks` |
| `cgroup v1 not supported` | cgroups v1 удалены в Buildah 1.44+ | Перейдите на cgroups v2 |

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

# Проверка хранилища
buildah info --format '{{.Store.VolumeDriver}}'

# Тестирование плейбука (dry-run)
ansible-playbook build_image.yml --check --diff

# Просмотр команд без выполнения
ansible-playbook build_image.yml -vvv

# Проверка синтаксиса
ansible-playbook build_image.yml --syntax-check

# Проверка подключения к registry
buildah login registry.example.com --get-login

# Проверка доступного места на диске
df -h /var/lib/containers
```

## Сканирование уязвимостей и SBOM

### Интеграция Trivy в CI/CD

Trivy — сканер уязвимостей для образов контейнеров, файловых систем и Git-репозиториев.

```bash
# Установка Trivy
curl -fsSL https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
echo "deb https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee -a /etc/apt/sources.list.d/trivy.list
sudo apt update && sudo apt install -y trivy

# Сканирование образа
trivy image --severity HIGH,CRITICAL my-nginx:1.5.0

# Сканирование с выводом в JSON
trivy image -f json -o trivy-report.json my-nginx:1.5.0

# Сканирование с минимальным порогом
trivy image --exit-code 1 --severity CRITICAL my-nginx:1.5.0
```

**Интеграция с Ansible:**
```yaml
- name: Сканирование образа на уязвимости
  hosts: localhost
  gather_facts: false
  vars:
    image_name: "my-app"
    image_tag: "1.5.0"

  tasks:
    - name: Установка Trivy (если отсутствует)
      ansible.builtin.apt:
        name: trivy
        state: present

    - name: Сканирование образа
      ansible.builtin.command: >
        trivy image
        --severity HIGH,CRITICAL
        --exit-code 1
        {{ image_name }}:{{ image_tag }}
      register: trivy_result
      failed_when: trivy_result.rc == 1
      changed_when: false

    - name: Пропуск сканирования при отсутствии уязвимостей
      ansible.builtin.debug:
        msg: "Уязвимостей HIGH/CRITICAL не обнаружено"
```

### Генерация SBOM

SBOM (Software Bill of Materials) — инвентаризационный список компонентов ПО.

```bash
# Использование Trivy для генерации SBOM
trivy image -f cyclonedx -o sbom.json my-nginx:1.5.0

# Использование Syft
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin
syft my-nginx:1.5.0 -o cyclonedx-json=sbom.json
```

**Интеграция с Ansible:**
```yaml
- name: Генерация SBOM для образа
  hosts: localhost
  gather_facts: false
  vars:
    image_name: "my-app"
    image_tag: "1.5.0"
    sbom_dir: "/opt/sbom"

  tasks:
    - name: Создание директории для SBOM
      ansible.builtin.file:
        path: "{{ sbom_dir }}"
        state: directory
        mode: '0755'

    - name: Генерация SBOM через Trivy
      ansible.builtin.command: >
        trivy image
        -f cyclonedx
        -o {{ sbom_dir }}/{{ image_name }}:{{ image_tag }}-sbom.json
        {{ image_name }}:{{ image_tag }}
      changed_when: true

    - name: Генерация SBOM через Syft (альтернатива)
      ansible.builtin.command: >
        syft {{ image_name }}:{{ image_tag }}
        -o cyclonedx-json={{ sbom_dir }}/{{ image_name }}:{{ image_tag }}-sbom.json
      changed_when: true
      when: syft_installed | default(false)

    - name: Валидация SBOM
      ansible.builtin.command: >
        trivy image -f cyclonedx -o {{ sbom_dir }}/{{ image_name }}:{{ image_tag }}-sbom-validated.json
        {{ image_name }}:{{ image_tag }}
      changed_when: true
```

## Подпись и верификация образов

### Подпись образа через Cosign

Cosign — инструмент для цифровой подписи и верификации образов контейнеров.

```bash
# Установка Cosign
curl -fsSL https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64 | \
  sudo tee /usr/local/bin/cosign > /dev/null && \
  sudo chmod +x /usr/local/bin/cosign

# Генерация ключевой пары
cosign generate-key-pair

# Подпись образа
cosign sign --key cosign.key registry.example.com/my-app:1.5.0

# Верификация образа
cosign verify --key cosign.pub registry.example.com/my-app:1.5.0
```

**Интеграция с Ansible:**
```yaml
- name: Подпись образа перед публикацией
  hosts: localhost
  gather_facts: false
  vars:
    image_name: "my-app"
    image_tag: "1.5.0"
    cosign_key: "/etc/ansible/secrets/cosign.key"
    cosign_password: "{{ lookup('env', 'COSIGN_PASSWORD') }}"

  tasks:
    - name: Подпись образа через Cosign
      ansible.builtin.command: >
        COSIGN_PASSWORD={{ cosign_password }} cosign sign
        --key {{ cosign_key }}
        --yes
        {{ registry }}/{{ image_name }}:{{ image_tag }}
      changed_when: true
      no_log: true

    - name: Верификация подписи перед деплоем
      ansible.builtin.command: >
        cosign verify
        --key {{ cosign_pub }}
        {{ registry }}/{{ image_name }}:{{ image_tag }}
      changed_when: false
      register: cosign_verify
      failed_when: cosign_verify.rc != 0
```

## Multi-arch сборки

### Создание multi-arch манифеста

Multi-arch образы содержат слои для разных архитектур процессоров под одним тегом.

```bash
# Создание multi-arch образа
buildah manifest create my-app:1.5.0 --arch amd64 --arch arm64

# Сборка для amd64
buildah bud --arch amd64 -t my-app:1.5.0-amd64 -f Containerfile ./context/

# Сборка для arm64
buildah bud --arch arm64 -t my-app:1.5.0-arm64 -f Containerfile ./context/

# Добавление в манифест
buildah manifest add my-app:1.5.0 my-app:1.5.0-amd64 --arch amd64
buildah manifest add my-app:1.5.0 my-app:1.5.0-arm64 --arch arm64

# Пуш multi-arch образа
buildah manifest push --all my-app:1.5.0 docker://registry.example.com/my-app:1.5.0
```

**Интеграция с Ansible:**
```yaml
- name: Multi-arch сборка образа
  hosts: localhost
  gather_facts: false
  vars:
    image_name: "my-app"
    image_tag: "1.5.0"
    registry: "registry.example.com"

  tasks:
    - name: Создание multi-arch манифеста
      ansible.builtin.command: >
        buildah manifest create {{ image_name }}:{{ image_tag }}
        --arch amd64
        --arch arm64
      changed_when: false

    - name: Сборка образа для amd64
      ansible.builtin.command: >
        buildah bud --arch amd64
        -t {{ image_name }}:{{ image_tag }}-amd64
        -f Containerfile ./context/
      changed_when: true

    - name: Сборка образа для arm64
      ansible.builtin.command: >
        buildah bud --arch arm64
        -t {{ image_name }}:{{ image_tag }}-arm64
        -f Containerfile ./context/
      changed_when: true

    - name: Добавление amd64 в манифест
      ansible.builtin.command: >
        buildah manifest add {{ image_name }}:{{ image_tag }}
        {{ image_name }}:{{ image_tag }}-amd64
        --arch amd64
      changed_when: false

    - name: Добавление arm64 в манифест
      ansible.builtin.command: >
        buildah manifest add {{ image_name }}:{{ image_tag }}
        {{ image_name }}:{{ image_tag }}-arm64
        --arch arm64
      changed_when: false

    - name: Пуш multi-arch образа
      ansible.builtin.command: >
        buildah manifest push --all {{ image_name }}:{{ image_tag }}
        docker://{{ registry }}/{{ image_name }}:{{ image_tag }}
      changed_when: true
```

## Контрольный список: лучшие практики

- [ ] **Безопасность секретов:** Пароли и ключи хранятся в `ansible-vault`, передаются через `template`/`copy`, удаляются перед `commit`
- [ ] **Идемпотентность:** Используйте ресурсные модули `containers.podman` вместо `command` там, где это возможно
- [ ] **Минимизация слоев:** Фиксируйте изменения одним `buildah commit` в конце плейбука
- [ ] **Не-root пользователь:** Указывайте `--user 1000:1000` или создавайте dedicated-пользователя в образе
- [ ] **Тегирование:** Всегда указывайте версию и дату сборки в labels (`version`, `build-date`)
- [ ] **Кэширование:** Монтируйте кэш пакетного менеджера с хоста для ускорения сборок в CI/CD
- [ ] **Верификация:** Проверяйте образ после сборки (размер, labels, entrypoint, порты, пользователь)
- [ ] **Cleanup:** Удаляйте рабочие контейнеры после фиксации (`buildah rm`)
- [ ] **Пиннинг версий:** Указывайте конкретную версию базового образа (`alpine:3.20`, не `alpine:latest`)
- [ ] **Linting:** Проходите `ansible-lint` перед коммитом плейбуков
- [ ] **Check mode:** Проверяйте `--check --diff` перед реальными изменениями
- [ ] **Rootless по умолчанию:** Используйте `buildah unshare` для сборок без прав root
- [ ] **Сканирование уязвимостей:** Интегрируйте Trivy/Grype в CI/CD
- [ ] **SBOM:** Генерируйте Software Bill of Materials для каждого образа
- [ ] **Подпись:** Подписывайте образы через cosign/notation перед публикацией
- [ ] **Хардениг:** Удаляйте кэш пакетов и временные файлы перед коммитом
- [ ] **Docs:** Описывайте назначение каждого образа через labels и README

## Дополнительная информация

### Оптимизация и кэширование

1. **Слои:** При использовании плагина `buildah` изменения фиксируются только при вызове `buildah commit`. Это позволяет создавать образы с минимальным количеством слоев (один слой на весь плейбук), что повышает производительность при скачивании.

2. **Storage driver:** Для rootless-сборок используйте `fuse-overlayfs`. Настройте `~/.config/containers/storage.conf` для использования этого драйвера по умолчанию.

3. **Кэш пакетов:** Для ускорения сборок в CI/CD рекомендуется монтировать кэш пакетного менеджера (например, `/var/cache/apk` или `/var/cache/dnf`) с хоста в рабочий контейнер через параметры `buildah run`.

4. **Кэширование pip/npm:** Используйте `--cache-dir` при установке зависимостей для повторного использования кэша между сборками.

5. **Распределенный кэш:** В CI/CD используйте `--cache-from`/`--cache-to` для распределенного кэширования слоев через registry.

6. **Reproducible builds:** Используйте `--timestamp 0` в `buildah manifest push` для получения детерминированных таймстемпов.

### Защита секретов

Никогда не используйте `ENV` или `ARG` в `Dockerfile` для передачи паролей. При использовании Ansible:

1. Храните секреты в `ansible-vault`.
2. Используйте модуль `ansible.builtin.template` для генерации конфигурационных файлов "на лету" внутри контейнера.
3. Если секрет нужен только в процессе установки (например, ключ SSH для доступа к приватному репозиторию), передавайте его как переменную и удаляйте временные файлы перед фиксацией образа (`buildah commit`).
4. Используйте `no_log: true` в задачах Ansible для скрытия секретов в логах.

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
| **Rootless** | Да (с Podman) | Да | Да | Да |
| **Multi-arch** | Buildx | Manifest + multi-build | Нет | Manifest + multi-build |

### Обновления и изменения в версиях

При обновлении Buildah до новых версий учитывайте:

1. **Buildah 1.44.0:** удалены cgroups v1, Slirp4netns и CNI. Добавлены `--metadata-file` и `--valid-exit-codes`. Добавлена поддержка сборки Windows-образов на Linux.

2. **Buildah 1.45.0:** добавлены `--no-follow-symlinks` для COPY/ADD, `--timestamp 0` для manifest push, символический chmod, новые SFTP/SSHFS CLI команды. Репозиторий перенесен с `containers/buildah` на `podman-container-tools/buildah`.

3. **containers.conf:** изменилось поведение конфигурационного файла. Ознакомьтесь с `containers-config(5)` для деталей.

### Смотрите также

*   **[Buildah: Концепции и практика](../Podman/buildah_overview.md)** — подробный разбор CLI-команд Buildah и механизмов монтирования.
*   **[Сравнение Podman и Docker](../Podman/podman_vs_docker.md)** — выбор инструмента для сборки.
*   **[Daemonless-архитектура](../Podman/podman_daemonless_architecture.md)** — принципы работы без демона.
*   **[Обнаружение проблем с образами в Kubernetes](../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/common_errors.md)** — типичные ошибки при работе с образами.
