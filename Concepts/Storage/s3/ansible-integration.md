# Ansible и S3: интеграция, автоматизация и эксплуатация

**Актуально для:** Ansible 2.15+, community.aws collection 3.x, AWS CLI 2.x, S3 API, Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**Ansible** — инструмент автоматизации конфигурации и развёртывания инфраструктуры, работающий по модели push (agentless). Ansible подключается к целевым хостам по SSH/WinRM и выполняет задачи, описанные в playbooks.

**S3 (Simple Storage Service)** — объектное хранилище с REST API, стандарт де-факто для хранения артефактов, бэкапов, статических файлов. В контексте Ansible используется как:
- **Целевое хранилище** для выгрузки артефактов сборок, бэкапов, конфигураций.
- **Источник файлов** для распространения на серверы (деплой артефактов через S3).
- **Backend для state** распределённых систем (etcd, Consul, Vault — через их S3 backend).
- **Канал доставки** для обновлений пакетов, образов, конфигураций.

**Collection `community.aws`** — community-driven коллекция, содержащая модули для работы с S3 через S3 API. Поддерживает `endpoint_url` для S3-совместимых хранилищ.

**AWS CLI профиль** — конфигурационный файл `~/.aws/config` и `~/.aws/credentials`, содержащий несколько наборов credentials (profiles). Ansible может использовать профили через переменную `profile` в модулях, что позволяет работать с несколькими endpoint'ами.

**no_log** — параметр Ansible задач, который скрывает вывод задачи в логах. Используется для задач с чувствительными данными (credentials, секреты, ключи).

**check_mode** — режим Ansible (`ansible-playbook --check`), который показывает, какие изменения будут применены, без их фактического выполнения. Критично для dry-run перед изменениями production инфраструктуры.

**delegate_to** — параметр Ansible, который перенаправляет выполнение задачи на другой хост. Для S3 операций обычно используется `delegate_to: localhost`, так как boto3 работает на control node.

**block/rescue** — конструкция Ansible для обработки ошибок. `block` группирует задачи, `rescue` выполняется при ошибке в блоке, `always` выполняется всегда. Позволяет реализовать откат (rollback) при ошибках.

---

## 2. Базовые концепции

### 2.1 Почему Ansible + S3

В production-инфраструктуре S3 часто выступает центральным узлом для артефактов и данных, а Ansible — инструментом их распространения и управления. Сочетание даёт:

- **Идемпотентность:** Ansible задачи можно выполнять многократно без побочных эффектов. Если объект уже существует в S3 с нужными свойствами — задача завершится как `ok`, без повторной загрузки.
- **Гранулярный контроль:** Ansible модули предоставляют детальный контроль над bucket'ами, объектами, lifecycle policies, versioning, encryption, notification configuration.
- **Интеграция с пайплайнами:** S3可作为 artefact repository для CI/CD, а Ansible — инструмент доставки этих артефактов на серверы.
- **Управление конфигурацией:** Ansible может управлять bucket configuration (versioning, lifecycle, encryption, bucket policies, CORS, website, tags) так же, как управляет конфигурацией серверов.
- **Audit и reproducibility:** Все изменения S3 configuration описываются в playbooks и версионируются в Git.
- **Error handling и rollback:** Конструкции `block/rescue/always` позволяют реализовать откат при ошибках деплоя.

### 2.2 Архитектура взаимодействия

```
┌─────────────┐     SSH/WinRM     ┌─────────────┐
│ Control     │─────────────────▶│ Target      │
│ Node        │                  │ Hosts       │
│ (Ansible)   │                  │             │
└──────┬──────┘                  └─────────────┘
         │
         │ HTTPS (boto3 / botocore / aws-cli)
         │
         ▼
┌──────────────────────────────────────────────┐
│  Ceph RGW / S3-compatible endpoint            │
│  (http://rgw:7480)                            │
│                                               │
│  - Buckets (артефакты, бэкапы, конфиги)       │
│  - Objects (файлы, архивы)                    │
│  - Configuration (lifecycle, versioning)      │
└──────────────────────────────────────────────┘

Альтернативный паттерн (artifact distribution):

CI/CD → RGW (upload artifacts) → Ansible (download from RGW → deploy)
```

**Два основных паттерна использования:**

1. **Ansible управляет RGW** — Ansible playbooks создают/настраивают bucket'ы, lifecycle policies, versioning, encryption, bucket policies, CORS, website configuration. Используется для infrastructure-as-code RGW configuration.

2. **RGW как artefact repository для Ansible** — CI/CD пайплайн загружает артефакты в RGW, Ansible скачивает их и развёртывает на целевых хостах. RGW выступает промежуточным хранилищем между сборкой и деплоем.

### 2.3 Требования

**Control Node (сервер, на котором запущен Ansible):**
- Ansible 2.15+
- Python 3.8+
- `boto3` и `botocore` (`pip install boto3 botocore`)
- `community.aws` collection (`ansible-galaxy collection install community.aws`)
- AWS CLI 2.x (`pip install awscli`)
- Ceph RGW credentials (access key / secret key)

**Target Hosts (серверы, на которые развёртываются артефакты):**
- Не требуют Python boto3, если Ansible просто копирует файлы с control node.
- Требуют `awscli` если используется `s3_sync` или `s3_object` на целевом хосте (delegate_to: localhost).

---

## 3. Практические сценарии

### 3.1 Управление bucket'ами через community.aws

**Создание bucket с безопасными defaults:**

```yaml
# playbooks/s3_setup.yml
- name: Настройка S3 bucket для артефактов приложения
  hosts: localhost
  gather_facts: false
  collections:
    - community.aws

  vars:
    s3_bucket_name: my-app-artifacts-prod
    s3_region: us-east-1
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Создание S3 bucket
      amazon.aws.s3_bucket:
        name: "{{ s3_bucket_name }}"
        region: "{{ s3_region }}"
        state: present
        endpoint_url: "{{ rgw_endpoint }}"
        versioning:
          status: Enabled
        encryption:
          algorithm: AES256
        public_access:
          block_public_acls: true
          ignore_public_acls: true
          block_public_policy: true
          restrict_public_buckets: true
        lifecycle_rules:
          - id: ArchiveOldReleases
            status: Enabled
            prefix: releases/
            transitions:
              - days: 7
                storage_class: WARM
              - days: 90
                storage_class: COLD
            noncurrent_version_transitions:
              - days: 7
                storage_class: WARM
              - days: 30
                storage_class: COLD
            noncurrent_version_expiration:
              noncurrent_days: 90
            abort_incomplete_multipart_upload:
              days_after_initiation: 7
        tags:
          Environment: production
          Team: platform
          ManagedBy: ansible
      register: bucket_result
      no_log: false

    - name: Применение bucket policy (принудительное шифрование)
      amazon.aws.s3_bucket:
        name: "{{ s3_bucket_name }}"
        region: "{{ s3_region }}"
        state: present
        endpoint_url: "{{ rgw_endpoint }}"
        policy: "{{ lookup('template', 'templates/bucket-policy.json.j2') }}"
      when: bucket_result.changed
      no_log: true

    - name: Вывод информации о bucket
      ansible.builtin.debug:
        msg: "Bucket {{ s3_bucket_name }} создан/обновлён в регионе {{ s3_region }}"
      when: bucket_result.changed
```

**Bucket Policy template (`templates/bucket-policy.json.j2`):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnencryptedUploads",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::{{ s3_bucket_name }}/*",
      "Condition": {
        "StringNotEquals": {"s3:x-amz-server-side-encryption": "AES256"}
      }
    },
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::{{ s3_bucket_name }}",
        "arn:aws:s3:::{{ s3_bucket_name }}/*"
      ],
      "Condition": {
        "Bool": {"aws:SecureTransport": "false"}
      }
    },
    {
      "Sid": "AllowCIUpload",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::rgw:user/ci-user"},
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::{{ s3_bucket_name }}",
        "arn:aws:s3:::{{ s3_bucket_name }}/*"
      ]
    }
  ]
}
```

### 3.2 Загрузка артефактов (deploy)

**Сценарий: CI/CD пайплайн собирает артефакт, загружает в RGW, Ansible доставляет на серверы.**

```yaml
# playbooks/deploy_artifact.yml
- name: Деплой артефакта приложения с RGW
  hosts: app_servers
  gather_facts: true
  vars:
    artifact_bucket: my-app-artifacts-prod
    artifact_key: "releases/v{{ app_version }}/app.tar.gz"
    deploy_path: /opt/app/releases
    service_name: my-app
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Создание директории для релизов
      ansible.builtin.file:
        path: "{{ deploy_path }}"
        state: directory
        owner: app
        group: app
        mode: '0755'

    - name: Скачивание артефакта из RGW
      amazon.aws.s3_object:
        bucket: "{{ artifact_bucket }}"
        key: "{{ artifact_key }}"
        dest: "/tmp/app-{{ app_version }}.tar.gz"
        mode: get
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
      delegate_to: localhost
      run_once: true
      register: download_result
      no_log: false

    - name: Проверка целостности (если есть checksum в S3 metadata)
      amazon.aws.s3_object:
        bucket: "{{ artifact_bucket }}"
        key: "{{ artifact_key }}"
        mode: get
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
      delegate_to: localhost
      run_once: true
      register: s3_metadata
      no_log: false

    - name: Распаковка артефакта
      ansible.builtin.unarchive:
        src: "/tmp/app-{{ app_version }}.tar.gz"
        dest: "{{ deploy_path }}/"
        remote_src: no
        owner: app
        group: app

    - name: Создание symlink на текущий релиз
      ansible.builtin.file:
        src: "{{ deploy_path }}/{{ app_version }}"
        dest: /opt/app/current
        state: link
        force: yes

    - name: Перезапуск сервиса
      ansible.builtin.systemd:
        name: "{{ service_name }}"
        state: restarted
        enabled: true

    - name: Проверка health endpoint
      ansible.builtin.uri:
        url: "http://localhost:8080/health"
        status_code: 200
        timeout: 30
      register: health_check
      no_log: false

    - name: Откат при ошибке health check
      ansible.builtin.file:
        src: "{{ deploy_path }}/{{ previous_version }}"
        dest: /opt/app/current
        state: link
        force: yes
      when: health_check.status != 200

    - name: Очистка старых релизов (храним последние 3)
      ansible.builtin.shell: |
        ls -t {{ deploy_path }} | tail -n +4 | xargs rm -rf
      args:
        executable: /bin/bash
```

**С block/rescue для production-grade отката:**

```yaml
- name: Деплой артефакта с автоматическим откатом
  hosts: app_servers
  gather_facts: true
  vars:
    artifact_bucket: my-app-artifacts-prod
    artifact_key: "releases/v{{ app_version }}/app.tar.gz"
    deploy_path: /opt/app/releases
    service_name: my-app
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Скачивание артефакта из RGW
      amazon.aws.s3_object:
        bucket: "{{ artifact_bucket }}"
        key: "{{ artifact_key }}"
        dest: "/tmp/app-{{ app_version }}.tar.gz"
        mode: get
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
      delegate_to: localhost
      run_once: true
      register: download_result
      no_log: false

    - block:
        - name: Распаковка артефакта
          ansible.builtin.unarchive:
            src: "/tmp/app-{{ app_version }}.tar.gz"
            dest: "{{ deploy_path }}/"
            remote_src: no
            owner: app
            group: app

        - name: Создание symlink на текущий релиз
          ansible.builtin.file:
            src: "{{ deploy_path }}/{{ app_version }}"
            dest: /opt/app/current
            state: link
            force: yes

        - name: Перезапуск сервиса
          ansible.builtin.systemd:
            name: "{{ service_name }}"
            state: restarted
            enabled: true

        - name: Проверка health endpoint
          ansible.builtin.uri:
            url: "http://localhost:8080/health"
            status_code: 200
            timeout: 30
          register: health_check
          no_log: false

      rescue:
        - name: Откат при ошибке деплоя
          ansible.builtin.file:
            src: "{{ deploy_path }}/{{ previous_version }}"
            dest: /opt/app/current
            state: link
            force: yes

        - name: Уведомление об ошибке
          ansible.builtin.debug:
            msg: "Деплой не удался, выполнен откат на {{ previous_version }}"

        - name: Завершение с ошибкой
          ansible.builtin.fail:
            msg: "Деплой не удался, требуется ручное вмешательство"

      always:
        - name: Очистка временных файлов
          ansible.builtin.file:
            path: "/tmp/app-{{ app_version }}.tar.gz"
            state: absent
```

### 3.3 Использование radosgw-admin через Ansible

```yaml
- name: Управление пользователями RGW через radosgw-admin
  hosts: ceph_mon
  gather_facts: true
  vars:
    rgw_user: app-user
    rgw_bucket: my-app-backups

  tasks:
    - name: Создание RGW пользователя
      ansible.builtin.command: >
        radosgw-admin user create
        --uid="{{ rgw_user }}"
        --display-name="Application User"
        --system
      register: user_create
      changed_when: "'user_id' in user_create.stdout"

    - name: Получение ключей пользователя
      ansible.builtin.command: >
        radosgw-admin user info --uid="{{ rgw_user }}"
      register: user_info
      changed_when: false

    - name: Установка квоты на пользователя
      ansible.builtin.command: >
        radosgw-admin user modify --uid="{{ rgw_user }}"
        --max-bytes=10737418240
        --max-objects=1000
      register: quota_set
      changed_when: quota_set.rc == 0

    - name: Статистика пользователя
      ansible.builtin.command: >
        radosgw-admin user stats --uid="{{ rgw_user }}"
      register: user_stats
      changed_when: false
```

### 3.4 Синхронизация директории в RGW

```yaml
- name: Синхронизация директории конфигураций в RGW
  hosts: localhost
  gather_facts: false
  vars:
    config_bucket: my-app-configs-prod
    local_config_dir: ./configs/
    s3_prefix: configs/{{ ansible_date_time.date }}/
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Синхронизация локальной директории в RGW
      amazon.aws.s3_sync:
        bucket: "{{ config_bucket }}"
        prefix: "{{ s3_prefix }}"
        file_root: "{{ local_config_dir }}"
        mode: upload
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
        metadata:
          managed_by: ansible
          sync_date: "{{ ansible_date_time.iso8601 }}"
        storage_class: WARM
      register: sync_result

    - name: Удаление старых конфигураций (старше 7 дней)
      amazon.aws.s3_object:
        bucket: "{{ config_bucket }}"
        prefix: "configs/"
        mode: delete
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
      when: sync_result.changed
```

### 3.5 Event-driven: обработка событий RGW

**Сценарий: при загрузке файла в RGW генерируется событие, которое триггерит Ansible через HTTP webhook или MQTT.**

```yaml
# playbooks/process_rgw_event.yml
- name: Обработка загруженного файла (вызывается из webhook)
  hosts: localhost
  gather_facts: false
  vars:
    event_bucket: "{{ s3_event.Records[0].s3.bucket.name }}"
    event_key: "{{ s3_event.Records[0].s3.object.key }}"
    event_size: "{{ s3_event.Records[0].s3.object.size }}"

  tasks:
    - name: Логирование события
      ansible.builtin.debug:
        msg: "Загружен объект {{ event_key }} ({{ event_size }} bytes) в bucket {{ event_bucket }}"

    - name: Проверка расширения файла
      ansible.builtin.set_fact:
        file_ext: "{{ event_key | splitext | last }}"

    - name: Обработка CSV файла (загрузка в базу)
      ansible.builtin.include_tasks: tasks/process_csv.yml
      when: file_ext == '.csv'

    - name: Обработка JSON файла (валидация schema)
      ansible.builtin.include_tasks: tasks/process_json.yml
      when: file_ext == '.json'

    - name: Архивирование обработанного файла
      amazon.aws.s3_object:
        bucket: "{{ event_bucket }}"
        key: "{{ event_key }}"
        mode: copy
        dest: "processed/{{ event_key }}"
        metadata:
          processed_at: "{{ ansible_date_time.iso8601 }}"
          processor: ansible
        endpoint_url: "http://rgw:7480"
      delegate_to: localhost
```

### 3.6 Резервное копирование серверов в RGW

```yaml
- name: Бэкап баз данных в RGW
  hosts: db_servers
  gather_facts: true
  vars:
    backup_bucket: my-app-backups-prod
    backup_region: us-east-1
    postgres_data_dir: /var/lib/postgresql/14/main
    retention_days: 30
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Создание директории для временных бэкапов
      ansible.builtin.file:
        path: /tmp/backups
        state: directory
        mode: '0700'

    - name: Дамп PostgreSQL
      ansible.builtin.shell: |
        pg_dump -U postgres -Fc mydb > /tmp/backups/mydb-{{ ansible_date_time.date }}.dump
      args:
        executable: /bin/bash
      environment:
        PGPASSWORD: "{{ postgres_password }}"
      no_log: true

    - name: Сжатие бэкапа
      ansible.builtin.shell: |
        zstd -3 /tmp/backups/mydb-{{ ansible_date_time.date }}.dump
      args:
        executable: /bin/bash

    - name: Загрузка бэкапа в RGW
      amazon.aws.s3_object:
        bucket: "{{ backup_bucket }}"
        key: "postgres/{{ ansible_date_time.date }}/mydb-{{ ansible_date_time.date }}.dump.zst"
        src: "/tmp/backups/mydb-{{ ansible_date_time.date }}.dump.zst"
        mode: put
        region: "{{ backup_region }}"
        endpoint_url: "{{ rgw_endpoint }}"
        storage_class: WARM
        encryption: AES256
        metadata:
          host: "{{ ansible_hostname }}"
          db: mydb
          backup_type: pg_dump
      delegate_to: localhost
      register: upload_result

    - name: Проверка загрузки
      ansible.builtin.assert:
        that:
          - upload_result.changed or upload_result.checksum_same
        fail_msg: "Бэкап не был загружен в RGW"
        success_msg: "Бэкап успешно загружен"

    - name: Очистка временных файлов
      ansible.builtin.file:
        path: "/tmp/backups/mydb-{{ ansible_date_time.date }}.dump.zst"
        state: absent
```

### 3.7 Управление конфигурациями через RGW

**Сценарий: конфигурации приложений хранятся в RGW, Ansible гарантирует, что на серверах актуальные версии.**

```yaml
- name: Распространение конфигураций из RGW
  hosts: app_servers
  gather_facts: true
  vars:
    config_bucket: my-app-configs-prod
    config_prefix: "configs/{{ app_env }}/"
    local_config_dir: /etc/myapp/
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Получение списка конфигураций из RGW
      amazon.aws.s3_object:
        bucket: "{{ config_bucket }}"
        prefix: "{{ config_prefix }}"
        mode: list
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
      delegate_to: localhost
      run_once: true
      register: s3_configs

    - name: Скачивание конфигураций
      amazon.aws.s3_object:
        bucket: "{{ config_bucket }}"
        key: "{{ item.key }}"
        dest: "{{ local_config_dir }}/{{ item.key | basename }}"
        mode: get
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
      delegate_to: localhost
      loop: "{{ s3_configs.s3_keys }}"
      loop_control:
        label: "{{ item.key }}"
      register: download_results

    - name: Установка прав на конфигурации
      ansible.builtin.file:
        path: "{{ local_config_dir }}/{{ item.key | basename }}"
        owner: root
        group: root
        mode: '0640'
      loop: "{{ s3_configs.s3_keys }}"
      loop_control:
        label: "{{ item.key | basename }}"
```

### 3.8 S3 как backend для etcd (через Ansible)

**Сценарий: развёртывание etcd с S3 backend для бэкапов.**

```yaml
- name: Настройка etcd с S3 backup backend
  hosts: etcd_servers
  gather_facts: true
  vars:
    etcd_data_dir: /var/lib/etcd
    backup_bucket: my-etcd-backups-prod
    backup_region: us-east-1
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Установка awscli для etcd backup скрипта
      ansible.builtin.package:
        name: awscli
        state: present

    - name: Создание systemd service для автоматического бэкапа
      ansible.builtin.copy:
        dest: /etc/systemd/system/etcd-s3-backup.service
        content: |
          [Unit]
          Description=etcd S3 Backup
          After=network.target

          [Service]
          Type=oneshot
          ExecStart=/usr/local/bin/etcd-s3-backup.sh
          Environment=AWS_DEFAULT_REGION={{ backup_region }}
          Environment=BACKUP_BUCKET={{ backup_bucket }}
          Environment=RGW_ENDPOINT={{ rgw_endpoint }}
        mode: '0644'

    - name: Создание systemd timer
      ansible.builtin.copy:
        dest: /etc/systemd/system/etcd-s3-backup.timer
        content: |
          [Unit]
          Description=etcd S3 Backup Timer (every 6 hours)
          Requires=etcd-s3-backup.service

          [Timer]
          OnBootSec=5min
          OnUnitActiveSec=6h
          Persistent=true

          [Install]
          WantedBy=timers.target
        mode: '0644'

    - name: Включение timer
      ansible.builtin.systemd:
        name: etcd-s3-backup.timer
        state: started
        enabled: true
        daemon_reload: yes
```

**Bash скрипт `/usr/local/bin/etcd-s3-backup.sh` (вызывается Ansible):**

```bash
#!/bin/bash
set -euo pipefail

DATE=$(date +%Y%m%d-%H%M%S)
ETCDCTL_API=3 etcdctl --endpoints=http://localhost:2379 \
  snapshot save /tmp/etcd-snapshot-${DATE}.db

aws s3 cp /tmp/etcd-snapshot-${DATE}.db \
  s3://${BACKUP_BUCKET}/etcd/${DATE}/ \
  --storage-class WARM \
  --server-side-encryption AES256 \
  --endpoint-url ${RGW_ENDPOINT}

rm /tmp/etcd-snapshot-${DATE}.db
```

---

## 4. Ansible и Vault Secrets in RGW

**Сценарий: хранение зашифрованных секретов в RGW, доступ через Ansible Vault.**

```yaml
- name: Загрузка зашифрованных секретов в RGW
  hosts: localhost
  gather_facts: false
  vars:
    secrets_bucket: my-app-secrets-prod
    vault_password_file: ~/.vault_pass.txt
    rgw_endpoint: http://rgw:7480

  tasks:
    - name: Шифрование секрета через Ansible Vault
      ansible.builtin.shell: |
        echo 'db_password: "SuperSecret123!"' | \
        ansible-vault encrypt --vault-password-file {{ vault_password_file }}
      register: encrypted_secret
      changed_when: false

    - name: Загрузка зашифрованного секрета в RGW
      amazon.aws.s3_object:
        bucket: "{{ secrets_bucket }}"
        key: "app/db-password.yml"
        content: "{{ encrypted_secret.stdout }}"
        mode: put
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
        encryption: AES256

    - name: Скачивание и дешифрование секрета
      amazon.aws.s3_object:
        bucket: "{{ secrets_bucket }}"
        key: "app/db-password.yml"
        dest: "/tmp/db-password.yml"
        mode: get
        region: us-east-1
        endpoint_url: "{{ rgw_endpoint }}"
      delegate_to: localhost
      register: secret_download

    - name: Чтение секрета
      ansible.builtin.include_vars:
        file: /tmp/db-password.yml
        name: db_creds
      no_log: true

    - name: Очистка временного файла
      ansible.builtin.file:
        path: /tmp/db-password.yml
        state: absent
```

---

## 5. S3-compatible хранилища

### 5.1 Общие параметры подключения

При работе с Ceph RGW через Ansible используйте следующие параметры модулей:

| Параметр | Назначение | Пример |
|----------|-----------|--------|
| `endpoint_url` | Эндпоинт хранилища | `http://rgw:7480` |
| `region` | Регион (может быть любым для self-hosted) | `us-east-1` |
| `profile` | AWS CLI profile из `~/.aws/config` | `rgw` |
| `validate_certs` | Проверка SSL сертификата | `false` (для self-signed) |
| `addressing_style` | Стиль адресации: `path` или `virtual` | `path` |

**Важно:** Path-style addressing (`addressing_style: path`) обязателен для Ceph RGW.

### 5.2 Быстрые примеры подключения

```yaml
- name: Работа с Ceph RGW через Ansible
  hosts: localhost
  gather_facts: false
  vars:
    rgw_endpoint: http://rgw:7480
    rgw_bucket: my-app-backups

  tasks:
    - name: Создание bucket в Ceph RGW
      amazon.aws.s3_bucket:
        name: "{{ rgw_bucket }}"
        endpoint_url: "{{ rgw_endpoint }}"
        region: us-east-1
        state: present
        validate_certs: false
      delegate_to: localhost
```

---

## 6. Troubleshooting

### 6.1 Ошибки подключения к RGW

**Симптом:** `botocore.exceptions.NoCredentialsError` или `Unable to locate credentials`

**Причины и решения:**

```yaml
# 1. Не настроены AWS credentials
- name: Проверка credentials
  ansible.builtin.command: aws sts get-caller-identity --endpoint-url http://rgw:7480
  delegate_to: localhost

# 2. Неправильный endpoint
- name: Тест с явным указанием endpoint
  amazon.aws.s3_object:
    bucket: my-bucket
    key: test.txt
    mode: list
    region: us-east-1
    endpoint_url: http://rgw:7480
  delegate_to: localhost
```

### 6.2 403 Forbidden

**Причины:**
- Bucket policy или ACL блокирует доступ.
- Неправильный `addressing_style` для S3-compatible хранилища.
- Нет permissions на bucket/object.

**Диагностика:**
```yaml
- name: Проверка bucket policy
  amazon.aws.s3_bucket:
    name: my-app-artifacts-prod
    region: us-east-1
    mode: get
    endpoint_url: "http://rgw:7480"
  delegate_to: localhost
  register: bucket_info

- name: Вывод bucket policy для диагностики
  ansible.builtin.debug:
    var: bucket_info.policy
```

### 6.3 Ошибки при больших файлах

**Симптом:** Upload/download зависает или fails для файлов > 1 ГБ.

**Решение:** Используйте multipart upload через `s3_sync` или настройте multipart parameters:

```yaml
- name: Загрузка большого файла с multipart
  amazon.aws.s3_object:
    bucket: my-app-artifacts-prod
    key: "releases/large-backup.tar.gz"
    src: "/tmp/large-backup.tar.gz"
    mode: put
    region: us-east-1
    endpoint_url: "http://rgw:7480"
    multipart_threshold: 64MB
    multipart_chunksize: 16MB
  delegate_to: localhost
```

### 6.4 Проблемы с консистентностью

**Причины:**
- Ceph RGW: eventual consistency для LIST операций.
- Overwrite может временно возвращать старую версию.

**Решение:**
```yaml
- name: Загрузка с проверкой ETag
  amazon.aws.s3_object:
    bucket: my-app-artifacts-prod
    key: "releases/app.tar.gz"
    src: "./app.tar.gz"
    mode: put
    region: us-east-1
    endpoint_url: "http://rgw:7480"
  register: upload

- name: Проверка ETag после загрузки
  ansible.builtin.assert:
    that:
      - upload.etag is defined
    fail_msg: "ETag не был возвращен после загрузки"
    success_msg: "Объект загружен с ETag {{ upload.etag }}"
```

### 6.5 Ошибки SSL/TLS и endpoint

**Симптом:** `SSL: CERTIFICATE_VERIFY_FAILED` или `ConnectionError`

**Причины:**
- Self-signed сертификат на RGW.
- Неправильный endpoint URL.

**Решение:**
```yaml
# Для self-signed сертификатов
- name: Загрузка с отключенной проверкой SSL
  amazon.aws.s3_object:
    bucket: my-bucket
    key: test.txt
    mode: get
    region: us-east-1
    endpoint_url: "http://rgw:7480"
    validate_certs: false
  delegate_to: localhost
```

### 6.6 idempotency violations

**Симптом:** Повторный запуск playbook показывает `changed` для уже существующих bucket'ов.

**Причины:**
- Не все параметры модуля `s3_bucket` поддерживают сравнение для idempotency.
- Bucket policy применяется отдельным модулем, что может вызывать лишние изменения.

**Решение:**
```yaml
# Используйте register + assert для проверки idempotency
- name: Проверка idempotency
  amazon.aws.s3_bucket:
    name: my-app-artifacts-prod
    region: us-east-1
    state: present
    versioning:
      status: Enabled
    endpoint_url: "http://rgw:7480"
  register: bucket_result

- name: Assert idempotency
  ansible.builtin.assert:
    that:
      - not bucket_result.changed
    fail_msg: "Задача не идемпотентна"
```

---

## 7. Best Practices (Production Checklist)

### Security
- [ ] Используются **краткоживущие credentials** (STS, Vault, OIDC) вместо статических ключей.
- [ ] **RGW bucket'ы** имеют включённый Block Public Access.
- [ ] Используется **SSE-S3** или **SSE-KMS** (rgw crypto / Vault) для encryption at rest.
- [ ] Настроен **Bucket Policy** с explicit Deny для нешифрованных загрузок.
- [ ] **AWS CLI профили** хранятся в защищённом месте (`~/.aws/` с permissions 600).
- [ ] Используется **no_log: true** для задач с чувствительными данными.
- [ ] Включён **Bucket Owner Enforced** для отключения ACL.

### Reliability
- [ ] **Multipart upload** используется для файлов > 5 ГБ.
- [ ] **Retry logic** добавлен в playbooks для неидемпотентных операций.
- [ ] **Idempotency** проверена: повторный запуск playbook не вызывает дублирования.
- [ ] **Checksum validation** после загрузки/скачивания.
- [ ] **Lifecycle policies** настроены через Ansible для автоматического управления.
- [ ] **Versioning** включён для критичных bucket'ов.
- [ ] **Object Lock** или **Legal Hold** для критичных данных.
- [ ] **Multisite replication** настроен для DR.

### Operational
- [ ] Playbooks версионируются в Git.
- [ ] Используются **tags** для запуска только необходимых tasks.
- [ ] **delegate_to: localhost** явно указан для S3 операций.
- [ ] **check_mode** поддерживается для dry-run перед применением.
- [ ] **block/rescue/always** используется для отката при ошибках.
- [ ] **IAM permissions** минимальные (principle of least privilege).
- [ ] **assert** используется для валидации результатов операций.

### Performance
- [ ] **Multipart threshold** увеличен для больших файлов.
- [ ] **max_concurrent_requests** увеличен для параллельных загрузок.
- [ ] **addressing_style=path** настроен для RGW endpoint'ов.
- [ ] **Prefix naming** оптимизирован для параллелизма.

### Cost Optimization
- [ ] **Lifecycle policies** настроены для миграции между hot/warm/cold pools.
- [ ] **Versioning** включён для критичных bucket'ов.
- [ ] **Inventory** настроен для анализа объектов.
- [ ] **Multipart upload cleanup** настроен через lifecycle.

### Cleanup и откат

Знайте, как откатить изменения:

```bash
# Отключение versioning
aws s3api put-bucket-versioning --bucket my-app-artifacts-prod --versioning-configuration Status=Suspended --endpoint-url http://rgw:7480

# Удаление lifecycle
aws s3api delete-bucket-lifecycle --bucket my-app-artifacts-prod --endpoint-url http://rgw:7480

# Удаление bucket policy
aws s3api delete-bucket-policy --bucket my-app-artifacts-prod --endpoint-url http://rgw:7480

# Удаление encryption
aws s3api delete-bucket-encryption --bucket my-app-artifacts-prod --endpoint-url http://rgw:7480

# Удаление public access block
aws s3api delete-public-access-block --bucket my-app-artifacts-prod --endpoint-url http://rgw:7480

# Удаление CORS
aws s3api delete-bucket-cors --bucket my-app-artifacts-prod --endpoint-url http://rgw:7480

# Отмена multipart upload
aws s3api abort-multipart-upload --bucket my-app-artifacts-prod --key <key> --upload-id <id> --endpoint-url http://rgw:7480
```

---

## 8. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [Ceph RGW: S3-совместимое хранилище на базе Ceph](../../../Kubernetes/Storage/Ceph/ceph_rgw_s3.md)
