# Ansible: Управление Docker

## Определения

**Управление Docker с помощью Ansible** — автоматизация жизненного цикла Docker-контейнеров: сборка образов, распространение и запуск на целевых хостах через плейбуки Ansible.

## Базовые концепции

### Архитектура развертывания

| Роль хоста | Назначение |
|---|---|
| `build-host` | Сборка Docker-образов из Dockerfile (требуется Docker Software Development Kit (SDK)) |
| `run-host` | Запуск контейнеров на основе готовых образов |
| `control-node` | Узел Ansible: координация, хранение артефактов |

### Жизненный цикл Build-Ship-Run

1. **Build** (Сборка) — сборка образа из Dockerfile на `build-host`
2. **Ship** (Доставка) — архивация образа в `.tar` и передача на `run-host` через контрольный узел
3. **Run** (Запуск) — загрузка образа в Docker и запуск контейнера на `run-host`

### Ключевые модули

Для управления Docker в Ansible используется коллекция `community.docker`.

| Модуль | Назначение | Параметры |
|---|---|---|
| `community.docker.docker_image` | Работа с образами | `source: build` (сборка), `source: pull` (архивация), `source: load` (загрузка) |
| `community.docker.docker_container` | Управление контейнерами | `state: started/stopped/absent`, `restart_policy`, `ports` |
| `ansible.builtin.fetch` | Копирование файлов с удаленного хоста на контрольный узел | `src`, `dest`, `flat` |
| `ansible.builtin.copy` | Копирование файлов с контрольного узла на удаленный хост | `src`, `dest` |

### Делегирование задач

`delegate_to: localhost` выполняет задачу на контрольном узле Ansible, а не на целевом хосте из `hosts`. Применяется для:

- Поиска файлов локально (`find`)
- Подготовки артефактов перед отправкой
- Промежуточного хранения данных

---

## Практические сценарии

### Сценарий: Полный цикл сборки и развертывания

**Структура проекта:**

```
.
├── files/
│   └── dockerfiles/
│       ├── webapp/
│       │   └── Dockerfile
│       └── database/
│           └── Dockerfile
├── artifacts/
└── docker-playbook.yml
```

**Плейбук `docker-playbook.yml`:**

```yaml
---
- name: Build Docker images
  hosts: build-host
  gather_facts: false
  tags: build

  tasks:
    - name: Find Dockerfile directories on control node
      ansible.builtin.find:
        paths: "{{ playbook_dir }}/files/dockerfiles"
        file_type: directory
      register: dockerfile_dirs
      delegate_to: localhost

    - name: Create build and archive directories
      ansible.builtin.file:
        path: "{{ item }}"
        state: directory
      loop:
        - /build
        - /archives

    - name: Build and archive each image
      loop: "{{ dockerfile_dirs.files }}"
      loop_control:
        loop_var: dockerfile_dir
      block:
        - name: Copy Dockerfile context to build-host
          ansible.builtin.copy:
            src: "{{ dockerfile_dir.path }}/"
            dest: "/build/{{ dockerfile_dir.path | basename }}"

        - name: Build Docker image
          community.docker.docker_image:
            name: "my-app/{{ dockerfile_dir.path | basename }}"
            tag: "1.0"
            build:
              path: "/build/{{ dockerfile_dir.path | basename }}"
            source: build
          register: image_build_result

        - name: Archive image to .tar file
          community.docker.docker_image:
            name: "my-app/{{ dockerfile_dir.path | basename }}:1.0"
            archive_path: "/archives/{{ dockerfile_dir.path | basename }}.tar"
            source: pull
          when: image_build_result.changed

        - name: Fetch archive to control node
          ansible.builtin.fetch:
            src: "/archives/{{ dockerfile_dir.path | basename }}.tar"
            dest: "{{ playbook_dir }}/artifacts/"
            flat: yes
          when: image_build_result.changed

- name: Deploy Docker containers
  hosts: run-host
  gather_facts: false
  tags: deploy

  tasks:
    - name: Find local .tar archives
      ansible.builtin.find:
        paths: "{{ playbook_dir }}/artifacts"
        patterns: "*.tar"
      register: tar_archives
      delegate_to: localhost

    - name: Load and run each container
      loop: "{{ tar_archives.files }}"
      loop_control:
        loop_var: archive_file
      block:
        - name: Copy archive to run-host
          ansible.builtin.copy:
            src: "{{ archive_file.path }}"
            dest: "/tmp/{{ archive_file.path | basename }}"

        - name: Load image from archive
          community.docker.docker_image:
            name: "my-app/{{ (archive_file.path | basename).split('.')[0] }}"
            tag: "1.0"
            load_path: "/tmp/{{ archive_file.path | basename }}"
            source: load

        - name: Run container
          community.docker.docker_container:
            name: "{{ (archive_file.path | basename).split('.')[0] }}-app"
            image: "my-app/{{ (archive_file.path | basename).split('.')[0] }}:1.0"
            state: started
            restart_policy: always
            ports:
              - "8080:80"
```

---

### Сценарий: Проверка состояния (Health Check)

**Проверка количества запущенных контейнеров:**

```yaml
- name: Health Check
  hosts: run-host
  gather_facts: false
  tags: health_check

  tasks:
    - name: Check running containers
      community.docker.docker_host_info:
      register: docker_info
      until: "docker_info.containers | length == 2"
      retries: 5
      delay: 10
```

**Проверка доступности веб-сервиса:**

```yaml
- name: Healthcheck web server
  hosts: run-host
  tasks:
    - name: Check web server endpoint
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}:8080"
      register: result
      until: result.status == 200
      retries: 5
      delay: 5
```

---

## Дополнительная информация

- **Коллекция Docker:** Модули `community.docker.*` требуют установки коллекции — `ansible-galaxy collection install community.docker`
- **Docker Compose:** Управление compose-файлами через модуль [`community.docker.docker_compose`](https://docs.ansible.com/ansible/latest/collections/community/docker/docker_compose_module.html)
- **Безопасность:** Рекомендации по изоляции контейнеров — [Docker/Docker_security/overview.md](../../Docker/Docker_security/overview.md)
- **Реестры образов:** Работа с Docker Registry — [Docker/docker_registries.md](../../Docker/docker_registries.md)
- **Альтернативы:** [Сборка образов с Buildah и Ansible](../ansible_buildah_image_building.md)
