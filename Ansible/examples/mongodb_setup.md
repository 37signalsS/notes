# Развертывание MongoDB Replica Set с помощью Ansible

## Определения

**MongoDB Replica Set** — группа процессов `mongod`, поддерживающих идентичный набор данных для обеспечения избыточности и высокой доступности (HA — High Availability). Подробное описание механизмов работы приведено в разделе **[Репликация в MongoDB](../../Databases/MongoDB/mongodb.md#репликация-replica-set)**.

**Автоматизация развертывания через Ansible** — процесс воспроизводимой конфигурации кластера с использованием ролей (Ansible Galaxy) и специализированных модулей коллекции `community.mongodb` или `mongodb.mongodb`.

**Идемпотентность** — свойство плейбука, гарантирующее, что повторные запуски не изменят систему, если она уже находится в целевом состоянии. В контексте MongoDB это касается инициализации реплика-сета и управления пользователями.

## Базовые концепции

### Инструментарий и зависимости

Для управления MongoDB через Ansible необходимы следующие компоненты:

| Компонент | Где требуется | Назначение |
|---|---|---|
| `mongodb.mongodb` | Управляющий узел | Официальная коллекция (рекомендуется для новых проектов) |
| `community.mongodb` | Управляющий узел | Сообщество модулей (наиболее распространена) |
| `pymongo` | Целевой хост / Управляющий узел | Python-драйвер для работы модулей Ansible |

Установка зависимостей:

```bash
ansible-galaxy collection install community.mongodb # → коллекция установлена
pip install pymongo # → драйвер установлен
```

### Инициализация кластера

Модуль `community.mongodb.mongodb_replicaset` выполняет инициализацию реплика-сета. Основные правила:

1.  **Run Once**: Задача инициализации должна выполняться строго один раз на одном из узлов (обычно `primary`).
2.  **Localhost Exception**: Если аутентификация включена, первый запуск должен происходить с локального интерфейса без пароля (особенность MongoDB для первичной настройки).
3.  **Идемпотентность**: Модуль сравнивает текущий статус `rs.conf()` с описанным в Ansible и применяет изменения только при необходимости.

### Структура инвентаря

Для управления кластером рекомендуется логическое разделение:

- **Группы**: `mongo_primary`, `mongo_secondary`, `mongo_arbiter`.
- **Общие переменные**: Находятся в `group_vars/mongo_cluster.yml` (например, `mongodb_version`, `replica_set_name`).
- **Специфичные параметры**: В `host_vars/` (например, `priority` для каждого узла).

---

## Практические сценарии

### Сценарий: Развертывание MongoDB Replica Set

#### 1. Подготовка инвентаря и переменных

**Файл `hosts.ini`:**

```ini
[mongo_nodes]
mongo-01 ansible_host=192.168.52.2 priority=10
mongo-02 ansible_host=192.168.52.3 priority=5
mongo-03 ansible_host=192.168.52.4 arbiter=true
```

**Файл `group_vars/mongo_nodes.yml`:**

```yaml
mongodb_replset_name: "rs0"
mongodb_version: "8.0"
mongodb_bind_ip: "0.0.0.0"
```

#### 2. Плейбук развертывания

```yaml
---
- name: Install and Configure MongoDB Cluster
  hosts: mongo_nodes
  become: true
  tasks:
    - name: Install MongoDB and Python dependencies
      ansible.builtin.package:
        name:
          - mongodb-org
          - python3-pymongo
        state: present

    - name: Configure MongoDB replication
      ansible.builtin.template:
        src: mongod.conf.j2
        dest: /etc/mongod.conf
      notify: restart mongodb

    - name: Ensure MongoDB is started
      ansible.builtin.service:
        name: mongod
        state: started
        enabled: yes

  handlers:
    - name: restart mongodb
      ansible.builtin.service:
        name: mongod
        state: restarted

- name: Initialize Replica Set
  hosts: mongo_nodes
  become: true
  tasks:
    - name: Initiate replica set configuration
      community.mongodb.mongodb_replicaset:
        login_host: localhost
        replica_set: "{{ mongodb_replset_name }}"
        members: "{{ groups['mongo_nodes'] | map('extract', hostvars) | map('attribute', 'ansible_host') | list }}"
      run_once: true
      # Примечание: для сложной конфигурации (приоритеты, арбитры) 
      # используйте явный список members или расширенный фильтр.
```

---

## Дополнительная информация

### Безопасность

В производственных средах обязательна настройка аутентификации (Internal Authentication через keyFile и RBAC). 

1.  **keyFile**: Файл должен быть идентичен на всех узлах.
2.  **Vault**: Параметры `login_user` и `login_password` должны передаваться в модуль `mongodb_replicaset` после первичной инициализации. Конфиденциальные данные храните в **[Ansible Vault](../Vault/basics.md)**.

### Масштабирование и мониторинг

- **Динамический инвентарь**: В облаках используйте **[динамический инвентарь](../dynamic_inventory.md)** для автоматического обнаружения новых узлов.
- **Роли**: Для сложных инсталляций рекомендуется использовать проверенные роли. Подробнее — в **[ansible_roles.md](../ansible_roles.md)**.
- **Мониторинг**: Для сбора метрик используйте `mongodb_exporter` совместно с **[Prometheus](../../Prometheus/Exporters/other_exporters.md)**.

## Смотрите также

- [MongoDB: Теория репликации](../../Databases/MongoDB/mongodb.md#репликация-replica-set)
- [Ansible Vault: Работа с секретами](../Vault/basics.md)
- [Развертывание PostgreSQL с Ansible](example_postgresql_setup.md)
