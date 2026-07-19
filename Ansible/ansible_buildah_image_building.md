# Сборка образов: Buildah и Ansible

## Определения

**Buildah** — инструмент командной строки для сборки образов контейнеров, соответствующих стандартам **OCI (Open Container Initiative)**. Работает без фонового демона (daemonless) и не требует привилегий root.

**Ansible-bender** — устаревшая утилита-мост, позволяющая описывать сборку образа через плейбуки Ansible.
*   **Статус:** Проект не имеет активного мейнтейнера с 2023 года. Рекомендуется использовать плагин соединения `buildah`.

**Плагин соединения buildah (containers.podman.buildah)** — современный и поддерживаемый способ использования Ansible для сборки образов. Позволяет Ansible подключаться напрямую к рабочему контейнеру Buildah и выполнять в нем задачи.

## Основные концепции

Использование Ansible для сборки образов предоставляет ряд преимуществ перед стандартными `Dockerfile`:

*   **Идемпотентность** — гарантия того, что повторная сборка не внесет изменений, если состояние уже достигнуто.
*   **Переиспользование ролей** — возможность применять одни и те же роли Ansible как для настройки виртуальных машин, так и для сборки контейнеров.
*   **Сложная логика** — использование циклов, условий и шаблонов Jinja2, которые ограничены в стандартном синтаксисе Dockerfile.

## Практические сценарии

### 1. Использование плагина соединения Buildah (рекомендуемый способ)

Это наиболее гибкий метод, позволяющий использовать любые модули Ansible внутри контейнера.

```yaml
- name: Подготовка рабочего контейнера
  hosts: localhost
  tasks:
    - name: Создать рабочий контейнер из базового образа
      ansible.builtin.command: buildah from alpine
      register: container

    - name: Добавить контейнер в инвентарь
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

- name: Фиксация образа
  hosts: localhost
  tasks:
    - name: Сохранить изменения в новый образ
      ansible.builtin.command: >
        buildah commit {{ hostvars['temp_container']['ansible_buildah_container'] }} my-nginx-image
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

Хотя инструмент устарел, он все еще встречается в старых проектах. Сборка запускается внешней командой:

```bash
ansible-bender build playbook.yml my-image-name
```

Конфигурация описывается в секции `vars` плейбука под ключом `ansible_bender`.

## Дополнительная информация

При выборе стратегии сборки учитывайте следующее:
1.  **Сложность:** Для простых задач (копирование бинарника) достаточно `podman_image` и `Dockerfile`.
2.  **Гибкость:** Если нужно устанавливать много пакетов и настраивать конфиги через сложные шаблоны — используйте **плагин соединения buildah**.
3.  **Безопасность:** Buildah позволяет собирать образы полностью в userspace, что идеально для CI/CD в Kubernetes (без DinD).

### Смотрите также

*   [Buildah: Концепции и практика](../Podman/buildah_overview.md) — подробное описание CLI-команд.
*   [Podman: Управление образами](../Podman/podman_vs_docker.md) — сравнение с Docker.
*   [Переменные в Ansible](PlaybookStructure/variables.md) — использование динамических данных при сборке.
