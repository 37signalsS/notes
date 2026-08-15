# Тестирование ролей Ansible с помощью Molecule

## Определения

**Molecule** — специализированный фреймворк для разработки и автоматизированного тестирования [ролей Ansible](ansible_roles.md). Он управляет всем циклом тестирования: от создания изолированных окружений до проверки итогового состояния системы и удаления тестовых стендов. Это ключевой инструмент для внедрения практик **CI/CD (Continuous Integration / Continuous Deployment)** в разработку автоматизации.

**Драйвер (Driver)** — плагин Molecule, определяющий технологию создания тестовых инстансов. Основные драйверы: `docker`, `podman`, `vagrant`, `delegated`.

**Провайдер (Provisioner)** — компонент, отвечающий за применение конфигурации к инстансам. Стандартом является Ansible.

**Верификатор (Verifier)** — инструмент для проверки корректности настройки системы. Варианты: `ansible` (плейбуки с `assert`) или `testinfra` (Python-тесты).

**Сценарий (Scenario)** — набор конфигураций и тестов, описывающих конкретный вариант проверки (например, `default`, `centos-7`, `multi-node`).

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

1. `dependency`: Установка зависимостей роли из `meta/main.yml` или `requirements.yml` (через `ansible-galaxy`).
2. `cleanup`: Очистка артефактов предыдущих запусков.
3. `destroy`: Удаление существующих инстансов.
4. `syntax`: Проверка синтаксиса плейбуков.
5. `create`: Создание тестового инстанса (Docker, Podman, ВМ).
6. `prepare`: Выполнение подготовительного плейбука `prepare.yml` (например, установка Python или регистрация подписок).
7. `converge`: Запуск основного плейбука `converge.yml`, применяющего тестируемую роль.
8. `idempotence`: Повторный запуск `converge.yml` для проверки отсутствия изменений (статус `changed=0`).
9. `side_effect`: Выполнение действий, имитирующих внешние факторы.
10. `verify`: Проверка состояния системы через верификатор (Testinfra или Ansible).
11. `cleanup`: Очистка временных ресурсов.
12. `destroy`: Уничтожение инстансов.

Для отладки каждый шаг можно запускать отдельно (например, `molecule converge`, `molecule login`, `molecule verify`).

### Установка

Molecule v6+ является модульной системой. Рекомендуется устанавливать её в виртуальное окружение с необходимыми плагинами.

```bash
# Рекомендуемая установка в виртуальное окружение
pip install "molecule>=24.0" "molecule-plugins[docker,podman]" ansible-lint pytest-testinfra

# Проверка установки
molecule --version
# → molecule 24.x.x using python 3.x
```

> **Примечание:** Рекомендуется использовать виртуальные окружения Python (`venv`) для изоляции зависимостей тестов от системы.

## Практические сценарии

### Полный цикл тестирования роли

#### Шаг 1: Создание роли и инициализация Molecule

С версии 6.0 команда `molecule init role` удалена. Используйте `ansible-galaxy` для структуры роли и `molecule init scenario` для тестов.

```bash
# Создание структуры роли
ansible-galaxy role init nginx
cd nginx

# Инициализация сценария default
molecule init scenario
# → INFO     Initializing new scenario default...
```

Это создаст поддиректорию `molecule/default/` с базовыми конфигурационными файлами.

#### Шаг 2: Настройка сценария (`molecule/default/molecule.yml`)

Это главный файл конфигурации. Ниже приведены примеры для разных технологий.

**Драйвер Docker:**
```yaml
driver:
  name: docker
platforms:
  - name: instance
    image: "geerlingguy/docker-ubuntu2204-ansible:latest"
    pre_build_image: true
    privileged: true
    command: /sbin/init
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw
```

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

#### Шаг 3: Написание логики роли (`tasks/main.yml`)

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

#### Шаг 5: Верификация

**Вариант А: Написание тестов с помощью Testinfra (`molecule/default/tests/test_default.py`)**
Индустриальным стандартом для сложных инфраструктурных тестов является **Testinfra** (плагин для `pytest`).

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

**Вариант Б: Ansible Verifier (плейбук `molecule/default/verify.yml`)**
Рекомендуется для простых проверок на чистом YAML с помощью `ansible.builtin.assert`.

```yaml
---
- name: Verify
  hosts: all
  tasks:
    - name: Проверка HTTP ответа
      ansible.builtin.uri:
        url: http://localhost
        status_code: 200
```

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

**Команды для отладки:**
* `molecule create`
* `molecule converge`
* `molecule login` (для подключения к контейнеру и ручной проверки)
* `molecule verify`
* `molecule destroy`

## Типовые проблемы и решения

#### 1. Таймаут проверки (Verify timeout)
**Проявление:** `verify` падает по таймауту (60s по умолчанию).
**Причина:** Медленный сбор фактов на целевых хостах.
**Решение:** Увеличить `ansible_timeout` в `provisioner` molecule.yml:
```yaml
provisioner:
  name: ansible
  config_options:
    defaults:
      ansible_timeout: 600
```

#### 2. Ошибки прав доступа в Docker (Rootless)
**Проявление:** `Failed to create temporary directory` при `converge`.
**Причина:** Несоответствие UID/GID при использовании Docker connection.
**Решение:** Явно указать пользователя в `provisioner`:
```yaml
provisioner:
  inventory:
    group_vars:
      all:
        ansible_user: root
```

#### 3. Отсутствие systemd и ошибки сервисов
**Проявление:** `service_facts` не находит сервисы, или контейнер падает с ошибкой `Exited (255)`.
**Причина:** Docker не запускает init-процесс по умолчанию.
**Решение:** 
1. Используйте `package_facts` для проверки установки пакета и `command: pidof <process>`.
2. Если systemd необходим, используйте образы с его поддержкой (от `geerlingguy`), монтируйте cgroups и указывайте `command: /sbin/init`.

#### 4. Проблемы с идемпотентностью (changed > 0)
**Проявление:** Шаг `idempotence` возвращает `changed`.
**Причина:** Использование модулей `command` или `shell` без параметров `creates`/`removes`.
**Решение:** Используйте `changed_when: false` для команд, которые не меняют состояние, или добавьте логику проверки существования артефактов.

#### 5. Molecule не находит конфигурацию
**Проявление:** Ошибка `'molecule/default/molecule.yml' glob failed`.
**Причина:** Запуск команды вне корня роли.
**Решение:** Перейдите в каталог с папкой `molecule/`: `cd ~/my_role && molecule test`.

#### 6. Проблемы с cgroup v2 на современных ядрах
**Проявление:** Контейнеры с systemd не запускаются или не работают cgroups внутри.
**Решение:** Используйте `--cgroupns=host` в параметрах драйвера или запускайте Docker с необходимыми привилегиями.

## Дополнительная информация

### Интеграция в CI/CD (GitLab CI)

Пример конфигурации для запуска Molecule в GitLab с использованием Docker-in-Docker:

```yaml
molecule_test:
  stage: test
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - apk add --no-cache python3 py3-pip gcc musl-dev python3-dev libffi-dev openssl-dev
    - python3 -m venv .venv && source .venv/bin/activate
    - pip install molecule[docker] ansible-lint
    - molecule test
```

### Подготовительный плейбук (`prepare.yml`)

Если роль требует предварительной настройки (например, установки `curl` или создания пользователей), поместите задачи в `molecule/default/prepare.yml`. Molecule выполнит его после создания инстанса и до применения роли.

### Несколько сценариев

Molecule позволяет тестировать роль на разных ОС через сценарии:
```bash
# Создать сценарий для Rocky Linux
molecule init scenario rockylinux
# Запуск конкретного сценария
molecule test -s rockylinux
```

### Смотрите также

* [Тестирование коллекций через ansible-test](./ansible-test.md) — стандарт для разработчиков модулей и плагинов.
* [Интеграция тестов в CI/CD](../Testing/testing_cicd_integration.md) — общие подходы к автоматизации.
* [Основные концепции Ansible](ansible_core_concepts.md) — идемпотентность и линтинг.
* [Структура проекта](examples/example_project_layout.md) — организация файлов.
* [Антипаттерны Ansible](./ansible_bad_practices.md) — типичные ошибки.
