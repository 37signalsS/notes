# Установка и настройка кластера MongoDB с помощью Ansible

Этот пример демонстрирует, как автоматизировать развертывание кластера MongoDB с использованием готовой роли из Ansible Galaxy. Плейбук настраивает реплика-сет, состоящий из `primary`, `secondary` и `arbiter` узлов.

Использование ролей позволяет значительно сократить объем кода в плейбуке и переиспользовать логику для стандартных задач.

## Пример: MongoDB Replica Set

### Файл инвентаря `hosts.ini`

```ini
[mongo_primary]
server_mongo_primary ansible_host=192.168.52.2

[mongo_secondary]
server_mongo_secondary ansible_host=192.168.52.3

[mongo_arbiter]
server_mongo_arbiter ansible_host=192.168.52.4

[mongo_cluster:children]
mongo_primary
mongo_secondary
mongo_arbiter
```

### Плейбук `mongo-playbook.yml`

Этот плейбук использует роль `undergreen.mongodb` (в оригинальном тексте `green.mongodb`, но более вероятно, что имеется в виду `undergreen`) для настройки каждого узла в соответствии с его ролью в кластере.

```yaml
---
- name: Configure MongoDB Primary
  hosts: mongo_primary
  become: true
  vars:
    mongodb_replication_role: 'primary'
    # Другие переменные, специфичные для роли...
  roles:
    - undergreen.mongodb

- name: Configure MongoDB Secondary
  hosts: mongo_secondary
  become: true
  vars:
    mongodb_replication_role: 'secondary'
    mongodb_master_host: '192.168.52.2' # IP primary узла
    # Другие переменные...
  roles:
    - undergreen.mongodb

- name: Configure MongoDB Arbiter
  hosts: mongo_arbiter
  become: true
  vars:
    mongodb_replication_role: 'arbiter'
    mongodb_master_host: '192.168.52.2' # IP primary узла
    # Другие переменные...
  roles:
    - undergreen.mongodb

- name: Initiate Replica Set
  hosts: mongo_primary
  become: true
  tasks:
    - name: Initiate the replica set
      community.mongodb.mongodb_replicaset:
        login_host: localhost
        replica_set: rs0
        members:
          - host: '192.168.52.2:27017'
            priority: 10
          - host: '192.168.52.3:27017'
            priority: 5
          - host: '192.168.52.4:27017'
            arbiter: true
      run_once: true
```

**Примечание:** Для работы плейбука необходимо предварительно установить роль `undergreen.mongodb` и коллекцию `community.mongodb`:

```bash
ansible-galaxy install undergreen.mongodb
ansible-galaxy collection install community.mongodb
```

Этот подход показывает, как сложные задачи, такие как настройка кластера базы данных, могут быть упрощены до нескольких вызовов ролей с правильными параметрами.
