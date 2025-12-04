# Продвинутое управление Docker с Ansible

В этом руководстве рассматривается сложный, но реалистичный сценарий CI/CD: сборка Docker-образов на выделенном "сборочном" хосте и их последующее развертывание на "рабочем" хосте. Мы будем использовать несколько продвинутых техник Ansible, включая делегирование задач, циклы, теги и различные модули из коллекции `community.docker`.

**Цели:**
1.  Понять, как разделить процесс сборки и развертывания в Ansible.
2.  Научиться использовать `delegate_to` для выполнения задач на разных хостах.
3.  Освоить модули `docker_image` для сборки, архивации и загрузки образов.
4.  Использовать `fetch` для перемещения артефактов.
5.  Применять циклы `loop` и `until` для автоматизации повторяющихся действий и проверок.

---

## Сценарий

У нас есть два типа хостов в инвентаре:
-   `build-host`: Машина с доступом к исходному коду (Dockerfile) и установленным Docker SDK. Здесь мы будем собирать образы.
-   `run-host`: Машина, где должны запускаться контейнеры.

**План плейбука:**
1.  **[Тег: build]** На `build-host`:
    *   Найти все `Dockerfile` в локальной директории проекта (используя `delegate_to: localhost`).
    *   Скопировать найденные директории с `Dockerfile` на `build-host`.
    *   Собрать Docker-образы из каждого `Dockerfile` с помощью `community.docker.docker_image`.
    *   Заархивировать собранные образы в `.tar` файлы.
    *   Забрать (`fetch`) `.tar` архивы с `build-host` на контрольный узел.
2.  **[Тег: deploy]** На `run-host`:
    *   Скопировать `.tar` архивы с контрольного узла.
    *   Загрузить образы в локальный Docker daemon из архивов.
    *   Запустить контейнеры из загруженных образов.
3.  **[Тег: health_check]** На `run-host`:
    *   Убедиться, что все контейнеры успешно запустились, используя цикл `until`.

---

## Плейбук и разбор задач

### Play 1: Сборка образов на `build-host`

```yaml
- name: Build Docker Images
  hosts: build-host
  gather_facts: false
  tags: build

  tasks:
    - name: 1. Find Dockerfile directories on localhost
      ansible.builtin.find:
        paths: "{{ playbook_dir }}/files/dockerfiles"
        file_type: directory
      register: dockerfile_dirs
      delegate_to: localhost

    - name: 2. Create build directory on build-host
      ansible.builtin.file:
        path: /build
        state: directory

    - name: 3. Copy Dockerfile directories to build-host
      ansible.builtin.copy:
        src: "{{ item.path }}/"
        dest: "/build/{{ item.path | basename }}"
      loop: "{{ dockerfile_dirs.files }}"

    - name: 4. Build and Archive Docker images
      ansible.builtin.include_tasks: tasks/build_and_archive.yml
      loop: "{{ dockerfile_dirs.files }}"
      loop_control:
        loop_var: build_dir
```

**Разбор:**
- **Задача 1:** С помощью `delegate_to: localhost` мы ищем директории с `Dockerfile` не на `build-host`, а на машине, где запущен `ansible-playbook`. Результат (`dockerfile_dirs`) будет доступен для `build-host`.
- **Задачи 3 и 4:** Мы используем `loop` для итерации по списку найденных директорий. Для каждой директории копируем ее на `build-host`, а затем включаем отдельный файл с задачами `build_and_archive.yml`. Это необходимо, чтобы выполнить несколько действий в цикле.

### Файл `tasks/build_and_archive.yml`

```yaml
- name: Build docker image from {{ build_dir.path | basename }}
  community.docker.docker_image:
    name: "my-app/{{ build_dir.path | basename }}"
    tag: "1.0"
    build:
      path: "/build/{{ build_dir.path | basename }}"
    source: build
  register: image_build_result

- name: Archive image to a .tar file
  community.docker.docker_image:
    name: "my-app/{{ build_dir.path | basename }}:1.0"
    archive_path: "/build/{{ build_dir.path | basename }}.tar"
    source: pull # 'pull' is a bit misleading, it just means use the local image
  when: image_build_result is changed

- name: Fetch the .tar archive to the control node
  ansible.builtin.fetch:
    src: "/build/{{ build_dir.path | basename }}.tar"
    dest: "{{ playbook_dir }}/artifacts/"
    flat: yes # Сохраняет файл без создания поддиректорий с именем хоста
  when: image_build_result is changed
```
**Разбор:**
- **`docker_image` (сборка):** Мы используем `source: build` и указываем `path` к `Dockerfile`.
- **`docker_image` (архивация):** Тот же модуль, но с параметром `archive_path`, сохраняет существующий локальный образ в `.tar` файл.
- **`fetch`:** Этот модуль является "обратным" `copy` — он забирает файлы с удаленного хоста на контрольный узел.

### Play 2: Развертывание образов на `run-host`

```yaml
- name: Deploy and Run Docker Containers
  hosts: run-host
  gather_facts: false
  tags: deploy

  tasks:
    - name: 1. Find local .tar archives
      ansible.builtin.find:
        paths: "{{ playbook_dir }}/artifacts"
        patterns: "*.tar"
      register: tar_archives
      delegate_to: localhost

    - name: 2. Load and Run containers
      ansible.builtin.include_tasks: tasks/load_and_run.yml
      loop: "{{ tar_archives.files }}"
      loop_control:
        loop_var: archive_file
```

### Файл `tasks/load_and_run.yml`

```yaml
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
```
**Разбор:**
- **`docker_image` (загрузка):** Используем `source: load` и `load_path` для загрузки образа из `.tar` архива.
- **Jinja2 фильтры:** Мы активно используем фильтры `basename` и `split` для извлечения имени образа из пути к файлу.
- **`docker_container`:** Запускает контейнер из только что загруженного образа.

### Play 3: Проверка состояния (`health_check`)

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
**Разбор:**
- **`docker_host_info`:** Собирает информацию о Docker на хосте.
- **`until`:** Задача будет повторяться (`retries: 5`) с паузой (`delay: 10`), пока условие не станет истинным. Условие `docker_info.containers | length == 2` проверяет, что в списке запущенных контейнеров теперь 2 элемента.

Этот пример демонстрирует, как можно оркестрировать сложные рабочие процессы с помощью Ansible, выходя за рамки простой настройки конфигурации.

---

## Пример 2: Сборка и запуск контейнеров с разделением логики

Этот пример показывает более простой подход к сборке и запуску Docker-контейнеров с помощью Ansible. Логика разделена на два шага, которые импортируются в основной плейбук:

1.  **Сборка контейнера**: На `build_host` происходит сборка Docker-образа и его сохранение в архив.
2.  **Запуск контейнера**: На `runner_host` архив с образом загружается и из него запускается контейнер.

Этот подход использует `docker` и `docker-sdk` на целевых машинах.

### Основной плейбук `docker-playbook.yml`

```yaml
---
- name: Copy files and build them
  hosts: build_host
  tasks:
    - include_tasks: container_assembly.yml

- name: Load images and run them
  hosts: runner_host
  tasks:
    - include_tasks: container_load.yml

- name: Healthcheck
  hosts: runner_host
  tasks:
    - name: Check web server
      uri:
        url: "http://{{ ansible_host }}:8080"
      register: result
      until: result.status == 200
      retries: 5
      delay: 5
```

### Шаг 1: Сборка контейнера (`container_assembly.yml`)

Этот файл задач отвечает за сборку Docker-образа для каждого Dockerfile и последующее создание архива для передачи на другой хост.

```yaml
---
# tasks for container_assembly.yml

- name: Build web container
  community.docker.docker_image:
    name: web_container
    tag: v1.0
    build:
      path: ./web/
    source: build

- name: Build db container
  community.docker.docker_image:
    name: db_container
    tag: v1.0
    build:
      path: ./db/
    source: build

- name: Archive web container
  community.docker.docker_image:
    name: web_container
    tag: v1.0
    archive_path: ./web_container.tar
    source: pull

- name: Archive db container
  community.docker.docker_image:
    name: db_container
    tag: v1.0
    archive_path: ./db_container.tar
    source: pull
```

### Шаг 2: Запуск контейнера (`container_load.yml`)

Этот файл задач копирует архивы на целевой хост, загружает из них образы и запускает контейнеры.

```yaml
---
# tasks for container_load.yml

- name: Copy web container archive
  copy:
    src: ./web_container.tar
    dest: ./web_container.tar

- name: Load web container
  community.docker.docker_image:
    name: web_container
    tag: v1.0
    load_path: ./web_container.tar
    source: load

- name: Run web container
  community.docker.docker_container:
    name: web_app
    image: web_container:v1.0
    state: started
    ports:
      - "80:8080"

# Аналогичные шаги для db_container...
```

### Проверка запущенных контейнеров

После выполнения плейбука можно проверить запущенные контейнеры на `runner_host`:

```bash
sudo docker ps
```

Ожидаемый вывод:

```
CONTAINER ID   IMAGE                COMMAND                  CREATED          STATUS          PORTS                NAMES
ca9cc7f2a851   web_container:v1.0   "/bin/sh -c 'nc -l..."   26 seconds ago   Up 22 seconds   0.0.0.0:80->8080/tcp   web_app
5288521862b6   db_container:v1.0    "/bin/sh -c 'nc -l..."   12 seconds ago   Up 11 seconds   8080/tcp             db_app
```

Этот пример иллюстрирует, как можно разделить логику сборки и развертывания на логические шаги, используя `include_tasks` для чистоты и переиспользуемости кода.
