# Ansible: Развертывание MongoDB Replica Set

## Определения

**MongoDB Replica Set** — отказоустойчивый кластер из нескольких узлов `mongod`, обеспечивающий избыточность данных и высокую доступность (High Availability). Подробная теория механизмов кворума и выборов описана в разделе **[Обзор MongoDB](../../Databases/MongoDB/mongodb.md)** (SSoT).

**community.mongodb** — основная и единственная рекомендуемая коллекция Ansible для управления MongoDB 8.0+ в 2026 году. Поддерживает работу с локальными инстансами и MongoDB Atlas.

**keyFile** — файл с общим секретом, используемый для внутренней аутентификации узлов внутри реплика-сета.

**RBAC (Role-Based Access Control)** — модель управления доступом на основе ролей, обязательная для защиты данных в MongoDB.

## Базовые концепции

### Зависимости и инструментарий

Для автоматизации MongoDB 8.0+ требуются современные драйверы и коллекции. Старая оболочка `mongo` удалена, используется исключительно `mongosh`.

| Компонент | Где требуется | Назначение |
|---|---|---|
| `community.mongodb` | Управляющий узел | Коллекция модулей (FQCN: `community.mongodb.*`) |
| `pymongo` | Целевой хост | Python-драйвер для взаимодействия модулей с БД |
| `mongosh` | Целевой хост | Современная оболочка для выполнения административных команд |

Установка коллекции:
```bash
ansible-galaxy collection install community.mongodb  # → коллекция установлена
```

### Принципы идемпотентности и безопасности

1.  **Порядок инициализации**: Сначала разворачиваются бинарные файлы и конфигурация, затем инициализируется Replica Set, и только после создания первого администратора включается параметр `security.authorization`.
2.  **Управление секретами**: Все пароли и содержимое `keyFile` должны храниться в **[Ansible Vault](../Vault/basics.md)**.
3.  **Localhost Exception**: При первом запуске (до создания пользователей) MongoDB позволяет подключаться с `localhost` без аутентификации.

---

## Практические сценарии

### Сценарий: Развертывание защищенного кластера MongoDB 8.0

#### 1. Подготовка переменных (group_vars/mongo.yml)

```yaml
mongodb_version: "8.0"
mongodb_replset_name: "rs0"
# vault_mongodb_keyfile_content: "..." (хранится в Vault)
# vault_mongodb_admin_password: "..." (хранится в Vault)

mongo_config:
  Debian:
    packages: ["mongodb-org", "python3-pymongo"]
  RedHat:
    packages: ["mongodb-org", "python3-pymongo"]
```

#### 2. Плейбук: Установка и настройка безопасности

```yaml
---
- name: Развертывание узлов MongoDB
  hosts: mongo_nodes
  become: true
  tasks:
    - name: Установка MongoDB и зависимостей Python
      ansible.builtin.package:
        name: "{{ mongo_config[ansible_facts['os_family']].packages }}"
        state: present
        update_cache: yes

    - name: Деплой keyFile для внутренней аутентификации
      ansible.builtin.copy:
        content: "{{ vault_mongodb_keyfile_content }}"
        dest: /var/lib/mongodb/keyfile
        owner: mongodb
        group: mongodb
        mode: '0400'
      no_log: true

    - name: Конфигурация mongod.conf (без авторизации для первого запуска)
      ansible.builtin.template:
        src: mongod.conf.j2
        dest: /etc/mongod.conf
      notify: restart mongodb

    - name: Обеспечение запуска службы
      ansible.builtin.service:
        name: mongod
        state: started
        enabled: yes

- name: Инициализация Replica Set и RBAC
  hosts: mongo_primary # Выполняем только на одном узле
  become: true
  tasks:
    - name: Инициализация Replica Set
      community.mongodb.mongodb_replicaset:
        login_host: localhost
        replica_set: "{{ mongodb_replset_name }}"
        members: "{{ groups['mongo_nodes'] }}"
      run_once: true

    - name: Создание администратора кластера
      community.mongodb.mongodb_user:
        database: admin
        name: admin
        password: "{{ vault_mongodb_admin_password }}"
        roles:
          - { db: "admin", role: "root" }
        state: present
      run_once: true

    - name: Включение авторизации в конфигурации
      ansible.builtin.lineinfile:
        path: /etc/mongod.conf
        regexp: '^#?security:'
        line: 'security:'
      # Далее необходимо добавить authorization: enabled через template или block
```

---

## Дополнительная информация

### Масштабирование: Добавление узлов

При добавлении нового узла в инвентарь модуль `mongodb_replicaset` автоматически определит изменение и выполнит `rs.reconfig()`. Важно убедиться, что новый узел имеет тот же `keyFile`, что и остальная часть кластера.

### Использование TLS/SSL

В 2026 году использование TLS является стандартом. Для автоматизации сертификатов используйте коллекцию `community.crypto`. В конфигурации MongoDB (`net.ssl`) укажите пути к `PEMKeyFile` и `CAFile`.

### Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `keyFile precision too open` | Права на файл выше `0600` | Установите `mode: '0400'` в задаче `copy`. |
| `mongosh not found` | Используется старая версия MongoDB | Обновите MongoDB до 8.0+; `mongo` shell больше не поддерживается. |
| `No replica set status available` | Служба не запущена или `bindIp` некорректен | Проверьте `systemctl status mongod` и доступность порта 27017. |

## Смотрите также

- [Обзор MongoDB (SSoT)](../../Databases/MongoDB/mongodb.md)
- [Установка MongoDB на Ubuntu](../../Databases/MongoDB/installation_ubuntu.md)
- [Ansible Vault: Работа с секретами](../Vault/basics.md)
- [Мониторинг MongoDB с Prometheus](../../Prometheus/Exporters/other_exporters.md)
