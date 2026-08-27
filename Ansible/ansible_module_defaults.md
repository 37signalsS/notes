# module_defaults: устранение дублирования параметров

## Определения

- **module_defaults** — механизм уровня play или group_tasks, позволяющий задать значения параметров по умолчанию для конкретного модуля или группы модулей, чтобы не дублировать их в каждой задаче
- **Group module_defaults** — расширение (Ansible 2.12+), позволяющее применять дефолты сразу к группе модулей (например, всем модулям MySQL или всем модулям AWS)
- **Разрешение приоритетов** — module_defaults имеет наименьший приоритет среди всех способов задания переменных (ниже extra_vars, set_fact, host_vars, group_vars)

---

## Почему это критично на собеседованиях

Типичный вопрос: "У вас 50 задач, каждая подключается к PostgreSQL с одними и теми же параметрами. Как избавиться от дублирования?" Ответ — `module_defaults`. Это глубже чем "используйте vars", потому что module_defaults работает на уровне модуля, а не переменных, и автоматически применяется ко всем вызовам указанного модуля.

---

## Базовый синтаксис

### На уровне play

```yaml
---
- name: Setup PostgreSQL databases
  hosts: db_servers
  become: true
  module_defaults:
    community.postgresql.postgresql_db:
      login_host: db-primary.internal
      login_user: postgres
      login_password: "{{ vault_pg_password }}"
      port: 5432
    community.postgresql.postgresql_user:
      login_host: db-primary.internal
      login_user: postgres
      login_password: "{{ vault_pg_password }}"
  tasks:
    - name: Create application database
      community.postgresql.postgresql_db:
        name: myapp
        encoding: UTF-8
        state: present

    - name: Create readonly user
      community.postgresql.postgresql_user:
        name: myapp_readonly
        password: "{{ vault_readonly_pass }}"
        db: myapp
        priv: "CONNECT/SELECT"
        state: present

    - name: Create readwrite user
      community.postgresql.postgresql_user:
        name: myapp_readwrite
        password: "{{ vault_readwrite_pass }}"
        db: myapp
        priv: "CONNECT/CREATE/SELECT/INSERT/UPDATE/DELETE"
        state: present
```

### На уровне group_tasks (в role или плейбуке)

```yaml
---
- name: Database operations
  hosts: db_servers
  module_defaults:
    group/community.postgresql:
      login_host: db-primary.internal
      login_user: postgres
      login_password: "{{ vault_pg_password }}"
  tasks:
    - name: Ensure database exists
      community.postgresql.postgresql_db:
        name: myapp
        state: present

    - name: Ensure user exists
      community.postgresql.postgresql_user:
        name: myapp_user
        password: "{{ vault_app_pass }}"
        state: present
```

---

## Практические сценарии

### Сценарий 1: MySQL/MariaDB — все модули сразу

Вместо дублирования `login_user`, `login_password`, `login_unix_socket` в каждой задаче:

```yaml
---
- name: MySQL setup
  hosts: mysql_servers
  become: true
  module_defaults:
    group/community.mysql:
      login_unix_socket: /var/run/mysqld/mysqld.sock
      login_user: root
      login_password: "{{ vault_mysql_root_pass }}"
  tasks:
    - name: Create database
      community.mysql.mysql_db:
        name: production
        state: present

    - name: Create user
      community.mysql.mysql_user:
        name: app_user
        password: "{{ vault_app_pass }}"
        priv: "production.*:ALL"
        state: present

    - name: Configure replication
      community.mysql.mysql_replication:
        mode: configure_primary
        server_id: 1
        state: present
```

### Сценарий 2: MongoDB — все задачи с одними credentials

```yaml
---
- name: MongoDB cluster setup
  hosts: mongo_servers
  become: true
  module_defaults:
    group/community.mongodb:
      login_host: "{{ ansible_default_ipv4.address }}"
      login_user: admin
      login_password: "{{ vault_mongo_admin_pass }}"
      login_port: 27017
  tasks:
    - name: Create application database
      community.mongodb.mongodb_shell:
        eval: "db = db.getSiblingDB('myapp'); db.createCollection('users')"
        login_database: admin

    - name: Ensure admin user exists
      community.mongodb.mongodb_user:
        database: admin
        name: admin
        password: "{{ vault_mongo_admin_pass }}"
        roles: root
        state: present

    - name: Create app user
      community.mongodb.mongodb_user:
        database: myapp
        name: app_user
        password: "{{ vault_mongo_app_pass }}"
        roles: readWrite
        state: present
```

### Сценарий 3: AWS — все модули с одним профилем

```yaml
---
- name: Provision AWS infrastructure
  hosts: localhost
  connection: local
  gather_facts: false
  module_defaults:
    group/amazon.aws:
      profile: production
      region: eu-central-1
  tasks:
    - name: Create VPC
      amazon.aws.ec2_vpc_net:
        name: production-vpc
        cidr_block: 10.0.0.0/16
        multi_ok: false
        state: present
      register: vpc

    - name: Create subnet
      amazon.aws.ec2_vpc_subnet:
        vpc_id: "{{ vpc.vpc.id }}"
        cidr: 10.0.1.0/24
        state: present

    - name: Create security group
      amazon.aws.ec2_security_group:
        name: web-sg
        description: "Web server security group"
        vpc_id: "{{ vpc.vpc.id }}"
        rules:
          - proto: tcp
            from_port: 443
            to_port: 443
            cidr_ip: 0.0.0.0/0
        state: present
```

### Сценарий 4: Azure — все модули с одним subscription

```yaml
---
- name: Azure infrastructure
  hosts: localhost
  connection: local
  gather_facts: false
  module_defaults:
    group/azure.azcollection:
      auth_source: cli
      subscription_id: "{{ azure_subscription_id }}"
      resource_group: production-rg
      location: westeurope
  tasks:
    - name: Create virtual network
      azure.azcollection.azure_rm_virtualnetwork:
        name: production-vnet
        address_prefixes: "10.0.0.0/16"
        state: present

    - name: Create subnet
      azure.azcollection.azure_rm_subnet:
        name: web-subnet
        virtual_network: production-vnet
        address_prefix: "10.0.1.0/24"
        state: present
```

### Сценарий 5: Kubernetes — все модули с одним kubeconfig

```yaml
---
- name: Kubernetes namespace setup
  hosts: localhost
  connection: local
  gather_facts: false
  module_defaults:
    group/kubernetes.core:
      kubeconfig: ~/.kube/config
      context: production-cluster
  tasks:
    - name: Create namespace
      kubernetes.core.k8s:
        definition:
          apiVersion: v1
          kind: Namespace
          metadata:
            name: myapp
            labels:
              env: production

    - name: Create deployment
      kubernetes.core.k8s:
        definition:
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: myapp
            namespace: myapp
          spec:
            replicas: 3
            selector:
              matchLabels:
                app: myapp
            template:
              metadata:
                labels:
                  app: myapp
              spec:
                containers:
                  - name: myapp
                    image: myapp:latest
                    ports:
                      - containerPort: 8080
```

---

## Приоритеты и разрешение конфликтов

module_defaults имеет самый низкий приоритет среди всех способов задания значений:

```
extra_vars (CLI) > set_fact/register > play vars > role defaults > inventory vars > 
group_vars > host_vars > module_defaults
```

### Пример перекрытия

```yaml
---
- name: Priority demo
  hosts: all
  module_defaults:
    ansible.builtin.debug:
      verbosity: 0
  tasks:
    # Использует module_defaults (verbosity: 0)
    - name: Simple debug
      ansible.builtin.debug:
        msg: "Default verbosity"

    # Перекрывает через переменную задачи
    - name: Override verbosity
      ansible.builtin.debug:
        msg: "Higher verbosity"
        verbosity: 2
```

---

## Группы модулей (group/module_defaults)

### Автоматические группы

Ansible автоматически группирует модули по коллекциям:

| Группа | Модули |
| :--- | :--- |
| `group/amazon.aws` | Все модули коллекции amazon.aws |
| `group/azure.azcollection` | Все модули Azure |
| `group/google.cloud` | Все модули GCP |
| `group/community.postgresql` | Все PostgreSQL-модули |
| `group/community.mysql` | Все MySQL-модули |
| `group/community.mongodb` | Все MongoDB-модули |
| `group/kubernetes.core` | Все Kubernetes-модули |

### Кастомные группы модулей

Можно создать свою группу через файл `runtime.yml` в коллекции:

```yaml
# collections/ansible_collections/myorg/mycollection/meta/runtime.yml
group_names:
  - myorg_database:
      - myorg.postgresql_db
      - myorg.postgresql_user
      - myorg.postgresql_role
```

Тогда в плейбуке:

```yaml
module_defaults:
  group/myorg_database:
    login_host: db.internal
    login_user: admin
```

---

## Интеграция с Ansible Vault

module_defaults идеально сочетается с Vault для изоляции секретов:

```yaml
---
- name: Secure database setup
  hosts: db_servers
  become: true
  module_defaults:
    group/community.postgresql:
      login_host: "{{ vault_db_host }}"
      login_user: "{{ vault_db_user }}"
      login_password: "{{ vault_db_password }}"
      port: "{{ vault_db_port | default(5432) }}"
  vars_files:
    - vault/secrets.yml
  tasks:
    - name: Ensure database
      community.postgresql.postgresql_db:
        name: "{{ app_name }}"
        state: present
```

---

## Ограничения и подводные камни

| Проблема | Решение |
| :--- | :--- |
| module_defaults не работает с `command`/`shell` | Это не модули с параметрами — используйте vars |
| Перекрывается extra_vars | Это ожидаемо — extra_vars имеет приоритет |
| Не работает в requires_PLAYBOOK-level defaults | Только на уровне play или group_tasks |
| Сложность отладки | Используйте `-vvv` для просмотра итоговых значений |

---

## Диагностические команды

```bash
# Просмотр module_defaults для хоста
ansible localhost -m debug -a "msg={{ module_defaults }}" 2>/dev/null

# Проверка переменных модуля
ansible-doc -t module community.postgresql.postgresql_db | grep -A5 "OPTIONS"

# Запуск с проверкой значений
ansible-playbook site.yml --check --diff -vvv 2>&1 | grep -i "module_default\|login_host"
```

---

## Дополнительная информация

- [ansible_core_concepts.md](ansible_core_concepts.md) — переменные и приоритеты
- [ansible_roles.md](ansible_roles.md) — передача параметров через role defaults
- [ansible_security_best_practices.md](ansible_security_best_practices.md) — Vault и секреты
- [ansible_bad_practices.md](ansible_bad_practices.md) — антипаттерны дублирования
