# Сборка OCI-образов с помощью Ansible и Buildah

## Определения

**Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, полностью соответствующих стандартам **OCI (Open Container Initiative)**. Он спроектирован для работы без фонового демона (**daemonless**) и поддерживает полноценный безрутовый режим (**rootless**).

**Плагин соединения buildah (`containers.podman.buildah`)** — современный и официально поддерживаемый способ использования Ansible для сборки образов. Он позволяет Ansible "монтировать" рабочий контейнер Buildah и выполнять в нем задачи напрямую через драйвер файловой системы, обходясь без SSH-сервера или установленного Python внутри образа.

**Ansible-builder** — специализированный инструмент для сборки **[Execution Environments (EE)](./ansible-execution-environments.md)**.

**Ansible-bender** — устаревшая утилита-мост (legacy). Проект признан архивным и не рекомендуется для новых разработок. Для сборки образов на базе плейбуков следует использовать плагин соединения `buildah`.

## Основные концепции

Использование Ansible в связке с Buildah предоставляет критические преимущества перед классическими `Dockerfile`:

*   **Идемпотентность** — гарантия того, что повторный запуск сборки не внесет изменений в слои, если целевое состояние конфигурации уже достигнуто.
*   **Переиспользование кода** — возможность применять одни и те же проверенные роли Ansible (например, по харденингу ОС или настройке мониторинга) как для инфраструктуры (ВМ, Bare Metal), так и для сборки неизменяемых (immutable) контейнеров.
*   **Безопасность секретов** — использование **Ansible Vault** позволяет передавать пароли, ключи и сертификаты в процессе сборки без их сохранения в метаданных или слоях итогового образа.
*   **Сложная логика сборки** — использование циклов, условий, шаблонов Jinja2 и динамического получения данных из внешних API (например, NetBox или Vault) на этапе генерации образа.

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

### 4. Создание Execution Environments (EE)

Для специализированной сборки сред выполнения Ansible рекомендуется использовать утилиту **ansible-builder**. Она автоматизирует создание образов с учетом зависимостей коллекций, Python и системных пакетов.

Подробное руководство: **[Ansible Execution Environments — глубокое погружение](./ansible-execution-environments.md)**.

## Дополнительная информация


### Оптимизация и кэширование
1.  **Слои:** При использовании плагина `buildah` изменения фиксируются только при вызове `buildah commit`. Это позволяет создавать образы с минимальным количеством слоев (один слой на весь плейбук), что повышает производительность при скачивании.
2.  **Кэш пакетов:** Для ускорения сборок в CI/CD рекомендуется монтировать кэш пакетного менеджера (например, `/var/cache/apk` или `/var/cache/dnf`) с хоста в рабочий контейнер через параметры `buildah run`.

### Защита секретов
Никогда не используйте `ENV` или `ARG` в `Dockerfile` для передачи паролей. При использовании Ansible:
1.  Храните секреты в `ansible-vault`.
2.  Используйте модуль `ansible.builtin.template` для генерации конфигурационных файлов "на лету" внутри контейнера.
3.  Если секрет нужен только в процессе установки (например, ключ SSH для доступа к приватному репозиторию), передавайте его как переменную и удаляйте временные файлы перед фиксацией образа (`buildah commit`).

### Сравнение подходов

| Критерий | Podman Build (Dockerfile) | Ansible + Buildah Plugin | Ansible-builder (EE) |
| :--- | :--- | :--- | :--- |
| **Гибкость логики** | Низкая (Shell скрипты) | Высокая (Модули, YAML) | Средняя (Конфиг YAML) |
| **Идемпотентность** | На уровне слоев | На уровне каждой задачи | На уровне сборки целиком |
| **Слои образа** | Много (на каждую команду) | Минимум (ручной коммит) | Много |
| **Применение** | Стандартные приложения | Сложная инфраструктура | Инфраструктура Ansible |

### Смотрите также

*   **[Buildah: Концепции и практика](../Podman/buildah_overview.md)** — подробный разбор CLI-команд Buildah и механизмов монтирования.
*   **[Сравнение Podman и Docker](../Podman/podman_vs_docker.md)** — архитектурные различия и почему Buildah важен для Podman.
*   **[Кроссплатформенные плейбуки Ansible](./CrossPlatform/concepts.md)** — стратегии написания ролей для разных типов таргетов.
