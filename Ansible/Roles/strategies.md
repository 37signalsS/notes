# Стратегии проектирования ролей Ansible

## Определения

**Стратегия разбиения ролей** — методология декомпозиции автоматизации на независимые логические модули (роли) для повышения переиспользования кода, упрощения тестирования и обеспечения масштабируемости инфраструктурного кода.

**Композиция ролей** — процесс объединения нескольких специализированных ролей в единый сценарий (Play) или через иерархию зависимостей для реализации комплексной настройки узла.

**Utility Role (Утилитарная роль)** — узкоспециализированная роль («библиотека»), выполняющая одну конкретную техническую задачу (например, настройка репозиториев или установка сертификатов) без внешних зависимостей.

**Composite Role (Композитная/Профильная роль)** — высокоуровневая роль, агрегирующая несколько утилитарных ролей для формирования законченного технического или бизнес-состояния системы (например, «Узел Kubernetes Worker»).

**Function-based Role (Функциональная роль)** — роль, сгруппированная по домену ответственности или бизнес-функции (например, `monitoring_agent`, `backup_client`), объединяющая несколько компонентов для реализации конкретной функции ИТ-инфраструктуры.

**Change Management (управление изменениями)** — процесс контроля всех изменений в инфраструктуре с целью минимизации рисков и влияния на производственные сервисы. В контексте Ansible роли обеспечивают атомарность и воспроизводимость изменений.

**Observability (наблюдаемость)** — способность понимать внутреннее состояние системы по внешним сигналам (логи, метрики, трейсы). Роли Ansible должны генерировать структурированные логи и метрики для интеграции с системами мониторинга.

**Compliance-as-Code** — практика реализации политик соответствия (PCI-DSS, HIPAA, SOC2) через код автоматизации. Структура роли должна поддерживать аудиторский след и валидацию соответствия.

**Supply Chain Security (безопасность цепочки поставок)** — практики защиты контента ролей: проверка подписей, контроль версий зависимостей, аудит использованных компонентов.

**Air-gapped Environment (изолированная среда)** — инфраструктурная среда без прямого выхода в интернет, требующая локальных зеркал репозиториев и предварительной загрузки всех зависимостей.

---

## Предварительные требования

### Системные требования (Ansible 2.21.4)

*   **Control Node:** Требуется **Python 3.12+**.
*   **Target Nodes:** Требуется **Python 3.9+** (для Ansible 2.21.4 рекомендуется Python 3.12+).
*   **Ansible:** 2.7+ для `public` в `include_role`; 2.11+ для `argument_specs`; 2.18+ для `end_role`

### Инструменты

```bash
# Установка ansible-core
pip install ansible-core

# Проверка версии
ansible --version  # Должна быть 2.21.4

# Инициализация роли для проверки структуры
ansible-galaxy role init test_strategy
rm -rf test_strategy

# Линтинг перед коммитом
ansible-lint roles/
```

---

## Архитектура и жизненный цикл роли

### Как Ansible обнаруживает и загружает роли

Ansible ищет роли в директориях, указанных в `roles_path` (по умолчанию `./roles` относительно плейбука, плюс `~/.ansible/roles`, `/usr/share/ansible/roles`). При вызове роли Ansible выполняет следующие этапы:

1. **Обнаружение:** Проверяет наличие каталога с именем роли в путях поиска. Поддерживается FQCN (`namespace.collection.role_name`).
2. **Загрузка зависимостей:** Выполняет роли из `meta/main.yml → dependencies` (неявные) или задачи из `tasks/main.yml` с `include_role` (явные).
3. **Порядок компонентов:**
   - `defaults/main.yml` — значения по умолчанию (самый низкий приоритет)
   - `vars/main.yml` — переменные роли (высокий приоритет)
   - `tasks/main.yml` — основная логика
   - `handlers/main.yml` — обработчики (уведомления)
   - `meta/main.yml` — зависимости и спецификация аргументов

### Критерии выбора стратегии

| Критерий | Рекомендуемая стратегия |
| :--- | :--- |
| Малый проект / быстрый старт | Component-based |
| Enterprise / compliance / стандарты | Layered |
| Высокое переиспользование кода | Composite + Utility |
| Организационная структура по командам | Capability |
| Максимальная гибкость, атомарные изменения | Micro-roles |

### Жизненный цикл роли в инфраструктуре

1. **Проектирование:** Выбор стратегии, определение интерфейса (`argument_specs.yml`), планирование зависимостей с учетом Change Management.
2. **Реализация:** Написание задач, шаблонов, обработчиков с учетом идемпотентности и Observability.
3. **Тестирование:** Molecule сценарии для разных ОС, check mode, интеграционное тестирование, валидация compliance.
4. **Версионирование:** Семантическое версионирование, changelog, tagged releases, аудит Supply Chain Security.
5. **CI/CD:** Линтинг (`ansible-lint`), тестирование в pipelines, автоматическое распространение через Galaxy или Git, проверка подписей.
6. **Эксплуатация:** Мониторинг изменений, обновление зависимостей, аудит безопасности, обратная связь от Observability систем.

---

## Основные концепции

### Стратегии декомпозиции

| Стратегия | Описание | Область применения |
| :--- | :--- | :--- |
| **По компонентам (Component-based)** | Одна роль = один технический сервис. Фокус на жизненном цикле ПО. | `nginx`, `postgresql`, `redis`. Самый популярный и рекомендуемый подход. |
| **По слоям (Layered)** | Разделение на уровни абстракции: базовый ОС, платформа (Runtime), приложение. | `base_os` (users, ssh), `java_runtime`, `spring_app`. Удобно для Enterprise-стандартов. |
| **Composite vs Utility** | Разделение на «кирпичики» (Utility) и их «сборки» (Composite). | Масштабируемые проекты с большим количеством повторяющихся задач. |
| **По функциональным ролям (Capability)** | Группировка по доменам ответственности или бизнес-функциям. | `monitoring_agent`, `backup_client`, `audit_logging`. |
| **Микро-роли (Micro-roles)** | Атомарные функции, выделенные в отдельные роли для максимальной гибкости. | `user_add`, `firewall_rule`, `motd_gen`. Требует сложной оркестрации. |

### Детализация стратегий

#### Стратегия "По компонентам" (Component-based)

Самый распространенный подход. Каждая роль отвечает за один технический компонент и его жизненный цикл (установка, настройка, обновление, удаление).

**Преимущества:**
- Простота тестирования и отладки
- Легкое переиспользование в разных проектах
- Четкое разделение ответственности
- Простое обновление (каждый компонент обновляется независимо)
- Удобство для Change Management: каждая роль = одно логическое изменение

**Недостатки:**
- Может привести к дублированию общих задач между ролями
- Сложность управления версиями зависимостей

**Пример структуры:**
```text
roles/
├── nginx/           # Веб-сервер
├── postgresql/      # База данных
├── redis/           # Кэш
├── java_runtime/    # Runtime
└── monitoring/      # Мониторинг
```

#### Стратегия "По слоям" (Layered)

Разделение на горизонтальные уровни абстракции. Каждый слой выполняет свою функцию в стеке инфраструктуры.

**Преимущества:**
- Четкая иерархия зависимостей
- Удобно для Enterprise-стандартов и compliance
- Легко контролировать порядок выполнения
- Поддержка аудита: каждый слой можно валидировать independently

**Недостатки:**
- Сложность в гибкости (изменение одного слоя может затронуть другие)
- Требует строгого контроля зависимостей

**Пример структуры:**
```text
layers/
├── 01_base_os/      # Базовая ОС (users, ssh, ntp)
├── 02_runtime/      # Runtime (java, python, docker)
├── 03_platform/     # Платформа (web server, app server)
└── 04_application/  # Приложение (деплой, конфигурация)
```

#### Стратегия "Composite vs Utility"

Разделение на мелкие переиспользуемые компоненты (Utility) и их сборки (Composite).

**Преимущества:**
- Максимальное переиспользование кода
- Легкость добавления новых функций
- Изоляция изменений
- Централизованное управление общими политиками (безопасность, мониторинг)

**Недостатки:**
- Сложность отладки (много уровней абстракции)
- Требует хорошей документации

**Пример структуры:**
```text
roles/
├── utility/
│   ├── lib_common/     # Общие задачи
│   ├── lib_db/         # Библиотека для БД
│   └── lib_web/        # Библиотека для веб
└── composite/
    ├── web_server/     # nginx + php + common
    ├── db_server/      # postgresql + common
    └── app_server/     # java + common
```

#### Стратегия "По функциональным ролям" (Capability)

Группировка по доменам ответственности или бизнес-функциям.

**Преимущества:**
- Удобно для командной структуры (разные команды отвечают за разные функции)
- Легко контролировать доступ и изменения
- Соответствие организационной структуре
- Удобство для Compliance: команда безопасности управляет всеми ролями безопасности

**Недостатки:**
- Может привести к дублированию компонентов между функциями
- Сложность в масштабировании при росте функций

**Пример структуры:**
```text
roles/
├── monitoring/       # Все для мониторинга
│   ├── agent/        # Установка агента
│   ├── alerts/       # Настройка алертов
│   └── dashboards/   # Графана
├── security/         # Все для безопасности
│   ├── ssh/          # Настройка SSH
│   ├── firewall/     # Правила файрвола
│   └── audit/        # Аудит
└── backup/           # Все для бэкапов
    ├── agent/        # Установка агента
    ├── policy/       # Политики бэкапов
    └── restore/      # Восстановление
```

#### Стратегия "Микро-роли" (Micro-roles)

Атомарные функции, выделенные в отдельные роли для максимальной гибкости.

**Преимущества:**
- Максимальная гибкость и переиспользование
- Легкость тестирования отдельных функций
- Минимальный scope изменений
- Идеально для атомарных изменений в Change Management

**Недостатки:**
- Сложность оркестрации (много мелких ролей)
- Требует сложной логики вызовов
- Сложность в отладке

**Пример структуры:**
```text
roles/
├── user_add/         # Добавление пользователя
├── user_remove/      # Удаление пользователя
├── firewall_rule/    # Добавление правила файрвола
├── motd_gen/         # Генерация MOTD
├── package_install/  # Установка пакета
└── service_manage/   # Управление сервисом
```

### Принципы проектирования "Role-First" (Ansible 2.17+)

1.  **Интерфейс прежде реализации (Interface First):** Начинайте проектирование с определения входных данных в `meta/argument_specs.yml`. Это гарантирует, что роль будет предсказуемой и валидируемой *до* выполнения первой задачи. В 2.17+ используйте поле `context` для передачи метаданных в IDE.
2.  **Единая ответственность (Single Responsibility):** Одна роль должна отвечать за один логический компонент. Если роль устанавливает и базу данных, и веб-сервер — её сложно тестировать и переиспользовать по частям.
3.  **Слабая связность (Loose Coupling):** Роль не должна зависеть от внутренних переменных других ролей. Используйте глобальные факты или четко определенные зависимости. Не обращайтесь к `hostvars` других хостов напрямую внутри роли.
4.  **Идемпотентность и предсказуемость:** Роль должна приводить систему к одному и тому же состоянию независимо от количества запусков. Используйте `changed_when: false` для задач-проверок.
5.  **Поддержка Check Mode:** Проектируйте задачи так, чтобы запуск с `--check` был информативным и не обрывался ошибками. Используйте `check_mode: no` только для задач получения данных (например, `ansible.builtin.stat`).
6.  **Использование FQCN:** Всегда используйте полное имя модулей (например, `ansible.builtin.template`), чтобы избежать конфликтов при расширении проекта коллекциями.
7.  **Безопасность (Secret Awareness):** Секреты должны быть вынесены из ролей. Используйте `no_log: true` для задач с чувствительными данными и иерархию `vault_`-переменных.

---

## Продвинутые паттерны проектирования

### Явные vs Неявные зависимости

Существует два подхода к управлению зависимостями ролей:

*   **Неявные (meta/main.yml):** Традиционный способ. Ansible автоматически выполняет зависимые роли перед основной.
    *   *Плюс:* Автоматизация цепочки вызовов.
    *   *Минус:* Сложно контролировать порядок выполнения внутри сложных сценариев, риск нежелательных повторных запусков (если не настроен `allow_duplicates`).
*   **Явные (tasks/main.yml + include_role):** Современный и рекомендуемый подход (Ansible 2.17+).
    *   *Плюс:* Полный контроль над тем, когда и с какими параметрами вызывается зависимая роль. Поддержка условий (`when`) и циклов (`loop`).
    *   *Минус:* Требует больше кода в `tasks/main.yml`.

### Паттерн "Wrapper Role" (Роль-обертка)

Используется для настройки внешних ролей (например, из Ansible Galaxy) под корпоративные стандарты без их модификации.
*   **Логика:** Создается роль `mycompany_nginx`, которая вызывает `geerlingguy.nginx` с жестко заданными корпоративными параметрами безопасности.
*   **Результат:** Внешняя роль остается неизменной (immutable), что упрощает её обновление (Upstream), а все специфичные настройки живут в обертке.

### Стратегия досрочного завершения (Ansible 2.18+)

Использование `ansible.builtin.meta: end_role` позволяет корректно прервать выполнение роли для конкретного хоста, если он не соответствует критериям (например, ОС уже настроена), не прерывая выполнение остального плейбука.

---

## Практические сценарии

### Сценарий 1: Многослойная композиция (Playbook level)

Использование слоев для обеспечения согласованности парка серверов:

```yaml
---
- name: Настройка веб-узла
  hosts: webservers
  become: true
  roles:
    - role: mycorp.base.os_hardening  # Слой безопасности
    - role: mycorp.infra.monitoring    # Слой наблюдаемости
    - role: ansible.builtin.include_role
      name: geerlingguy.nginx          # Внешний компонент
      vars:
        nginx_listen_port: 80
    - role: mycorp.app.frontend        # Прикладной слой
```

### Сценарий 2: Кроссплатформенная логика (Dynamic Includes)

Идиоматичный способ обработки различий между дистрибутивами ОС через динамическое включение задач и переменных. Подробности см. в **[Кроссплатформенные концепции](../CrossPlatform/concepts.md)**.

```yaml
# tasks/main.yml
- name: Загрузка переменных специфичных для ОС
  ansible.builtin.include_vars: "{{ item }}"
  with_first_found:
    - files:
        - "{{ ansible_facts['os_family'] }}.yml"
        - "default.yml"
      paths: ["../vars"]

- name: Установка пакетов для конкретной ОС
  ansible.builtin.include_tasks: "install_{{ ansible_facts['os_family'] | lower }}.yml"
```

### Сценарий 3: "Wrapper" для внешней роли

Пример реализации обертки в `tasks/main.yml` роли `mycorp_postgresql`:

```yaml
---
- name: Применение корпоративных политик безопасности БД
  ansible.builtin.include_role:
    name: geerlingguy.postgresql
  vars:
    postgresql_python_library: python3-psycopg2
    postgresql_global_config_options:
      - option: ssl
        value: 'on'
      - option: password_encryption
        value: 'scram-sha-256'
```

### Сценарий 4: Определение интерфейса (argument_specs)

Стратегия "защитного программирования" через `meta/argument_specs.yml` для предотвращения ошибок при вызове роли:

```yaml
# meta/argument_specs.yml
argument_specs:
  main:
    short_description: "Роль для деплоя микросервиса"
    options:
      deploy_version:
        type: str
        required: true
        description: "Версия артефакта для деплоя"
      deploy_env:
        type: str
        choices: ['prod', 'stage', 'test']
        default: 'test'
      app_port:
        type: int
        default: 8080
        context:
          monitoring: "prometheus_exporter"
```

### Сценарий 5: Оптимизация производительности (Async + Throttle)

Для ролей, выполняющих тяжелые операции (обновление БД, установка тяжелого ПО), используйте ограничение конкурентности.

```yaml
- name: Обновление распределенной БД
  ansible.builtin.include_role:
    name: db_update
  throttle: 1  # Выполнять только на одном узле одновременно, чтобы сохранить кворум
```

### Сценарий 6: Component-based стратегия — Полный пример

Демонстрация чистой Component-based стратегии для настройки веб-сервера:

```yaml
# playbooks/webserver.yml
---
- name: Настройка веб-сервера
  hosts: webservers
  become: true
  roles:
    - role: geerlingguy.nginx
      vars:
        nginx_worker_processes: "auto"
        nginx_worker_connections: 1024

    - role: geerlingguy.php
      vars:
        php_version: "8.2"
        php_memory_limit: "256M"

    - role: mycorp.monitoring.node_exporter
      vars:
        node_exporter_port: 9100
```

**Преимущество:** Каждую роль можно тестировать и обновлять независимо.

### Сценарий 7: Layered стратегия — Иерархия слоев

Порядок выполнения для обеспечения согласованности:

```yaml
# playbooks/full_stack.yml
---
- name: Полная настройка стека
  hosts: app_servers
  become: true
  roles:
    # Слой 1: Базовая ОС
    - role: mycorp.base.users
    - role: mycorp.base.ssh_hardening
    - role: mycorp.base.ntp

    # Слой 2: Runtime
    - role: mycorp.runtime.java
      vars:
        java_version: "21"

    # Слой 3: Платформа
    - role: mycorp.platform.nginx
    - role: mycorp.platform.postgresql

    # Слой 4: Приложение
    - role: mycorp.app.deploy
      vars:
        app_version: "{{ artifact_version }}"
```

### Сценарий 8: Composite vs Utility — Переиспользуемые библиотеки

Utility-роли предоставляют общие функции, Composite-роли их собирают:

**Utility-роль `lib_common`:**
```yaml
# roles/lib_common/tasks/main.yml
---
- name: Установка общих пакетов
  ansible.builtin.package:
    name: "{{ common_packages }}"
    state: present

- name: Настройка логирования
  ansible.builtin.template:
    src: rsyslog.conf.j2
    dest: /etc/rsyslog.d/app.conf
```

**Composite-роль `web_server`:**
```yaml
# roles/web_server/tasks/main.yml
---
- name: Подключение общих функций
  ansible.builtin.include_role:
    name: lib_common

- name: Настройка веб-сервера
  ansible.builtin.include_role:
    name: nginx
  vars:
    nginx_worker_processes: "{{ ansible_processor_vcpus }}"
```

### Сценарий 9: Capability стратегия — Группировка по функциям

Организация ролей по командам ответственности:

```yaml
# playbooks/monitoring_setup.yml
---
- name: Настройка мониторинга
  hosts: all
  become: true
  roles:
    - role: monitoring.agent        # Команда мониторинга
    - role: monitoring.alerts       # Команда мониторинга
    - role: monitoring.dashboards   # Команда мониторинга

# playbooks/security_setup.yml
---
- name: Настройка безопасности
  hosts: all
  become: true
  roles:
    - role: security.ssh            # Команда безопасности
    - role: security.firewall       # Команда безопасности
    - role: security.audit          # Команда безопасности
```

### Сценарий 10: Тестирование стратегий

Использование Molecule для тестирования разных стратегий:

```bash
# Тестирование Component-based роли
cd roles/nginx
molecule test

# Тестирование Composite роли
cd roles/web_server
molecule test --scenario-name composite

# Тестирование Layered стратегии
molecule test --scenario-name layered
```

**Molecule сценарий для Composite роли:**
```yaml
# molecule/composite/molecule.yml
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: instance
    image: docker.io/pycontribs/ubuntu:22.04
provisioner:
  name: ansible
  inventory:
    group_vars:
      all:
        # Тестирование всех зависимых ролей
        nginx_worker_processes: 2
        php_version: "8.2"
```

### Сценарий 11: Версионирование и обновление ролей

Стратегия управления версиями для разных типов ролей:

```yaml
# requirements.yml для зависимостей
---
roles:
  # Component-based: точные версии
  - name: geerlingguy.nginx
    version: "3.2.0"

  # Utility: диапазон версий
  - name: mycorp.lib_common
    version: ">=2.0.0,<3.0.0"

  # Composite: pinned для стабильности
  - name: mycorp.web_server
    version: "1.5.3"
```

**Автоматическое обновление:**
```bash
# Проверка доступных обновлений
ansible-galaxy role list --format json | jq '.[] | select(.installed == true)'

# Обновление конкретной роли
ansible-galaxy role install geerlingguy.nginx --force

# Обновление всех ролей
ansible-galaxy role install -r requirements.yml --force
```

### Сценарий 12: Миграция с монолита на roles

Пошаговая стратегия миграции:

```bash
# Шаг 1: Анализ монолитного плейбука
ansible-playbook monolithic.yml --list-tasks

# Шаг 2: Выделение компонентов в roles
mkdir -p roles/{nginx,postgresql,app}/{tasks,handlers,templates,defaults}

# Шаг 3: Постепенная миграция (начать с Utility)
# Создать roles/lib_common с общими задачами

# Шаг 4: Замена задач в монолите на include_role
# Было:
#   - name: Install nginx
#     ansible.builtin.package:
#       name: nginx
# Стало:
#   - ansible.builtin.include_role:
#       name: nginx

# Шаг 5: Тестирование каждой роли отдельно
molecule test

# Шаг 6: Интеграционное тестирование
ansible-playbook site.yml --check
```

### Сценарий 13: Роли в CI/CD пайплайне

Интеграция стратегий ролей в конвейер непрерывной интеграции:

```yaml
# .github/workflows/ansible-roles.yml
---
name: Ansible Roles CI/CD
on:
  push:
    paths:
      - 'roles/**'
      - 'requirements.yml'

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        role: [nginx, postgresql, lib_common, web_server]
    steps:
      - uses: actions/checkout@v4
      - name: Install dependencies
        run: pip install ansible-core ansible-lint molecule docker
      - name: Lint role
        run: ansible-lint roles/${{ matrix.role }}/
      - name: Test role
        run: |
          cd roles/${{ matrix.role }}
          molecule test
```

### Сценарий 14: Change Management с ролями

Стратегия атомарных изменений через роли:

```yaml
# playbooks/change-management.yml
---
- name: Change Management: Обновление Nginx с откатом
  hosts: webservers
  become: true
  vars:
    nginx_rollback_version: "1.24.0-1ubuntu3"

  pre_tasks:
    - name: Создание снапшота текущего состояния
      ansible.builtin.command: dpkg -l | grep nginx
      register: nginx_snapshot
      changed_when: false

    - name: Сохранение снапшота в лог
      ansible.builtin.debug:
        msg: "{{ nginx_snapshot.stdout }}"

  roles:
    - role: nginx_update

  post_tasks:
    - name: Валидация после обновления
      ansible.builtin.uri:
        url: http://localhost/
        status_code: 200
      register: validation_result

    - name: Откат при ошибке валидации
      ansible.builtin.include_role:
        name: nginx_rollback
      when: validation_result.status != 200
```

### Сценарий 15: Observability интеграция

Роли должны генерировать структурированные логи для систем мониторинга:

```yaml
# roles/monitoring_agent/tasks/main.yml
---
- name: Установка агента мониторинга
  ansible.builtin.package:
    name: prometheus-node-exporter
    state: present
  notify: restart node_exporter
  register: install_result

- name: Отправка метрики установки
  ansible.builtin.debug:
    msg: "prometheus_node_exporter_installed={{ install_result.changed | lower }}"
  when: install_result is defined

- name: Проверка доступности метрик
  ansible.builtin.uri:
    url: http://localhost:9100/metrics
    status_code: 200
  register: metrics_check
  retries: 3
  delay: 5
  until: metrics_check.status == 200
```

### Сценарий 16: Air-gapped среда

Стратегия работы в изолированной среде без доступа к интернету:

```bash
# Подготовка в среде с доступом к интернету
ansible-galaxy role download -r requirements.yml --output-path ./roles-cache/

# Создание локального зеркала
mkdir -p /opt/ansible-roles/
cp -r roles-cache/* /opt/ansible-roles/

# Настройка ansible.cfg для использования локальных ролей
cat > ansible.cfg << 'EOF'
[defaults]
roles_path = /opt/ansible-roles:./roles
EOF

# Проверка без доступа к интернету
ansible-galaxy role list
```

---

## Операции и команды

### Управление ролями через `ansible-galaxy`

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `ansible-galaxy role init <name>` | Инициализация структуры роли | `ansible-galaxy role init nginx` |
| `ansible-galaxy role install <name>` | Установка роли из Galaxy | `ansible-galaxy role install geerlingguy.nginx` |
| `ansible-galaxy role install -r requirements.yml` | Массовая установка из файла | `ansible-galaxy role install -r requirements.yml` |
| `ansible-galaxy role list` | Список установленных ролей | `ansible-galaxy role list --format json` |
| `ansible-galaxy role uninstall <name>` | Удаление роли | `ansible-galaxy role uninstall geerlingguy.nginx` |
| `ansible-galaxy role search <query>` | Поиск ролей в Galaxy | `ansible-galaxy role search nginx` |
| `ansible-galaxy role info <name>` | Информация о роли | `ansible-galaxy role info geerlingguy.nginx` |

### Управление зависимостями

| Команда / Файл | Описание | Пример |
| :--- | :--- | :--- |
| `requirements.yml` | Файл зависимостей с версиями | `name: geerlingguy.nginx, version: "3.2.0"` |
| `ansible-galaxy role install -r requirements.yml --force` | Принудительное обновление | Переустановка всех ролей из файла |
| `ansible-galaxy role list --format json \| jq` | Аудит установленных версий | Проверка drift версий |

### Валидация и линтинг

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `ansible-lint roles/` | Линтинг всех ролей | `ansible-lint roles/ -x schema` |
| `ansible-playbook site.yml --list-tasks` | Просмотр порядка выполнения | Диагностика дублирования |
| `ansible-playbook site.yml --syntax-check` | Проверка синтаксиса | Быстрая валидация перед коммитом |
| `ansible-playbook site.yml --check` | Проверка в режиме dry-run | Валидация без внесения изменений |

---

## Troubleshooting

### Роль не вызывается или выполняется дважды

**Причина:** Дублирование вызовов в `meta/main.yml` и `tasks/main.yml`.

**Решение:**
```bash
# Просмотр порядка выполнения
ansible-playbook site.yml --list-tasks

# Проверка зависимостей
ansible-galaxy role list

# Использование тегов для фильтрации
ansible-playbook site.yml --list-tags
```

### Переменные не переопределяются

**Причина:** Конфликт приоритетов переменных между ролями.

**Решение:**
```bash
# Просмотр переменных конкретной роли
ansible-playbook site.yml --list-variables -l webserver1

# Проверка приоритетов переменных
ansible-doc -t vars 2>/dev/null || echo "См. документацию по приоритетам"

# Использование group_vars для глобальных переменных
# roles/my_role/defaults/main.yml — для значений по умолчанию
# group_vars/all.yml — для глобальных переменных
# host_vars/host1.yml — для конкретных хостов
```

### Зависимости выполняются в неправильном порядке

**Причина:** Использование неявных зависимостей (`meta/main.yml`) вместо явных.

**Решение:**
```yaml
# Правильно: явный порядок в плейбуке
- hosts: webservers
  roles:
    - role: base_os      # 1. Сначала базовая ОС
    - role: nginx        # 2. Затем веб-сервер
    - role: app_deploy   # 3. Затем приложение

# Или использование import_tasks для явного контроля
- name: Основные задачи
  ansible.builtin.import_tasks: main.yml
```

### include_role не находит переменные из предыдущих ролей

**Причина:** По умолчанию `include_role` изолирует переменные.

**Решение:**
```yaml
# Использование public: true для экспорта переменных
- name: Подключение роли с экспортом переменных
  ansible.builtin.include_role:
    name: my_role
    public: true

# Теперь переменные из my_role доступны
- name: Использование переменных
  ansible.builtin.debug:
    msg: "{{ my_role_variable }}"
```

### end_role прерывает весь плейбук

**Причина:** Неправильное использование `ansible.builtin.meta: end_role`.

**Решение:**
```yaml
# Правильно: end_role прерывает только текущую роль для данного хоста
- name: Проверка условий
  ansible.builtin.meta: end_role
  when: not should_continue | bool

# Остальные роли продолжают выполняться
```

### Роль работает изолированно, но падает в композиции

**Причина:** Конфликт переменных, обработчиков или порядок выполнения.

**Диагностика:**
```bash
# Запуск с максимальной отладкой
ansible-playbook site.yml -vvvv

# Просмотр собранных переменных
ansible-playbook site.yml --list-variables -l host1
```

**Решение:**
- Используйте префиксы переменных для изоляции (`nginx_`, `postgresql_`).
- Явно управляйте порядком через директиву `roles:` в плейбуке.
- Для обработчиков используйте namespace в именах (`nginx_restart`, `php_restart`).

### `ansible-galaxy role install` падает с таймаутом

**Причина:** Нестабильное сетевое соединение или большая роль.

**Решение:**
```bash
# Увеличение таймаута
export ANSIBLE_GALAXY_SERVER_TIMEOUT=120

# Установка через прокси
ansible-galaxy role install geerlingguy.nginx --server https://galaxy.ansible.com

# Альтернатива: клонирование через Git
git clone https://github.com/geerlingguy/ansible-role-nginx.git roles/geerlingguy.nginx
```

### Molecule тесты failing на конкретной платформе

**Причина:** Несовместимость пакетов или различия в ОС.

**Диагностика:**
```bash
# Запуск конкретного сценария
molecule test --scenario-name default

# Подключение к контейнеру для отладки
molecule converge
docker exec -it instance bash
```

**Решение:**
- Уточните образ в `molecule.yml` (`platforms → image`).
- Используйте `dependency → name: galaxy` для установки зависимостей в тестовой среде.
- Добавьте `ansible_install_method: pip` в `provisioner → env` если системный pip неактуален.

### Лinting падает на старых версиях Ansible

**Причина:** `ansible-lint` использует правила для новых версий.

**Решение:**
```yaml
# .ansible-lint
profile: production
rule_files:
  - builtins
  - custom_rules
```

Или отключение конкретных правил:
```bash
ansible-lint roles/ -x schema,package-latest
```

### Конфликт версий зависимостей в CI/CD

**Причина:** Разные версии ролей в development и production окружениях.

**Решение:**
```yaml
# requirements.yml с фиксированными версиями
---
roles:
  - name: geerlingguy.nginx
    version: "3.2.0"  # Точная версия для production

# Использование block в плейбуке для изоляции
- block:
    - role: geerlingguy.nginx
      vars:
        nginx_version: "1.24.0"
  when: environment == "production"
```

### Роль не работает в air-gapped среде

**Причина:** Отсутствие доступа к Galaxy или внешним репозиториям.

**Решение:**
```bash
# Предварительная загрузка ролей
ansible-galaxy role download -r requirements.yml --output-path ./offline-roles/

# Установка из локального кэша
ansible-galaxy role install ./offline-roles/geerlingguy.nginx/

# Настройка локального сервера Galaxy (для больших команд)
# Используйте pulldist или автоматизированные зеркала
```

---

## Best Practices

### Выбор стратегии

1. **Начинайте с Component-based:** Это самый простой и рекомендуемый подход для большинства проектов.
2. **Используйте Layered для Enterprise:** Когда необходимы строгие стандарты и compliance.
3. **Применяйте Composite/Utility для масштабируемых проектов:** Когда есть повторяющиеся паттерны.
4. **Избегайте Micro-roles без необходимости:** Они добавляют сложность оркестрации.

### Проектирование ролей

1. **Одна роль = одна ответственность:** Не объединяйте несколько компонентов в одну роль.
2. **Используйте argument_specs:** Всегда определяйте входные параметры roles.
3. **Документируйте роли:** Добавляйте README.md с описанием назначения и параметров.
4. **Версионируйте роли:** Используйте семантическое версионирование.

### Управление зависимостями

1. **Предпочитайте явные зависимости:** Используйте `include_role` вместо `meta/main.yml`.
2. **Ограничивайте глубину зависимостей:** Максимум 2-3 уровня.
3. **Используйте версионирование:** Указывайте конкретные версии в `requirements.yml`.
4. **Тестируйте зависимости:** Проверяйте совместимость версий.

### Тестирование

1. **Используйте Molecule:** Тестируйте роли в изолированных средах.
2. **Тестируйте каждый сценарий:** Используйте `--scenario-name` для разных стратегий.
3. **Запускайте интеграционные тесты:** Проверяйте взаимодействие ролей.
4. **Используйте ansible-lint:** Проверяйте синтаксис и стиль перед коммитом.

### Миграция

1. **Начинайте с мелких изменений:** Выделяйте компоненты по одному.
2. **Сохраняйте обратную совместимость:** Не ломайте существующие плейбуки.
3. **Тестируйте после каждого шага:** Убедитесь, что изменения не нарушают работу.
4. **Документируйте изменения:** Описывайте что изменилось и почему.

### CI/CD и автоматизация

1. **Интегрируйте линтинг в pipeline:** Запускайте `ansible-lint` на каждом PR. Используйте `ansible-lint` в pre-commit hooks.
2. **Автоматическое тестирование:** Запускайте Molecule в CI (GitHub Actions, GitLab CI) для каждой роли.
3. **Проверка изменений:** Используйте `ansible-playbook --check --diff` для валидации без применения.
4. **Автоматическое обновление зависимостей:** Используйте Renovate или Dependabot для `requirements.yml`.

### Безопасность

1. **Секреты вне ролей:** Никогда не храните пароли/ключи в `defaults/main.yml` или репозитории.
2. **Используйте Ansible Vault:** Шифруйте чувствительные переменные (`vault_`-префикс).
3. **Минимальные привилегии:** Используйте `become: false` там, где это возможно. Разделяйте `become_method`.
4. **Аудит зависимостей:** Регулярно проверяйте роли из Galaxy на уязвимости (`ansible-galaxy role list --format json`).
5. **no_log для чувствительных задач:** Указывайте `no_log: true` для задач с секретами.

### Change Management

1. **Атомарность:** Каждая роль должна выполнять одно логическое изменение (установка, конфигурация или удаление).
2. **Обратимость:** Включайте задачи отката (`rollback.yml`) для критически важных изменений.
3. **Валидация:** После выполнения роли добавляйте задачу проверки (`validate.yml`) с `changed_when: false`.
4. **Теги:** Используйте теги `pre_deploy`, `deploy`, `rollback`, `validate` для фильтрации этапов change management.

### Observability

1. **Структурированные логи:** Используйте `ansible.builtin.debug` с четкими `msg` для ключевых этапов.
2. **Метрики:** Регистрируйте результаты выполнения задач (`register`) для последующей агрегации в Prometheus/Grafana.
3. **Callback-плагины:** Настройте `json` или `yaml` callback для отправки результатов в централизованный лог-агрегатор.
4. **Вербозность:** Используйте `verbosity` в задачах для контроля объема вывода в production.

### Compliance

1. **Валидация аргументов:** Всегда используйте `meta/argument_specs.yml` для проверки входных параметров.
2. **Документация:** Каждая роль должна иметь README с описанием соответствия требованиям compliance.
3. **Версионирование:** Используйте Git tags для отслеживания изменений, влияющих на compliance.
4. **Аудит:** Настройте `callback_whitelist` для логирования всех изменений во внешний SIEM.

### Документирование

1. **README.md:** Описание назначения, поддерживаемые ОС, входные параметры, примеры использования.
2. **CHANGELOG.md:** История изменений по семантическому версионированию.
3. **meta/main.yml:** Заполняйте `galaxy_info` (author, license, description) и `dependencies`.
4. **Примеры:** Добавляйте готовые плейбуки в `examples/` или `docs/`.

### Чистка и обслуживание

1. **Регулярный аудит:** Удаляйте неиспользуемые роли, обновляйте устаревшие зависимости.
2. **Стандартизация имен:** Используйте префиксы для утилитарных ролей (`lib_`, `util_`).
3. **Единый стиль:** Придерживайтесь соглашений по именованию переменных (`snake_case`), структуре каталогов.
4. **Архивация версий:** Не удаляйте старые версии из Galaxy/Git; используйте теги.

---

## Edge Cases

### Роли с одинаковыми именами

Если две роли имеют одинаковое имя, приоритет определяется порядком в `ansible.cfg`:

```ini
# ansible.cfg
[defaults]
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
```

### Циклические зависимости

Если_ROLE_A зависит от ROLE_B, а ROLE_B от ROLE_A:

```bash
# Решение: вынос общего кода в Utility-роль
# Было:
#   roles/A -> roles/B -> roles/A (цикл)
# Стало:
#   roles/A -> lib_common
#   roles/B -> lib_common
```

### Конфликт имен обработчиков

Если две роли определяют обработчики с одинаковыми именами:

```yaml
# Решение: использование namespace в именах обработчиков
# roles/nginx/handlers/main.yml
- name: nginx_restart
  ansible.builtin.service:
    name: nginx
    state: restarted

# roles/php/handlers/main.yml
- name: php_restart
  ansible.builtin.service:
    name: php-fpm
    state: restarted
```

### Динамические зависимости

Для условных зависимостей используйте `when` в `meta/main.yml`:

```yaml
# roles/web_server/meta/main.yml
---
galaxy_info:
  role_name: web_server
dependencies:
  - role: nginx
    when: use_nginx | bool
  - role: apache
    when: use_apache | bool
```

### Удаление устаревших ролей

```bash
# Просмотр всех установленных ролей
ansible-galaxy role list

# Удаление конкретной роли
ansible-galaxy role uninstall geerlingguy.nginx

# Удаление всех ролей (ОСТОРОЖНО!)
ansible-galaxy role uninstall --all
```

### Роли в air-graded среде

**Проблема:** Нет доступа к Galaxy для установки зависимостей.

**Решение:**
```bash
# Предварительная загрузка всех ролей
ansible-galaxy role download -r requirements.yml --output-path ./offline-roles/

# Использование локального репозитория
mkdir -p /opt/ansible/roles/
cp -r offline-roles/* /opt/ansible/roles/

# Настройка ansible.cfg
cat > ansible.cfg << 'EOF'
[defaults]
roles_path = /opt/ansible/roles:./roles
EOF
```

### Многоквантовая среда (multi-tenant)

**Проблема:** Одна роль используется в нескольких окружениях (dev/stage/prod) с разными требованиями.

**Решение:**
- Используйте `defaults/main.yml` для общих значений.
- Переопределяйте окружение-специфичные параметры через `group_vars/` или `host_vars/`.
- Используйте `include_vars` для динамической загрузки конфигураций окружения.

### Откат изменений в production

**Проблема:** Необходимость быстрого отката развертывания без полного перезапуска плейбука.

**Решение:**
- Разделите задачи на `deploy.yml` и `rollback.yml`.
- Используйте `meta: end_role` для досрочного завершения при обнаружении проблем.
- Сохраняйте снапшоты конфигураций перед применением изменений.

### Зависимости с нарушенными ссылками

**Проблема:** Внешняя роль из Galaxy удалена или перемещена.

**Решение:**
```bash
# Проверка целостности зависимостей
ansible-galaxy role list --format json | jq '.[] | select(.installed == true)'

# Восстановление из Git-резервной копии
git clone https://github.com/your-org/ansible-role-nginx.git roles/geerlingguy.nginx

# Использование source control для всех критичных ролей
```

### См. также

- [Структура роли](structure.md) — детальное описание каталогов (tasks, vars, meta) и инициализации.
- [Utility Role Pattern](utility_role_pattern.md) — использование ролей в качестве библиотек.
- [Создание и использование ролей](usage.md) — техническая реализация подключения (`import_role`, `include_role`).
- [Управление выполнением и отладка ролей](task-execution-and-debugging.md) — безопасность роли при rolling-деплое, `run_once`, `debugger`.
- [Decision Framework](decision_framework.md) — когда использовать роль, плейбук или коллекцию.
