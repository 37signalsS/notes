# Ansible: Развертывание MongoDB Replica Set

## Определения

**MongoDB Replica Set** — группа процессов MongoDB, поддерживающих идентичный набор данных для обеспечения избыточности и высокой доступности. Подробное описание компонентов и механизмов работы приведено в разделе **[Репликация в MongoDB](../../Databases/MongoDB/mongodb.md#репликация-replica-set)**.

**Автоматизация развертывания с Ansible** — воспроизводимая настройка кластера MongoDB с использованием ролей Ansible Galaxy и специализированных модулей коллекции `community.mongodb`.

## Базовые концепции

### Инструментарий для MongoDB

Для автоматизации обычно используются два компонента:

- **Роль `undergreen.mongodb`**: Отвечает за установку пакетов, настройку конфигурационных файлов и управление операционной системой (ОС — Операционная Система).
- **Коллекция `community.mongodb`**: Содержит модули для логической настройки кластера (например, `mongodb_replicaset`).

Установка зависимостей на управляющем узле:

```bash
ansible-galaxy install undergreen.mongodb  # → роль установлена
ansible-galaxy collection install community.mongodb  # → коллекция установлена
```

### Инициализация кластера

Модуль `community.mongodb.mongodb_replicaset` подключается к одному из узлов и передает конфигурацию Replica Set. Ключевые особенности:

- Задача выполняется один раз (`run_once: true`) на будущем узле `primary`.
- Модуль управляет списком участников (`members`) и их приоритетами.

### Структура инвентаря

Для управления кластером рекомендуется разделять хосты на группы в инвентаре:

- **Группы по ролям**: `mongo_primary`, `mongo_secondary`, `mongo_arbiter`.
- **Переменные**: Общие параметры (имя реплика-сета, bind_ip) выносятся в `group_vars/mongo_cluster.yml`, а специфичные (роль узла) — в `host_vars/`.

---

## Практические сценарии

### Сценарий: Развертывание MongoDB Replica Set

#### 1. Подготовка инвентаря и переменных

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

**Пример `host_vars/server_mongo_primary.yml`:**

```yaml
mongodb_replication_role: primary
```

#### 2. Плейбук развертывания

```yaml
---
- name: Configure MongoDB nodes
  hosts: mongo_cluster
  become: true
  roles:
    # Роль устанавливает MongoDB и настраивает конфиг
    - undergreen.mongodb

- name: Initiate Replica Set
  hosts: mongo_primary
  become: true
  tasks:
    - name: Initiate replica set configuration
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

В производственных средах обязательна настройка аутентификации. Параметры `login_user` и `login_password` должны передаваться в модуль `mongodb_replicaset`. Конфиденциальные данные следует хранить в **[Ansible Vault (защищенное хранилище)](../Vault/basics.md)**.

### Идемпотентность

Модуль `community.mongodb.mongodb_replicaset` является идемпотентным. При повторных запусках он сверяет текущую конфигурацию кластера с описанной в задаче и вносит изменения только при обнаружении расхождений (например, при добавлении нового узла).

### Масштабирование

- **Динамический инвентарь**: В облачных инфраструктурах используйте **[динамический инвентарь](../dynamic_inventory.md)** для автоматического обнаружения узлов кластера.
- **Роли**: Подробная информация об использовании и создании ролей доступна в **[ansible_roles.md](../ansible_roles.md)**.
