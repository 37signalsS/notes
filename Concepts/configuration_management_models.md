# Модели управления конфигурацией — Теоретический обзор

## Определения

**Управление конфигурацией** (Configuration Management, далее — CM) — это системный процесс приведения и поддержания ИТ-инфраструктуры в заранее определенном, желаемом состоянии. CM абстрагирует сложность системного администрирования, превращая настройку серверов в повторяемый и проверяемый процесс.

### Ключевые термины
*   **Желаемое состояние (Desired State):** Целевое описание системы в виде кода (YAML, DSL, HCL). Определяет, какие ресурсы должны существовать и с какими параметрами.
*   **Текущее состояние (Actual State):** Реальные параметры системы, полученные в ходе инспекции (инвентаризации фактов).
*   **Конвергенция (Convergence):** Свойство CM-системы, стремящейся минимизировать разрыв между желаемым и текущим состояниями до нуля.
*   **Идемпотентность (Idempotency):** Гарантия того, что многократное применение одной и той же конфигурации приведет к одному и тому же результату, не вызывая побочных эффектов после первого успешного выполнения. Подробнее: **[Идемпотентность](./idempotency.md)**.

Обзор инструментов: [Инструменты управления конфигурацией](./configuration_management_tools.md).

## Базовые концепции

### Императивная и Декларативная модели

Парадигмы описания конфигурации определяют способ взаимодействия инженера с системой:

*   **Императивная («Как делать»):** Описывает конкретный алгоритм действий и команды.
    *   *Механизм:* Последовательное выполнение шагов. Если один шаг падает, система может остаться в промежуточном (неконсистентном) состоянии.
    *   *Применение:* Быстрые Ad-hoc команды, скрипты первичной инициализации (bootstrap).
*   **Декларативная («Что должно быть»):** Описывает конечный результат, оставляя выбор средств реализации инструменту.
    *   *Механизм:* Инструмент строит **граф зависимостей (Dependency Graph)** между ресурсами и вычисляет необходимую дельту (Diff).
    *   *Преимущество:* Автоматическое разрешение зависимостей и высокая предсказуемость. Большинство современных IaC-инструментов (Terraform, Puppet) являются декларативными.

### Модели доставки: Push и Pull

Определяют архитектуру сетевого взаимодействия и сторону, инициирующую изменения:

*   **Push (Проталкивание):** Центральный контроллер подключается к узлам по SSH/WinRM.
    *   *Особенности:* Не требует агентов на узлах (Agentless). Легко контролировать момент начала изменений. Зависит от доступности SSH и производительности контроллера при больших масштабах.
*   **Pull (Вытягивание):** Агент на узле периодически запрашивает конфигурацию с сервера.
    *   *Особенности:* Высокая масштабируемость (тысячи узлов). Автоматическое исправление отклонений (self-healing) происходит локально. Требует установки и обновления агентов.
*   **GitOps:** Современная эволюция Pull-модели, где Git является единственным источником правды, а контроллеры в кластере (ArgoCD, Flux) постоянно синхронизируют состояние.

Детальное сравнение: [Сравнение Push и Pull моделей](./configuration_management_push_vs_pull.md).

### Agent-based vs Agentless

Архитектура CM-системы определяет, требуется ли установка специального ПО (агента) на управляемые узлы:

**Agent-based (С агентом):**
*   **Механизм:** На каждом управляемом узле работает демон (агент), который.periodically опрашивает сервер управления, получает каталог/манифест и применяет его локально.
*   **Преимущества:**
    *   Высокая масштабируемость (десятки тысяч узлов) — дельта вычисляется на агенте, а не на контроллере.
    *   Автономность — агент может применять конфигурацию при временной потере связи с сервером.
    *   Self-healing — автоматический возврат к эталонному состоянию каждые N минут.
    *   Широкие возможности по сбору фактов (facter, grains) и аудиту.
*   **Недостатки:**
    *   Жизненный цикл агента (установка, обновление, удаление) требует отдельной автоматизации.
    *   Дополнительное потребление ресурсов (RAM, CPU) на каждом узле.
    *   Сложность отладки сетевых проблем между агентом и сервером (mTLS, сертификаты).
*   **Примеры:** Puppet, Chef, SaltStack, CFEngine.

**Agentless (Без агентов):**
*   **Механизм:** Контроллер подключается к узлам по SSH/WinRM, передает и выполняет задания удаленно. Состояние не хранится на узле.
*   **Преимущества:**
    *   Отсутствие дополнительного ПО на узлах — минимальная поверхность атаки.
    *   Простота начала использования (нет этапа provisioning агентов).
    *   Единообразие — нет проблем с версиями агентов и несовместимостью.
*   **Недостатки:**
    *   Ограничение масштабируемости (задачи выполняются последовательно или параллельно через SSH).
    *   Зависимость от стабильности SSH-соединения.
    *   Нет встроенного self-healing (требуется внешний scheduler для регулярных запусков).
*   **Примеры:** Ansible, Fabric, Pulumi (CLI mode).

**Сравнительная таблица:**

| Критерий | Agent-based | Agentless |
| :--- | :--- | :--- |
| **Установка на узлы** | Требуется (агент) | Не требуется (только SSH) |
| **Масштабируемость** | Высокая (распределенный Diff) | Средняя (ограничена SSH) |
| **Self-healing** | Встроенный (периодический цикл) | Требует внешнего планировщика |
| **Сетевые требования** | Агент инициирует соединение наружу | Контроллер подключается внутрь |
| **Потребление ресурсов** | 256 MB–1 GB RAM на агент | Минимальное на узле |
| **Скорость применения** | Зависит от интервала агента | Мгновенно (push) |
| **Восстановление после сбоя** | Агент возобновляет работу автоматически | Требуется перезапуск контроллера |

### Модель Reconciliation Loop (Цикл сверки)

Ключевой паттерн, реализуемый Pull-агентами и GitOps-контроллерами:

1.  **Read (Чтение):** Считывание текущего состояния системы (факты, ресурсы).
2.  **Compare (Сравнение):** Сопоставление текущего состояния с желаемым (из манифеста/каталога).
3.  **Diff (Разница):** Вычисление набора изменений, необходимых для достижения желаемого состояния.
4.  **Act (Действие):** Применение изменений (установка пакетов, изменение конфигов, запуск сервисов).
5.  **Report (Отчет):** Логирование результатов и отправка метрик.

Этот цикл повторяется с заданной периодичностью (по умолчанию: Puppet — 30 минут, Chef — 30 минут, SaltStack — 60 секунд). Модель является **Level-triggered** (срабатывает на отклонение, а не на событие), что гарантирует надежность: даже если одно применение не удалось, следующий цикл обнаружит расхождение и повторит попытку.

### Изменяемая и Неизменяемая инфраструктура

Подходы к жизненному циклу серверов:

*   **Изменяемая (Mutable):** Конфигурация обновляется на работающих инстансах.
    *   *Проблема:* **Дрейф конфигурации (Configuration Drift)** — накопление мелких различий между серверами из-за ручных правок, что делает инфраструктуру хрупкой (Snowflake Servers).
*   **Неизменяемая (Immutable):** Инстансы никогда не меняются после развертывания. Для внесения изменений создается новый образ (**Golden Image**), запускается новый инстанс, а старый удаляется.
    *   *Механизмы:* Использование Packer для сборки образов, Docker-контейнеры, Blue-Green развертывания.

### Управление состоянием (State Management)

*   **Stateless (Без хранения состояния):** Инструмент каждый раз запрашивает все данные у системы (Ansible).
    *   *Плюс:* Простота, отсутствие риска рассинхронизации «кода и базы».
    *   *Минус:* Медленнее на больших инфраструктурах; сложно отслеживать ресурсы, которые были удалены из кода, но остались в системе.
*   **Stateful (С хранением состояния):** Инструмент ведет локальный или удаленный файл состояния (Terraform `tfstate`).
    *   *Плюс:* Мгновенное вычисление Diff, возможность управления жизненным циклом (удаление ресурсов).
    *   *Минус:* Файл состояния сам становится критическим ресурсом, требующим блокировок (locking) и бэкапов.

## Практические сценарии

### Выявление и устранение дрейфа конфигурации

Дрейф конфигурации неизбежен в долгоживущих системах. Стратегии борьбы с ним делятся на два типа:
1.  **Проактивная (Pull-агенты):** Агенты (Puppet, Salt) работают постоянно. Любое ручное изменение файла будет перезаписано эталоном из Git в течение 30-60 минут. Это «самозалечивающаяся» инфраструктура.
2.  **Реактивная (Scheduled Push):** Регулярный запуск Ansible-плейбуков в режиме `--check` через CI/CD. Если обнаружены расхождения, генерируется алерт, и инженер инициирует исправление.

### Стратегии миграции к неизменяемой инфраструктуре

Переход от мутабельной к немутабельной модели обычно проходит через следующие этапы:
1.  **Стандартизация:** Описание текущей конфигурации в IaC (Ansible/Puppet).
2.  **Сборка образов (Golden Images):** Использование Packer для создания преднастроенных AMI (AWS) или образов ВМ с уже установленным базовым ПО.
3.  **Контейнеризация:** Перенос логики приложения в Docker-образы, где конфигурация подается через переменные окружения.
4.  **Blue-Green развертывание:** Запуск новой версии рядом со старой и переключение трафика. Это позволяет полностью отказаться от обновления пакетов на работающих серверах.

### Выбор модели под задачу

| Тип задачи | Рекомендуемая модель | Причина |
| :--- | :--- | :--- |
| **Инсталляция ОС / Bootstrap** | Императивная + Push | Разовая настройка сетевых интерфейсов и базовых пользователей. |
| **Базы данных / Stateful-сервисы** | Декларативная + Stateful CM | Необходимость бережного управления томами и жизненным циклом данных. |
| **Web-приложения / Микросервисы** | Неизменяемая + GitOps | Высокая скорость релизов, легкость масштабирования и отката. |
| **Compliance / Аудит безопасности** | Декларативная + Pull | Гарантированное соблюдение политик 24/7 без участия человека. |

**Расширенная матрица выбора модели:**

| Размер команды | Тип инфраструктуры | Рекомендуемая связка | Обоснование |
| :--- | :--- | :--- | :--- |
| **1–3 инженера** | До 50 узлов, VM | Ansible (Push) | Низкий порог входа, не нужен агент, YAML |
| **3–10 инженеров** | 50–500 узлов, гибрид | Ansible (Push) + Ansible Pull (cron) | Bootstrap через Push, self-healing через Pull |
| **10–30 инженеров** | 500–5000 узлов | Puppet/SaltStack (Pull) + Ansible (Push) | Pull для compliance, Push для ad-hoc задач |
| **30+ инженеров** | 5000+ узлов, multi-site | SaltStack (гибрид) + GitOps (K8s) | Масштабируемость, реактивность, единый control plane |
| **Edge/IoT** | Тысячи устройств | CFEngine / SaltStack (Masterless) | Минимальные ресурсы, автономная работа |

### Подходы к хранению конфигурации приложений

1.  **В репозитории с кодом (Application-centric):**
    *   *Подход:* `config.yaml` лежит рядом с `main.py`.
    *   *Когда:* Trunk-based development, микросервисы, где за код и инфраструктуру отвечает одна команда.
2.  **В отдельном репозитории (Ops-centric):**
    *   *Подход:* Централизованный репозиторий `infrastructure-configs`, где лежат настройки для всех сред.
    *   *Когда:* Жесткие требования ИБ, необходимость разделения прав доступа (разработчики не видят прод-секреты).

## Практические сценарии

### Сценарий 1: Bootstrap нового сервера (Push + Императивный)

Задача: первичная настройка нового Ubuntu-сервера (пользователи, SSH-ключи, базовые пакеты, NTP).

```bash
# Ansible: плейбук bootstrap
ansible-playbook bootstrap.yml -l new_server \
  -e "target_user=deploy" \
  -e "ssh_pub_key=file:///home/deploy/.ssh/id_rsa.pub"
```

```yaml
# bootstrap.yml
- hosts: new_servers
  become: yes
  tasks:
    - name: Создание пользователя для автоматизации
      ansible.builtin.user:
        name: "{{ target_user }}"
        shell: /bin/bash
        groups: sudo
        append: yes

    - name: Настройка SSH-ключа
      ansible.posix.authorized_key:
        user: "{{ target_user }}"
        key: "{{ ssh_pub_key }}"
        state: present

    - name: Установка базовых пакетов
      ansible.builtin.apt:
        name: [curl, wget, git, htop, iotop, tmux, vim]
        state: present
        update_cache: yes

    - name: Синхронизация времени
      ansible.builtin.package:
        name: chrony
        state: present
    - name: Запуск Chrony
      ansible.builtin.service:
        name: chrony
        state: started
        enabled: yes
```

### Сценарий 2: Compliance-проверка (Pull + Декларативный)

Задача: гарантировать, что все веб-серверы соответствуют стандарту безопасности (открытые порты, версии пакетов, права на файлы).

```bash
# Puppet: применение манифеста безопасности
sudo puppet agent --test --server puppet.example.com

# SaltStack: проверка без применения (dry-run)
sudo salt 'web*' state.apply security_compliance test=True

# Ansible: проверка дрейфа без изменений
ansible-playbook compliance_check.yml --check --diff
```

```yaml
# security_compliance.yml (Ansible)
- hosts: web_servers
  become: yes
  tasks:
    - name: Проверка открытых портов
      ansible.builtin.command: ss -tlnp
      register: listening_ports
      changed_when: false

    - name: Блокировка неразрешенных портов
      ansible.builtin.iptables:
        chain: INPUT
        protocol: tcp
        jump: DROP
        destination_port: "{{ item }}"
      loop: ["23", "3389", "5900"]
      when: listening_ports.stdout is search("{{ item }}")

    - name: Проверка версий пакетов
      ansible.builtin.package_facts:
    - name: Вывод устаревших пакетов
      ansible.builtin.debug:
        msg: >
          Пакет {{ item.key }} имеет версию {{ item.value.version }},
          рекомендуется обновление
      loop: "{{ ansible_facts.packages | dict2items }}"
      when: item.key in ['openssl', 'openssh-server'] and
            item.value.version is version('1.1.1', '<')
```

### Сценарий 3: Исправление дрейфа конфигурации (Auto-remediation)

Задача: автоматический возврат конфигурации Nginx к эталонному состоянию при обнаружении ручных правок.

```bash
# Puppet: агент автоматически исправит дрейф каждые 30 минут
# Для немедленного исправления:
sudo puppet agent --test

# SaltStack: принудительное применение состояния
sudo salt 'web*' state.apply nginx_config

# Ansible: запуск через cron для auto-remediation
# crontab: 0 */2 * * * /usr/bin/ansible-playbook /opt/cm/nginx_compliance.yml
```

```yaml
# nginx_compliance.yml (Ansible)
- hosts: web_servers
  become: yes
  tasks:
    - name: Проверка текущей конфигурации Nginx
      ansible.builtin.stat:
        path: /etc/nginx/nginx.conf
      register: nginx_conf

    - name: Сравнение с эталоном
      ansible.builtin.command: >
        diff /etc/nginx/nginx.conf
        /opt/cm/templates/nginx.conf.standard
      register: diff_result
      changed_when: diff_result.rc != 0
      failed_when: false

    - name: Восстановление эталонной конфигурации
      ansible.builtin.copy:
        src: /opt/cm/templates/nginx.conf.standard
        dest: /etc/nginx/nginx.conf
        owner: root
        group: root
        mode: '0644'
        backup: yes
      notify: restart nginx
      when: diff_result.rc != 0

  handlers:
    - name: restart nginx
      ansible.builtin.service:
        name: nginx
        state: restarted
```

### Сценарий 4: Тестирование конфигурации перед применением

Задача: проверить плейбук Ansible в изолированной среде перед прод-применением.

```bash
# Molecule: создание тестового окружения
molecule create
molecule converge
molecule verify
molecule destroy

# Test Kitchen (Chef): полный цикл тестирования
kitchen create
kitchen converge
kitchen verify
kitchen destroy

# Goss: быстрая проверка состояния системы
dgoss run nginx:latest
```

```yaml
# molecule/default/molecule.yml
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: instance
    image: ubuntu:22.04
    privileged: true
    command: /lib/systemd/systemd
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:ro
provisioner:
  name: ansible
  inventory:
    group_vars:
      all:
        nginx_worker_processes: 2
verifier:
  name: ansible
test_sequence:
  - dependency
  - cleanup
  - destroy
  - syntax
  - create
  - prepare
  - converge
  - idempotence
  - verify
  - cleanup
  - destroy
```

```yaml
# validation.yml (Ansible верификация)
- hosts: instance
  become: yes
  tasks:
    - name: Проверка установки Nginx
      ansible.builtin.command: nginx -v
      register: nginx_version
      changed_when: false

    - name: Проверка запуска сервиса
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: yes

    - name: Проверка прослушивания порта
      ansible.builtin.wait_for:
        port: 80
        timeout: 5
```

## Дополнительная информация

### Тестирование и валидация конфигураций

Тестирование CM-конфигураций гарантирует, что изменения не сломают существующую инфраструктуру. Существует три уровня проверки:

**Уровень 1: Статический анализ (Linting)**
```bash
# Ansible
ansible-lint playbook.yml
yamllint playbook.yml

# Puppet
puppet-lint manifests/

# Chef
cookstyle lint cookbooks/
```

**Уровень 2: Тестирование в изолированной среде**
```bash
# Molecule (Ansible) — полный цикл
molecule create       # Создание контейнера
molecule converge     # Применение плейбука
molecule idempotence  # Проверка идемпотентности
molecule verify       # Запуск тестов верификации
molecule destroy      # Очистка

# Test Kitchen (Chef)
kitchen create
kitchen converge
kitchen verify
kitchen destroy
```

**Уровень 3: Инфраструктурные тесты (Проверка состояния)**
```bash
# Goss — быстрая проверка состояния системы
cat > goss.yaml <<EOF
package:
  nginx:
    installed: true
  chrony:
    installed: true
service:
  nginx:
    enabled: true
    running: true
listening:
  tcp:80:
    listening: true
user:
  deploy:
    exists: true
    groups:
      - deploy
      - sudo
EOF
goss validate

# Testinfra (Python)
pytest --tb=short tests/
```

**Сравнение фреймворков тестирования:**

| Фреймворк | Язык | Инструменты | Сценарий использования |
| :--- | :--- | :--- | :--- |
| **Molecule** | YAML + Python | Ansible, Docker, Podman | Тестирование ролей Ansible |
| **Test Kitchen** | Ruby | Chef, Docker, Vagrant | Тестирование cookbook'ов Chef |
| **Goss** | YAML | Любая инфраструктура | Быстрая проверка состояния ОС |
| **Testinfra** | Python | SSH, Docker | Проверка через Python API |
| **InSpec** | Ruby DSL | Chef, SSH, WinRM | Compliance-тесты безопасности |

### Мониторинг и логирование CM-операций

Контроль выполнения задач CM критичен для обнаружения ошибок и аудита.

**Централизованное логирование:**
```bash
# Ansible: настройка логирования в ansible.cfg
[defaults]
log_path = /var/log/ansible/ansible.log
callback_whitelist = profile_tasks, timer, json

# Включение профилирования по задачам
ANSIBLE_PROFILE_TASKS=true ansible-playbook site.yml

# Сохранение логов с меткой времени
ansible-playbook site.yml 2>&1 | \
  tee /var/log/ansible_deploy_$(date +%Y%m%d_%H%M%S).log
```

**Интеграция с Prometheus:**
```yaml
# Пример exporter для Puppet (puppet_exporter)
# Метрики: puppet_agent_enabled, puppet_agent_status, catalog_compile_time

# Пример метрик Ansible через callback-плагин
# ansible_playbook_duration_seconds
# ansible_task_duration_seconds{task="...", status="ok|changed|failed"}
```

**Метрики для мониторинга:**

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| **CM-операция_duration** | Время выполнения playbook/manifest | > 10 минут |
| **CM-операция_success_rate** | Доля успешных задач | < 95% |
| **drift_detection_count** | Количество обнаруженных drift-хостов | > 0 (для compliance) |
| **agent_last_run** | Время последнего запуска агента | > 2 часов |

### Безопасность в управлении конфигурацией

**Принципы:**

1.  **Least Privilege:** Выделенный пользователь автоматизации с минимальными правами sudo.
2.  **Секреты в коде — запрещены:** Используйте Ansible Vault, HashiCorp Vault или SOPS.
3.  **Аудит всех изменений:** Вся история — в Git, все запуски логируются.
4.  **Безопасность транспорта:** SSH — с проверкой ключей хостов, агенты — через mTLS.

**Практические рекомендации:**
```bash
# Ansible Vault: шифрование секретов
ansible-vault create secrets.yml
ansible-vault edit secrets.yml
ansible-playbook site.yml --ask-vault-pass

# HashiCorp Vault: динамические секреты
vault read ssh/creds/web_server

# Проверка SSL-сертификатов агентов (Puppet)
sudo puppetserver ca list --all
sudo puppetserver ca sign --certname agent01.example.com
```

### Эволюция инструментов управления конфигурацией

| Период | Событие |
| :--- | :--- |
| **1993** | Появление CFEngine — рождение концепции «обещаний» (promises) и идемпотентности |
| **2005** | Релиз Puppet — популяризация декларативного подхода в Open Source |
| **2009** | Релиз Chef — начало эпохи Infrastructure as Code через Ruby DSL |
| **2011** | Релиз SaltStack — фокус на скорость, ZeroMQ, событийная оркестрация |
| **2012** | Релиз Ansible — успех благодаря простоте, YAML и agentless-архитектуре |
| **2015** | Red Hat приобретает Ansible; 시작ается эра GitOps (ArgoCD, Flux) |
| **2020+** | Смещение к GitOps и Kubernetes-операторам как основному способу управления |
| **2023** | Broadcom завершает покупку VMware (включая SaltStack); CFEngine продолжает развиваться |
| **2024–2026** | Policy-as-Code (OPA, Sentinel), Secrets Management (Vault), Crossplane для управления инфраструктурой через Kubernetes API |

### Лучшие практики для масштабных систем

*   **Принцип DRY (Don't Repeat Yourself):** Используйте шаблонизацию (Jinja2) и общие роли/модули.
*   **Иерархия данных (Separation of Concerns):** Разделяйте логику (код CM) и данные (переменные). В Ansible это `roles` vs `group_vars`, в Puppet — `manifests` vs `Hiera`.
*   **Тестирование инфраструктуры:** Используйте Molecule или Test Kitchen для проверки конфигурации на временных инстансах перед деплоем в Production.
*   **Версионирование:** Все изменения — через Git с code review. Никаких ручных правок на серверах.
*   **Rollback-стратегия:** Всегда имейте план отката. Для декларативных систем достаточно вернуть предыдущий коммит в Git.

### См. также
*   **[Инструменты управления конфигурацией](./configuration_management_tools.md)**
*   **[Сравнение Push и Pull моделей](./configuration_management_push_vs_pull.md)**
*   **[GitOps: Обзор](../GitOps/GitOps_overview.md)**
*   **[Идемпотентность](./idempotency.md)**
*   **[Обзор IaC](./iac_overview.md)**
