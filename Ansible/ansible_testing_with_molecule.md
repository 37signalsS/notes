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

#### Шаг 4: Написание тестов (`molecule/default/verify.yml`)

Это плейбук, который проверяет, что роль отработала корректно.

```yaml
---
- name: Verify
  hosts: all
  gather_facts: false
  tasks:
    - name: Check that Nginx package is installed
      ansible.builtin.package:
        name: nginx
        state: present
      check_mode: true
      register: nginx_pkg

    - name: Assert that nginx package is present
      ansible.builtin.assert:
        that:
          - not nginx_pkg.changed
        fail_msg: "Nginx package was not installed"

    - name: Check if nginx service is running
      ansible.builtin.service_facts:
      register: service_facts

    - name: Assert that nginx service is running
      ansible.builtin.assert:
        that:
          - service_facts.ansible_facts.services['nginx.service'].state == 'running'
        fail_msg: "Nginx service is not running"
```

#### Шаг 5: Запуск тестов

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

### Связанные документы

* **[Ansible Lint](ansible_core_concepts.md#качество-кода-ansible-lint)** — статический анализ плейбуков
* **[Структура проекта](examples/example_project_layout.md)** — организация файлов и директорий
* **[Роли](ansible_roles.md)** — тестирование ролей — ключевой компонент CI/CD
* **[Интеграция тестов в CI/CD](../Testing/testing_cicd_integration.md)** — общие практики тестирования
* **[Quality Gates](../Testing/testing_cicd_integration.md#quality-gates-лучшие-практики-20252026)** — Molecule как часть ворот качества
