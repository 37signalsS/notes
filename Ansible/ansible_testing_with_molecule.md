# Тестирование ролей Ansible с помощью Molecule

## Определения

**Molecule** — специализированный фреймворк для разработки и автоматизированного тестирования [ролей Ansible](ansible_roles.md). Он управляет всем циклом тестирования: от создания изолированных окружений до проверки итогового состояния системы и удаления тестовых стендов. Это ключевой инструмент для внедрения практик **CI/CD (Continuous Integration / Continuous Deployment)** в разработку автоматизации.

**Драйвер (Driver)** — плагин Molecule, определяющий технологию создания тестовых инстансов. Основные драйверы: `docker`, `podman`, `vagrant`, `delegated`.

**Провайдер (Provisioner)** — компонент, отвечающий за применение конфигурации к инстансам. Стандартом является Ansible.

**Верификатор (Verifier)** — инструмент для проверки корректности настройки системы. Варианты: `ansible` (плейбуки с `assert`) или `testinfra` (Python-тесты на базе `pytest`).

**Сценарий (Scenario)** — набор конфигураций и тестов, описывающих конкретный вариант проверки (например, `default`, `rockylinux`, `multi-node`). Позволяет тестировать роль на разных ОС и в разных конфигурациях.

**Плагины Molecule (molecule-plugins)** — модульная архитектура, вынесенная в отдельный пакет начиная с v6. Содержит драйверы (`molecule-plugins[docker]`, `molecule-plugins[podman]`) и верификаторы.

## Предварительные требования

### Для Control Node

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| Python | 3.10 | 3.11+ | Обязательно |
| Ansible (ansible-core) | 2.15 | 2.17+ | Провайдер для Molecule |
| Docker или Podman | 20.10+ / 4.0+ | 24.0+ / 4.9+ | Драйвер для контейнеров |
| pytest | 7.0 | 8.0+ | Для Testinfra верификатора |
| molecule-plugins | 23.0 | 24.0+ | Драйверы и верификаторы |

### Установка Docker (если не установлен)

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y docker.io
sudo usermod -aG docker $USER
# → Перелогиньтесь для применения группы!

# macOS (Docker Desktop)
brew install --cask docker

# Проверка
docker --version
# → Docker version 24.0.7, build afdd53b
docker info | grep "Server Version"
# → Server Version: 24.0.7
```

### Установка Podman (альтернатива Docker, rootless)

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y podman

# RHEL / Fedora
sudo dnf install -y podman

# Проверка
podman --version
# → podman version 4.9.3
```

### Установка Molecule

```bash
# Рекомендуемая установка в виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate

# Установка Molecule с плагинами для Docker и Podman + Testinfra
pip install "molecule>=24.0" "molecule-plugins[docker,podman]" ansible-lint pytest-testinfra

# Проверка установки
molecule --version
# → molecule 24.x.x using python 3.11.x
#   molecule-plugins[docker,podman] version: 24.x.x
#   ansible-core version: 2.17.x

# Проверка доступных плагинов
molecule drivers
# → docker
#   podman
#   delegated
#   vagrant
```

> **Примечание:** Начиная с Molecule v6 все плагины вынесены в отдельный пакет `molecule-plugins`. Драйверы Docker и Podman больше не входят в базовую установку — устанавливайте их явно.

## Основные концепции

### Зачем нужен Molecule?

Тестирование сложной роли вручную требует значительных затрат времени на поднятие серверов и ручную проверку. Molecule автоматизирует этот процесс, обеспечивая:

* **Изоляцию:** Тесты проводятся в чистых окружениях, что гарантирует воспроизводимость.
* **Матричное тестирование:** Возможность проверки роли на матрице различных операционных систем одновременно.
* **Идемпотентность:** Встроенная проверка того, что повторный запуск плейбука не вносит изменений в систему.
* **Интеграция в CI/CD:** Molecule является фундаментом для построения Quality Gates в пайплайнах (GitLab CI, GitHub Actions).
* **Проведение линтинга:** Автоматическая проверка кода с помощью `ansible-lint` как один из обязательных шагов.

### Жизненный цикл тестирования

Команда `molecule test` запускает полный, последовательный цикл тестирования. В современных версиях (v6+) последовательность включает:

| Шаг | Команда | Описание | Что проверяется |
| :--- | :--- | :--- | :--- |
| 1 | `dependency` | Установка зависимостей роли из `meta/main.yml` или `requirements.yml` | Корректность `meta/main.yml` |
| 2 | `cleanup` | Очистка артефактов предыдущих запусков | Чистота окружения |
| 3 | `destroy` | Удаление существующих инстансов | — |
| 4 | `syntax` | Проверка синтаксиса плейбуков | YAML-синтаксис, FQCN |
| 5 | `create` | Создание тестового инстанса (Docker, Podman, ВМ) | Доступность драйвера |
| 6 | `prepare` | Выполнение `prepare.yml` (установка Python, регистрация подписок) | Готовность инстанса |
| 7 | `converge` | Запуск `converge.yml` — основной плейбук с тестируемой ролью | Применение роли |
| 8 | `idempotence` | Повторный запуск `converge.yml` — проверка отсутствия изменений | `changed=0` |
| 9 | `side_effect` | Выполнение действий, имитирующих внешние факторы | Устойчивость к изменениям |
| 10 | `verify` | Проверка состояния через верификатор (Testinfra или Ansible) | Корректность настройки |
| 11 | `cleanup` | Очистка временных ресурсов | — |
| 12 | `destroy` | Уничтожение инстансов | Освобождение ресурсов |

Для отладки каждый шаг можно запускать отдельно:

```bash
molecule create          # Только создание инстанса
molecule converge        # Только применение роли (без destroy)
molecule verify          # Только проверка (без apply)
molecule login -h instance  # Вход в контейнер для ручной отладки
molecule destroy         # Удаление инстансов
```

> **Примечание:** После `molecule converge` инстанс остаётся запущенным — можно подключиться через `molecule login` и отлаживать вручную. Для полной очистки выполните `molecule destroy`.

## Практические сценарии

### Полный цикл тестирования роли

#### Шаг 1: Создание роли и инициализация Molecule

С версии 6.0 команда `molecule init role` удалена. Используйте `ansible-galaxy` для структуры роли и `molecule init scenario` для тестов.

```bash
# Создание структуры роли
ansible-galaxy role init nginx
cd nginx
# → Role nginx was created successfully
# → Структура: defaults/ handlers/ files/ meta/ tasks/ templates/ vars/ README.md

# Инициализация сценария default с драйвером Docker
molecule init scenario --driver-name docker
# → INFO     Initializing new scenario default...
# → SUCCESS  Initialized scenario in /path/to/nginx/molecule/default

# Структура созданного каталога molecule/
ls -la molecule/default/
# → converge.yml   # Тестовый плейбук
# → molecule.yml   # Конфигурация Molecule
# → prepare.yml    # Предусловия (опционально)
# → verify.yml     # Проверки (по умолчанию с ansible verifier)
```

#### Шаг 2: Настройка сценария (`molecule/default/molecule.yml`)

Это главный файл конфигурации. Ниже приведены примеры для разных технологий.

**Драйвер Docker (с матрицей платформ):**
```yaml
---
dependency:
  name: galaxy
  options:
    requirements-file: requirements.yml

driver:
  name: docker

platforms:
  - name: ubuntu-2204
    image: geerlingguy/docker-ubuntu2204-ansible:latest
    pre_build_image: true
    privileged: true
    command: /sbin/init
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw

  - name: rockylinux-9
    image: geerlingguy/docker-rockylinux9-ansible:latest
    pre_build_image: true
    privileged: true
    command: /usr/sbin/init
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw

provisioner:
  name: ansible
  config_options:
    defaults:
      ansible_timeout: 600
      host_key_checking: false
  inventory:
    host_vars:
      ubuntu-2204:
        ansible_python_interpreter: /usr/bin/python3

verifier:
  name: ansible
```

> **Примечание:** Образы `geerlingguy/docker-*-ansible` содержат Python и systemd, что упрощает тестирование ролей, зависящих от сервисов.

**Драйвер Podman (рекомендуется для Rootless):**
```yaml
driver:
  name: podman
platforms:
  - name: instance
    image: quay.io/rockylinux/rockylinux:9
    privileged: true
```

**Драйвер Vagrant (для виртуальных машин):**
```yaml
driver:
  name: vagrant
platforms:
  - name: instance
    box: bento/ubuntu-22.04
    provider_options:
      gui: false
```

**Драйвер Delegated (для реальных серверов):**
```yaml
driver:
  name: delegated
platforms:
  - name: remote-server
    managed: false
```

#### Шаг 3: Написание логики роли (`tasks/main.yml`)

```yaml
---
# tasks file for nginx
- name: Install nginx
  ansible.builtin.apt:
    name: nginx
    state: present
    update_cache: true
    cache_valid_time: 3600

- name: Copy nginx config
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: "0644"
    validate: "nginx -t -c %s"
  notify: reload nginx

- name: Start and enable nginx service
  ansible.builtin.service:
    name: nginx
    state: started
    enabled: true
```

#### Шаг 4: Подготовительный плейбук (`molecule/default/prepare.yml`)

`prepare.yml` выполняется после создания инстанса и до применения роли. Используйте его для установки зависимостей, которых нет в образе.

```yaml
---
- name: Prepare
  hosts: all
  gather_facts: true
  tasks:
    - name: Установка Python (если отсутствует)
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      when: ansible_facts['os_family'] == 'Debian'

    - name: Установка зависимостей
      ansible.builtin.package:
        name:
          - curl
          - wget
          - gnupg2
        state: present

    - name: Создание тестового пользователя
      ansible.builtin.user:
        name: testuser
        shell: /bin/bash
        state: present
```

> **Примечание:** Если используете образы `geerlingguy/docker-*-ansible`, Python уже установлен — `prepare.yml` можно опустить.

#### Шаг 5: Основной плейбук (`molecule/default/converge.yml`)

`converge.yml` — точка входа, которую Molecule выполняет для применения роли.

```yaml
---
- name: Converge
  hosts: all
  become: true
  gather_facts: true
  tasks:
    - name: Apply role nginx
      ansible.builtin.include_role:
        name: nginx
```

#### Шаг 6: Верификация

Molecule поддерживает два верификатора. Выбор зависит от сложности проверок.

**Вариант А: Testinfra (рекомендуется для инфраструктурных тестов)**

Testinfra — Python-библиотека на базе `pytest` с декларативным API для проверки пакетов, сервисов, портов, файлов.

Установка:
```bash
pip install pytest-testinfra
```

Создайте `molecule/default/tests/test_default.py`:
```python
import os
import testinfra.utils.ansible_runner

testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
    os.environ['MOLECULE_INVENTORY_FILE']
).get_hosts('all')


def test_nginx_installed(host):
    assert host.package("nginx").is_installed

def test_nginx_running(host):
    svc = host.service("nginx")
    assert svc.is_running
    assert svc.is_enabled

def test_nginx_listens_on_port_80(host):
    assert host.socket("tcp://0.0.0.0:80").is_listening

def test_nginx_config_valid(host):
    cmd = host.run("nginx -t")
    assert cmd.rc == 0
    assert "syntax is ok" in cmd.stderr

def test_nginx_config_file(host):
    f = host.file("/etc/nginx/nginx.conf")
    assert f.exists
    assert f.user == "root"
```

Настройка Testinfra в `molecule/default/molecule.yml`:
```yaml
verifier:
  name: testinfra
  options:
    v: true
  additional_files_or_dirs:
    - tests/*
```

Запуск:
```bash
molecule verify
# → tests/test_default.py::test_nginx_installed PASSED
# → tests/test_default.py::test_nginx_running PASSED
# → ======================== 5 passed in 12.34s ========================
```

**Вариант Б: Ansible Verifier (`molecule/default/verify.yml`)**

Для простых проверок на чистом YAML с `ansible.builtin.assert`:

```yaml
---
- name: Verify
  hosts: all
  gather_facts: false
  tasks:
    - name: Проверка версии nginx
      ansible.builtin.command: nginx -v
      register: nginx_version
      changed_when: false

    - name: Проверка что nginx установлен
      ansible.builtin.assert:
        that:
          - "'nginx version' in nginx_version.stderr"

    - name: Проверка что сервис запущен
      ansible.builtin.service_facts:

    - name: Убедиться что nginx запущен
      ansible.builtin.assert:
        that:
          - "'nginx.service' in ansible_facts.services"
          - "ansible_facts.services['nginx.service'].state == 'running'"

    - name: Проверка HTTP ответа
      ansible.builtin.uri:
        url: http://localhost
        status_code: 200
```

**Сравнение верификаторов:**

| Критерий | Testinfra | Ansible Verifier |
| :--- | :--- | :--- |
| Язык | Python (`pytest`) | YAML (Ansible tasks) |
| Сложность проверок | Высокая (программируемая логика) | Средняя (declarative asserts) |
| Скорость | Быстрее (без overhead Ansible) | Медленнее (запуск плейбука) |
| Рекомендация | Инфраструктурные тесты, CI/CD | Простые проверки, DevOps-команды |

#### Шаг 7: Запуск тестов

Команда `molecule test` запустит полный жизненный цикл.

```bash
molecule test
# → INFO     Running default > dependency
# → INFO     Running default > cleanup
# → INFO     Running default > destroy
# → INFO     Running default > syntax
# → INFO     Running default > create
# → INFO     Running default > prepare
# → INFO     Running default > converge
# → INFO     Running default > idempotence
# → INFO     Running default > side_effect
# → INFO     Running default > verify
# → INFO     Running default > cleanup
# → INFO     Running default > destroy
# → .........
# → ======================== 9 passed in 45.67s ========================
```

**Запуск отдельных шагов:**

```bash
molecule test -- --step create          # Только создание
molecule converge                       # Create + converge (без destroy)
molecule verify                         # Только verify (после converge)
molecule login -h ubuntu-2204           # Вход в контейнер
molecule destroy                        # Удаление инстансов
molecule test -s alternative            # Запуск другого сценария
```

**Полезные опции:**

```bash
molecule test --destroy=never           # Не удалять инстансы после тестов
molecule converge --ansible-args="-vvv" # Подробный вывод Ansible
molecule verify --debug                 # Отладочный вывод Molecule
```

#### Шаг 8: Проверка конфигурации и линтинг

Перед запуском тестов рекомендуется проверить конфигурацию Molecule и плейбуки:

```bash
# Линтинг плейбука роли
ansible-lint molecule/default/converge.yml
# → role-name[path]: Role name nginx should not use path separators
# → yaml[truthy]: Truthy value should be true

# Линтинг конфигурации Molecule (проверка molecule.yml)
ansible-lint molecule/default/molecule.yml

# Проверка синтаксиса всех YAML-файлов
yamllint molecule/

# Линтинг всей роли целиком (включая tasks, handlers, defaults)
ansible-lint .
```

**Примеры часто встречающихся ошибок:**
- `fqcn[action-core]`: Используйте полные имена модулей (`ansible.builtin.apt` вместо `apt`)
- `yaml[truthy]`: Используйте `true`/`false` вместо `yes`/`no`
- `role-name`: Имя роли не должно содержать спецсимволов

## Типовые проблемы и решения

| # | Проблема | Проявление | Причина | Решение |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **Verify timeout** | `verify` падает по таймауту (60s) | Медленный сбор фактов | `ansible_timeout: 600` в `provisioner.config_options.defaults` |
| 2 | **Rootless permissions** | `Failed to create temporary directory` | Несоответствие UID/GID | `ansible_user: root` в `provisioner.inventory.group_vars.all` |
| 3 | **systemd отсутствует** | `service_facts` пуст, `Exited (255)` | Docker без init-процесса | Образы `geerlingguy/docker-*-ansible`, `command: /sbin/init`, монтирование cgroups |
| 4 | **Idempotence failed** | `changed > 0` на повторном запуске | `command`/`shell` без `changed_when` | Добавить `changed_when: false` или `creates`/`removes` |
| 5 | **Config not found** | `glob 'molecule/default/molecule.yml' failed` | Запуск вне корня роли | `cd ~/my_role && molecule test` |
| 6 | **cgroup v2** | Контейнеры с systemd не стартуют | Несовместимость cgroup v2 | `--cgroupns=host` в параметрах драйвера |
| 7 | **No such file** | `FAILED! => {"msg": "No such file"}` | Неверный путь в `converge.yml` | Проверить `name` в `include_role` |
| 8 | **Docker pull timeout** | `i/o timeout` при pull образа | Сеть / Docker Hub недоступен | Mirror registry или локальный registry |
| 9 | **Permission denied login** | `Error: Permission denied` | Контейнер удалён или нет доступа к Docker | `molecule create`, проверить `docker ps` |

**Примеры решений:**

```yaml
# Решение #1: Таймаут
provisioner:
  name: ansible
  config_options:
    defaults:
      ansible_timeout: 600

# Решение #4: Idempotence
- name: Run custom script
  ansible.builtin.command: /opt/scripts/setup.sh
  changed_when: false

# Решение #8: Mirror registry
platforms:
  - name: instance
    image: mirror.example.com/geerlingguy/docker-ubuntu2204-ansible:latest
```

## Дополнительная информация

### Структура каталога molecule

```
roles/nginx/molecule/
├── default/
│   ├── molecule.yml       # Конфигурация
│   ├── converge.yml       # Применение роли
│   ├── prepare.yml        # Предусловия
│   ├── verify.yml         # Verifier: Ansible
│   └── tests/
│       └── test_default.py  # Verifier: Testinfra
├── alternative/
│   ├── molecule.yml
│   ├── converge.yml
│   └── verify.yml
└── shared/
    └── Dockerfile.j2
```

### Интеграция в CI/CD

**GitLab CI (Docker-in-Docker):**
```yaml
molecule_test:
  stage: test
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  before_script:
    - apk add --no-cache python3 py3-pip gcc musl-dev
    - python3 -m venv .venv && source .venv/bin/activate
    - pip install molecule[docker] ansible-lint pytest-testinfra
  script:
    - molecule test
```

**GitHub Actions (матрица сценариев):**
```yaml
name: Ansible Molecule Tests
on: [push, pull_request]
jobs:
  molecule:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        scenario: [default, rockylinux]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install "molecule>=24.0" "molecule-plugins[docker]" ansible-lint pytest-testinfra
      - run: molecule test -s ${{ matrix.scenario }}
        env:
          PY_COLORS: "1"
          ANSIBLE_FORCE_COLOR: "1"
```

### Несколько сценариев

```bash
molecule init scenario rockylinux --driver-name docker  # Создать сценарий
molecule test -s rockylinux                             # Запуск конкретного
molecule test --all                                     # Все сценарии
ls molecule/                                            # Список
```

### Рекомендации и нюансы

- **`pre_build_image: true`** — ускоряет создание инстансов (образ уже содержит Python).
- **Не храните секреты в molecule.yml** — используйте переменные окружения или Vault.
- **`destroy: always`** для CI/CD / `destroy: never` для локальной отладки.
- **Для ролей с зависимостями** добавьте `requirements.yml` в `dependency.options`.
- **Тестируйте в порядке**: `default` (быстрый фидбек) → матрица ОС.

### Смотрите также

* [Тестирование коллекций через ansible-test](./ansible-test.md) — для модулей и плагинов.
* [Ansible Roles](./ansible_roles.md) — создание и структура ролей.
* [Ansible: установка и настройка](./ansible_setup_and_config.md) — Bootstrap Python.
* [Антипаттерны Ansible](./ansible_bad_practices.md) — типичные ошибки.
