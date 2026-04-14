# Ansible: Развертывание MongoDB Replica Set

## Определения

**MongoDB Replica Set** — группа процессов MongoDB, поддерживающих одинаковый набор данных для обеспечения избыточности и высокой доступности.

**Автоматизация развертывания с Ansible** — воспроизводимая настройка кластера MongoDB с использованием готовых ролей Ansible Galaxy и модулей `community.mongodb`.

## Базовые концепции

### Компоненты Replica Set

- **Primary**: Основной узел, который принимает все операции записи. В реплика-сете может быть только один primary.
- **Secondary**: Вторичный узел, который реплицирует данные с primary. Он может обрабатывать операции чтения и берет на себя роль primary в случае его отказа.
- **Arbiter**: "Арбитр", который не хранит данные, но участвует в голосовании при выборе нового primary. Он нужен для обеспечения кворума в архитектурах с четным количеством узлов данных.

### Ansible Galaxy для MongoDB

- **Роль `undergreen.mongodb`** — установка и базовая настройка MongoDB
- **Коллекция `community.mongodb`** — модули для управления кластером (`mongodb_replicaset`)

Установка зависимостей на управляющем узле:

```bash
ansible-galaxy install undergreen.mongodb
ansible-galaxy collection install community.mongodb
```

### Инициализация кластера

Модуль `community.mongodb.mongodb_replicaset` подключается к одному из узлов и передает конфигурацию replica set. Задача выполняется один раз (`run_once: true`) на узле primary.

### Структура инвентаря и переменных

- **Инвентарь (`hosts.ini`)** — группы хостов по ролям: `mongo_primary`, `mongo_secondary`, `mongo_arbiter`
- **`group_vars/mongo_cluster.yml`** — общие переменные для всех узлов
- **`host_vars/<hostname>.yml`** — специфичные переменные для каждого узла

---

## Практические сценарии

### Сценарий: Развертывание MongoDB Replica Set

#### Шаг 1: Инвентарь и переменные

**Файл `hosts.ini`:**

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

**Файл `group_vars/mongo_cluster.yml`:**

```yaml
mongodb_replication_replset: rs0
mongodb_bind_ip: 0.0.0.0
```

**Файлы `host_vars/`:**

- `server_mongo_primary.yml`:

  ```yaml
  mongodb_replication_role: primary
  ```

- `server_mongo_secondary.yml`:

  ```yaml
  mongodb_replication_role: secondary
  mongodb_master_host: 192.168.52.2
  ```

- `server_mongo_arbiter.yml`:

  ```yaml
  mongodb_replication_role: arbiter
  mongodb_master_host: 192.168.52.2
  ```

#### Шаг 2: Плейбук развертывания

```yaml
---
- name: Configure MongoDB nodes
  hosts: mongo_cluster
  become: true
  roles:
    # Роль сама подхватит переменные из group_vars/host_vars
    - undergreen.mongodb

- name: Initiate Replica Set
  hosts: mongo_primary
  become: true
  tasks:
    - name: Initiate replica set
      community.mongodb.mongodb_replicaset:
        login_host: localhost
        replica_set: "{{ mongodb_replication_replset }}"
        members:
          - host: 192.168.52.2:27017
            priority: 10
          - host: 192.168.52.3:27017
            priority: 5
          - host: 192.168.52.4:27017
            arbiter: true
      run_once: true
```

---

## Дополнительная информация

### Безопасность

В производственной среде необходимо включить аутентификацию и передавать `login_user`/`login_password` в модуль `mongodb_replicaset`. Пароли хранить в [Ansible Vault](../Vault/basics.md).

### Идемпотентность

Модуль `community.mongodb.mongodb_replicaset` идемпотентен: при повторном запуске проверяет конфигурацию и не вносит изменений, если состояние соответствует заданному.

### Динамический инвентарь

В облачных средах с динамическими IP-адресами используйте [динамический инвентарь](../dynamic_inventory.md) для автоматического обнаружения хостов вместо статического `hosts.ini`.

### Роли Ansible

Подробнее о ролях и Ansible Galaxy — в [ansible_roles.md](../ansible_roles.md).
