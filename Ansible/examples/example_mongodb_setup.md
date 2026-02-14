# Развертывание кластера MongoDB с Ansible

## Определения

**MongoDB Replica Set** — это группа процессов MongoDB, которые поддерживают одинаковый набор данных, обеспечивая избыточность и высокую доступность. **Автоматизация развертывания с помощью Ansible** позволяет быстро и воспроизводимо настраивать такой кластер, используя готовые [роли](ansible_roles.md) и модули.

## Основные концепции

- **Компоненты Replica Set**:
  - **Primary**: Основной узел, который принимает все операции записи. В реплика-сете может быть только один primary.
  - **Secondary**: Вторичный узел, который реплицирует данные с primary. Он может обрабатывать операции чтения и берет на себя роль primary в случае его отказа.
  - **Arbiter**: "Арбитр", который не хранит данные, но участвует в голосовании при выборе нового primary. Он нужен для обеспечения кворума в архитектурах с четным количеством узлов данных.

- **Автоматизация с помощью Ansible Galaxy**:
  - **[Ansible Galaxy](ansible_roles.md#управление-ролями-с-ansible-galaxy)** — это репозиторий для ролей и коллекций Ansible. Использование готовых ролей, таких как `undergreen.mongodb`, значительно ускоряет развертывание, так как вся логика установки и базовой настройки уже написана и протестирована сообществом.

- **Инициализация кластера**:
  - После установки и настройки всех узлов необходимо инициировать Replica Set. Для этого используется модуль `community.mongodb.mongodb_replicaset`, который подключается к одному из узлов (обычно к future primary) и передает ему конфигурацию всего кластера.

- **Структура инвентаря и переменных**:
  - **Инвентарь (`hosts.ini`)**: Определяет группы хостов для каждой роли (`mongo_primary`, `mongo_secondary`, `mongo_arbiter`).
  - **Переменные (`group_vars`)**: Для чистоты и гибкости плейбуков переменные лучше выносить в файлы `group_vars`. Общие переменные кладутся в `group_vars/all.yml` или `group_vars/<имя_группы>.yml`, а специфичные — в `host_vars/<имя_хоста>.yml`.

## Практические сценарии

### Подготовка: Установка зависимостей

Для работы плейбука необходимо предварительно установить роль `undergreen.mongodb` из Ansible Galaxy и коллекцию `community.mongodb` на **управляющем узле**.

```bash
ansible-galaxy install undergreen.mongodb
ansible-galaxy collection install community.mongodb
```

### Сценарий: Развертывание MongoDB Replica Set

#### Шаг 1: Структура проекта и инвентаря

**Файл инвентаря `hosts.ini`:**

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

**Переменные для группы `group_vars/mongo_cluster.yml`:**

```yaml
# Общие переменные для всех узлов кластера
mongodb_replication_replset: rs0
mongodb_bind_ip: 0.0.0.0
```

**Переменные для ролей в `host_vars` (или можно использовать `group_vars`):**

- `host_vars/server_mongo_primary.yml`:

    ```yaml
    mongodb_replication_role: 'primary'
    ```

- `host_vars/server_mongo_secondary.yml`:

    ```yaml
    mongodb_replication_role: 'secondary'
    mongodb_master_host: '192.168.52.2'
    ```

- `host_vars/server_mongo_arbiter.yml`:

    ```yaml
    mongodb_replication_role: 'arbiter'
    mongodb_master_host: '192.168.52.2'
    ```

#### Шаг 2: Основной плейбук

Этот плейбук разделен на две части: первая настраивает все узлы с помощью роли, а вторая — инициирует кластер с помощью модуля.

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
    - name: Initiate the replica set on the primary node
      community.mongodb.mongodb_replicaset:
        login_host: localhost
        replica_set: "{{ mongodb_replication_replset }}" # Используем переменную
        members:
          - host: '192.168.52.2:27017' # Primary
            priority: 10
          - host: '192.168.52.3:27017' # Secondary
            priority: 5
          - host: '192.168.52.4:27017' # Arbiter
            arbiter: true
      run_once: true # Гарантирует, что задача выполнится только один раз
```

## Дополнительная информация

### Безопасность

В данном примере для простоты не используется аутентификация. В производственной среде необходимо:

- Включить аутентификацию в MongoDB.
- Передавать `login_user` и `login_password` в модуль `mongodb_replicaset`.
- Хранить все пароли и ключи в зашифрованном виде с помощью **[Ansible Vault](../Vault/basics.md)**.

### Идемпотентность

Модуль `community.mongodb.mongodb_replicaset` является идемпотентным. При повторном запуске он проверит состояние replica set и не будет вносить изменений, если конфигурация уже соответствует заданной.

### Динамический инвентарь

В облачных средах IP-адреса узлов могут меняться. Вместо жесткого кодирования адресов в `hosts.ini` и плейбуке, следует использовать динамический инвентарь для автоматического обнаружения хостов.
