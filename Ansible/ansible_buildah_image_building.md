# Сборка образов: Buildah и Ansible

## Определения

**Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, полностью соответствующих стандартам **OCI (Open Container Initiative)**. Он спроектирован для работы без фонового демона (**daemonless**) и без необходимости предоставления привилегий root (**rootless**).

**Плагин соединения buildah (`containers.podman.buildah`)** — современный и официально поддерживаемый способ использования Ansible для сборки образов. Он позволяет Ansible "монтировать" рабочий контейнер Buildah и выполнять в нем задачи напрямую, обходясь без SSH-сервера внутри образа.

**Ansible-bender** — устаревшая утилита-мост (legacy). Проект не имеет активного мейнтейнера, поэтому для новых проектов строго рекомендуется использовать связку `buildah` + `podman` коллекции.

## Основные концепции

Использование Ansible для сборки OCI-образов предоставляет критические преимущества перед классическими `Dockerfile`:

*   **Идемпотентность** — гарантия того, что повторная сборка не внесет изменений, если целевое состояние (пакеты, конфиги) уже достигнуто.
*   **Переиспользование ролей** — возможность применять одни и те же проверенные роли Ansible (например, установку Nginx или настройку PHP) как для конфигурации виртуальных машин, так и для сборки неизменяемых (immutable) контейнеров.
*   **Сложная логика и защита секретов** — использование циклов, шаблонов Jinja2 и Ansible Vault (для передачи секретов без их сохранения в слоях образа), что практически невозможно реализовать в стандартном синтаксисе Dockerfile.

## Практические сценарии

### 1. Использование плагина соединения Buildah (рекомендуемый способ)

Это наиболее мощный метод. При использовании **rootless-режима** запуск плейбука необходимо оборачивать в `buildah unshare`, чтобы Ansible получил доступ к нужному user namespace.

**Команда запуска:**
```bash
buildah unshare ansible-playbook build_image.yml
# → PLAY [Подготовка рабочего контейнера] ...
```

**Плейбук (`build_image.yml`):**
```yaml
---
- name: Подготовка рабочего контейнера
  hosts: localhost
  tasks:
    - name: Создать рабочий контейнер из базового образа
      ansible.builtin.command: buildah from alpine:latest
      register: container
      changed_when: false # Инициализация не является изменением конфигурации

    - name: Добавить контейнер во временный инвентарь
      ansible.builtin.add_host:
        name: "temp_container"
        ansible_connection: containers.podman.buildah
        ansible_buildah_container: "{{ container.stdout }}"

- name: Настройка окружения внутри контейнера
  hosts: temp_container
  tasks:
    - name: Установить nginx
      ansible.builtin.apk:
        name: nginx
        state: present

    - name: Копировать конфигурацию из шаблона
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf

- name: Фиксация и очистка
  hosts: localhost
  tasks:
    - name: Сохранить изменения в новый OCI-образ
      ansible.builtin.command: >
        buildah commit {{ hostvars['temp_container']['ansible_buildah_container'] }} my-nginx-image
      # В реальном сценарии идемпотентность проверяется через подпись/теги
      
    - name: Удалить временный рабочий контейнер
      ansible.builtin.command: >
        buildah rm {{ hostvars['temp_container']['ansible_buildah_container'] }}
      changed_when: false
```

### 2. Сборка из Containerfile через podman_image

Если у вас уже есть `Dockerfile` или `Containerfile`, используйте модуль `podman_image` из коллекции `containers.podman`.

```yaml
- name: Сборка образа из файла
  containers.podman.podman_image:
    name: my-app
    path: ./build_context/
    dockerfile: Containerfile
    state: build
```

### 3. Нативная сборка через Buildah CLI (Shell)

Минималистичный подход для простых образов, не требующий установки дополнительных коллекций Ansible.

```yaml
- name: Сборка через прямые вызовы CLI
  hosts: localhost
  tasks:
    - name: Инициализация контейнера
      ansible.builtin.shell: buildah from fedora
      register: c

    - name: Установка софта
      ansible.builtin.shell: buildah run {{ c.stdout }} -- dnf install -y httpd

    - name: Настройка конфигурации
      ansible.builtin.shell: buildah config --port 80 {{ c.stdout }}

    - name: Коммит образа
      ansible.builtin.shell: buildah commit {{ c.stdout }} my-httpd
```

### 4. Использование Ansible-bender (legacy)

Хотя инструмент устарел, он все еще встречается в старых проектах (до 2023 года). Сборка запускается внешней командой поверх плейбука.

```bash
ansible-bender build playbook.yml my-image-name
# → ... Image my-image-name was built successfully
```

Конфигурация описывается в секции `vars` плейбука под ключом `ansible_bender`.

## Дополнительная информация

При выборе стратегии сборки учитывайте следующее:
1.  **Сложность:** Для простых задач (копирование бинарника) достаточно `podman_image` и `Dockerfile`.
2.  **Гибкость:** Если нужно устанавливать много пакетов и настраивать конфиги через сложные шаблоны, используйте плагин соединения `containers.podman.buildah`.
3.  **Безопасность:** Buildah позволяет собирать образы полностью в userspace (безрутовый режим через `buildah unshare`), что идеально для безопасных CI/CD-пайплайнов в Kubernetes (замена небезопасного DinD).

### Смотрите также

*   [Buildah: Концепции и практика](../Podman/buildah_overview.md) — подробное описание CLI-команд Buildah и Rootless-режима.
*   [Сравнение Podman и Docker](../Podman/podman_vs_docker.md) — фундаментальные архитектурные различия.
*   [Кроссплатформенные плейбуки Ansible](./CrossPlatform/concepts.md) — паттерны использования одних и тех же ролей для ВМ и контейнеров.
