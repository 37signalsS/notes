# Тестирование ролей Ansible с помощью Molecule

## Определения

**Molecule** — это фреймворк для автоматизированного тестирования [ролей](ansible_roles.md) и плейбуков Ansible. Он позволяет создавать временные, изолированные окружения (с помощью Docker, Vagrant, облачных провайдеров), применять к ним ваш код и проверять, что он работает корректно. Это ключевой инструмент для внедрения практик **CI/CD (Continuous Integration / Continuous Deployment — непрерывная интеграция и доставка)** в разработку Ansible-автоматизации.

## Основные концепции

### Зачем нужен Molecule?

Тестирование сложной роли вручную требует: поднятия тестовых серверов, запуска плейбука, ручной проверки и повторения для разных **ОС (Операционная Система)**. Molecule автоматизирует этот процесс, позволяя:

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

Molecule является Python-пакетом. Современные версии (v5+, v6+) требуют явной установки драйверов через систему плагинов, а `ansible-lint` больше не устанавливается по умолчанию как зависимость, его нужно указывать отдельно.

```bash
# Рекомендуемая установка в виртуальное окружение
pip install "molecule-plugins[docker]" ansible-lint pytest-testinfra

# Проверка установки
molecule --version
# → molecule 24.x.x using python 3.x
```

> **Примечание:** Рекомендуется использовать виртуальные окружения Python (`venv`) для изоляции зависимостей тестов от системы.

## Практические сценарии

### Полный цикл тестирования роли

#### Шаг 1: Создание роли и инициализация Molecule

Команда `molecule init role` была удалена в версии 6.0. Рекомендуемый подход — создание роли через `ansible-galaxy` с последующей инициализацией сценария Molecule.

```bash
# Создание структуры роли
ansible-galaxy role init nginx
# → - Role nginx was created successfully

cd nginx

# Инициализация сценария default
molecule init scenario
# → INFO     Initializing new scenario default...
```

Это создаст поддиректорию `molecule/default/` с базовыми конфигурационными файлами.

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
    image: "geerlingguy/docker-ubuntu2204-ansible:latest"
    pre_build_image: true
provisioner:
  name: ansible
verifier:
  # Можно использовать "ansible" (модули assert) или "testinfra" (Python)
  name: testinfra
```

#### Драйвер Docker

Для работы с Docker Molecule использует плагин `molecule-plugins[docker]`. Он автоматически управляет жизненным циклом контейнеров (создание, удаление, подключение), поэтому файлы `create.yml` и `destroy.yml` создавать вручную не требуется.

Основные настройки контейнера задаются в `molecule.yml` в секции `platforms`.

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

`converge.yml` — точка входа, которую Molecule выполняет для применения роли.

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

#### Шаг 5: Написание тестов с помощью Testinfra (`molecule/default/tests/test_default.py`)

Индустриальным стандартом для сложных инфраструктурных тестов является **Testinfra** (плагин для `pytest`). Создайте папку `tests` и добавьте туда Python-файл.

```python
import os
import testinfra.utils.ansible_runner

testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
    os.environ['MOLECULE_INVENTORY_FILE']
).get_hosts('all')

def test_nginx_is_installed(host):
    nginx = host.package("nginx")
    assert nginx.is_installed

def test_nginx_running_and_enabled(host):
    nginx = host.service("nginx")
    assert nginx.is_running
    assert nginx.is_enabled

def test_nginx_listens_on_port_80(host):
    assert host.socket("tcp://0.0.0.0:80").is_listening
```

> **Альтернатива:** Вы можете использовать `verifier: name: ansible` и писать тесты на чистом YAML с помощью `ansible.builtin.assert`, но `testinfra` обеспечивает большую гибкость при сложных проверках (например, анализ конфигурационных файлов через регулярные выражения).

#### Шаг 6: Запуск тестов

Команда `molecule test` запустит полный жизненный цикл.

```bash
molecule test
# → INFO     Running default > dependency
# → ...
# → INFO     Running default > idempotence
# → ...
# → INFO     Running default > verify
# → ... (100% PASS)
```

Если все шаги пройдены успешно, вы увидите зеленый вывод, подтверждающий, что ваша роль работает как ожидалось и является идемпотентной.

**Команды для отладки:**

* `molecule create`
* `molecule converge`
* `molecule login` (для подключения к контейнеру и ручной проверки)
* `molecule verify`
* `molecule destroy`

## Типовые проблемы и решения

#### 1. Таймаут проверки (Verify timeout) при `gather_facts: true`

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

#### 4. Отсутствие systemd и ошибки сервисов

**Проявление:** `service_facts` не находит сервисы, или контейнер падает с ошибкой `Exited (255)`.

**Причина:** Большинство Docker-образов не запускают systemd по умолчанию. На хостах с cgroup v2 это также требует дополнительных настроек.

**Решение:** 
1. Используйте `package_facts` для проверки установки пакета и `command: pidof <process>` для проверки работы.
2. Если systemd необходим, используйте образы с его поддержкой (например, `geerlingguy/docker-<os>-ansible`) и настройте `command: /sbin/init` или `sleep infinity`.

#### 5. Проблемы с Handlers и идемпотентностью

**Проявление:** `Handler Restart` не срабатывает или шаг `idempotence` возвращает `changed`.

**Причина:** Модули `service` не работают без systemd. Прямой запуск команды (например, `nginx`) при повторном прогоне возвращает ошибку, так как процесс уже запущен.

**Решение:** 
1. Используйте `command: nginx -s reload` в хендлерах.
2. Для задач запуска используйте `failed_when: false` или проверку через `creates`/`removes`, чтобы избежать повторных изменений.

#### 6. Molecule не находит конфигурацию

**Проявление:** Ошибка `'molecule/default/molecule.yml' glob failed`.

**Причина:** Команда запущена не из корня роли.

**Решение:** Убедитесь, что вы находитесь в директории, содержащей папку `molecule/`: `cd ~/my_role && molecule test`.

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

Molecule является стандартным инструментом для интеграции тестов в CI/CD пайплайны и выступает частью Quality Gates. Тестирование ролей — ключевой компонент автоматизации Ansible.

- [Интеграция тестов в CI/CD](../Testing/testing_cicd_integration.md) — паттерны и Quality Gates.
- [Основные концепции Ansible](ansible_core_concepts.md) — идемпотентность и линтинг.
- [Структура проекта](examples/example_project_layout.md) — организация файлов и каталогов.
