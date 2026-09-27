# Ansible и S3: интеграция, автоматизация и эксплуатация

## 1. Определения

**Ansible** — инструмент автоматизации конфигурации и развёртывания инфраструктуры, работающий по модели push (agentless). Ansible подключается к целевым хостам по SSH/WinRM и выполняет задачи, описанные в playbooks.

**S3 (Simple Storage Service)** — объектное хранилище с REST API, стандарт де-факто для хранения артефактов, бэкапов, статических файлов. В контексте Ansible используется как:
- **Целевое хранилище** для выгрузки артефактов сборок, бэкапов, конфигураций.
- **Источник файлов** для распространения на серверы (деплой артефактов через S3).
- **Backend для state** распределённых систем (etcd, Consul, Vault — через их S3 backend).
- **Канал доставки** для обновлений пакетов, образов, конфигураций.

**Ansible Collection `amazon.aws`** — официальная коллекция модулей для работы с AWS, включая S3. Содержит модули `s3_bucket`, `s3_object`, `s3_sync`. Требует установки `boto3` и `botocore` на control node.

**Collection `community.aws`** — community-driven коллекция, часто содержит альтернативные реализации и более новые фичи. В некоторых случаях `amazon.aws` и `community.aws` дублируют модули; предпочитайте `amazon.aws` для production.

**AWS CLI профиль** — конфигурационный файл `~/.aws/config` и `~/.aws/credentials`, содержащий несколько наборов credentials (profiles). Ansible может использовать профили через переменную `profile` в модулях, что позволяет работать с несколькими аккаунтами AWS.

**IAM Role** — роль AWS IAM, которая может быть назначена EC2 инстансу, Lambda, ECS task и другим сервисам. Роли позволяют избежать хранения статических ключей на инстансах, так как credentials предоставляются временно через instance metadata service (IMDS).

**Instance Metadata Service (IMDS)** — HTTP-сервис на уровне EC2 инстанса, доступный по `http://169.254.169.254`. Предоставляет временные credentials IAM role, назначенного инстансу. Ansible, запущенный на EC2, автоматически использует IMDS credentials, если не заданы явные ключи.

**VPC Endpoint (Gateway)** — инфраструктурный компонент AWS, позволяющий обращаться к S3 напрямую через private network внутри VPC, без выхода в интернет через Internet Gateway или NAT Gateway. Критично для security и latency в production.

---

## 2. Базовые концепции

### 2.1 Почему Ansible + S3

В production-инфраструктуре S3 часто выступает центральным узлом для артефактов и данных, а Ansible — инструментом их распространения и управления. Сочетание даёт:

- **Идемпотентность:** Ansible задачи можно выполнять многократно без побочных эффектов. Если объект уже существует в S3 с нужными свойствами — задача завершится как `ok`, без повторной загрузки.
- **Гранулярный контроль:** Ansible модули предоставляют детальный контроль над bucket'ами, объектами, lifecycle policies, versioning, encryption.
- **Интеграция с пайплайнами:** S3可作为 artefact repository для CI/CD, а Ansible — инструмент доставки этих артефактов на серверы.
- **Управление конфигурацией:** Ansible может управлять bucket configuration (versioning, lifecycle, encryption, bucket policies) так же, как управляет конфигурацией серверов.
- **Audit и reproducibility:** Все изменения S3 configuration описываются в playbooks и версионируются в Git.

### 2.2 Архитектура взаимодействия

```
┌─────────────┐     SSH/WinRM     ┌─────────────┐
│ Control     │─────────────────▶│ Target      │
│ Node        │                  │ Hosts       │
│ (Ansible)   │                  │             │
└──────┬──────┘                  └─────────────┘
       │
       │ HTTPS (boto3)
       │
       ▼
┌──────────────────────────────────────────────┐
│  AWS S3 / S3-compatible endpoint              │
│  (Ceph RGW, Garage, Yandex Storage)           │
│                                               │
│  - Buckets (артефакты, бэкапы, конфиги)       │
│  - Objects (файлы, архивы)                    │
│  - Configuration (lifecycle, versioning)      │
└──────────────────────────────────────────────┘

Альтернативный паттерн (artifact distribution):

CI/CD → S3 (upload artifacts) → Ansible (download from S3 → deploy)
```

**Два основных паттерна использования:**

1. **Ansible управляет S3** — Ansible playbooks создают/настраивают bucket'ы, lifecycle policies, versioning, encryption, IAM policies. Используется для infrastructure-as-code S3 configuration.

2. **S3 как artefact repository для Ansible** — CI/CD пайплайн загружает артефакты в S3, Ansible скачивает их и развёртывает на целевых хостах. S3 выступает промежуточным хранилищем между сборкой и деплоем.

### 2.3 Требования

**Control Node (сервер, на котором запущен Ansible):**
- Python 3.8+
- `boto3` и `botocore` (`pip install boto3 botocore`)
- `amazon.aws` collection (`ansible-galaxy collection install amazon.aws`)
- AWS credentials (IAM user/role с permissions на S3)

**Target Hosts (серверы, на которые развёртываются артефакты):**
- Не требуют Python boto3, если Ansible просто копирует файлы с control node.
- Требуют `boto3` если используется `s3_sync` или `s3_object` на целевом хосте (delegate_to: localhost).

**AWS Permissions (минимальные для S3 управления):**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:PutBucketVersioning",
        "s3:GetBucketVersioning",
        "s3:PutBucketEncryption",
        "s3:GetBucketEncryption",
        "s3:PutBucketPolicy",
        "s3:GetBucketPolicy",
        "s3:DeleteBucketPolicy",
        "s3:PutBucketLifecycleConfiguration",
        "s3:GetBucketLifecycleConfiguration",
        "s3:DeleteBucketLifecycle",
        "s3:PutBucketAcl",
        "s3:PutObjectAcl",
        "s3:PutPublicAccessBlock",
        "s3:GetPublicAccessBlock"
      ],
      "Resource": [
        "arn:aws:s3:::my-app-artifacts",
        "arn:aws:s3:::my-app-artifacts/*"
      ]
    }
  ]
}
```

---

## 3. Практические сценарии

### 3.1 Управление bucket'ами

**Создание bucket с безопасными defaults:**

```yaml
# playbooks/s3_setup.yml
- name: Настройка S3 bucket для артефактов приложения
  hosts: localhost
  gather_facts: false
  collections:
    - amazon.aws

  vars:
    s3_bucket_name: my-app-artifacts-prod
    s3_region: eu-central-1
    kms_key_id: "arn:aws:kms:eu-central-1:123456789012:alias/app-key"

  tasks:
    - name: Создание S3 bucket
      amazon.aws.s3_bucket:
        name: "{{ s3_bucket_name }}"
        region: "{{ s3_region }}"
        state: present
        versioning:
          status: Enabled
        encryption:
          algorithm: aws:kms
          kms_key_id: "{{ kms_key_id }}"
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
              - days: 30
                storage_class: STANDARD_IA
              - days: 90
                storage_class: GLACIER_IR
              - days: 365
                storage_class: DEEP_ARCHIVE
            noncurrent_version_transitions:
              - days: 7
                storage_class: STANDARD_IA
              - days: 30
                storage_class: GLACIER_IR
            noncurrent_version_expiration:
              noncurrent_days: 90
            abort_incomplete_multipart_upload:
              days_after_initiation: 7
          - id: DeleteOldLogs
            status: Enabled
            prefix: logs/
            expiration:
              days: 30
            abort_incomplete_multipart_upload:
              days_after_initiation: 1
        tags:
          Environment: production
          Team: platform
          ManagedBy: ansible
      register: bucket_result

    - name: Применение bucket policy (принудительное шифрование)
      amazon.aws.s3_bucket:
        name: "{{ s3_bucket_name }}"
        region: "{{ s3_region }}"
        policy: "{{ lookup('template', 'templates/bucket-policy.json.j2') }}"
      when: bucket_result.changed

    - name: Вывод информации о bucket
      debug:
        msg: "Bucket {{ s3_bucket_name }} создан/обновлён в регионе {{ s3_region }}"
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
        "StringNotEquals": {"s3:x-amz-server-side-encryption": "aws:kms"}
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
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:role/ci-deploy-role"
      },
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

**Сценарий: CI/CD пайплайн собирает артефакт, загружает в S3, Ansible доставляет на серверы.**

```yaml
# playbooks/deploy_artifact.yml
- name: Деплой артефакта приложения с S3
  hosts: app_servers
  gather_facts: true
  vars:
    artifact_bucket: my-app-artifacts-prod
    artifact_key: "releases/v{{ app_version }}/app.tar.gz"
    deploy_path: /opt/app/releases
    service_name: my-app

  tasks:
    - name: Создание директории для релизов
      ansible.builtin.file:
        path: "{{ deploy_path }}"
        state: directory
        owner: app
        group: app
        mode: '0755'

    - name: Скачивание артефакта из S3
      amazon.aws.s3_object:
        bucket: "{{ artifact_bucket }}"
        key: "{{ artifact_key }}"
        dest: "/tmp/app-{{ app_version }}.tar.gz"
        mode: get
        region: eu-central-1
      delegate_to: localhost
      run_once: true
      register: download_result

    - name: Проверка целостности (если есть checksum в S3 metadata)
      amazon.aws.s3_object:
        bucket: "{{ artifact_bucket }}"
        key: "{{ artifact_key }}"
        mode: get
      delegate_to: localhost
      run_once: true
      register: s3_metadata

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

### 3.3 Синхронизация директории в S3

```yaml
- name: Синхронизация директории конфигураций в S3
  hosts: localhost
  gather_facts: false
  collections:
    - amazon.aws

  vars:
    config_bucket: my-app-configs-prod
    local_config_dir: ./configs/
    s3_prefix: configs/{{ ansible_date_time.date }}/

  tasks:
    - name: Синхронизация локальной директории в S3
      amazon.aws.s3_sync:
        bucket: "{{ config_bucket }}"
        prefix: "{{ s3_prefix }}"
        file_root: "{{ local_config_dir }}"
        mode: upload
        region: eu-central-1
        metadata:
          managed_by: ansible
          sync_date: "{{ ansible_date_time.iso8601 }}"
        storage_class: STANDARD_IA
      register: sync_result

    - name: Удаление старых конфигураций (старше 7 дней)
      amazon.aws.s3_object:
        bucket: "{{ config_bucket }}"
        prefix: "configs/"
        mode: delete
        region: eu-central-1
      when: sync_result.changed
```

### 3.4 Event-driven: обработка событий S3

**Сценарий: при загрузке файла в S3 генерируется событие, которое триггерит Ansible через AWS Lambda или EventBridge.**

```yaml
# playbooks/process_s3_event.yml
- name: Обработка загруженного файла (вызывается из Lambda)
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
      delegate_to: localhost
```

### 3.5 Резервное копирование серверов в S3

```yaml
- name: Бэкап баз данных в S3
  hosts: db_servers
  gather_facts: true
  vars:
    backup_bucket: my-app-backups-prod
    backup_region: eu-central-1
    postgres_data_dir: /var/lib/postgresql/14/main
    retention_days: 30

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

    - name: Сжатие бэкапа
      ansible.builtin.shell: |
        zstd -3 /tmp/backups/mydb-{{ ansible_date_time.date }}.dump
      args:
        executable: /bin/bash

    - name: Загрузка бэкапа в S3
      amazon.aws.s3_object:
        bucket: "{{ backup_bucket }}"
        key: "postgres/{{ ansible_date_time.date }}/mydb-{{ ansible_date_time.date }}.dump.zst"
        src: "/tmp/backups/mydb-{{ ansible_date_time.date }}.dump.zst"
        mode: put
        region: "{{ backup_region }}"
        storage_class: STANDARD_IA
        encryption: aws:kms
        kms_key_id: "arn:aws:kms:{{ backup_region }}:123456789012:alias/backup-key"
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
        fail_msg: "Бэкап не был загружен в S3"
        success_msg: "Бэкап успешно загружен"

    - name: Очистка временных файлов
      ansible.builtin.file:
        path: /tmp/backups/mydb-{{ ansible_date_time.date }}.dump.zst
        state: absent
```

### 3.6 Управление конфигурациями через S3

**Сценарий: конфигурации приложений хранятся в S3, Ansible гарантирует, что на серверах актуальные версии.**

```yaml
- name: Распространение конфигураций из S3
  hosts: app_servers
  gather_facts: true
  vars:
    config_bucket: my-app-configs-prod
    config_prefix: "configs/{{ app_env }}/"
    local_config_dir: /etc/myapp/

  tasks:
    - name: Получение списка конфигураций из S3
      amazon.aws.s3_object:
        bucket: "{{ config_bucket }}"
        prefix: "{{ config_prefix }}"
        mode: list
        region: eu-central-1
      delegate_to: localhost
      run_once: true
      register: s3_configs

    - name: Скачивание конфигураций
      amazon.aws.s3_object:
        bucket: "{{ config_bucket }}"
        key: "{{ item.key }}"
        dest: "{{ local_config_dir }}/{{ item.key | basename }}"
        mode: get
        region: eu-central-1
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

### 3.7 S3 как backend для etcd/Vault (через Ansible)

**Сценарий: развёртывание etcd с S3 backend для бэкапов.**

```yaml
- name: Настройка etcd с S3 backup backend
  hosts: etcd_servers
  gather_facts: true
  vars:
    etcd_data_dir: /var/lib/etcd
    backup_bucket: my-etcd-backups-prod
    backup_region: eu-central-1

  tasks:
    - name: Установка awscli для etcd backup скрипта
      ansible.builtin.package:
        name: awscli
        state: present

    - name: Настройка IAM role для EC2 (предпочтительно)
      ansible.builtin.debug:
        msg: "Назначьте IAM role с permissions на S3 backup bucket EC2 инстансу"

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
  --storage-class STANDARD_IA \
  --server-side-encryption aws:kms \
  --sse-kms-key-id arn:aws:kms:${AWS_DEFAULT_REGION}:123456789012:alias/backup-key

rm /tmp/etcd-snapshot-${DATE}.db
```

---

## 4. Ansible и Vault Secrets in S3

**Сценарий: хранение зашифрованных секретов в S3, доступ через Ansible Vault.**

```yaml
- name: Загрузка зашифрованных секретов в S3
  hosts: localhost
  gather_facts: false
  vars:
    secrets_bucket: my-app-secrets-prod
    vault_password_file: ~/.vault_pass.txt

  tasks:
    - name: Шифрование секрета через Ansible Vault
      ansible.builtin.shell: |
        echo 'db_password: "SuperSecret123!"' | \
        ansible-vault encrypt --vault-password-file {{ vault_password_file }}
      register: encrypted_secret
      changed_when: false

    - name: Загрузка зашифрованного секрета в S3
      amazon.aws.s3_object:
        bucket: "{{ secrets_bucket }}"
        key: "app/db-password.yml"
        content: "{{ encrypted_secret.stdout }}"
        mode: put
        region: eu-central-1
        encryption: aws:kms
        kms_key_id: "arn:aws:kms:eu-central-1:123456789012:alias/secret-key"

    - name: Скачивание и дешифрование секрета
      amazon.aws.s3_object:
        bucket: "{{ secrets_bucket }}"
        key: "app/db-password.yml"
        dest: "/tmp/db-password.yml"
        mode: get
        region: eu-central-1
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

### 5.1 Ceph RGW

```yaml
- name: Работа с Ceph RGW через Ansible
  hosts: localhost
  gather_facts: false
  vars:
    rgw_endpoint: http://ceph-rgw.local:7480
    rgw_bucket: my-app-backups

  tasks:
    - name: Создание bucket в Ceph RGW
      amazon.aws.s3_bucket:
        name: "{{ rgw_bucket }}"
        endpoint_url: "{{ rgw_endpoint }}"
        region: us-east-1
        mode: put
        validate_certs: false
```

### 5.2 Yandex Object Storage

```yaml
- name: Работа с Yandex Object Storage через Ansible
  hosts: localhost
  gather_facts: false
  vars:
    yandex_endpoint: https://storage.yandexcloud.net
    yandex_bucket: my-yandex-bucket
    yandex_profile: yandex

  tasks:
    - name: Создание bucket в Yandex Storage
      amazon.aws.s3_bucket:
        name: "{{ yandex_bucket }}"
        endpoint_url: "{{ yandex_endpoint }}"
        region: ru-central1
        profile: "{{ yandex_profile }}"
        mode: put
```

### 5.3 Garage

```yaml
- name: Работа с Garage через Ansible
  hosts: localhost
  gather_facts: false
  vars:
    garage_endpoint: http://garage.local:3900
    garage_bucket: my-garage-bucket

  tasks:
    - name: Создание bucket в Garage
      amazon.aws.s3_bucket:
        name: "{{ garage_bucket }}"
        endpoint_url: "{{ garage_endpoint }}"
        region: us-east-1
        mode: put
        validate_certs: false
```

---

## 6. Troubleshooting

### 6.1 Ошибки подключения к S3

**Симптом:** `botocore.exceptions.NoCredentialsError` или `Unable to locate credentials`

**Причины и решения:**

```yaml
# 1. Не настроены AWS credentials
# Решение: экспортируйте переменные или используйте aws configure
- name: Проверка credentials
  ansible.builtin.command: aws sts get-caller-identity
  delegate_to: localhost

# 2. Неправильный profile
- name: Тест с явным указанием profile
  amazon.aws.s3_object:
    bucket: my-bucket
    key: test.txt
    profile: my-profile
    region: eu-central-1
    mode: list

# 3. IAM role не применился (на EC2)
- name: Проверка IAM role
  ansible.builtin.uri:
    url: http://169.254.169.254/latest/meta-data/iam/security-credentials/
  delegate_to: localhost
```

### 6.2 403 Forbidden

**Причины:**
- IAM policy не授予 permissions на bucket/object.
- Bucket Policy denies доступ.
- KMS key policy denies `kms:Decrypt` для SSE-KMS объектов.
- Bucket в другом аккаунте, нет bucket owner permissions.

**Диагностика:**
```yaml
- name: Проверка bucket policy
  amazon.aws.s3_bucket:
    name: my-app-artifacts-prod
    region: eu-central-1
    mode: get
  delegate_to: localhost
  register: bucket_info

- name: Вывод bucket policy для диагностики
  ansible.builtin.debug:
    var: bucket_info.policy

- name: Проверка IAM permissions
  ansible.builtin.command: |
    aws iam simulate-principal-policy \
      --policy-source-arn arn:aws:iam::123456789012:role/ci-deploy-role \
      --action-names s3:GetObject s3:PutObject \
      --resource-arns arn:aws:s3:::my-app-artifacts-prod/*
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
    region: eu-central-1
    multipart_threshold: 64MB
    multipart_chunksize: 16MB
  delegate_to: localhost
```

### 6.4 Проблемы с консистентностью

**Причины:**
- S3 strong consistency для новых объектов (с 2020), но eventual для LIST/overwrite в self-hosted реализациях.
- Ceph RGW: eventual consistency для LIST операций.

**Решение:**
```yaml
- name: Загрузка с проверкой ETag
  amazon.aws.s3_object:
    bucket: my-app-artifacts-prod
    key: "releases/app.tar.gz"
    src: "./app.tar.gz"
    mode: put
    region: eu-central-1
  register: upload

- name: Проверка ETag после загрузки
  ansible.builtin.assert:
    that:
      - upload.etag is defined
    fail_msg: "ETag не был возвращен после загрузки"
    success_msg: "Объект загружен с ETag {{ upload.etag }}"
```

---

## 7. Best Practices (Production Checklist)

### Security
- [ ] Используются **IAM roles** вместо статических ключей на EC2 инстансах.
- [ ] **S3 bucket'ы** имеют включённый Block Public Access.
- [ ] Используется **SSE-KMS** для encryption at rest.
- [ ] Настроен **Bucket Policy** с explicit Deny для нешифрованных загрузок.
- [ ] **AWS CLI профили** хранятся в защищённом месте (`~/.aws/` с permissions 600).
- [ ] **Vault credentials** для AWS не хранятся в playbooks, используются `--vault-id` или external vault.

### Reliability
- [ ] **Multipart upload** используется для файлов > 5 ГБ.
- [ ] **Retry logic** добавлен в playbooks для неидеомпотентных операций.
- [ ] **Idempotency** проверена: повторный запуск playbook не вызывает дублирования.
- [ ] **Checksum validation** после загрузки/скачивания.
- [ ] **Lifecycle policies** настроены через Ansible для автоматического управления.

### Operational
- [ ] Playbooks версионируются в Git.
- [ ] Используются **tags** для запуска только необходимых tasks.
- [ ] **delegate_to: localhost** явно указан для S3 операций.
- [ ] **no_log: true** для задач с sensitive данными (credentials).
- [ ] **IAM permissions** минимальные (principle of least privilege).

---

## 8. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [Обзор систем хранения данных (СХД)](../data_storage_overview.md)
