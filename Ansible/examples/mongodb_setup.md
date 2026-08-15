# Ansible: автоматизация развертывания MongoDB Replica Set

## Определения

**MongoDB Replica Set** — отказоустойчивый кластер, состоящий из нескольких узлов `mongod`, который обеспечивает автоматическое переключение при сбоях (failover) и высокую доступность данных. Теоретические основы механизмов кворума описаны в разделе **[Обзор MongoDB](../../Databases/MongoDB/mongodb.md)**.

**community.mongodb** — специализированная коллекция Ansible (FQCN), предоставляющая модули для управления конфигурацией, пользователями и репликацией MongoDB. Начиная с версии 8.0+, является основным инструментом автоматизации.

**mongosh (MongoDB Shell)** — современная интерактивная оболочка на базе Node.js, пришедшая на смену устаревшей `mongo`. В 2026 году является обязательной для выполнения административных скриптов через Ansible.

**keyFile** — секретный файл, используемый для взаимной аутентификации узлов внутри реплика-сета. Без него включение RBAC в кластере невозможно.

**RBAC (Role-Based Access Control)** — система управления доступом на основе ролей (например, `root`, `readWrite`), критически важная для защиты данных в распределенных системах.

## Базовые концепции

### Зависимости и инструментарий

Автоматизация MongoDB 8.0+ требует актуальных версий Python-драйверов на целевых хостах.

| Компонент | Требование | Назначение |
|---|---|---|
| `community.mongodb` | Управляющий узел | Коллекция модулей для управления всеми аспектами БД. |
| `pymongo` | Целевой хост | Python-библиотека для взаимодействия Ansible с протоколом MongoDB. |
| `mongosh` | Целевой хост | CLI-инструмент для выполнения команд и проверки состояния кластера. |

Установка коллекции:
```bash
ansible-galaxy collection install community.mongodb
```

### Архитектура и роли узлов

1.  **Primary:** Единственный узел, принимающий операции записи.
2.  **Secondary:** Узлы, копирующие данные с Primary. Могут участвовать в выборах нового лидера.
3.  **Arbiter:** Узел, который участвует только в голосовании и не хранит данные (используется для достижения нечетного количества голосующих узлов).

### Принципы безопасности и идемпотентности

- **Этапность**: При первой установке сначала настраивается `keyFile` и базовая конфигурация, затем инициализируется Replica Set, и только после создания пользователя `admin` включается авторизация (`security.authorization: enabled`).
- **Тюнинг системы**: Для работы MongoDB 8.0+ через Ansible необходимо обеспечить отключение **Transparent Huge Pages (THP)** и установку лимитов `ulimit` (не менее 64000).
- **Секреты**: Содержимое `keyFile` и пароли пользователей должны храниться исключительно в **[Ansible Vault](../Vault/basics.md)**.

---

## Практические сценарии

### Сценарий 1: Полный цикл развертывания кластера MongoDB 8.0

Плейбук включает настройку репозиториев, установку и инициализацию репликации.

```yaml
---
- name: Подготовка узлов MongoDB
  hosts: mongo_nodes
  become: true
  vars:
    mongodb_version: "8.0"
    mongodb_replset_name: "rs0"
    # vault_mongodb_keyfile: "..." (через Vault)

  tasks:
    - name: Импорт GPG-ключа MongoDB
      ansible.builtin.apt_key:
        url: "https://www.mongodb.org/static/pgp/server-{{ mongodb_version }}.asc"
        state: present
        keyring: /usr/share/keyrings/mongodb-server.gpg

    - name: Добавление официального репозитория
      ansible.builtin.apt_repository:
        repo: "deb [signed-by=/usr/share/keyrings/mongodb-server.gpg] https://repo.mongodb.org/apt/ubuntu {{ ansible_facts['distribution_release'] }}/mongodb-org/{{ mongodb_version }} multiverse"
        state: present

    - name: Установка пакетов MongoDB и Python-драйверов
      ansible.builtin.package:
        name:
          - mongodb-org
          - python3-pymongo
        state: present

    - name: Отключение Transparent Huge Pages (THP)
      ansible.builtin.shell: |
        echo never > /sys/kernel/mm/transparent_hugepage/enabled
        echo never > /sys/kernel/mm/transparent_hugepage/defrag
      changed_when: false

    - name: Деплой keyFile для кластера
      ansible.builtin.copy:
        content: "{{ vault_mongodb_keyfile }}"
        dest: /var/lib/mongodb/keyfile
        owner: mongodb
        group: mongodb
        mode: '0400'
      no_log: true

    - name: Настройка конфигурации mongod.conf
      ansible.builtin.template:
        src: templates/mongod.conf.j2
        dest: /etc/mongod.conf
      notify: Restart Mongodb

- name: Инициализация Replica Set
  hosts: mongo_primary
  become: true
  tasks:
    - name: Ожидание запуска службы
      ansible.builtin.wait_for:
        port: 27017
        timeout: 30

    - name: Инициализация репликации (Replica Set)
      community.mongodb.mongodb_replicaset:
        login_host: localhost
        replica_set: "{{ mongodb_replset_name }}"
        members: "{{ groups['mongo_nodes'] }}"
      run_once: true

    - name: Создание администратора кластера
      community.mongodb.mongodb_user:
        database: admin
        name: admin
        password: "{{ vault_mongodb_admin_pass }}"
        roles:
          - { db: "admin", role: "root" }
        state: present
      run_once: true
```

### Сценарий 2: Настройка TLS/SSL для защиты трафика

Обязательный шаг для обеспечения безопасности в 2026 году.

```yaml
- name: Деплой сертификатов SSL
  ansible.builtin.copy:
    src: "certs/{{ inventory_hostname }}.pem"
    dest: /etc/ssl/mongodb.pem
    mode: '0400'
    owner: mongodb

- name: Включение TLS в конфигурации
  ansible.builtin.blockinfile:
    path: /etc/mongod.conf
    block: |
      net:
        ssl:
          mode: requireSSL
          PEMKeyFile: /etc/ssl/mongodb.pem
          CAFile: /etc/ssl/ca.pem
```

### Сценарий 3: Настройка брандмауэра (Firewall)

```yaml
- name: Разрешение порта 27017 в UFW (Debian/Ubuntu)
  community.general.ufw:
    rule: allow
    port: 27017
    proto: tcp
    from_ip: "{{ item }}"
  loop: "{{ groups['mongo_nodes'] }}"
  when: ansible_facts['os_family'] == 'Debian'

- name: Открытие порта в Firewalld (RHEL/Rocky)
  ansible.posix.firewalld:
    port: 27017/tcp
    permanent: yes
    state: enabled
    immediate: yes
  when: ansible_facts['os_family'] == 'RedHat'
```

---

## Дополнительная информация

### Масштабирование и обслуживание

При добавлении новых узлов в инвентарь модуль `mongodb_replicaset` автоматически обнаруживает новые IP-адреса и выполняет `rs.reconfig()`. Если узел является Арбитром, укажите параметр `arbiterOnly: true` в определении участника.

### Типичные ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `keyFile precision too open` | Права на файл превышают `0400`. | Убедитесь, что `mode: '0400'` и владелец `mongodb`. |
| `mongosh not found` | Используется устаревшая версия MongoDB. | Обновите MongoDB до 8.0+. Shell `mongo` удален. |
| `Replica set is not yet initialized` | Попытка создать пользователя до `rs.initiate()`. | Соблюдайте порядок задач в сценарии 1. |
| `Authentication failed` | Несовпадение `keyFile` на разных узлах. | Используйте одну переменную из Vault для всех узлов. |

### Безопасность и надежность

- **Write Concern**: Для критических данных используйте `w: majority`.
- **Ansible Vault**: Никогда не оставляйте `vault_mongodb_keyfile` в открытом виде.
- **Мониторинг**: Рекомендуется развертывание `mongodb_exporter` для сбора метрик в Prometheus.

## Смотрите также

- **[Обзор MongoDB (SSoT)](../../Databases/MongoDB/mongodb.md)**
- **[Установка MongoDB на Ubuntu](../../Databases/MongoDB/installation_ubuntu.md)**
- **[Ansible Vault: работа с секретами](../Vault/basics.md)**
- **[Мониторинг MongoDB с Prometheus](../../Prometheus/Exporters/other_exporters.md)**
