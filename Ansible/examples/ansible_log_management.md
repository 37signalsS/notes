# Управление логами и централизованный сбор через Ansible

> **Примечание:** этот файл покрывает развёртывание агентов сбора, настройку ротации и доставки логов на управляемых хостах. Вопросы логирования самого Ansible и callback-плагинов см. в **[Ansible/ansible-callback-plugins.md](../ansible-callback-plugins.md)**. Вопросы защиты секретов и `no_log` — в **[Ansible/ansible_security_best_practices.md](../ansible_security_best_practices.md)**.

## Определения

**Централизованный сбор логов** — процесс агрегации логов с управляемых хостов в одно хранилище для поиска, корреляции и долгосрочного хранения. В контексте Ansible это bedeutet автоматизация развертывания агентов сбора, настройки ротации и доставки логов без ручного редактирования конфигураций на каждом сервере.

**Structured logging** — формат логов, где каждое событие представлено как структурированный объект (обычно JSON) с фиксированными полями: `timestamp`, `level`, `service`, `message`, `trace_id`. Позволяет эффективно парсить и индексировать логи в Elasticsearch/Loki/VictoriaLogs.

**logrotate** — механизм ротации логов на уровне ОС, который автоматически архивирует, сжимает и удаляет устаревшие файлы логов. В production-среде часто complement centralized pipeline, обеспечивая локальный fallback.

**rsyslog** — высокопроизводительный демон сбора и пересылки логов, поддерживающий фильтры, модули и удаленную отправку в Loki/ELK/Kafka.

**journald** — системный демон сбора логов в Linux, который хранит события в бинарном формате и предоставляет `journalctl` для поиска. Может выступать источником для rsyslog или Vector.

**Vector** — легковесный агрегатор логов и метрик, который заменяет rsyslog/filebeat в современных стеках и отправляет данные в Loki/ELK/VictoriaLogs.

**Promtail** — агент сбора логов для Loki. Читает journald, файлы и docker logs, отправляет в Loki с метками.

**Filebeat** — легковесный шipper логов от Elastic для отправки в Elasticsearch/OpenSearch.

**Fluent Bit** — edge-агент сбора логов для контейнерных и ресурсо-ограниченных окружений.

**Retention policy** — политика хранения логов, определяющая, как долго хранить сырые и агрегированные данные. Обычно задается на уровне индекса (Elasticsearch) или хранилища (Loki/объектное хранилище).

**Backpressure** — механизм защиты от перегрузки пайплайна логов, когда источник генерирует события быстрее, чем приемник может их обработать. В Ansible это означает настройку буферов, лимитов и queue depth.

**Blast radius (радиус поражения)** — множество хостов или сервисов, затронутых при сбое конфигурации логирования. В контексте Ansible это scope плейбука (`--limit`, `serial`, tags) и наличие local fallback.

**MTTR (Mean Time To Repair)** — среднее время восстановления пайплайна логов после сбоя. Ansible снижает MTTR за счёт идемпотентных операций, pre-flight проверок и автоматизированных recovery-сценариев.

**Circuit breaker (прерыватель)** — паттерн, при котором при недоступности центрального хранилища логи буферизируются локально или отбрасываются с предотвращением переполнения диска.

**Log integrity (целостность логов)** — гарантия того, что логи не были изменены или удалены после записи. Обеспечивается append-only правами, immutable флагами и audit trail.

**Canary deployment** — постепенный rollout конфигурации логирования на подмножество хостов для проверки стабильности перед полным каскадным деплоем.

## Основные концепции

### Архитектура пайплайна логов

Типичная production-архитектура:

```
Managed Nodes
    ├── journald (бинарный журнал systemd)
    ├── rsyslog (фильтрация и forwarding)
    ├── Vector (агрегация и нормализация)
    └── Приложения (JSON stdout/stderr)
            ↓
            ↓ (syslog / journald / file / docker log driver)
            ↓
Centralized Storage
    ├── Loki (логи, Promtail)
    ├── Elasticsearch (логи, Index lifecycle)
    ├── VictoriaLogs (логи)
    └── Alertmanager (алерты по логам)
```

### Принципы проектирования logging-пайплайна

1. **Reliability over completeness** — лучше потерять редкий debug-лог, чем перегрузить пайплайн.
2. **Local fallback** — каждый хост должен хранить логи локально (journald/rsyslog) на случай отключения центра.
3. **Structured first** — если возможно, сразу пишите JSON, а не plain text.
4. **Backpressure awareness** — настраивайте лимиты и буферы на каждом этапе.
5. **Security** — маскируйте чувствительные данные (пароли, ключи) на этапе сбора.

### Жизненный цикл лога

1. **Создание** — приложение или система пишет событие.
2. **Сбор** — rsyslog/journald/Vector picking up событие.
3. **Фильтрация** — отбрасывание ненужных событий, маскирование чувствительных данных.
4. **Нормализация** — преобразование в структурированный формат (JSON).
5. **Доставка** — отправка в центральное хранилище через reliable queue.
6. **Хранение** — индексация и retention согласно политике.
7. **Поиск и алертинг** — query, dashboard, alert rules.

### Выбор инструмента

| Инструмент | Назначение | Когда использовать |
|---|---|---|
| **rsyslog** | Сбор syslog и forwarding | Существующие инфраструктуры, совместимость с legacy |
| **journald** | Локальный сбор systemd логов | Современные ОС, требуется быстрый поиск |
| **Vector** | Агрегация и нормализация | Высоконагруженные среды, замена rsyslog/filebeat |
| **Promtail** | Сбор логов для Loki | Стек Loki + Prometheus + Grafana |
| **Filebeat** | Сбор логов для Elasticsearch | Стек ELK/OpenSearch |
| **Fluent Bit** | Edge сбор логов | Контейнеры, ограниченные ресурсы |

### Модель выполнения

Все операции настраиваются **на управляемом хосте**:
- Установка пакетов (rsyslog, vector, promtail, filebeat) выполняется через `ansible.builtin.package`.
- Конфигурационные файлы пишутся в `/etc/` целевого хоста.
- Systemd-юниты активируются на целевом хосте.
- При работе с centralized storage убедитесь, что хост имеет сетевая доступность (DNS, firewall, routing).

### Идемпотентность

Все задачи настройки логирования идемпотентны:
- `state: present` / `state: started` / `state: enabled` — создают ресурс только если он отсутствует.
- `creates: /path/to/binary` — не скачивает архив повторно.
- Конфигурационные файлы перезаписываются только при изменении содержимого (Ansible checksum).

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible Core | 2.21+ | `ansible --version` |
| Python | 3.12+ | `python3 --version` |
| rsyslog | 8.2302+ | `rsyslogd -v` |
| Vector | 0.40+ | `vector --version` |
| Promtail | 3.0+ | `promtail --version` |
| Loki | 3.0+ | `loki --version` |
| Elasticsearch | 8.0+ | `curl -s http://localhost:9200` |
| Целевые ОС | Ubuntu 22.04+ / Debian 12+ / RHEL 9+ | `lsb_release -a` |

## Практические сценарии

### Сценарий 1: Pre-flight аудит logging-пайплайна (blast radius minimization)

Перед любым изменением конфигурации логирования выполните pre-flight проверку: доступность centralized storage, место на диске, статус сервисов. Это предотвращает каскадный сбой и потерю логов.

```yaml
- name: Pre-flight audit logging pipeline
  hosts: all
  gather_facts: yes
  tasks:
    - name: Проверка доступности Loki
      ansible.builtin.uri:
        url: "http://loki.internal:3100/ready"
        status_code: 200
        timeout: 5
      register: loki_health
      changed_when: false
      failed_when: false

    - name: Проверка доступности Elasticsearch
      ansible.builtin.uri:
        url: "http://elasticsearch.internal:9200/_cluster/health"
        status_code: 200
        timeout: 5
      register: es_health
      changed_when: false
      failed_when: false

    - name: Проверка свободного места на диске для логов
      ansible.builtin.stat:
        path: /var/log
      register: var_log_stat

    - name: Проверка статуса journald
      ansible.builtin.command: systemctl is-active journald
      register: journald_status
      changed_when: false

    - name: Проверка статуса rsyslog
      ansible.builtin.command: systemctl is-active rsyslog
      register: rsyslog_status
      changed_when: false

    - name: Проверка статуса Vector/Promtail
      ansible.builtin.command: systemctl is-active vector
      register: vector_status
      changed_when: false
      failed_when: false

    - name: Отчёт по health logging-пайплайна
      ansible.builtin.debug:
        msg: |
          Host: {{ inventory_hostname }}
          Loki: {{ 'OK' if loki_health.status == 200 else 'UNREACHABLE' }}
          Elasticsearch: {{ 'OK' if es_health.status == 200 else 'UNREACHABLE' }}
          /var/log free: {{ (var_log_stat.stat.size - var_log_stat.stat.blocks_available * 1024) / 1024 / 1024 / 1024 | round(1) }} GB
          journald: {{ journald_status.stdout }}
          rsyslog: {{ rsyslog_status.stdout }}
          vector: {{ vector_status.stdout | default('not installed') }}
```

**SRE-рекомендации:**
- Встройте pre-flight audit в `pre_tasks` плейбука. Если audit падает — операция не выполняется.
- Для production установите порог: если свободного места < 15 %, операция отменяется с явным сообщением.
- Используйте `check_mode` для dry-run оценки изменений.

### Сценарий 2: Canary deployment конфигурации логирования (blast radius minimization)

Постепенный rollout конфигурации на подмножество хостов перед полным деплоем. Позволяет обнаружить ошибки в конфигурации до влияния на весь кластер.

```yaml
- name: Canary deployment logging config
  hosts: webservers
  serial: "20%"
  vars:
    loki_url: "http://loki.internal:3100/loki/api/v1/push"
    vector_version: "0.40.0"
  tasks:
    - name: Approval gate для canary
      ansible.builtin.pause:
        prompt: |
          Approve logging config deployment on {{ inventory_hostname }}?
          This is canary deployment (20% of hosts).
      when: ansible_facts['distribution'] != 'Windows'

    - name: Проверка, что Loki доступен
      ansible.builtin.uri:
        url: "{{ loki_url }}"
        status_code: 200
        timeout: 5
      register: loki_check
      changed_when: false
      failed_when: loki_check.status != 200

    - name: Установка Vector
      ansible.builtin.unarchive:
        src: "https://github.com/vectordotdev/vector/releases/download/v{{ vector_version }}/vector-{{ vector_version }}-linux-x86_64.tar.gz"
        dest: /usr/local/bin/
        remote_src: yes
        creates: /usr/local/bin/vector

    - name: Размещение конфигурации Vector
      ansible.builtin.copy:
        dest: /etc/vector/vector.toml
        content: |
          [sources.journald]
          type = "journald"

          [transforms.parse]
          type = "remap"
          inputs = ["journald"]
          source = '''
          .host = "{{ inventory_hostname }}"
          '''

          [sinks.loki]
          type = "loki"
          inputs = ["parse"]
          endpoint = "{{ loki_url }}"
          encoding = "json"
          labels = { host = "{{ inventory_hostname }}" }
        mode: '0644'

    - name: Создание systemd юнита Vector
      ansible.builtin.copy:
        dest: /etc/systemd/system/vector.service
        content: |
          [Unit]
          Description=Vector log agent
          After=network.target

          [Service]
          ExecStart=/usr/local/bin/vector --config /etc/vector/vector.toml
          Restart=always
          RestartSec=5

          [Install]
          WantedBy=multi-user.target
        mode: '0644'

    - name: Включение и запуск Vector
      ansible.builtin.systemd:
        name: vector
        state: started
        enabled: true
        daemon_reload: true

    - name: Валидация доставки логов
      ansible.builtin.command: sleep 10 && curl -s "{{ loki_url }}"
      register: delivery_check
      changed_when: false
      failed_when: delivery_check.rc != 0
```

**SRE-рекомендации:**
- `serial: "20%"` ограничивает blast radius. При проблемах откатывается только 20% хостов.
- Для enterprise используйте `serial: 1` с approval gate на каждом хосте.
- Всегда валидируйте доставку логов после деплоя; добавьте health check в monitoring.

### Сценарий 3: Change management — dry-run и валидация конфигурации

Использование `--check --diff` и валидации конфигурации перед применением в production. Подходит для change approval board (CAB) и CI/CD пайплайнов.

```bash
# Dry-run: показать, что будет изменено
ansible-playbook site.yml -i inventories/production/ \
  --limit webservers \
  --check --diff \
  -e "loki_url=http://loki.internal:3100/loki/api/v1/push"

# Применение после approval
ansible-playbook site.yml -i inventories/production/ \
  --limit webservers \
  --diff \
  -e "loki_url=http://loki.internal:3100/loki/api/v1/push"
```

```yaml
# tasks/logging_config.yml
- name: Настройка конфигурации Vector с валидацией
  hosts: webservers
  become: true
  vars:
    loki_url: "{{ loki_url | default('http://loki.internal:3100/loki/api/v1/push') }}"
  tasks:
    - name: Проверка конфигурации Vector (dry-run)
      ansible.builtin.command: vector --config /etc/vector/vector.toml --dry-run
      register: vector_validate
      changed_when: false
      failed_when: "'valid' not in vector_validate.stdout | lower"

    - name: Размещение конфигурации Vector
      ansible.builtin.copy:
        dest: /etc/vector/vector.toml
        content: |
          [sources.journald]
          type = "journald"

          [transforms.parse]
          type = "remap"
          inputs = ["journald"]
          source = '''
          .host = "{{ inventory_hostname }}"
          '''

          [sinks.loki]
          type = "loki"
          inputs = ["parse"]
          endpoint = "{{ loki_url }}"
          encoding = "json"
          labels = { host = "{{ inventory_hostname }}" }
        mode: '0644'
      notify: Restart Vector

    - name: Проверка работы Vector после применения
      ansible.builtin.systemd:
        name: vector
        state: started
        enabled: true
      register: vector_service

  handlers:
    - name: Restart Vector
      ansible.builtin.systemd:
        name: vector
        state: restarted
```

**SRE-рекомендации:**
- Всегда запускайте `--check --diff` перед применением в production. Результат `--diff` показывает точные изменения конфигурации.
- Добавьте `ansible.builtin.command: vector --dry-run` в плейбук для программной валидации.
- Для CI/CD добавьте job, который выполняет `ansible-playbook --check` на every PR, меняющей logging-код.

### Сценарий 4: Disaster recovery — backup и restore конфигурации логирования

Автоматизация бэкапа конфигураций rsyslog, Vector, Promtail, logrotate и recovery после сбоя. Восстановление logging-пайплайна — критичная операция для compliance и forensic.

```yaml
- name: DR backup logging configurations
  hosts: all
  become: yes
  vars:
    backup_dir: /var/backups/logging-config
  tasks:
    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0700'

    - name: Бэкап конфигурации rsyslog
      ansible.builtin.copy:
        src: /etc/rsyslog.conf
        dest: "{{ backup_dir }}/rsyslog.conf.{{ ansible_date_time.date }}"
        remote_src: yes
        mode: '0640'

    - name: Бэкап конфигураций rsyslog.d
      ansible.builtin.copy:
        src: /etc/rsyslog.d/
        dest: "{{ backup_dir }}/rsyslog.d.{{ ansible_date_time.date }}/"
        remote_src: yes
        mode: '0640'

    - name: Бэкап конфигурации Vector
      ansible.builtin.copy:
        src: /etc/vector/vector.toml
        dest: "{{ backup_dir }}/vector.toml.{{ ansible_date_time.date }}"
        remote_src: yes
        mode: '0640'

    - name: Бэкап конфигурации Promtail
      ansible.builtin.copy:
        src: /etc/promtail/config.yml
        dest: "{{ backup_dir }}/promtail-config.{{ ansible_date_time.date }}"
        remote_src: yes
        mode: '0640'

    - name: Бэкап конфигурации logrotate
      ansible.builtin.copy:
        src: /etc/logrotate.d/
        dest: "{{ backup_dir }}/logrotate.d.{{ ansible_date_time.date }}/"
        remote_src: yes
        mode: '0640'

    - name: Архивирование конфигураций
      ansible.builtin.command: tar -C {{ backup_dir }} -czf {{ backup_dir }}/logging-config-{{ ansible_date_time.date }}.tar.gz .
      register: archive_result
      changed_when: archive_result.rc == 0

    - name: Ротация бэкапов (хранить 30 дней)
      ansible.builtin.command: find {{ backup_dir }} -name 'logging-config-*.tar.gz' -mtime +30 -delete
      changed_when: false
```

**SRE-рекомендации:**
- Храните бэкапы конфигураций отдельно от логов. При сбое пайплайна восстановите конфиг за 5 минут вместо debugging.
- Включите задачу в disaster recovery runbook. Тестируйте restore раз в квартал.
- Для compliance (PCI DSS, GDPR) храните конфигурации минимум 1 год с immutable флагом.

### Сценарий 5: Automated rollback при сбое конфигурации

Автоматический откат к предыдущей рабочей конфигурации при ошибке валидации после деплоя. Использует бэкап из сценария 4.

```yaml
- name: Rollback logging configuration
  hosts: webservers
  become: yes
  vars:
    backup_dir: /var/backups/logging-config
    target_date: "{{ rollback_date | default(ansible_date_time.date) }}"
  tasks:
    - name: Проверка наличия бэкапа за целевую дату
      ansible.builtin.stat:
        path: "{{ backup_dir }}/logging-config-{{ target_date }}.tar.gz"
      register: backup_exists
      failed_when: not backup_exists.stat.exists

    - name: Остановка Vector
      ansible.builtin.systemd:
        name: vector
        state: stopped
      ignore_errors: yes

    - name: Распаковка бэкапа конфигураций
      ansible.builtin.command: tar -xzf {{ backup_dir }}/logging-config-{{ target_date }}.tar.gz -C {{ backup_dir }}
      register: extract_result
      changed_when: extract_result.rc == 0

    - name: Восстановление конфигурации rsyslog
      ansible.builtin.copy:
        src: "{{ backup_dir }}/rsyslog.conf.{{ target_date }}"
        dest: /etc/rsyslog.conf
        remote_src: yes
        mode: '0640'
      notify: Restart rsyslog

    - name: Восстановление конфигурации Vector
      ansible.builtin.copy:
        src: "{{ backup_dir }}/vector.toml.{{ target_date }}"
        dest: /etc/vector/vector.toml
        remote_src: yes
        mode: '0640'
      notify: Restart Vector

    - name: Валидация восстановленной конфигурации
      ansible.builtin.command: vector --config /etc/vector/vector.toml --dry-run
      register: vector_validate
      changed_when: false
      failed_when: "'valid' not in vector_validate.stdout | lower"

    - name: Запуск Vector
      ansible.builtin.systemd:
        name: vector
        state: started
        enabled: true

  handlers:
    - name: Restart rsyslog
      ansible.builtin.systemd:
        name: rsyslog
        state: restarted

    - name: Restart Vector
      ansible.builtin.systemd:
        name: vector
        state: restarted
```

**SRE-рекомендации:**
- Храните минимум 2 последних рабочих бэкапа. При сбое автоматически откатывайтесь на последний рабочий.
- Встройте rollback в CI/CD pipeline: если health check после деплоя падает — автоматически запускайте rollback playbook.
- Тестируйте rollback на staging перед использованием в production.

### Сценарий 6: Compliance — аудит retention и целостности логов

Автоматизация проверки compliance retention policy и целостности логов. Подходит для PCI DSS, GDPR, SOX аудитов.

```yaml
- name: Compliance audit logging
  hosts: all
  gather_facts: yes
  vars:
    max_log_age_days: 90
    required_retention_days: 365
    immutable_log_dirs:
      - /var/log/immutable
  tasks:
    - name: Проверка retention policy в logrotate
      ansible.builtin.find:
        paths: /etc/logrotate.d
        patterns: "*"
      register: logrotate_confs

    - name: Проверка максимального возраста логов
      ansible.builtin.command: find /var/log -type f -mtime +{{ max_log_age_days }}
      register: old_logs
      changed_when: false
      failed_when: false

    - name: Проверка immutable флага на критичных директориях
      ansible.builtin.command: lsattr {{ item }}
      loop: "{{ immutable_log_dirs }}"
      register: immutable_check
      changed_when: false
      failed_when: false

    - name: Проверка прав доступа к логам
      ansible.builtin.stat:
        path: /var/log
      register: var_log_stat

    - name: Проверка аудит логов (auditd)
      ansible.builtin.command: systemctl is-active auditd
      register: auditd_status
      changed_when: false

    - name: Проверка audit политики для логов
      ansible.builtin.command: auditctl -l | grep -i log
      register: audit_rules
      changed_when: false
      failed_when: false

    - name: Отчёт по compliance
      ansible.builtin.debug:
        msg: |
          Host: {{ inventory_hostname }}
          Logrotate configs: {{ logrotate_confs.matched }}
          Old logs (>{{ max_log_age_days }} days): {{ old_logs.matched }}
          Immutable dirs: {{ immutable_check.results | map(attribute='stdout') | list }}
          auditd: {{ auditd_status.stdout }}
          Audit rules for logs: {{ audit_rules.stdout_lines | length }}
```

**SRE-рекомендации:**
- Для PCI DSS требуются retention 1+ год и immutable флаг на логах транзакций.
- Настройте `chattr +i /var/log/immutable` для критичных логов; только root может удалить.
- Используйте `auditd` для отслеживания попыток удаления/модификации логов.

### Сценарий 7: Мониторинг logging-пайплайна (drop rate, queue depth, error rate)

Мониторинг самого пайплайна логов: drop rate, queue depth, error rate. Позволяет выявить проблемы до потери данных.

```yaml
- name: Monitor logging pipeline health
  hosts: webservers
  gather_facts: no
  tasks:
    - name: Проверка статуса Vector
      ansible.builtin.command: systemctl is-active vector
      register: vector_status
      changed_when: false

    - name: Проверка очереди Vector
      ansible.builtin.command: vector --config /etc/vector/vector.toml --health-check
      register: vector_health
      changed_when: false
      failed_when: false

    - name: Проверка размера буфера Vector
      ansible.builtin.command: ls -la /tmp/vector-buffer* 2>/dev/null || echo "no buffer"
      register: vector_buffer
      changed_when: false
      failed_when: false

    - name: Проверка логов Vector на ошибки
      ansible.builtin.command: journalctl -u vector --since "1 hour ago" | grep -iE 'error|fail|drop' || echo "no errors"
      register: vector_errors
      changed_when: false
      failed_when: false

    - name: Проверка доступности Loki
      ansible.builtin.uri:
        url: "http://loki.internal:3100/ready"
        status_code: 200
        timeout: 5
      register: loki_health
      changed_when: false
      failed_when: false

    - name: Проверка размера логов journald
      ansible.builtin.command: journalctl --disk-usage
      register: journald_disk
      changed_when: false

    - name: Алерт при ошибках Vector
      ansible.builtin.debug:
        msg: "ALERT: Vector errors on {{ inventory_hostname }}: {{ vector_errors.stdout }}"
      when: vector_errors.stdout != 'no errors'

    - name: Алерт при недоступности Loki
      ansible.builtin.debug:
        msg: "ALERT: Loki unreachable from {{ inventory_hostname }}"
      when: loki_health.status != 200
```

**SRE-рекомендации:**
- Мониторьте drop rate (количество отброшенных событий) и queue depth. При превышении порога — алерт в PagerDuty/OpsGenie.
- Настройте `Restart=always` и `RestartSec=5` для Vector/Promtail; демон сам перезапустится при падении.
- Используйте `vector --health-check` или callback-плагин для отправки метрик в Prometheus.

### Сценарий 8: Circuit breaker — переключение на локальный fallback при недоступности центра

Настройка circuit breaker для rsyslog/Vector: при недоступности Loki/Elasticsearch логи буферизируются локально или отбрасываются с предотвращением переполнения диска.

```yaml
- name: Circuit breaker для logging pipeline
  hosts: webservers
  become: true
  vars:
    loki_url: "http://loki.internal:3100/loki/api/v1/push"
    local_fallback_dir: /var/log/local-buffer
  tasks:
    - name: Создание директории для локального fallback
      ansible.builtin.file:
        path: "{{ local_fallback_dir }}"
        state: directory
        mode: '0750'
        owner: root
        group: adm

    - name: Настройка rsyslog с локальным fallback
      ansible.builtin.copy:
        dest: /etc/rsyslog.d/50-circuit-breaker.conf
        content: |
          # Circuit breaker: при недоступности центрального хранилища
          # буферизируем логи локально

          # Определение action для центрального хранилища
          action(
            type="omfwd"
            target="loki.internal"
            port="514"
            protocol="tcp"
            queue.type="LinkedList"
            queue.size="10000"
            queue.maxdiskspace="1g"
            action.resumeRetryCount="-1"
            action.resumeInterval="30"
          )

          # Fallback: запись в локальный файл при переполнении очереди
          action(
            type="omfile"
            file="{{ local_fallback_dir }}/fallback.log"
            asyncWriting="on"
          )
        mode: '0644'

    - name: Настройка logrotate для fallback-логов
      ansible.builtin.copy:
        dest: /etc/logrotate.d/local-buffer
        content: |
          {{ local_fallback_dir }}/*.log {
              daily
              missingok
              rotate 7
              compress
              delaycompress
              notifempty
              create 0640 root adm
              maxsize 1G
              postrotate
                  systemctl reload rsyslog >/dev/null 2>&1 || true
              endscript
          }
        mode: '0644'

    - name: Перезапуск rsyslog
      ansible.builtin.systemd:
        name: rsyslog
        state: restarted
```

**SRE-рекомендации:**
- `queue.maxdiskspace="1g"` ограничивает размер буфера на диске. При превышении старые события отбрасываются.
- `action.resumeRetryCount="-1"` означает бесконечные попытки переподключения. Для production установите ограничение и алерт при исчерпании попыток.
- Мониторьте размер `local_fallback_dir`; при превышении 80% — алерт об отказе центрального хранилища.

### Сценарий 9: Structured logging — enforcement JSON schema через Vector

Автоматизация enforcement структурированных логов: все события проходят через Vector transform, который гарантирует наличие обязательных полей (`timestamp`, `level`, `service`, `message`, `trace_id`). От事件 с отсутствующими полями отправляются в dead-letter queue для анализа.

```yaml
- name: Structured logging enforcement
  hosts: webservers
  become: true
  vars:
    loki_url: "http://loki.internal:3100/loki/api/v1/push"
    vector_version: "0.40.0"
  tasks:
    - name: Установка Vector
      ansible.builtin.unarchive:
        src: "https://github.com/vectordotdev/vector/releases/download/v{{ vector_version }}/vector-{{ vector_version }}-linux-x86_64.tar.gz"
        dest: /usr/local/bin/
        remote_src: yes
        creates: /usr/local/bin/vector

    - name: Конфигурация Vector с enforcement schema
      ansible.builtin.copy:
        dest: /etc/vector/vector.toml
        content: |
          [sources.journald]
          type = "journald"

          [transforms.enforce_schema]
          type = "remap"
          inputs = ["journald"]
          source = '''
          # Принудительное добавление обязательных полей
          .timestamp = to_timestamp!(.timestamp)
          .level = .level ?? "INFO"
          .service = .SYSTEMD_UNIT ?? .SYSLOG_IDENTIFIER ?? "unknown"
          .message = .message ?? .MESSAGE ?? ""
          .host = "{{ inventory_hostname }}"

          # Проверка обязательных полей
          if .message == "" || .service == "unknown" {
            .dropped = true
          }
          '''

          [transforms.parse]
          type = "remap"
            inputs = ["enforce_schema"]
            source = '''
            # Пропуск событий без message
            if !exists(.message) || .message == null {
              . = null
            }
            '''

          [sinks.loki]
          type = "loki"
          inputs = ["parse"]
          endpoint = "{{ loki_url }}"
            encoding = "json"
            labels = { host = "{{ inventory_hostname }}" }

          [sinks.dead_letter]
          type = "file"
            inputs = ["enforce_schema"]
            path = "/var/log/vector/dead-letter.log"
        mode: '0644'

    - name: Создание директории для dead-letter
      ansible.builtin.file:
        path: /var/log/vector
        state: directory
        mode: '0750'
        owner: root
        group: adm

    - name: Создание systemd юнита Vector
      ansible.builtin.copy:
        dest: /etc/systemd/system/vector.service
        content: |
          [Unit]
          Description=Vector log agent
          After=network.target

          [Service]
          ExecStart=/usr/local/bin/vector --config /etc/vector/vector.toml
          Restart=always
          RestartSec=5

          [Install]
          WantedBy=multi-user.target
        mode: '0644'

    - name: Включение и запуск Vector
      ansible.builtin.systemd:
        name: vector
        state: started
        enabled: true
        daemon_reload: true
```

**SRE-рекомендации:**
- Dead-letter queue позволяет выявлять приложения, которые пишут невалидные логи. Регулярно анализируйте `/var/log/vector/dead-letter.log`.
- Enforce schema на edge-уровне (Vector/Promtail), а не на приемнике (Loki/ES), чтобы снизить нагрузку.
- Для stricter compliance добавьте validation JSON Schema в Vector 0.40+.

### Сценарий 10: Автоматический сбор логов systemd/journald в Loki через Promtail

Развертывание Promtail на управляемых хостах для сбора journald логов и доставки в Loki.

```yaml
---
- name: Централизованный сбор journald логов
  hosts: all
  become: true
  vars:
    loki_url: "http://loki.internal:3100/loki/api/v1/push"
    promtail_version: "3.0.0"

  tasks:
    - name: Установка Promtail
      ansible.builtin.unarchive:
        src: "https://github.com/grafana/loki/releases/download/v{{ promtail_version }}/promtail-linux-amd64.zip"
        dest: /usr/local/bin/
        remote_src: yes
        creates: /usr/local/bin/promtail

    - name: Размещение конфигурации Promtail
      ansible.builtin.copy:
        dest: /etc/promtail/config.yml
        content: |
          server:
            http_listen_port: 9080
            grpc_listen_port: 0

          positions:
            filename: /tmp/positions.yaml

          clients:
            - url: {{ loki_url }}

          scrape_configs:
            - job_name: journald
              journal:
                max_age: 12h
                labels:
                  host: {{ inventory_hostname }}
              relabel_configs:
                - source_labels: [__journal__system]
                  target_label: systemd_unit
                - source_labels: [__journal__priority]
                  target_label: log_level
        mode: '0644'

    - name: Создание systemd юнита Promtail
      ansible.builtin.copy:
        dest: /etc/systemd/system/promtail.service
        content: |
          [Unit]
          Description=Promtail log collector
          After=network.target

          [Service]
          ExecStart=/usr/local/bin/promtail -config.file=/etc/promtail/config.yml
          Restart=always
          RestartSec=5

          [Install]
          WantedBy=multi-user.target
        mode: '0644'

    - name: Включение и запуск Promtail
      ansible.builtin.systemd:
        name: promtail
        state: started
        enabled: true
        daemon_reload: true
```

**Валидация:**

```bash
# Проверка статуса Promtail
systemctl status promtail
# → active (running)

# Проверка отправки логов
curl -s http://loki.internal:3100/loki/api/v1/query?query={host=web1} | jq .
# → возвращает логи с хоста web1

# Проверка positions файла
cat /tmp/positions.yaml
# → содержит последнюю позицию чтения journald
```

### Сценарий 11: Централизованный сбор rsyslog логов в Elasticsearch

Настройка rsyslog для отправки логов в Elasticsearch через модуль `omelasticsearch`.

```yaml
---
- name: Централизованный сбор rsyslog логов
  hosts: all
  become: true
  vars:
    elasticsearch_url: "http://elasticsearch.internal:9200"
    rsyslog_conf: "/etc/rsyslog.d/50-elasticsearch.conf"

  tasks:
    - name: Установка rsyslog и модуля elasticsearch
      ansible.builtin.package:
        name:
          - rsyslog
          - rsyslog-elasticsearch
        state: present

    - name: Настройка отправки в Elasticsearch
      ansible.builtin.copy:
        dest: "{{ rsyslog_conf }}"
        content: |
          module(load="omelasticsearch")
          template(name="json-template"
                   type="string"
                   string="{\"timestamp\":\"%timegenerated%\",\"host\":\"%hostname%\",\"facility\":\"%syslogfacility%\",\"priority\":\"%syslogpriority%\",\"message\":\"%msg%\"}")

          action(type="omelasticsearch"
                 server="{{ elasticsearch_url }}"
                 template="json-template"
                 searchIndex="ansible-logs"
                 bulkmode="on"
                 queue.maxdiskspace="1g"
                 queue.size="10000"
                 queue.type="LinkedList"
                 action.resumeRetryCount="-1"
                 queue.workerThreads="4")
        mode: '0644'

    - name: Разрешение отправки в Elasticsearch в rsyslog.conf
      ansible.builtin.lineinfile:
        path: /etc/rsyslog.conf
        regexp: '^#?\$ModLoad imudp'
        line: '$ModLoad imudp'
        state: present

    - name: Перезапуск rsyslog
      ansible.builtin.systemd:
        name: rsyslog
        state: restarted
```

**Валидация:**

```bash
# Проверка конфигурации rsyslog
rsyslogd -N1
# → rsyslogd: Нет ошибок в конфигурации

# Проверка отправки логов
curl -s http://elasticsearch.internal:9200/ansible-logs/_search?pretty | jq .
# → возвращает логи из индекса ansible-logs

# Проверка очереди rsyslog
logger "Test message from Ansible"
# → через несколько секунд появляется в Elasticsearch
```

### Сценарий 12: Ротация логов через logrotate

Автоматизация настройки logrotate для приложений, которые пишут логи в файлы.

```yaml
---
- name: Настройка ротации логов
  hosts: all
  become: true
  vars:
    logrotate_conf: "/etc/logrotate.d/ansible-apps"

  tasks:
    - name: Создание конфигурации logrotate
      ansible.builtin.copy:
        dest: "{{ logrotate_conf }}"
        content: |
          /var/log/ansible/*.log {
              daily
              missingok
              rotate 14
              compress
              delaycompress
              notifempty
              create 0640 root root
              sharedscripts
              postrotate
                  systemctl reload rsyslog >/dev/null 2>&1 || true
              endscript
          }
        mode: '0644'

    - name: Принудительная проверка logrotate
      ansible.builtin.command: logrotate -f {{ logrotate_conf }}
      register: logrotate_result
      changed_when: "'error' not in logrotate_result.stdout.lower()"
```

**Валидация:**

```bash
# Проверка конфигурации
logrotate -d /etc/logrotate.d/ansible-apps
# → показывает, какие файлы будут ротированы

# Проверка после ротации
ls -la /var/log/ansible/
# → app.log, app.log.1.gz, app.log.2.gz

# Проверка размеров
du -sh /var/log/ansible/*
# → app.log (small), app.log.1.gz (compressed)
```

### Сценарий 13: Нормализация логов и маскирование чувствительных данных

Использование Vector для маскирования чувствительных данных перед отправкой в центральное хранилище.

```yaml
---
- name: Нормализация и маскирование логов
  hosts: all
  become: true
  vars:
    vector_version: "0.40.0"

  tasks:
    - name: Установка Vector
      ansible.builtin.unarchive:
        src: "https://github.com/vectordotdev/vector/releases/download/v{{ vector_version }}/vector-{{ vector_version }}-linux-x86_64.tar.gz"
        dest: /usr/local/bin/
        remote_src: yes
        creates: /usr/local/bin/vector

    - name: Конфигурация Vector с маскированием
      ansible.builtin.copy:
        dest: /etc/vector/vector.toml
        content: |
          [sources.journald]
          type = "journald"
          include_matches = ["_SYSTEMD_UNIT=ansible.service"]

          [transforms.mask_sensitive]
          type = "remap"
          inputs = ["journald"]
          source = '''
          .message = gsub(.message, '(?i)(password|secret|key)\\s*[:=]\\s*\\S+', '${1}=***')
          .message = gsub(.message, '(?i)(token|auth)\\s*[:=]\\s*\\S+', '${1}=***')
          '''

          [sinks.loki]
          type = "loki"
          inputs = ["mask_sensitive"]
            endpoint = "http://loki.internal:3100"
            encoding = "json"
            labels = { host = "{{ inventory_hostname }}" }
        mode: '0644'

    - name: Создание systemd юнита Vector
      ansible.builtin.copy:
        dest: /etc/systemd/system/vector.service
        content: |
          [Unit]
          Description=Vector log agent
          After=network.target

          [Service]
          ExecStart=/usr/local/bin/vector --config /etc/vector/vector.toml
          Restart=always
          RestartSec=5

          [Install]
          WantedBy=multi-user.target
        mode: '0644'

    - name: Включение и запуск Vector
      ansible.builtin.systemd:
        name: vector
        state: started
        enabled: true
        daemon_reload: true
```

**Валидация:**

```bash
# Проверка конфигурации Vector
vector --config /etc/vector/vector.toml --dry-run
# → Configuration is valid

# Проверка маскирования
journalctl -u ansible.service | vector --config /etc/vector/vector.toml --stdin
# → чувствительные данные маскируются

# Проверка в Loki
curl -s http://loki.internal:3100/loki/api/v1/query?query={host=web1} | jq .
# → логи без чувствительных данных
```

### Сценарий 14: Сбор логов Docker контейнеров

Автоматизация сбора логов из Docker контейнеров через Vector.

```yaml
---
- name: Сбор логов Docker контейнеров
  hosts: all
  become: true
  vars:
    vector_version: "0.40.0"

  tasks:
    - name: Установка Vector
      ansible.builtin.unarchive:
        src: "https://github.com/vectordotdev/vector/releases/download/v{{ vector_version }}/vector-{{ vector_version }}-linux-x86_64.tar.gz"
        dest: /usr/local/bin/
        remote_src: yes
        creates: /usr/local/bin/vector

    - name: Конфигурация Vector для Docker логов
      ansible.builtin.copy:
        dest: /etc/vector/vector.toml
        content: |
          [sources.docker]
          type = "docker_logs"
          include_containers = ["web", "app", "nginx"]

          [transforms.parse]
          type = "remap"
          inputs = ["docker"]
          source = '''
          .service = .container_name
          .host = "{{ inventory_hostname }}"
          '''

          [sinks.loki]
          type = "loki"
          inputs = ["parse"]
          endpoint = "http://loki.internal:3100"
          encoding = "json"
          labels = { host = "{{ inventory_hostname }}" }
        mode: '0644'

    - name: Настройка Docker logging driver
      ansible.builtin.copy:
        dest: /etc/docker/daemon.json
        content: |
          {
            "log-driver": "json-file",
            "log-opts": {
              "max-size": "100m",
              "max-file": "3"
            }
          }
        mode: '0644'
      notify: Restart Docker

    - name: Создание systemd юнита Vector
      ansible.builtin.copy:
        dest: /etc/systemd/system/vector.service
        content: |
          [Unit]
          Description=Vector log agent
          After=network.target docker.service
          Requires=docker.service

          [Service]
          ExecStart=/usr/local/bin/vector --config /etc/vector/vector.toml
          Restart=always
          RestartSec=5

          [Install]
          WantedBy=multi-user.target
        mode: '0644'

    - name: Включение и запуск Vector
      ansible.builtin.systemd:
        name: vector
        state: started
        enabled: true
        daemon_reload: true

  handlers:
    - name: Restart Docker
      ansible.builtin.systemd:
        name: docker
        state: restarted
```

**Валидация:**

```bash
# Проверка статуса Vector
systemctl status vector
# → active (running)

# Проверка отправки логов
docker logs web | logger
# → появляется в Loki

# Проверка в Loki
curl -s http://loki.internal:3100/loki/api/v1/query?query={service=web} | jq .
# → логи контейнера web
```

## Операции и команды

### Основные команды для управления логами

| Команда | Назначение | Пример |
|---|---|---|
| `journalctl -u <service>` | Просмотр логов systemd | `journalctl -u nginx -f` |
| `journalctl --since "1 hour ago"` | Логи за последний час | `journalctl --since "1 hour ago"` |
| `journalctl --disk-usage` | Проверка размера journald | `journalctl --disk-usage` |
| `journalctl --vacuum-size=100M` | Очистка journald до 100M | `journalctl --vacuum-size=100M` |
| `rsyslogd -N1` | Проверка конфигурации rsyslog | `rsyslogd -N1` |
| `logrotate -f /etc/logrotate.d/<file>` | Принудительная ротация | `logrotate -f /etc/logrotate.d/ansible-apps` |
| `logrotate -d /etc/logrotate.d/<file>` | Dry-run ротации | `logrotate -d /etc/logrotate.d/ansible-apps` |
| `vector --config <file> --dry-run` | Проверка конфигурации Vector | `vector --config /etc/vector/vector.toml --dry-run` |
| `vector --config <file> --health-check` | Проверка здоровья Vector | `vector --config /etc/vector/vector.toml --health-check` |
| `promtool check config <file>` | Проверка конфигурации Promtail | `promtool check config /etc/promtail/config.yml` |
| `lsattr /var/log/*` | Проверка immutable флага | `lsattr /var/log/immutable` |
| `chattr +i /path/to/file` | Установка immutable флага | `chattr +i /var/log/immutable/audit.log` |

### Команды для проверки доставки логов

| Команда | Назначение | Пример |
|---|---|---|
| `curl -s http://loki:3100/loki/api/v1/query?query={host=<host>}` | Поиск логов в Loki | `curl -s http://loki:3100/loki/api/v1/query?query={host=web1}` |
| `curl -s http://elasticsearch:9200/ansible-logs/_search?pretty` | Поиск логов в Elasticsearch | `curl -s http://elasticsearch:9200/ansible-logs/_search?pretty` |
| `logger "Test message"` | Отправка тестового сообщения | `logger "Test message from Ansible"` |
| `journalctl -f` | tail логов journald в реальном времени | `journalctl -u nginx -f` |
| `tail -f /var/log/syslog` | tail логов rsyslog | `tail -f /var/log/syslog` |
| `systemctl status vector` | Проверка статуса Vector | `systemctl status vector` |
| `systemctl status promtail` | Проверка статуса Promtail | `systemctl status promtail` |

### Команды для аудита compliance

| Команда | Назначение | Пример |
|---|---|---|
| `auditctl -l` | Просмотр audit правил | `auditctl -l | grep -i log` |
| `ausearch -f /var/log/` | Поиск событий audit для логов | `ausearch -f /var/log/ -i` |
| `find /var/log -type f -mtime +365` | Проверка retention | `find /var/log -type f -mtime +365` |
| `tune2fs -l /dev/sda1 \| grep -i reserved` | Проверка reserved blocks для логов | `tune2fs -l /dev/sda1` |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `Failed to send batch to Loki` | Loki недоступен или перегружен | Проверьте `curl http://loki:3100/ready`, настройте backpressure |
| `rsyslogd: error loading module` | Модуль omelasticsearch не установлен | Установите `rsyslog-elasticsearch` |
| `Vector config validation failed` | Ошибка в TOML конфигурации | Запустите `vector --dry-run` для проверки |
| `Logs не появляются в Elasticsearch` | Неверный URL или индекс | Проверьте `curl http://elasticsearch:9200/_cat/indices?v` |
| `Journald logs are missing` | Неправильный journald filter | Проверьте `journalctl -u <service>` вручную |
| `Backpressure detected` | Источник генерирует логи быстрее, чем приемник может обработать | Увеличьте `queue.size` и `queue.workerThreads` |
| `Sensitive data in logs` | Не настроено маскирование | Добавьте `remap` трансформацию в Vector |
| `Disk full on /var/log` | Логи заполнили диск | Проверьте `du -sh /var/log/*`, настройте logrotate |
| `Logs lost after restart` | Буфер не сохранён или queue слишком мал | Увеличьте `queue.maxdiskspace`, проверьте `positions` файл |
| `Immutable flag prevents logrotate` | `chattr +i` блокирует ротацию | Уберите immutable флаг перед ротацией |
| `Promtail not sending logs` | Неверный endpoint или auth | Проверьте `promtail --config /etc/promtail/config.yml --dry-run` |
| `Vector drops logs silently` | Buffer переполнен или network partition | Проверьте `vector --health-check`, логи Vector |
| `Retention not applied` | Не настроено retention на приемнике | Настройте retention в Loki (ingester) или Elasticsearch (ILM) |
| `Logs tampered/deleted` | Нет immutable флага или audit | Настройте `chattr +i` и `auditd` |
| `High latency in log delivery` | Перегрузка сети или приемника | Увеличьте `queue.workerThreads`, проверьте `tc` и `ss` |

## Рекомендации

### Best Practices

1. **Structured logging first** — сразу пишите JSON, а не plain text. Это упростит парсинг и поиск.
2. **Local fallback** — на каждом хосте должен быть локальный сбор логов (journald/rsyslog) на случай отключения центра.
3. **Backpressure handling** — настраивайте лимиты очередей и буферов на каждом этапе пайплайна.
4. **Sensitive data masking** — маскируйте пароли, ключи, токены на этапе сбора, а не на этапе поиска.
5. **Retention policy** — задавайте retention на уровне индекса, а не на уровне приемника.
6. **Monitoring the pipeline** — мониторьте не только логи, но и сам пайплайн (drop rate, queue depth, error rate).
7. **Idempotency** — все задачи настройки логов должны быть идемпотентными.
8. **Blast radius minimization** — используйте `serial`, `--limit`, canary deployment для изменений конфигурации логирования.
9. **Change management** — всегда используйте `--check --diff` и approval gate перед применением в production.
10. **Pre-flight checks** — запускайте pre-flight audit (доступность хранилища, место на диске, статус сервисов) перед изменениями.
11. **DR automation** — автоматизируйте backup и restore конфигураций логирования.
12. **Compliance** — настройте retention enforcement, immutable флаги и audit trail для compliance (PCI DSS, GDPR, SOX).

### Чек-лист валидации после настройки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Promtail запущен | `systemctl status promtail` | `active (running)` |
| Vector запущен | `systemctl status vector` | `active (running)` |
| Логи доставляются | `curl -s http://loki:3100/loki/api/v1/query?query={host=<host>}` | Возвращает логи |
| Ротация работает | `logrotate -d /etc/logrotate.d/ansible-apps` | Нет ошибок |
| Маскирование работает | `journalctl -u <service> \| vector` | Чувствительные данные скрыты |
| Retention policy | `curl -s http://loki:3100/loki/api/v1/tenant/schemas` | Правила retention применены |
| Journald размер | `journalctl --disk-usage` | Размер в пределах нормы |
| Immutable флаг | `lsattr /var/log/immutable` | `----i` присутствует |
| Auditd активен | `systemctl status auditd` | `active (running)` |
| Queue depth | `vector --health-check` | Нет предупреждений о переполнении |

### Рекомендации по безопасности

- **no_log:** Для защиты секретов в Ansible используйте `no_log: true`; см. **[Ansible/ansible_security_best_practices.md](../ansible_security_best_practices.md)**.
- **Маскирование в Vector:** Используйте `remap` трансформации для маскирования паролей, ключей, токенов.
- **Права доступа:** Логи должны иметь права `0640` (root:adm). Группа `adm` читает логи, остальные — нет.
- **Immutable флаг:** Для критичных логов установите `chattr +i`; только root может удалить/изменить файл.
- **Network encryption:** При отправке логов по сети используйте TLS (Loki/ES с HTTPS) или VPN/tunnel.
- **Audit trail:** Включите `auditd` для отслеживания доступа к логам (чтение, запись, удаление).

### Рекомендации по производительности

- **Journald rate limiting:** Настройте `RateLimitIntervalSec` и `RateLimitBurst` в `journald.conf` для предотвращения переполнения.
- **Vector buffering:** Используйте disk-backed buffer (`buffer.type = "disk"`) для надежности при перегрузке.
- **Batch sending:** Настройте `batch.max_bytes` и `batch.timeout` в Vector для оптимальной отправки.
- **Compression:** Используйте `encoding.compress = "gzip"` в sinks для снижения сетевой нагрузки.
- **Filtering на edge:** Отбрасывайте ненужные логи на уровне Vector/Promtail, а не на приемнике.

### Эксплуатация и disaster recovery

- **Ротация снапшотов:** Храните минимум 2 рабочих бэкапа конфигураций логирования.
- **Тестирование восстановления:** Раз в квартал восстанавливайте конфигурацию из бэкапа на staging.
- **Runbook:** Храните процедуры recovery в ITSM/wiki. Ansible playbook — не замена runbook, а его исполнение.
- **Self-healing:** Настройте `Restart=always` для Vector/Promtail; добавьте health check в monitoring.

## Дополнительная информация

### Смотрите также

- **[Ansible/ansible-callback-plugins.md](../ansible-callback-plugins.md)** — callback-плагины для логирования выполнения Ansible.
- **[Ansible/ansible_security_best_practices.md](../ansible_security_best_practices.md)** — маскирование чувствительных данных, `no_log`.

### Интеграция с другими системами

| Система | Назначение | Интеграция |
|---|---|---|
| **Loki** | Логи, Promtail | Vector/Promtail → Loki |
| **Elasticsearch** | Логи, поиск | Filebeat/rsyslog → Elasticsearch |
| **VictoriaLogs** | Логи, низкие ресурсы | Vector → VictoriaLogs |
| **Alertmanager** | Алерты по логам | Loki/Elasticsearch → Alertmanager |
| **Grafana** | Дашборды | Loki/Elasticsearch → Grafana |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Высокая нагрузка на пайплайн | Источник генерирует логи быстрее, чем приемник может обработать | Настройте `queue.size` и `queue.workerThreads`, добавьте буфер |
| Отключение центрального хранилища | Логи теряются | Используйте local fallback (journald/rsyslog), circuit breaker |
| Чувствительные данные в логах | Утечка паролей, ключей | Настройте маскирование на этапе сбора |
| Ротация не работает | Логи заполняют диск | Проверьте `logrotate -d`, настройте `max-size` |
| Пайплайн логов упал | Логи не доставляются | Настройте мониторинг самого пайплайна (drop rate, queue depth) |
| Логи удалены/изменены | Нет защиты от tampering | Настройте immutable флаг и auditd |
| Retention не применяется | Логи хранятся бесконечно | Настройте ILM в Elasticsearch или retention в Loki |
