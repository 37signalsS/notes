# Разработка коллекций Ansible

## Определения

**Collection (коллекция)** — стандартный способ упаковки и распространения Ansible content (роли, модули, плагины, playbooks) через Ansible Galaxy или внутренний реестр. Коллекция — это директория с определенной структурой, которая может быть опубликована для повторного использования.

**Namespace (пространство имен)** — уникальный идентификатор автора или организации в Galaxy, например `my_company`. Полное имя коллекции включает namespace и имя: `my_company.my_collection`.

**Role (роль)** — набор задач, шаблонов, переменных и обработчиков, которые можно повторно использовать в разных плейбуках. Подробнее о ролях см. **[Ansible: Роли](../ansible_roles.md)**.

**Module (модуль)** — блок кода, который выполняется на управляемых хостах для выполнения специфичной задачи. Подробнее о разработке модулей см. **[Ansible: Кастомные модули](../ansible_custom_modules.md)**.

**Plugin (плагин)** — расширение Ansible, которое добавляет новую функциональность. Подробнее о плагинах см. **[Ansible: Action-плагины](../ansible-action-plugins.md)**.

**FQCN (Fully Qualified Collection Name)** — полное имя коллекции, включающее namespace и имя: `my_company.my_collection.my_module`. Использование FQCN является обязательным стандартом для предотвращения конфликтов имен.

**Collection structure** — стандартная структура директорий и файлов коллекции, определенная в спецификации Ansible.

**galaxy.yml** — манифест коллекции, который содержит метаданные: namespace, name, version, dependencies, description, requires_ansible.

**Manifest** — файл `MANIFEST.json`, который создается при сборке коллекции и содержит хеши всех файлов для проверки целостности.

**Release** — опубликованная версия коллекции в Galaxy или в приватном репозитории.

**Versioning** — семантическое версионирование коллекций (MAJOR.MINOR.PATCH).

**Supply Chain Security** — практики защиты цепочки поставок контента: проверка подписей, контроль версий зависимостей, аудит использованных компонентов. Подробнее см. **[Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md)**.

**Private Galaxy / Automation Hub** — корпоративные реестры для хранения приватных или сертифицированных коллекций в изолированных сетях.

## Базовые концепции

### Жизненный цикл коллекции

1. **Создание** — инициализация структуры коллекции с помощью `ansible-galaxy collection init`.
2. **Разработка** — написание ролей, модулей, плагинов и документации.
3. **Тестирование** — запуск тестов (sanity, unit, integration) с помощью `ansible-test` или `pytest-ansible`.
4. **Сборка** — создание tarball с помощью `ansible-galaxy collection build`.
5. **Валидация** — проверка подлинности, линтинг, signed manifest.
6. **Публикация** — загрузка в Galaxy, Automation Hub или приватный реестр.
7. **Использование** — установка в проекты через `ansible-galaxy collection install`.
8. **Поддержка** — исправление багов, добавление новых функций, публикация новых версий.

### Структура коллекции

```
my_collection/
├── galaxy.yml                 # Манифест коллекции
├── README.md                  # Документация
├── CHANGELOG.md               # История изменений
├── CONTRIBUTING.md            # Руководство для контрибьюторов
├── LICENSE                    # Лицензия
├── meta/
│   └── runtime.yml             # Зависимости runtime
├── plugins/
│   ├── modules/                # Модули
│   │   └── my_module.py
│   ├── module_utils/           # Утилиты для модулей
│   │   └── my_utils.py
│   ├── lookup/                 # Lookup плагины
│   ├── filter/                 # Filter плагины
│   ├── callback/               # Callback плагины
│   ├── connection/             # Connection плагины
│   ├── vars/                   # Vars плагины
│   └── strategy/               # Strategy плагины
├── roles/                      # Роли
│   └── my_role/
│       ├── tasks/
│       │   └── main.yml
│       ├── handlers/
│       │   └── main.yml
│       ├── defaults/
│       │   └── main.yml
│       ├── vars/
│       │   └── main.yml
│       ├── templates/
│       │   └── my_template.j2
│       ├── files/
│       │   └── my_file.txt
│       └── meta/
│           └── main.yml
├── playbooks/                  # Playbooks
│   └── my_playbook.yml
├── docs/                       # Документация
│   ├── my_module.md
│   └── my_role.md
├── tests/                      # Тесты
│   ├── unit/
│   │   └── test_my_module.py
│   └── integration/
│       └── targets/
│           └── my_test/
│               ├── runme.sh
│               └── verify.yml
└── build/                      # Собранные артефакты
```

**Для SRE:** структура коллекции обеспечивает:
- **Versioning** — семантическое версионирование с `requires_ansible` для совместимости
- **Auditability** — все изменения фиксируются в Git, `CHANGELOG.md` для каждой версии
- **Change management** — обновление коллекций проходит через maintenance windows с `serial` и `throttle`
- **Supply chain security** — проверка подписей через `ansible-galaxy collection verify`

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| ansible-core | 2.21+ | `ansible --version` |
| Python (control node) | 3.12+ | `python3 --version` |
| Python (managed node) | 3.9+ | `python3 --version` |
| ansible-lint | 26.8+ | `ansible-lint --version` |
| PyYAML | 6.0+ | `python3 -c "import yaml; print(yaml.__version__)"` |
| jinja2 | 3.1+ | `python3 -c "import jinja2; print(jinja2.__version__)"` |
| pytest | 8.0+ | `pytest --version` |
| pytest-ansible | 24.0+ | `pytest --co -q` |
| GPG | 2.2+ | `gpg --version` |

### Ключевые принципы

1. **Reusability** — коллекция должна быть переиспользуемой в разных проектах.
2. **Documentation** — каждая роль и модуль должны иметь документацию.
3. **Testing** — покрытие тестами (sanity, unit, integration).
4. **Versioning** — семантическое версионирование с `requires_ansible`.
5. **Dependencies** — явное указание зависимостей в `galaxy.yml` и `requirements.yml`.
6. **Idempotency** — все задачи должны быть идемпотентными.
7. **Security** — проверка подписей, supply chain security, separation of duties.
8. **Change management** — обновление через maintenance windows с approval process.

## Практические сценарии

### Сценарий 1: Инициализация новой коллекции

Создание новой коллекции с помощью `ansible-galaxy`.

```bash
# Инициализация коллекции
ansible-galaxy collection init my_company.my_collection

# Структура после инициализации
my_company.my_collection/
├── galaxy.yml
├── README.md
├── plugins/
│   └── modules/
│       └── my_module.py
├── roles/
└── tests/
```

**galaxy.yml:**

```yaml
# galaxy.yml
namespace: my_company
name: my_collection
version: 1.0.0
readme: README.md
authors:
  - My Name <my.name@example.com>
description: My Ansible collection for common tasks
license: MIT
tags:
  - infrastructure
  - automation
dependencies:
  my_company.other_collection: ">=1.0.0"
  community.general: ">=13.0.0"
requires_ansible: ">=2.21,<2.22"
repository: https://github.com/my_company/my_collection
documentation: https://my_company.github.io/my_collection
homepage: https://github.com/my_company/my_collection
issues: https://github.com/my_company/my_collection/issues
```

**Валидация:**

```bash
# Проверка валидности galaxy.yml
ansible-galaxy collection build my_company.my_collection
# → создает tarball my_company-my_collection-1.0.0.tar.gz

# Проверка структуры
tree my_company.my_collection/
# → показывает структуру коллекции
```

### Сценарий 2: Создание модуля в коллекции

Создание модуля для управления конфигурационным файлом. Подробнее о разработке модулей см. **[Ansible: Кастомные модули](../ansible_custom_modules.md)**.

```python
# plugins/modules/app_config.py
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule
import os
import hashlib

def calculate_file_hash(filepath):
    """Вычисление SHA256 хеша файла."""
    if not os.path.exists(filepath):
        return None

    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def main():
    """Основная логика модуля."""
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(type='str', required=True),
            content=dict(type='str', required=True),
            owner=dict(type='str', required=False, default='root'),
            group=dict(type='str', required=False, default='root'),
            mode=dict(type='str', required=False, default='0644')
        ),
        supports_check_mode=True
    )

    path = module.params['path']
    content = module.params['content']
    owner = module.params['owner']
    group = module.params['group']
    mode = module.params['mode']

    result = dict(changed=False, path=path, checksum=None)

    # Проверка существования файла
    if not os.path.exists(path):
        # Файл не существует, создаем
        if module.check_mode:
            result['changed'] = True
        else:
            try:
                with open(path, 'w') as f:
                    f.write(content)
                os.chown(path, owner, group)
                os.chmod(path, int(mode, 8))
                result['changed'] = True
            except Exception as e:
                module.fail_json(msg=f"Failed to create file: {e}", **result)
    else:
        # Файл существует, проверяем содержимое
        current_hash = calculate_file_hash(path)
        new_hash = hashlib.sha256(content.encode()).hexdigest()

        result['checksum'] = current_hash

        if current_hash != new_hash:
            if module.check_mode:
                result['changed'] = True
            else:
                try:
                    with open(path, 'w') as f:
                        f.write(content)
                    os.chown(path, owner, group)
                    os.chmod(path, int(mode, 8))
                    result['changed'] = True
                except Exception as e:
                    module.fail_json(msg=f"Failed to update file: {e}", **result)

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

**Документация модуля (docs/docsite/rst/):**

```rst
..  include:: my_module.rst

my_module – Управление конфигурационным файлом приложения
=======================================================

.. versionadded:: 1.0.0

Synopsis
--------

Этот модуль управляет конфигурационными файлами приложения, обеспечивая
идемпотентность и безопасное обновление.

Requirements
------------

Плагин выполняется на управляемых хостах и не требует дополнительных
зависимостей.

Parameters
----------

path
  Описание параметра path.

  Тип: ``str``

  Обязательный: ``yes``

content
  Описание параметра content.

  Тип: ``str``

  Обязательный: ``yes``

owner
  Описание параметра owner.

  Тип: ``str``

  Обязательный: ``no``

  Значение по умолчанию: ``root``

group
  Описание параметра group.

  Тип: ``str``

  Обязательный: ``no``

  Значение по умолчанию: ``root``

mode
  Описание параметра mode.

  Тип: ``str``

  Обязательный: ``no``

  Значение по умолчанию: ``0644``

Examples
--------

.. code-block:: yaml

  - name: Установка конфигурации приложения
    my_company.my_collection.app_config:
      path: /etc/myapp/config.yml
      content: "{{ lookup('file', 'templates/config.yml') }}"
      owner: myapp
      group: myapp
      mode: '0640'

Return Values
-------------

path
  Путь к управляемому файлу.

checksum
  SHA256 хеш текущего содержимого файла.
```

**Использование модуля:**

```yaml
---
- name: Использование модуля из коллекции
  hosts: all
  tasks:
    - name: Установка конфигурации
      my_company.my_collection.app_config:
        path: /etc/myapp/config.yml
        content: "{{ lookup('template', 'myapp/config.yml.j2') }}"
        owner: myapp
        group: myapp
        mode: '0640'
      register: config_result

    - name: Проверка результата
      ansible.builtin.debug:
        msg: "Config changed: {{ config_result.changed }}"
```

**Валидация:**

```bash
# Установка коллекции
ansible-galaxy collection install .
# → устанавливает локальную коллекцию

# Использование модуля
ansible all -m my_company.my_collection.app_config -a "path=/tmp/test.txt content='test'" -i inventory.ini
# → создает файл на хосте

# Проверка документации
ansible-doc my_company.my_collection.app_config
# → показывает документацию модуля
```

### Сценарий 3: Создание роли в коллекции

Создание роли для развертывания веб-приложения. Подробнее о ролях см. **[Ansible: Роли](../ansible_roles.md)**.

```yaml
# roles/web_app/tasks/main.yml
---
- name: Установка зависимостей
  ansible.builtin.package:
    name:
      - python3
      - python3-pip
      - nginx
    state: present

- name: Создание пользователя приложения
  ansible.builtin.user:
    name: webapp
    system: yes
    shell: /bin/bash

- name: Создание директории приложения
  ansible.builtin.file:
    path: /opt/webapp
    state: directory
    owner: webapp
    group: webapp
    mode: '0755'

- name: Развертывание приложения
  ansible.builtin.unarchive:
    src: "{{ webapp_package_url }}"
    dest: /opt/webapp
    remote_src: yes
    owner: webapp
    group: webapp

- name: Установка зависимостей Python
  ansible.builtin.pip:
    requirements: /opt/webapp/requirements.txt
    virtualenv: /opt/webapp/venv
    virtualenv_python: python3

- name: Размещение конфигурации systemd
  ansible.builtin.copy:
    src: files/webapp.service
    dest: /etc/systemd/system/webapp.service
    mode: '0644'
  notify: Reload systemd

- name: Включение и запуск приложения
  ansible.builtin.systemd:
    name: webapp
    state: started
    enabled: yes
    daemon_reload: yes

- name: Размещение конфигурации Nginx
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/sites-available/webapp
    mode: '0644'
  notify: Reload Nginx

- name: Включение сайта Nginx
  ansible.builtin.file:
    src: /etc/nginx/sites-available/webapp
    dest: /etc/nginx/sites-enabled/webapp
    state: link
  notify: Reload Nginx

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: yes

    - name: Reload Nginx
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

**Значения по умолчанию (roles/web_app/defaults/main.yml):**

```yaml
---
# webapp версия по умолчанию
webapp_version: "1.0.0"
webapp_package_url: "https://releases.example.com/webapp-{{ webapp_version }}.tar.gz"

# Конфигурация приложения
webapp_listen_port: 8080
webapp_workers: 4
webapp_max_requests: 1000

# Nginx конфигурация
nginx_server_name: "{{ ansible_hostname }}"
nginx_listen_port: 80
```

**Переменные (roles/web_app/vars/main.yml):**

```yaml
---
# Операционная система
supported_os:
  - Debian
  - Ubuntu
  - RedHat
  - AlmaLinux
  - Rocky

# Пользователь
webapp_user: webapp
webapp_group: webapp

# Директории
webapp_install_dir: /opt/webapp
webapp_log_dir: /var/log/webapp
webapp_pid_dir: /var/run/webapp
```

**Зависимости (roles/web_app/meta/main.yml):**

```yaml
---
dependencies:
  - role: nginxinc.nginx
    vars:
      nginx_install_method: "package"
```

**Использование роли:**

```yaml
---
- name: Развертывание веб-приложения
  hosts: web_servers
  become: true
  vars:
    webapp_version: "1.1.0"
    webapp_package_url: "https://releases.example.com/webapp-1.1.0.tar.gz"

  roles:
    - role: my_company.my_collection.web_app
```

**Валидация:**

```bash
# Установка зависимостей роли
ansible-galaxy role install nginxinc.nginx

# Запуск плейбука с ролью
ansible-playbook -i inventory.ini deploy_webapp.yml
# → развертывает веб-приложение

# Проверка статуса приложения
ansible web1 -m systemd -a "name=webapp state=started"
# → активен
```

### Сценарий 4: Тестирование коллекции

Настройка и запуск тестов для коллекции. Подробнее о тестировании см. **[Ansible: Тестирование с Molecule](../ansible_testing_with_molecule.md)**.

```yaml
# tests/integration/targets/web_app/runme.sh
#!/usr/bin/env bash
set -eux

# Запуск плейбука
ansible-playbook -i ../../inventory.yml playbooks/deploy_webapp.yml

# Проверка, что сервис запущен
ansible localhost -m systemd -a "name=webapp state=started" -i ../../inventory.yml
```

```yaml
# tests/integration/targets/web_app/verify.yml
---
- name: Verify web app is running
  hosts: all
  gather_facts: yes
  tasks:
    - name: Check webapp service is running
      ansible.builtin.systemd:
        name: webapp
        state: started
      register: webapp_status

    - name: Verify webapp is listening on port 8080
      ansible.builtin.wait_for:
        port: 8080
        host: "{{ ansible_host }}"
        timeout: 30
      register: webapp_port

    - name: Verify webapp health endpoint
      ansible.builtin.uri:
        url: http://{{ ansible_host }}:8080/health
        status_code: 200
        timeout: 10
      register: webapp_health
```

**Запуск тестов:**

```bash
# Установка зависимостей для тестирования
pip install ansible-core ansible-lint pytest pytest-ansible

# Запуск sanity тестов
ansible-test sanity --docker default -v

# Запуск unit тестов
ansible-test units --docker default -v

# Запуск integration тестов
ansible-test integration web_app --docker default -v

# Запуск линтинга
ansible-lint
```

**Валидация:**

```bash
# Проверка тестов
ansible-test integration --list-targets
# → показывает список доступных тестов

# Запуск конкретного теста
ansible-test integration web_app
# → запускает тест web_app

# Проверка результатов
# → результаты тестов в директории tests/integration/targets/web_app/
```

### Сценарий 5: Подписание и публикация коллекции

Сборка, подписание и публикация коллекции в Galaxy или Automation Hub с supply chain security.

```bash
# Сборка коллекции
ansible-galaxy collection build my_company.my_collection
# → создает my_company-my_collection-1.0.0.tar.gz

# Подписание коллекции (требуется GPG ключ)
ansible-galaxy collection sign my_company-my_collection-1.0.0.tar.gz \
  --key-id 1234567890ABCDEF

# Проверка подписи
ansible-galaxy collection verify my_company-my_collection-1.0.0.tar.gz
# → подпись действительна

# Публикация в публичный Galaxy
ansible-galaxy collection publish my_company-my_collection-1.0.0.tar.gz

# Или публикация в Automation Hub / приватный Galaxy
ansible-galaxy collection publish my_company-my_collection-1.0.0.tar.gz \
  --api-key $GALAXY_API_KEY \
  --server-url https://galaxy.example.com
```

**Использование опубликованной коллекции:**

```bash
# Установка коллекции из Galaxy
ansible-galaxy collection install my_company.my_collection:1.0.0

# Установка из Automation Hub
ansible-galaxy collection install my_company.my_collection:1.0.0 \
  --server-url https://galaxy.example.com \
  --api-key $GALAXY_API_KEY

# Использование в playbook
- name: Deploy web app
  hosts: all
  roles:
    - role: my_company.my_collection.web_app
```

**Валидация:**

```bash
# Проверка установленной версии
ansible-galaxy collection list | grep my_company.my_collection
# → my_company.my_collection 1.0.0

# Проверка подписи установленной коллекции
ansible-galaxy collection verify my_company.my_collection
# → подпись действительна

# Проверка документации
ansible-doc my_company.my_collection.app_config
# → показывает документацию модуля

# Запуск плейбука
ansible-playbook -i inventory.ini deploy.yml
# → использует модули и роли из коллекции
```

### Сценарий 6: CI/CD пайплайн для коллекции

Автоматизация тестирования и публикации коллекции через CI/CD. Подробнее о CI/CD см. **[Архитектура Ansible для безопасного CI/CD](../examples/example_real_world_ci_cd.md)**.

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - build
  - publish

variables:
  ANSIBLE_COLLECTIONS_PATHS: ./ansible_collections

lint:
  stage: lint
  image: python:3.14
  script:
    - pip install ansible-core ansible-lint==26.8.0 yamllint
    - ansible-lint
    - yamllint .

sanity-test:
  stage: test
  image: python:3.14
  script:
    - pip install ansible-core
    - ansible-test sanity --docker default -v

unit-test:
  stage: test
  image: python:3.14
  script:
    - pip install ansible-core pytest pytest-ansible
    - ansible-test units --docker default -v

integration-test:
  stage: test
  image: python:3.14
  script:
    - pip install ansible-core
    - ansible-test integration web_app --docker default -v

build:
  stage: build
  image: python:3.14
  script:
    - pip install ansible-core
    - ansible-galaxy collection build
  artifacts:
    paths:
      - my_company-my_collection-*.tar.gz

publish:
  stage: publish
  image: python:3.14
  script:
    - pip install ansible-core
    - ansible-galaxy collection publish my_company-my_collection-*.tar.gz --api-key $GALAXY_API_KEY
  only:
    - tags
```

## Операции и команды

### Основные команды для работы с коллекциями

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-galaxy collection init <namespace.collection>` | Инициализация коллекции | `ansible-galaxy collection init my_company.my_collection` |
| `ansible-galaxy collection build <path>` | Сборка коллекции | `ansible-galaxy collection build my_company.my_collection` |
| `ansible-galaxy collection publish <tarball>` | Публикация в Galaxy | `ansible-galaxy collection publish my_company-my_collection-1.0.0.tar.gz` |
| `ansible-galaxy collection install <collection>` | Установка коллекции | `ansible-galaxy collection install my_company.my_collection` |
| `ansible-galaxy collection list` | Список установленных коллекций | `ansible-galaxy collection list` |
| `ansible-galaxy collection info <collection>` | Информация о коллекции | `ansible-galaxy collection info my_company.my_collection` |
| `ansible-galaxy collection verify <collection>` | Проверка подписи | `ansible-galaxy collection verify my_company.my_collection` |
| `ansible-galaxy collection sign <tarball>` | Подписание коллекции | `ansible-galaxy collection sign my_collection-1.0.0.tar.gz --key-id ABCD` |
| `ansible-galaxy collection upgrade <collection>` | Обновление коллекции | `ansible-galaxy collection upgrade my_company.my_collection` |
| `ansible-doc <fqcn>` | Документация модуля | `ansible-doc my_company.my_collection.app_config` |
| `ansible-test sanity` | Sanity тесты | `ansible-test sanity --docker default` |
| `ansible-test units` | Unit тесты | `ansible-test units --docker default` |
| `ansible-test integration` | Integration тесты | `ansible-test integration web_app --docker default` |
| `ansible-lint` | Линтинг | `ansible-lint` |

### Команды для управления зависимостями

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-galaxy collection install -r requirements.yml` | Установка из requirements | `ansible-galaxy collection install -r requirements.yml` |
| `pip install <package>` | Установка Python зависимостей | `pip install pyyaml jinja2` |
| `ansible-galaxy role install -r requirements.yml` | Установка ролей | `ansible-galaxy role install -r requirements.yml` |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `ModuleNotFoundError` | Зависимости модуля не установлены | Установите зависимости: `pip install <package>` |
| `FQCN not found` | Коллекция не установлена | Установите коллекцию: `ansible-galaxy collection install <namespace.collection>` |
| `galaxy.yml validation failed` | Ошибка в манифесте | Проверьте синтаксис YAML, обязательные поля |
| `Build failed` | Ошибка в структуре коллекции | Проверьте структуру директорий, права доступа |
| `Tests failed` | Ошибка в коде или тестах | Проверьте логи тестов, исправьте код |
| `Collection not found in Galaxy` | Коллекция не опубликована | Опубликуйте коллекцию: `ansible-galaxy collection publish` |
| `ImportError in plugin` | Неверный импорт | Проверьте пути импорта, относительные пути внутри коллекции |
| `Signature verification failed` | Подпись недействительна | Проверьте GPG ключ, `ansible-galaxy collection verify` |
| `Dependency conflict` | Конфликт версий зависимостей | Используйте семантическое версионирование, `requires_ansible` |
| `requires_ansible mismatch` | Несовместимость с ansible-core | Обновите `requires_ansible` в `galaxy.yml` |

## Рекомендации

### Best Practices

1. **Semantic versioning** — используйте семантическое версионирование (MAJOR.MINOR.PATCH) с `requires_ansible`.
2. **Documentation** — документируйте каждый модуль и роль в RST/Markdown.
3. **Testing** — покрывайте код sanity, unit и integration тестами.
4. **Dependencies** — явно указывайте зависимости в `galaxy.yml` и `requirements.yml`.
5. **Idempotency** — все задачи должны быть идемпотентными.
6. **Security** — проверяйте подписи коллекций, используйте supply chain security practices.
7. **Change management** — обновляйте коллекции через maintenance windows с `serial` и `throttle`.
8. **FQCN** — используйте полные имена модулей для предотвращения конфликтов.
9. **Audit** — все изменения фиксируются в Git, ведется журнал изменений.
10. **Private registry** — для production используйте Automation Hub или приватный Galaxy.

### Чек-лист валидации после создания коллекции

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Структура коллекции | `tree my_collection/` | Структура соответствует спецификации |
| Валидность galaxy.yml | `ansible-galaxy collection build my_collection` | Tarball создан без ошибок |
| Установка коллекции | `ansible-galaxy collection install .` | Коллекция установлена |
| Модуль загружается | `ansible-doc my_company.my_collection.app_config` | Документация отображается |
| Роль выполняется | `ansible-playbook test_role.yml` | Роль выполняется без ошибок |
| Sanity тесты | `ansible-test sanity --docker default` | Все тесты PASSED |
| Линтинг | `ansible-lint` | Нет ошибок |
| Подпись | `ansible-galaxy collection verify my_collection` | Подпись действительна |

## Дополнительная информация

### Смотрите также

- **[Ansible: Кастомные модули](../ansible_custom_modules.md)** — разработка модулей, module_utils, Ansiballz, идемпотентность.
- **[Ansible: Action-плагины](../ansible-action-plugins.md)** — разработка action, lookup, filter, callback плагинов.
- **[Ansible: Роли](../ansible_roles.md)** — структура ролей, зависимые роли, Galaxy tags.

### Интеграция с другими системами

| Система | Назначение | Интеграция |
|---|---|---|
| **Ansible Galaxy** | Публичный реестр | `ansible-galaxy collection publish` |
| **Automation Hub** | Приватный реестр | `ansible-galaxy collection publish --server-url` |
| **GitHub/GitLab** | Хостинг кода | CI/CD pipelines, release artifacts |
| **GitLab CI/Jenkins** | Тестирование | Автоматические тесты при каждом коммите |
| **ReadTheDocs** | Документация | Sphinx, MkDocs |
| **SonarQube** | Анализ качества кода | Плагины и модули |
| **GPG** | Подписание коллекций | `ansible-galaxy collection sign` |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Крупная коллекция | Долгая сборка и тестирование | Используйте кеширование, параллельные тесты, `ansible-dev-environment` |
| Зависимости коллекций | Конфликты версий | Используйте `requirements.yml`, семантическое версионирование, `requires_ansible` |
| Частые изменения API | Несовместимость с существующим кодом | Строгое семантическое версионирование, changelog, deprecation warnings |
| Разработка нескольких версий | Поддержка старых версий | Используйте ветки в Git, бэкпортинг, `requires_ansible` |
| Коллекция в приватном Galaxy | Ограниченный доступ | Настройте аутентификацию, используйте API ключи, Automation Hub |
| Подпись коллекции | Отсутствие GPG ключа | Создайте GPG ключ, импортируйте в `ansible-galaxy` |
| Supply chain атака | Вредоносный код в зависимостях | Проверяйте подписи, используйте `ansible-galaxy collection verify`, pin dependencies |
| Concurrent publishing | Два релиза одновременно | Используйте version bump, maintain release queue, Git tags |
