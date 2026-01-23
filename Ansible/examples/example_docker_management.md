# Управление Docker с помощью Ansible

## Определения

**Управление Docker с помощью Ansible** — это процесс автоматизации жизненного цикла Docker-контейнеров, включая сборку образов, их распространение и запуск на целевых хостах с использованием плейбуков Ansible. Это позволяет создавать воспроизводимые и надежные окружения.

## Основные концепции

Для эффективного управления Docker-контейнерами в Ansible применяется несколько ключевых подходов и модулей.

-   **Разделение ролей хостов**:
    -   `build-host`: Выделенная машина с доступом к исходному коду (Dockerfile) и установленным Docker SDK. Её задача — исключительно сборка Docker-образов.
    -   `run-host`: Целевая машина, на которой будут запускаться контейнеры.

-   **Жизненный цикл образа (Build-Ship-Run)**:
    1.  **Сборка (Build)**: На `build-host` из Dockerfile создается образ.
    2.  **Архивация и передача (Ship)**: Собранный образ упаковывается в `.tar` архив и передается на `run-host` (обычно через контрольный узел Ansible).
    3.  **Загрузка и запуск (Run)**: На `run-host` образ загружается из архива в локальный Docker-демон и на его основе запускается контейнер.

-   **Ключевые модули Ansible**:
    -   `community.docker.docker_image`: Универсальный модуль для работы с образами.
        -   `source: build`: Собирает образ из Dockerfile.
        -   `source: pull`: Используется для сохранения локального образа в архив (`archive_path`).
        -   `source: load`: Загружает образ из архива (`load_path`).
    -   `community.docker.docker_container`: Управляет жизненным циклом контейнеров (создание, запуск, остановка).
    -   `ansible.builtin.fetch`: Забирает файлы с удаленного хоста на контрольный узел Ansible.
    -   `ansible.builtin.copy`: Копирует файлы с контрольного узла на удаленный хост.

-   **Делегирование задач**:
    -   `delegate_to: localhost`: Позволяет выполнить задачу локально на контрольном узле Ansible, а не на целевом хосте, указанном в `hosts`. Это удобно для поиска файлов или подготовки артефактов перед их отправкой.

## Практические сценарии

### Сценарий: Полный цикл сборки и развертывания

Этот плейбук демонстрирует полный процесс: поиск Dockerfile на локальной машине, сборка образов на `build-host`, передача их через контрольный узел и развертывание на `run-host`.

**Структура проекта:**

```
.
├── files/
│   └── dockerfiles/
│       ├── webapp/
│       │   └── Dockerfile
│       └── database/
│           └── Dockerfile
├── artifacts/  (будет создана)
└── docker-playbook.yml
```

**Основной плейбук `docker-playbook.yml`:**

```yaml
---
- name: Build, Archive, and Fetch Docker Images
  hosts: build-host
  gather_facts: false
  tags: build

  tasks:
    - name: Find Dockerfile directories on the control node
      ansible.builtin.find:
        paths: "{{ playbook_dir }}/files/dockerfiles"
        file_type: directory
      register: dockerfile_dirs
      delegate_to: localhost

    - name: Create build and archive directories on build-host
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

        - name: Build docker image
          community.docker.docker_image:
            name: "my-app/{{ dockerfile_dir.path | basename }}"
            tag: "1.0"
            build:
              path: "/build/{{ dockerfile_dir.path | basename }}"
            source: build
          register: image_build_result

        - name: Archive image to a .tar file
          community.docker.docker_image:
            name: "my-app/{{ dockerfile_dir.path | basename }}:1.0"
            archive_path: "/archives/{{ dockerfile_dir.path | basename }}.tar"
            source: pull
          when: image_build_result.changed

        - name: Fetch the .tar archive to the control node
          ansible.builtin.fetch:
            src: "/archives/{{ dockerfile_dir.path | basename }}.tar"
            dest: "{{ playbook_dir }}/artifacts/"
            flat: yes
          when: image_build_result.changed

- name: Deploy and Run Docker Containers
  hosts: run-host
  gather_facts: false
  tags: deploy

  tasks:
    - name: Find local .tar archives on the control node
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
        - name: Copy .tar archive to run-host
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
              - "8080:80" # Пример проброса порта
```

## Дополнительная информация

### Проверка состояния (Health Check)

После развертывания важно убедиться, что контейнеры работают корректно. Это можно сделать с помощью цикла `until`.

**Пример 1: Проверка количества запущенных контейнеров**

```yaml
- name: Health Check
  hosts: run-host
  gather_facts: false
  tags: health_check

  tasks:
    - name: Check that all containers are running
      community.docker.docker_host_info:
      register: docker_info
      until: "docker_info.containers | length == 2" # Проверяем, что запущено 2 контейнера
      retries: 5
      delay: 10
```

**Пример 2: Проверка доступности веб-сервиса**

Если контейнер запускает веб-сервис, можно проверить его доступность по HTTP.

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