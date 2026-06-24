# Тестирование ролей Ansible с помощью Molecule

## Определения

**Molecule** — это фреймворк для автоматизированного тестирования [ролей](ansible_roles.md) и плейбуков Ansible. Он позволяет создавать временные, изолированные окружения (с помощью Docker, Vagrant, облачных провайдеров), применять к ним ваш код и проверять, что он работает корректно. Это ключевой инструмент для внедрения практик CI/CD в разработку Ansible-автоматизации.

## Основные концепции

### Зачем нужен Molecule?

Тестирование сложной роли вручную требует: поднятия тестовых серверов, запуска плейбука, ручной проверки и повторения для разных ОС. Molecule автоматизирует этот процесс, позволяя:

* **Инициализировать роль** со всей необходимой тестовой обвязкой.
* **Интегрироваться в CI/CD пайплайны** (GitLab CI, Jenkins) для автоматического прогона тестов при каждом коммите.
* **Создавать и уничтожать тестовые окружения** на лету, используя различные "драйверы".
* **Проводить линтинг** кода (например, с помощью `ansible-lint`), как один из шагов тестирования.

### Жизненный цикл тестирования

`molecule test` запускает полный, последовательный цикл тестирования, который включает следующие основные шаги:

1. `dependency`: Установка зависимостей роли из `meta/main.yml`.
2. `lint`: Проверка кода статическим анализатором.
3. `create`: Создание тестового инстанса (например, Docker-контейнера).
4. `prepare`: Выполнение подготовительного плейбука `prepare.yml` (если он есть).
5. `converge`: Запуск основного плейбука `converge.yml`, который применяет тестируемую роль.
6. `idempotence`: Повторный запуск `converge.yml` для проверки идемпотентности (не должно быть `changed` задач).
7. `verify`: Запуск плейбука `verify.yml` с тестами для проверки состояния системы.
8. `destroy`: Уничтожение тестового инстанса.

Для отладки каждый шаг можно запускать отдельно (например, `molecule converge`, `molecule login`, `molecule verify`).

### Установка

Molecule является Python-пакетом и устанавливается через `pip`. Рекомендуется устанавливать его вместе с драйвером (например, Docker) и линтером.

```bash
# Установка Molecule с поддержкой Docker и ansible-lint
pip install "molecule[docker,lint]"
```

> **Примечание о версиях:** Molecule тесно связан с версией Ansible. При ошибках совместимости может потребоваться установка конкретной версии: `pip install molecule==X.Y.Z`.

## Практические сценарии

### Полный цикл тестирования роли

#### Шаг 1: Инициализация роли

Команда `molecule init role` создает новую роль со стандартной структурой и тестовым сценарием `default`.

```bash
molecule init role nginx
cd nginx
```

Это создаст директорию `nginx/` и поддиректорию `molecule/default/` со всеми необходимыми файлами.

#### Шаг 2: Настройка сценария (`molecule/default/molecule.yml`)

Это главный файл конфигурации теста. Укажем Docker-образ, который будем использовать.

```yaml
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: instance
    image: "geerlingguy/docker-ubuntu2004-ansible:latest"
    pre_build_image: true
provisioner:
  name: ansible
verifier:
  name: ansible
```

#### Драйвер Docker: `create.yml` и `destroy.yml`

Для драйвера `docker` Molecule использует `create.yml` для создания контейнера и `destroy.yml` для его удаления. Эти файлы не создаются `molecule init role` по умолчанию — их нужно написать вручную, если требуется Docker-драйвер без SSH и systemd (как в образах `geerlingguy`).

**`molecule/default/create.yml`:**

```yaml
---
- name: Create
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    molecule_platforms: "{{ molecule_yml.platforms }}"
  tasks:
    - name: Create molecule instance(s)
      community.docker.docker_container:
        name: "{{ item.name }}"
        hostname: "{{ item.name }}"
        image: "{{ item.image }}"
        state: started
        privileged: "{{ item.privileged | default(false) }}"
        volumes: "{{ item.volumes | default([]) }}"
        command: "{{ item.command | default(omit) }}"
        cgroupns_mode: "{{ item.cgroupns_mode | default(omit) }}"
        detach: true
      loop: "{{ molecule_platforms }}"
```

**`molecule/default/destroy.yml`:**

```yaml
---
- name: Destroy
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    molecule_platforms: "{{ molecule_yml.platforms }}"
  tasks:
    - name: Destroy molecule instance(s)
      community.docker.docker_container:
        name: "{{ item.name }}"
        state: absent
        force_kill: true
      loop: "{{ molecule_platforms }}"
```

#### Шаг 3: Написание логики роли (`tasks/main.yml`)

Добавим простые задачи по установке и запуску Nginx.

```yaml
---
# tasks file for nginx
- name: Install nginx
  ansible.builtin.apt:
    name: nginx
    state: latest
    update_cache: true

- name: Start and enable nginx service
  ansible.builtin.service:
    name: nginx
    state: started
    enabled: true
```

#### Шаг 4: Основной плейбук (`molecule/default/converge.yml`)

`converge.yml` — точка входа, которую Molecule выполняет для применения роли. Минимальный converge.yml просто подключает тестируемую роль. Если роль требует предварительных задач (например, запуск nginx через command), они добавляются до `include_role`.

```yaml
---
- name: Converge
  hosts: all
  gather_facts: true
  tasks:
    - name: Apply role nginx
      ansible.builtin.include_role:
        name: nginx
```

#### Шаг 5: Написание тестов (`molecule/default/verify.yml`)

Это плейбук, который проверяет, что роль отработала корректно.

```yaml
---
- name: Verify
  hosts: all
  gather_facts: true
  tasks:
    - name: Gather package facts
      ansible.builtin.package_facts:
        manager: auto

    - name: Check that nginx is installed
      ansible.builtin.assert:
        that:
          - "'nginx' in ansible_facts.packages"

    - name: Check that nginx is running
      ansible.builtin.command: pidof nginx
      changed_when: false
```

> `service_facts` полагается на systemd и не работает в Docker-контейнерах без него (см. Типовые проблемы №7). Вместо него используется `package_facts` (проверка установки) + `pidof` (проверка работы). `gather_facts: true` требует увеличения `ansible_timeout` (см. Типовые проблемы №1).

#### Шаг 6: Запуск тестов

Команда `molecule test` запустит полный жизненный цикл.

```bash
molecule test
```

Если все шаги пройдены успешно, вы увидите зеленый вывод, подтверждающий, что ваша роль работает как ожидалось и является идемпотентной.

**Команды для отладки:**

* `molecule create`
* `molecule converge`
* `molecule login` (для подключения к контейнеру и ручной проверки)
* `molecule verify`
* `molecule destroy`

### Типовые проблемы и решения (Troubleshooting)

#### 1. Verify timeout при `gather_facts: true`

**Проявление:** `verify` падает по таймауту (60s по умолчанию).

**Причина:** Cбор фактов на медленных хостах или в контейнерах через `community.docker` connection не укладывается в стандартный таймаут.

**Решение:** Увеличить `ansible_timeout` в `provisioner` molecule.yml:

```yaml
provisioner:
  name: ansible
  config_options:
    defaults:
      ansible_timeout: 600
```

#### 2. Неправильный `remote_user` в Docker connection

**Проявление:** `Failed to create temporary directory` при `converge`.

**Причина:** Docker connection выполняет `docker exec -u vagrant`, а пользователя `vagrant` нет в контейнере.

**Решение:** Убедиться, что `ansible_user` явно не задан в инвентаре, либо установить в `molecule.yml`:

```yaml
provisioner:
  inventory:
    group_vars:
      all:
        ansible_user: root
```

#### 3. Отсутствие SSH в образах `geerlingguy`

**Проявление:** Таймаут `Wait for SSH` в create.yml.

**Причина:** Образы `geerlingguy` предназначены для Docker connection (не содержат SSH-сервер).

**Решение:** Переписать create.yml без ожидания SSH, используя `community.docker.docker_container`.

#### 4. Systemd не стартует (cgroup v2)

**Проявление:** Контейнер падает сразу после создания — `Exited (255)`.

**Причина:** Современные дистрибутивы (Ubuntu 24.04+/Rocky Linux 9+) используют cgroup v2. systemd в контейнере требует cgroup v1 или `--cgroupns host`.

**Решение:** Заменить `command: /usr/lib/systemd/systemd` на `command: sleep infinity` в `molecule.yml`:

```yaml
platforms:
  - name: ubuntu
    image: geerlingguy/docker-rockylinux9-ansible:latest
    pre_build_image: true
    command: sleep infinity
```

#### 5. Handler Restart Nginx не работает

**Проявление:** `Service is in unknown state` или non-zero return code при рестарте.

**Причина:** Модули `service` и `systemd` не работают без systemd (см. проблему №4). `nginx -s reload` падает, если nginx не запущен (нет PID-файла).

**Решение:** Добавить задачу запуска nginx перед изменением конфига; в handler использовать `command: nginx -s reload` (работает только после старта nginx).

#### 6. Idempotence проваливается (Start nginx)

**Проявление:** При повторном `converge` задача запуска nginx возвращает `changed`.

**Причина:** `command: nginx` при уже запущенном экземпляре возвращает `rc=1`.

**Решение:** Добавить `failed_when: false` — ошибка игнорируется, задача считается `ok`.

```yaml
- name: Start nginx
  ansible.builtin.command: nginx
  failed_when: false
```

#### 7. `service_facts` падает без systemd

**Проявление:** `Failed to find any services` в verify.yml.

**Причина:** `service_facts` полагается на systemd, который не запущен в контейнере (см. проблему №4).

**Решение:** Заменить `service_facts` на `package_facts` (проверка установки) + `pidof` (проверка работы процесса).

#### 8. Molecule не находит molecule.yml

**Проявление:** `'molecule/default/molecule.yml' glob failed`.

**Причина:** `molecule test` запущен не из директории роли.

**Решение:** Перейти в корень роли: `cd ~/nginx && molecule test`.

#### 9. Warnings о дублирующихся коллекциях

**Проявление:** Warnings про `ansible.netcommon`, `ansible.posix` и др.

**Причина:** Коллекции установлены одновременно в системной директории (`/usr/lib/python3/dist-packages/`) и в пользовательской (`~/.ansible/collections/`).

**Решение:** Не влияет на работу, warnings не критичны.

## Дополнительная информация

### Подготовительный плейбук (`prepare.yml`)

Если роль требует предварительной настройки тестового инстанса (например, установки `curl` для проверки веб-сервера), эти задачи можно поместить в файл `molecule/default/prepare.yml`. Molecule выполнит его после создания инстанса (`create`) и до применения роли (`converge`).

### Несколько сценариев

Molecule позволяет создавать несколько сценариев для тестирования роли на разных ОС.

```bash
# Создать новый сценарий для CentOS
molecule init scenario centos -r nginx
```

Это создаст новую директорию `molecule/centos/`, где в `molecule.yml` можно указать другой `image` (например, `geerlingguy/docker-centos8-ansible:latest`) и, при необходимости, адаптировать тесты.

```bash
# Запустить тесты только для сценария centos
molecule test -s centos
```

### Интеграция с CI/CD

Molecule является стандартным инструментом для [интеграции тестов в CI/CD пайплайны](../Testing/testing_cicd_integration.md) и выступает частью [Quality Gates](../Testing/testing_cicd_integration.md#quality-gates-лучшие-практики-20252026). Тестирование ролей — ключевой компонент автоматизации Ansible, который также упоминается в документации по [ролям](ansible_roles.md) и [Ansible Lint](ansible_core_concepts.md). Для организации файлов проекта см. [структуру проекта](examples/example_project_layout.md).
