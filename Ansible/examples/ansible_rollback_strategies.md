# Стратегии отката (rollback) в Ansible

## Определения

**Rollback (откат)** — процесс возврата системы к предыдущему стабильному состоянию после неудачного развертывания или изменения. В контексте Ansible это означает автоматизацию отката изменений, примененных плейбуком, ролью или ad-hoc командой.

**Blue/Green deployment** — стратегия развертывания, при которой новая версия развертывается параллельно со старой средой, и переключение трафика происходит атомарно. В случае проблем откат выполняется мгновенно путем переключения обратно на старую среду.

**Canary deployment** — стратегия развертывания, при которой новая версия сначала развертывается на небольшом подмножестве инфраструктуры (1–5% хостов), и только после успешной проверки развертывание продолжается на остальной инфраструктуре.

**Feature flag (флаг функциональности)** — механизм, который позволяет включать или выключать функциональность без развертывания нового кода. В Ansible это может означать использование переменных, `set_fact`, или внешних систем управления конфигурациями.

**Rollback plan (план отката)** — документированный процесс отката, который описывает шаги, необходимые для возврата системы в стабильное состояние, включая ответственных, maintenance windows и критерии запуска.

**Snapshot/backup (снапшот/бэкап)** — резервная копия состояния системы перед развертыванием, используемая для отката. Включает конфигурационные файлы, артефакты приложения и, при необходимости, дампы баз данных.

**Health check (проверка работоспособности)** — автоматизированная проверка после развертывания, которая определяет, требуется ли откат. В SRE-практике health check — это первая линия обороны против каскадных сбоев.

**Blast Radius (радиус поражения)** — масштаб последствий при сбое деплоя. Ограничивается параметрами `serial`, `max_fail_percentage` и стратегией деплоя. Чем меньше blast radius, тем безопаснее деплой и легче откат.

**MTTR (Mean Time To Repair/Recovery)** — среднее время восстановления после сбоя. Автоматизированный откат напрямую снижает MTTR за счет исключения ручного вмешательства.

**RPO (Recovery Point Objective)** — максимально допустимый интервал потери данных, определяющий частоту создания бэкапов. Например, RPO=15 минут означает, что при сбое можно потерять не более 15 минут данных.

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления после сбоя. Определяет, как быстро должен работать процесс отката. В production-среде RTO часто составляет 5–30 минут.

**Configuration drift (дрейф конфигурации)** — неконтролируемое отклонение фактического состояния хоста от desired state. Дрейф часто является причиной неудачного деплоя и требует отката. Подробнее: **[Обнаружение дрейфа конфигурации](ansible_configuration_drift.md)**.

**Block/Rescue/Always** — встроенный механизм Ansible для атомарных изменений с автоматическим откатом при ошибке. `block` содержит задачи деплоя, `rescue` — задачи отката, `always` — финальные действия (уведомления, очистка).

## Базовые концепции

### Принципы автоматизированного отката

1. **Automated rollback** — откат должен быть автоматизированным, а не ручным. Ручной откат увеличивает MTTR и риск человеческой ошибки.
2. **Idempotent rollback** — повторный запуск rollback playbook не должен вызывать ошибок или дополнительных изменений.
3. **Tested rollback** — регулярно тестируйте процесс отката на staging-среде. Откат, который не тестировался, не работает в production.
4. **Fast rollback** — время отката должно быть минимальным (цель: <5 минут для stateless-сервисов, <15 минут для stateful).
5. **Safe rollback** — откат не должен усугублять проблему (например, не удалять данные при откате, не ломать зависимости).
6. **Documented rollback** — каждый процесс отката должен быть документирован в runbook с явными критериями запуска.
7. **SLO-aware rollback** — откат должен triggering при нарушении SLO (Service Level Objective), а не только при падении health check.

### Жизненный цикл развертывания с откатом

```
Pre-deployment
    ├── Определение RPO/RTO для компонента
    ├── Создание снапшота/бэкапа конфигураций и данных
    ├── Проверка работоспособности (pre-flight checks)
    ├── Уведомление stakeholders (ops, monitoring, on-call)
    └── Блокировка новых изменений (change freeze)
            ↓
Deployment
    ├── Применение изменений через Ansible
    │   ├── serial: "10%" (ограничение blast radius)
    │   ├── max_fail_percentage: 5
    │   └── throttle: 10 (ограничение параллелизма)
    ├── Проверка health check после каждого батча
    └── Мониторинг метрик (error rate, latency, saturation)
            ↓
        [Success] ────→ Post-deployment
            ├── Валидация SLO
            ├── Уведомление об успехе
            └── Разблокировка изменений
            ↓
        [Failure] ────→ Rollback
            ├── Анализ корневой причины (root cause)
            ├── Выбор стратегии отката:
            │   ├── block/rescue (внутри плейбука)
            │   ├── import_playbook (отдельный плейбук)
            │   ├── blue/green переключение
            │   └── package downgrade
            ├── Восстановление из бэкапа
            ├── Откат миграций БД (если применимо)
            ├── Перезапуск сервисов
            ├── Проверка работоспособности после отката
            ├── Уведомление stakeholders
            └── Постмортем (post-mortem)
```

### Ключевые метрики SRE/DevOps

| Метрика | Описание | Влияние на rollback |
|---|---|---|
| **MTTR** | Среднее время восстановления | Автоматизированный откат снижает MTTR с 45+ до <5 минут |
| **Change Failure Rate** | Процент изменений, приведших к сбою | Хороший rollback снижает fear of change, увеличивая пропускную способность изменений |
| **Blast Radius** | Масштаб последствий при сбое | Ограничивается `serial`, `max_fail_percentage`, canary-подходом |
| **RTO** | Время восстановления | Определяет выбор стратегии отката (blue/green для <1 мин, package downgrade для <5 мин) |
| **RPO** | Потеря данных | Определяет частоту бэкапов и тип snapshot (LVM/ZFS для RPO<1 мин) |

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible Core | 2.15+ | `ansible --version` |
| Python | 3.10+ | `python3 --version` |
| OpenSSH | 8.0+ | `ssh -V` |
| Backup tool | Restic/Borg/rsync | `restic version` или `borg --version` |
| Database client | psql/mysql | `psql --version` или `mysql --version` |

### Ключевые принципы

1. **Automated rollback** — откат должен быть автоматизированным, а не ручным.
2. **Idempotent rollback** — повторный запуск rollback playbook не должен вызывать ошибок.
3. **Tested rollback** — регулярно тестируйте процесс отката на staging.
4. **Fast rollback** — время отката должно быть минимальным (цель: <5 минут).
5. **Safe rollback** — откат не должен усугублять проблему (например, не удалять данные при откате).
6. **SLO-aware rollback** — откат должен triggering при нарушении SLO, а не только при падении health check.
7. **Documented rollback** — каждый процесс отката должен быть документирован в runbook.

## Практические сценарии

### Сценарий 1: Rollback с использованием block/rescue

Атомарный откат внутри плейбука с использованием встроенного механизма `block/rescue/always`. Это наиболее предпочтительный способ для stateless-сервисов, так как он не требует внешних плейбуков и работает на уровне задачи.

```yaml
---
- name: Развертывание с атомарным откатом
  hosts: webservers
  become: true
  vars:
    app_version: "v2.1.0"
    rollback_version: "v2.0.0"
    backup_dir: "/var/backups/ansible-rollback"

  tasks:
    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0750'

    - name: Создание бэкапа конфигураций
      ansible.builtin.copy:
        src: "{{ item }}"
        dest: "{{ backup_dir }}/{{ item | basename }}"
        remote_src: yes
      loop:
        - /etc/nginx/nginx.conf
        - /etc/systemd/system/app.service

    - name: Создание снапшота приложения
      ansible.builtin.command: tar czf {{ backup_dir }}/app-{{ ansible_date_time.date }}.tar.gz /opt/app
      register: snapshot_result
      changed_when: snapshot_result.rc == 0

    - name: Развертывание новой версии
      ansible.builtin.unarchive:
        src: "https://releases.example.com/app-{{ app_version }}.tar.gz"
        dest: /opt/app
        remote_src: yes
      register: deploy_result
      notify: Restart app

    - name: Проверка работоспособности приложения
      ansible.builtin.uri:
        url: http://localhost:8080/health
        status_code: 200
        timeout: 10
      register: health_check
      until: health_check.status == 200
      retries: 5
      delay: 10

  handlers:
    - name: Restart app
      ansible.builtin.systemd:
        name: app
        state: restarted

  rescue:
    - name: Остановка приложения
      ansible.builtin.systemd:
        name: app
        state: stopped

    - name: Восстановление предыдущей версии
      ansible.builtin.unarchive:
        src: "https://releases.example.com/app-{{ rollback_version }}.tar.gz"
        dest: /opt/app
        remote_src: yes

    - name: Восстановление конфигураций
      ansible.builtin.copy:
        src: "{{ backup_dir }}/{{ item | basename }}"
        dest: "{{ item }}"
        remote_src: yes
        owner: root
        mode: '0644'
      loop:
        - /etc/nginx/nginx.conf
        - /etc/systemd/system/app.service
      notify: Restart app

    - name: Уведомление об ошибке деплоя
      ansible.builtin.debug:
        msg: "Деплой не удался, выполнен откат на версию {{ rollback_version }}"
      delegate_to: localhost
```

**Валидация:**

```bash
# Запуск деплоя с атомарным откатом
ansible-playbook deploy_with_atomic_rollback.yml
# → если деплой успешен, rescue блок не выполняется
# → если деплой падает, автоматически выполняется rescue

# Проверка, что откат сработал
systemctl status app
# → активен на предыдущей версии

# Проверка конфигураций
diff /etc/nginx/nginx.conf /var/backups/ansible-rollback/nginx.conf
# → файлы идентичны (откат успешен)
```

### Сценарий 2: Blue/Green deployment с Ansible

Развертывание в параллельной среде с атомарным переключением трафика. Подходит для инфраструктуры с duplicated environments (Blue/Green) и load balancer (HAProxy/Nginx).

```yaml
---
- name: Blue/Green deployment
  hosts: green
  become: true
  vars:
    app_version: "v2.1.0"
    green_lb_port: 8081
    blue_lb_port: 8080
    switch_traffic: true

  tasks:
    - name: Развертывание в Green среде
      ansible.builtin.unarchive:
        src: "https://releases.example.com/app-{{ app_version }}.tar.gz"
        dest: /opt/app
        remote_src: yes
      register: green_deploy

    - name: Запуск Green приложения
      ansible.builtin.systemd:
        name: app-green
        state: started
        enabled: yes

    - name: Проверка Green приложения
      ansible.builtin.uri:
        url: "http://localhost:{{ green_lb_port }}/health"
        status_code: 200
        timeout: 10
      register: green_health_check
      until: green_health_check.status == 200
      retries: 5
      delay: 10

    - name: Атомарное переключение трафика
      ansible.builtin.command: >
        curl -X POST http://localhost:8080/api/v1/switch
        -H "Content-Type: application/json"
        -d '{"target": "green", "version": "{{ app_version }}"}'
      register: switch_result
      when: switch_traffic | default(true)
      changed_when: "'switched' in switch_result.stdout"

    - name: Откат на Blue при ошибке
      ansible.builtin.import_playbook: rollback_to_blue.yml
      when: green_health_check is failed or switch_result is failed
```

**Rollback to Blue (`rollback_to_blue.yml`):**

```yaml
---
- name: Rollback to Blue
  hosts: blue
  become: true
  tasks:
    - name: Переключение трафика на Blue
      ansible.builtin.command: >
        curl -X POST http://localhost:8080/api/v1/switch
        -H "Content-Type: application/json"
        -d '{"target": "blue", "version": "v2.0.0"}'
      register: blue_switch
      changed_when: "'switched' in blue_switch.stdout"

    - name: Остановка Green приложения
      ansible.builtin.systemd:
        name: app-green
        state: stopped
        enabled: no
```

**Валидация:**

```bash
# Запуск Blue/Green deployment
ansible-playbook blue_green_deploy.yml
# → развертывает в Green, проверяет, переключает трафик

# В случае ошибки автоматически переключает обратно на Blue

# Проверка текущей активной среды
curl http://localhost:8080/api/v1/status
# → {"active": "green", "version": "v2.1.0"} или {"active": "blue", "version": "v2.0.0"}
```

### Сценарий 3: Rollback миграций базы данных

Автоматизация отката миграций базы данных с использованием версионирования. Важно: откат миграций БД требует согласованности с кодом приложения (см. паттерн Expand-Contract).

```yaml
---
- name: Rollback database migrations
  hosts: db_servers
  become: true
  vars:
    migration_tool: "alembic"
    migration_dir: "/opt/app/migrations"
    rollback_version: "v2.0.0"
    db_url: "postgresql://app:password@localhost:5432/app_production"

  tasks:
    - name: Установка инструмента миграций
      ansible.builtin.package:
        name:
          - python3-alembic
          - python3-psycopg2
        state: present

    - name: Проверка текущей версии миграции
      ansible.builtin.command: alembic current --url {{ db_url }}
      register: current_migration
      changed_when: false

    - name: Откат миграций до предыдущей версии
      ansible.builtin.command: alembic downgrade {{ rollback_version }} --url {{ db_url }}
      register: rollback_migration
      changed_when: rollback_migration.rc == 0

    - name: Проверка отката миграций
      ansible.builtin.command: alembic current --url {{ db_url }}
      register: after_rollback_migration
      changed_when: false

    - name: Убедиться, что откат успешен
      ansible.builtin.assert:
        that:
          - after_rollback_migration.stdout is search(rollback_version)
        fail_msg: "Rollback failed: current version is {{ after_rollback_migration.stdout }}"
        success_msg: "Rollback successful: database at version {{ rollback_version }}"
```

**Валидация:**

```bash
# Запуск отката миграций
ansible-playbook rollback_migrations.yml
# → откатывает миграции до указанной версии

# Проверка текущей версии
alembic current --url postgresql://app:password@localhost:5432/app_production
# → v2.0.0

# Проверка целостности БД
psql -U app -d app_production -c "SELECT count(*) FROM users;"
# → данные на месте
```

> **Production note:** Откат миграций БД — операция рискованная. Используйте паттерн **Expand-Contract** для обеспечения обратной совместимости. Никогда не откатывайте только код, оставляя новую миграцию — это ломает старую версию. Детали: **[Стратегии отката данных](../../Databases/Concepts/rollback_strategies.md)**.

### Сценарий 4: Rollback конфигураций с использованием Git

Использование Git для отслеживания изменений конфигураций и отката к предыдущему стабильному коммиту.

```yaml
---
- name: Rollback конфигураций через Git
  hosts: all
  become: true
  vars:
    config_repo: "https://github.com/example/configs.git"
    config_dir: "/etc/ansible-configs"
    rollback_commit: "abc123"

  tasks:
    - name: Установка Git
      ansible.builtin.package:
        name: git
        state: present

    - name: Клонирование репозитория конфигураций
      ansible.builtin.git:
        repo: "{{ config_repo }}"
        dest: "{{ config_dir }}"
        version: main
        force: yes
      register: git_clone

    - name: Откат к предыдущему коммиту
      ansible.builtin.command: git checkout {{ rollback_commit }} -- {{ config_dir }}
      args:
        chdir: "{{ config_dir }}"
      register: git_rollback
      changed_when: "'Switched' in git_rollback.stdout"

    - name: Развертывание откатанных конфигураций
      ansible.builtin.copy:
        src: "{{ config_dir }}/{{ item }}"
        dest: "/etc/{{ item }}"
        remote_src: yes
        owner: root
        mode: '0644'
      loop:
        - nginx/nginx.conf
        - ssh/sshd_config
      notify: Restart services

  handlers:
    - name: Restart services
      ansible.builtin.systemd:
        name: "{{ item }}"
        state: restarted
      loop:
        - nginx
        - sshd
```

**Валидация:**

```bash
# Запуск rollback через Git
ansible-playbook rollback_git.yml
# → откатывает конфигурации к указанному коммиту

# Проверка текущего коммита
git -C /etc/ansible-configs log --oneline -1
# → abc123 Rollback to previous stable version

# Проверка конфигураций
diff /etc/nginx/nginx.conf /etc/ansible-configs/nginx/nginx.conf
# → файлы идентичны
```

### Сценарий 5: Rollback пакетов с использованием package downgrade

Откат пакетов к предыдущей версии с учетом особенностей разных ОС. Важно для SRE-сценариев, где обновление пакета сломало зависимость.

```yaml
---
- name: Rollback пакетов с кросс-платформенным откатом
  hosts: webservers
  become: true
  vars:
    pkg_name: "nginx"
    previous_version:
      Debian: "1.18.0-6"
      RedHat: "1.18.0-6.el9"
      Alpine: "1.18.0-r6"
    service_name: "nginx"

  tasks:
    - name: Откат пакета (Debian/Ubuntu)
      ansible.builtin.apt:
        name: "{{ pkg_name }}={{ previous_version }}"
        state: present
        allow_downgrade: yes
      when: ansible_facts['os_family'] == 'Debian'
      register: pkg_rollback_deb

    - name: Откат пакета (RedHat/Fedora/Rocky/Alma)
      ansible.builtin.dnf:
        name: "{{ pkg_name }}-{{ previous_version }}"
        state: downgrade
      when: ansible_facts['os_family'] == 'RedHat'
      register: pkg_rollback_rhel

    - name: Откат пакета (Alpine)
      ansible.builtin.apk:
        name: "{{ pkg_name }}={{ previous_version }}"
        state: present
      when: ansible_facts['distribution'] == 'Alpine'
      register: pkg_rollback_alpine

    - name: Перезапуск сервиса после отката
      ansible.builtin.systemd:
        name: "{{ service_name }}"
        state: restarted
      when: ansible_facts['service_mgr'] == 'systemd'

    - name: Проверка работоспособности после отката
      ansible.builtin.uri:
        url: http://localhost/health
        status_code: 200
        timeout: 10
      register: rollback_health
      until: rollback_health.status == 200
      retries: 5
      delay: 10
```

**Валидация:**

```bash
# Запуск отката пакета
ansible-playbook rollback_package.yml
# → откатывает пакет к предыдущей версии в зависимости от ОС

# Проверка версии (Debian/Ubuntu)
dpkg -l | grep nginx
# → ii  nginx  1.18.0-6

# Проверка версии (RedHat/Rocky)
rpm -q nginx
# → nginx-1.18.0-6.el9

# Проверка работоспособности
curl -f http://localhost/health
# → HTTP 200 OK
```

### Сценарий 6: Rollback с использованием Ansible Vault и версионирования

Хранение версий конфигураций в Ansible Vault и откат к предыдущей версии. Подходит для сред с требованиями к безопасности и шифрованию конфигураций.

```yaml
---
- name: Rollback с использованием Vault
  hosts: all
  become: true
  vars_files:
    - vars/vault.yml
  vars:
    current_version: "v2.1.0"
    rollback_version: "v2.0.0"
    backup_dir: "/var/backups/ansible-vault"

  tasks:
    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0750'

    - name: Проверка наличия бэкапа предыдущей версии
      ansible.builtin.stat:
        path: "{{ backup_dir }}/config-{{ rollback_version }}.yml"
      register: backup_exists

    - name: Откат конфигурации
      ansible.builtin.copy:
        src: "{{ backup_dir }}/config-{{ rollback_version }}.yml"
        dest: /etc/app/config.yml
        remote_src: yes
        owner: root
        mode: '0600'
      when: backup_exists.stat.exists
      notify: Restart app

    - name: Проверка работоспособности после отката
      ansible.builtin.uri:
        url: http://localhost:8080/health
        status_code: 200
        timeout: 10
      register: rollback_health
      until: rollback_health.status == 200
      retries: 5
      delay: 10

  handlers:
    - name: Restart app
      ansible.builtin.systemd:
        name: app
        state: restarted
```

**Валидация:**

```bash
# Запуск rollback с Vault
ansible-playbook rollback_vault.yml --vault-password-file /etc/ansible/.vault_pass
# → откатывает конфигурацию к предыдущей версии

# Проверка расшифровки
ansible-vault view {{ backup_dir }}/config-v2.0.0.yml --vault-password-file /etc/ansible/.vault_pass
# → показывает содержимое откатанной конфигурации
```

### Сценарий 7: Canary deployment с автоматическим откатом

Поэтапное развертывание на 1 хосте с автоматическим откатом при ошибке health-check. Минимизирует blast radius.

```yaml
---
- name: Canary deployment с автоматическим откатом
  hosts: webservers
  become: true
  serial: 1
  max_fail_percentage: 0
  vars:
    app_version: "v2.1.0"
    rollback_version: "v2.0.0"
    app_conf_path: "/etc/app/config.yml"
    app_port: 8080

  tasks:
    - name: Создание бэкапа конфигурации canary-хоста
      ansible.builtin.command: cp {{ app_conf_path }} {{ app_conf_path }}.bak.{{ ansible_date_time.epoch }}
      changed_when: true
      register: canary_snapshot

    - name: Деплой новой версии на canary
      ansible.builtin.template:
        src: app.conf.j2
        dest: "{{ app_conf_path }}"
      notify: Restart app
      register: canary_deploy

    - name: Проверка работоспособности canary
      ansible.builtin.uri:
        url: "http://{{ inventory_hostname }}:{{ app_port }}/health"
        status_code: 200
        timeout: 10
      register: canary_health
      retries: 10
      delay: 15
      until: canary_health.status == 200

    - name: Откат canary при неудачном health-check
      ansible.builtin.command: cp {{ app_conf_path }}.bak.{{ canary_snapshot.stdout | regex_search('\d+') }} {{ app_conf_path }}
      notify: Restart app
      when: canary_health.status != 200

    - name: Пометка canary как стабильной
      ansible.builtin.debug:
        msg: "Canary на {{ inventory_hostname }} стабилен, можно продолжать деплой"
      when: canary_health.status == 200

  handlers:
    - name: Restart app
      ansible.builtin.systemd:
        name: app
        state: restarted
```

**Валидация:**

```bash
# Запуск canary deployment
ansible-playbook canary_deploy.yml
# → деплоит на 1 хост, проверяет health
# → при ошибке автоматически откатывает
# → при успехе можно продолжать на остальные хосты

# Проверка статуса canary
curl http://canary-host:8080/health
# → HTTP 200 OK
```

### Сценарий 8: Configuration snapshot и rollback

Создание снапшота конфигурации перед изменением с использованием timestamp и восстановление при ошибке.

```yaml
---
- name: Configuration snapshot перед изменением
  hosts: all
  become: true
  vars:
    config_path: "/etc/nginx/nginx.conf"
    snapshot_dir: "/var/backups/config-snapshots"
    retention_days: 30

  tasks:
    - name: Создание директории для снапшотов
      ansible.builtin.file:
        path: "{{ snapshot_dir }}"
        state: directory
        mode: '0750'

    - name: Создание снапшота конфигурации
      ansible.builtin.command: cp {{ config_path }} {{ snapshot_dir }}/{{ config_path | basename }}.{{ ansible_date_time.epoch }}.bak
      changed_when: true
      register: snapshot
      when: ansible_facts['system'] != 'Win32NT'

    - name: Применение новой конфигурации
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: "{{ config_path }}"
      notify: Reload nginx
      register: config_change

    - name: Откат при ошибке применения конфигурации
      ansible.builtin.command: cp {{ snapshot_dir }}/{{ config_path | basename }}.{{ snapshot.stdout | regex_search('\d+') }}.bak {{ config_path }}
      when: config_change is failed

    - name: Ротация старых снапшотов (Debian/Ubuntu)
      ansible.builtin.command: find {{ snapshot_dir }} -name "*.bak" -mtime +{{ retention_days }} -delete
      when: ansible_facts['os_family'] == 'Debian'

    - name: Ротация старых снапшотов (RedHat)
      ansible.builtin.command: find {{ snapshot_dir }} -name "*.bak" -mtime +{{ retention_days }} -delete
      when: ansible_facts['os_family'] == 'RedHat'

  handlers:
    - name: Reload nginx
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

**Валидация:**

```bash
# Запуск с созданием снапшота
ansible-playbook config_snapshot.yml
# → создает снапшот, применяет конфигурацию
# → при ошибке автоматически откатывает

# Проверка снапшотов
ls -la /var/backups/config-snapshots/
# → nginx.conf.1695686400.bak  nginx.conf.1695686401.bak
```

## Операции и команды

### Основные команды для отката

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook rollback.yml` | Запуск playbook отката | `ansible-playbook rollback.yml` |
| `git checkout <commit>` | Откат файлов к коммиту | `git checkout abc123 -- /etc/nginx/` |
| `alembic downgrade <version>` | Откат миграций БД | `alembic downgrade v2.0.0` |
| `dnf downgrade <pkg>` | Откат пакета (RedHat) | `dnf downgrade nginx-1.18.0-6.el9` |
| `apt install pkg=<version>` | Установка конкретной версии (Debian) | `apt install nginx=1.18.0-6` |
| `restic restore` | Восстановление из бэкапа | `restic restore latest --target /tmp/restore` |
| `borg extract` | Восстановление из borg-бэкапа | `borg extract ::archive /path` |

### Команды для проверки отката

| Команда | Назначение | Пример |
|---|---|---|
| `systemctl status <service>` | Проверка статуса сервиса | `systemctl status nginx` |
| `curl -f http://localhost:8080/health` | Проверка работоспособности | `curl -f http://localhost:8080/health` |
| `journalctl -u <service> -n 50` | Проверка логов сервиса | `journalctl -u nginx -n 50` |
| `psql -c "SELECT ..."` | Проверка данных в БД | `psql -U app -d app -c "SELECT count(*) FROM users;"` |
| `dpkg -l \| grep <pkg>` | Проверка версии пакета (Debian) | `dpkg -l \| grep nginx` |
| `rpm -q <pkg>` | Проверка версии пакета (RedHat) | `rpm -q nginx` |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `Rollback playbook не сработал` | Ошибка в playbook или переменных | Проверьте логи Ansible (`ansible-playbook -vvv`), убедитесь в правильности переменных |
| `Откат миграций БД упал` | Данные уже изменены, откат невозможен | Используйте DBA tools для ручного отката или восстановления из бэкапа; см. паттерн Expand-Contract |
| `Rollback занял слишком много времени` | Большой объем данных или медленное хранилище | Используйте быстрые методы (blue/green, snapshot, LVM/ZFS snapshot) |
| `Откат не восстановил работоспособность` | Откат только части изменений | Убедитесь, что rollback playbook покрывает все изменения: конфигурации, пакеты, данные |
| `Данные потеряны при откате` | Откат удалил данные вместо восстановления | Проверьте логику rollback, используйте backup вместо удаления |
| `Rollback бесконечный цикл` | Откат вызывает ту же ошибку | Проверьте корневую причину ошибки перед откатом; откат не должен повторять ту же операцию |
| `Откат пакета сломал зависимости` | `dnf downgrade` нарушил граф зависимостей | Используйте `dnf history rollback` или фиксируйте версии в `requirements.yml` |
| `Configuration drift после отката` | Ручные изменения на хостах после отката | Используйте drift detection для периодического аудита; см. **[Обнаружение дрейфа конфигурации](ansible_configuration_drift.md)** |
| `Резервное копирование не покрывает RPO` | Слишком редкие бэкапы | Настройте более частые бэкапы или используйте snapshot (LVM/ZFS) для снижения RPO; см. **[Автоматизация резервного копирования](ansible_backup_automation.md)** |

## Рекомендации

### Best Practices

1. **Automated rollback** — откат должен быть автоматизированным, а не ручным.
2. **Tested rollback** — регулярно тестируйте процесс отката на staging.
3. **Fast rollback** — время отката должно быть минимальным (цель: <5 минут).
4. **Safe rollback** — откат не должен усугублять проблему.
5. **Documentation** — документируйте каждый процесс отката (runbook).
6. **Monitoring during rollback** — мониторьте систему во время отката.
7. **Post-rollback analysis** — после отката проанализируйте причину сбоя.
8. **SLO-aware rollback** — откат должен triggering при нарушении SLO, а не только при падении health check.
9. **Blast radius control** — ограничивайте `serial` и `max_fail_percentage` для минимизации поражения.
10. **Configuration snapshot** — всегда создавайте снапшот конфигураций перед изменением.
11. **Stateful service awareness** — для БД и очередей используйте паттерн Expand-Contract, а не прямой откат схемы.
12. **Molecule testing** — тестируйте rollback сценарии через Molecule на матрице платформ (Debian, Ubuntu, RHEL/Rocky, Alpine).

### Чек-лист валидации после настройки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Создание бэкапа | `ls /var/backups/ansible-rollback/` | Файлы бэкапа присутствуют |
| Rollback playbook | `ansible-playbook rollback.yml --check` | Изменения для отката определены |
| Health check после отката | `curl -f http://localhost:8080/health` | Статус 200 OK |
| Миграции БД | `alembic current --url {{ db_url }}` | Правильная версия после отката |
| Версия пакета | `dpkg -l \| grep <pkg>` или `rpm -q <pkg>` | Правильная версия после отката |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Откат невозможен | Данные уже изменены или удалены | Используйте DBA tools или восстановление из бэкапа; см. **[Стратегии отката данных](../../Databases/Concepts/rollback_strategies.md)** |
| Откат занимает много времени | Большой объем данных | Используйте быстрые методы (blue/green, snapshot, LVM/ZFS) |
| Откат вызывает новые проблемы | Неполный rollback playbook | Убедитесь, что playbook покрывает все изменения |
| Откат в production | Риск дополнительного downtime | Используйте maintenance windows, blue/green, canary с автоматическим откатом |
| Частые откаты | Нестабильные изменения | Улучшите процесс тестирования перед деплоем; добавьте canary |
| Откат миграций БД сломал код | Откат кода без отката схемы | Используйте паттерн Expand-Contract; никогда не откатывайте только код |
| `any_errors_fatal: true` | Rescue блок не выполняется | Используйте `any_errors_fatal: false` для деплоев с откатом |
| Package downgrade сломал зависимости | Граф зависимостей нарушен | Используйте `dnf history rollback` или фиксируйте версии |

## Дополнительная информация

### Смотрите также

- **[Ansible: Стратегии деплоя](../ansible_deployment_strategies.md)** — rolling updates, blue-green, canary deployment.
- **[Ansible: Обнаружение дрейфа конфигурации](ansible_configuration_drift.md)** — drift detection, remediation, compliance.
- **[Ansible: Автоматизация резервного копирования](ansible_backup_automation.md)** — создание бэкапов для отката, RPO/RTO.
- **[Ansible: Кроссплатформенный откат, тестирование и drift detection](../CrossPlatform/ansible_cross_platform_rollback_testing_drift.md)** — кросс-платформенные нюансы, block/rescue, package downgrade.
- **[Ansible: Основные концепции](../ansible_core_concepts.md)** — MTTR, Change Failure Rate, Blast Radius, идемпотентность.
- **[Ansible: Антипаттерны](../ansible_bad_practices.md)** — распространенные ошибки при деплое и откате.

### Интеграция с другими системами

| Система | Назначение | Интеграция |
|---|---|---|
| **Ansible Automation Platform** | Планирование откатов | Workflow job templates, approval gates |
| **HAProxy/Nginx** | Переключение трафика (blue/green) | API calls через `uri` модуль или `command` |
| **Git** | Версионирование конфигураций | `git` модуль или `command: git checkout` |
| **Restic/BorgBackup** | Восстановление из бэкапа | `command` модуль или `expect` модуль |
| **Nagios/Icinga** | Health check | `uri` модуль с порогами |
| **Prometheus/Alertmanager** | Мониторинг отката | Внешние скрипты → Alertmanager |

### История изменений

- **2026-09-26:** Актуализация под стандарт GEMINI.md, удален Kubernetes-сценарий (cloud-specific), добавлены SRE-метрики (MTTR, RTO, RPO, Blast Radius), расширены практические сценарии (block/rescue, package downgrade, canary, Git, Vault, snapshot), добавлены граничные случаи и рекомендации по stateful-сервисам.
