# Управление мультисредами в Ansible

## Определения

- **Multi-environment** — подход к организации кода, при котором используются отдельные инвентари и переменные для dev/staging/prod
- **group_vars** — директория с переменными групп, привязанными к инвентарю
- **host_vars** — директория с переменными хостов
- **Inventory per environment** — отдельный инвентарь для каждого окружения
- **Environment overlay** — переопределение переменных для конкретного окружения через group_vars
- **Limit** — параметр CLI для ограничения выполнения определёнными хостами
- **Satellite/Foreman** — внешние CMDB для динамического инвентаря
- **Delegation** — делегирование задачи другому хосту (например, deploy-серверу)

## Основные концепции

1. Структура каталогов: `inventories/dev/`, `inventories/staging/`, `inventories/prod/`
2. Группы в инвентаре: `children`, adults (группа групп)
3. Переопределение переменных: `group_vars/all.yml`, `group_vars/webservers.yml`
4. `--limit` для точечного воздействия на конкретные хосты
5. Vault для разных окружений: `vault-id`, `multi-vault`
6. Динамический инвентарь для сред: конфигурация inventory plugins

## Практические сценарии

### Структура каталогов проекта для 3 сред

```
project/
├── ansible.cfg
├── inventories/
│   ├── dev/
│   │   ├── hosts.yml
│   │   ├── group_vars/
│   │   │   ├── all.yml
│   │   │   ├── webservers.yml
│   │   │   └── dbservers.yml
│   │   └── host_vars/
│   │       └── db-master-01.yml
│   ├── staging/
│   │   ├── hosts.yml
│   │   ├── group_vars/
│   │   │   ├── all.yml
│   │   │   ├── webservers.yml
│   │   │   └── dbservers.yml
│   │   └── host_vars/
│   ├── prod/
│   │   ├── hosts.yml
│   │   ├── group_vars/
│   │   │   ├── all.yml
│   │   │   ├── webservers.yml
│   │   │   └── dbservers.yml
│   │   └── host_vars/
│   └── production
├── playbooks/
├── roles/
└── group_vars/
    └── all.yml          # общие переменные для всех сред
```

### Примеры инвентарей для dev/staging/prod

```yaml
# inventories/dev/hosts.yml
---
all:
  children:
    webservers:
      hosts:
        web-dev-01:
          ansible_host: 192.168.1.10
        web-dev-02:
          ansible_host: 192.168.1.11
    dbservers:
      hosts:
        db-dev-01:
          ansible_host: 192.168.1.20
          postgresql_version: 15
```

```yaml
# inventories/prod/hosts.yml
---
all:
  children:
    webservers:
      hosts:
        web-prod-01:
          ansible_host: 10.0.1.10
        web-prod-02:
          ansible_host: 10.0.1.11
        web-prod-03:
          ansible_host: 10.0.1.12
    dbservers:
      hosts:
        db-prod-master:
          ansible_host: 10.0.1.20
          postgresql_version: 16
        db-prod-replica:
          ansible_host: 10.0.1.21
```

### Использование group_vars для переопределения переменных

```yaml
# inventories/dev/group_vars/all.yml
---
app_debug: true
app_replicas: 1
log_level: debug
db_backup_enabled: false

# inventories/prod/group_vars/all.yml
---
app_debug: false
app_replicas: 3
log_level: warning
db_backup_enabled: true
db_backup_schedule: "0 2 * * *"
```

```yaml
# inventories/dev/group_vars/webservers.yml
---
nginx_worker_processes: 2
nginx_worker_connections: 512
app_port: 8080

# inventories/prod/group_vars/webservers.yml
---
nginx_worker_processes: auto
nginx_worker_connections: 4096
app_port: 8080
ssl_certificate: /etc/ssl/certs/app.crt
ssl_certificate_key: /etc/ssl/private/app.key
```

### Запуск плейбука на конкретное окружение

```bash
# Только dev окружение
ansible-playbook -i inventories/dev playbooks/deploy.yml

# Только staging с ограничением по группе
ansible-playbook -i inventories/staging playbooks/deploy.yml -l webservers

# Только конкретный хост
ansible-playbook -i inventories/prod playbooks/deploy.yml --limit web-prod-01

# Проверка (dry-run) на prod
ansible-playbook -i inventories/prod playbooks/deploy.yml --check --diff

# Теги для dev
ansible-playbook -i inventories/dev playbooks/deploy.yml --tags "migrate,static"

# Конкретное задание на конкретных хостах
ansible-playbook -i inventories/prod playbooks/deploy.yml -l "webservers" -t "restart"
```

### Multi-vault: отдельные vault для dev и prod

```bash
# Шифрование переменных для разных сред
ansible-vault encrypt_string --vault-id dev@prompt \
  'dev_db_password' --name 'db_password'

ansible-vault encrypt_string --vault-id prod@prompt \
  'prod_db_password' --name 'db_password'
```

```yaml
# inventories/dev/group_vars/all/vault.yml
vault_db_password: !vault |
  $ANSIBLE_VAULT;1.2;AES256;dev
  65306262376163353931636634633530323065613038373164353362663434663735616436336362
```

```yaml
# inventories/prod/group_vars/all/vault.yml
vault_db_password: !vault |
  $ANSIBLE_VAULT;1.2;AES256;prod
  65306262376163353931636634633530323065613038373164353362663434663735616436336362
```

```bash
# Запуск с multi-vault
ansible-playbook -i inventories/prod playbooks/deploy.yml \
  --vault-id prod@prompt

ansible-playbook -i inventories/dev playbooks/deploy.yml \
  --vault-id dev@prompt
```

### Delegation: делегирование задач

```yaml
---
- name: Deploy application
  hosts: webservers
  become: true
  tasks:
    - name: Notify monitoring
      ansible.builtin.uri:
        url: "http://monitoring.internal:9090/api/deploy"
        method: POST
        body: '{"host": "{{ inventory_hostname }}"}'
        body_format: json
      delegate_to: localhost
      run_once: true

    - name: Run database migration on master
      ansible.builtin.command: /opt/app/manage.py migrate
      delegate_to: db-master
      run_once: true

    - name: Flush cache on proxy
      ansible.builtin.command: nginx -s reload
      delegate_to: proxy-lb-01
      run_once: true
```

### Факт кэширование для разных сред

```ini
# ansible.cfg
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400

# Для разных сред разные каталоги
# dev: /tmp/ansible_facts_cache_dev
# prod: /tmp/ansible_facts_cache_prod
```

### Динамический инвентарь через Foreman plugin

```yaml
# inventory/foreman.yml
plugin: theforeman.foreman.foreman
url: "https://foreman.example.com"
user: "ansible"
password: "{{ vault_foreman_password }}"
validate_certs: true
want_facts: true
want_hostgroups: true
plain_host_names: true

keyed_groups:
  - key: foreman_operatingsystem_name
    prefix: os
  - key: foreman_organization_name
    prefix: org
  - key: foreman_location_name
    prefix: location
```

```bash
# Запуск с динамическим инвентарём
ansible-playbook -i inventory/foreman.yml playbooks/site.yml --limit "os_centos"

# Использование в цикле по средам
for env in dev staging prod; do
  ansible-playbook -i "inventories/${env}" playbooks/site.yml
done
```

## Дополнительная информация

- [ansible_core_concepts.md](ansible_core_concepts.md)
- [PlaybookStructure/variables.md](PlaybookStructure/variables.md)
- [Vault/multi_vault.md](Vault/multi_vault.md)
- [dynamic_inventory.md](dynamic_inventory.md)
