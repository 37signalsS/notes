# Развертывание Apache Kafka с помощью Ansible

**Автоматизация развертывания Kafka через Ansible** — это стандарт де-факто для управления жизненным циклом (Lifecycle Management) кластеров на выделенных серверах (Bare Metal) или виртуальных машинах. Использование Ansible обеспечивает идемпотентность конфигурации, упрощает масштабирование и позволяет внедрять лучшие практики безопасности (TLS, SASL) централизованно.

---

## Определения

- **Ansible Role (Роль):** Структурированный набор плейбуков, шаблонов и переменных для выполнения конкретной задачи (установка Kafka, настройка тюнинга).
- **Inventory (Инвентарь):** Файл или скрипт, содержащий список всех хостов кластера и их группировку (например, `controllers` и `brokers`).
- **KRaft (Kafka Raft):** Режим работы без ZooKeeper, использующий протокол Raft для управления метаданными. В Kafka 3.x+ это основной режим для промышленной эксплуатации.
- **Node ID:** Уникальный числовой идентификатор брокера в кластере, обязательный для KRaft.
- **Voters:** Список узлов (контроллеров), участвующих в голосовании по протоколу Raft для обеспечения консенсуса.
- **Handlers (Обработчики):** Задачи в Ansible, которые запускаются только при изменении конфигурации (например, перезапуск сервиса Kafka после смены настроек в `server.properties`).

---

## Основные концепции

### Почему Ansible для Kafka?

В отличие от ручной установки, Ansible позволяет:
1. **Идемпотентность:** Повторный запуск плейбука не изменит систему, если конфигурация уже соответствует целевой.
2. **Безопасность:** Автоматическая генерация TLS-сертификатов и дистрибуция Java Keystores (JKS) на десятки нод.
3. **Контроль версий:** Вся инфраструктура описывается кодом (IaC), что позволяет версионировать изменения через Git.
4. **Тюнинг ОС:** Автоматическая настройка лимитов (`ulimit`), TCP-стека и параметров ядра (`sysctl`) под высокие нагрузки.

### Жизненный цикл развертывания в KRaft

Процесс автоматизации развертывания в режиме KRaft включает специфичные шаги:
1. **Генерация Cluster ID:** Использование `kafka-storage.sh random-uuid`. В Ansible рекомендуется сохранять ID в локальный файл на управляющей машине (Control Node), чтобы использовать один и тот же UUID для всех нод кластера.
2. **Форматирование хранилища:** Выполнение `kafka-storage.sh format` с использованием Cluster ID. 
   - **Важно:** В Ansible это должно быть защищено проверкой наличия файла `meta.properties` в директории `data`, чтобы избежать повторного форматирования и потери данных.
3. **Управление кворумом:** Правильная настройка `controller.quorum.voters` на основе IP-адресов из инвентаря.

---

## Практические сценарии

### 1. Подготовка промышленного кластера (Production Ready)

Этот сценарий описывает настройку кластера из 3 узлов в совмещенном режиме (Controller + Broker) с учетом тюнинга ОС и JVM.

#### Шаг 1: Инвентарь (`inventory/hosts.ini`)

```ini
[kafka_cluster]
kafka-node-1 ansible_host=10.0.1.1 kafka_node_id=1
kafka-node-2 ansible_host=10.0.1.2 kafka_node_id=2
kafka-node-3 ansible_host=10.0.1.3 kafka_node_id=3

[kafka_cluster:vars]
ansible_user=deploy
ansible_become=yes
kafka_version=3.7.1
scala_version=2.13
```

#### Шаг 2: Настройка Systemd (`templates/kafka.service.j2`)

Использование systemd гарантирует автоматический запуск после перезагрузки и перезапуск при сбоях.

```ini
[Unit]
Description=Apache Kafka Server
Documentation=http://kafka.apache.org/documentation.html
Requires=network.target remote-fs.target
After=network.target remote-fs.target

[Service]
Type=simple
User={{ kafka_user }}
Group={{ kafka_group }}
Environment="KAFKA_HEAP_OPTS=-Xmx6G -Xms6G"
Environment="KAFKA_JVM_PERFORMANCE_OPTS={{ kafka_jvm_performance_opts }}"
ExecStart=/opt/kafka/bin/kafka-server-start.sh /opt/kafka/config/server.properties
ExecStop=/opt/kafka/bin/kafka-server-stop.sh
Restart=on-failure
RestartSec=30
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

#### Шаг 3: Плейбук с тюнингом (`playbook.yaml`)

```yaml
- name: Развертывание кластера Kafka KRaft
  hosts: kafka_cluster
  roles:
    - role: kafka
      vars:
        # Системные настройки
        kafka_user: kafka
        kafka_group: kafka
        kafka_data_dir: /var/lib/kafka/data
        
        # JVM Тюнинг (Java 17/21)
        # Не давайте Kafka слишком много Heap, оставьте RAM для Page Cache ОС
        kafka_jvm_performance_opts: >-
          -XX:+UseG1GC 
          -XX:MaxGCPauseMillis=20 
          -XX:InitiatingHeapOccupancyPercent=35 
          -XX:+ExplicitGCInvokesConcurrent
        
        # Настройки KRaft
        kafka_process_roles: "broker,controller"
        kafka_controller_quorum_voters: "1@10.0.1.1:9093,2@10.0.1.2:9093,3@10.0.1.3:9093"
        
        # Тюнинг производительности
        kafka_additional_config:
          num.network.threads: 8
          num.io.threads: 16
          socket.send.buffer.bytes: 102400
          socket.receive.buffer.bytes: 102400
          num.partitions: 3
          default.replication.factor: 3
          min.insync.replicas: 2
          
          # Настройки Retention (7 дней)
          log.retention.hours: 168
          log.segment.bytes: 1073741824 # 1GB
```

#### Шаг 4: Настройка ОС через Ansible (Pre-tasks)

Перед установкой самой Kafka важно подготовить ОС и сетевой стек:
```yaml
  pre_tasks:
    - name: Увеличение лимитов файловых дескрипторов
      pam_limits:
        domain: "{{ kafka_user }}"
        limit_type: "{{ item }}"
        limit_item: nofile
        value: 65536
      loop: [ 'soft', 'hard' ]

    - name: Настройка параметров ядра для сети и диска
      sysctl:
        name: "{{ item.key }}"
        value: "{{ item.value }}"
        state: present
      with_dict:
        net.core.rmem_max: 16777216
        net.core.wmem_max: 16777216
        net.ipv4.tcp_rmem: "4096 87380 16777216"
        net.ipv4.tcp_wmem: "4096 65536 16777216"
        vm.swappiness: 1
        vm.dirty_ratio: 60
        vm.dirty_background_ratio: 10
```

#### Шаг 5: Автоматизация TLS (SSL)

Пример генерации Keystore для каждого брокера через Ansible:

```yaml
- name: Генерация сертификатов брокера
  shell: >
    keytool -genkey -keystore {{ kafka_certs_dir }}/kafka.keystore.jks
    -alias {{ inventory_hostname }} -validity 365
    -keyalg RSA -keysize 2048 -storepass {{ keystore_pass }}
    -keypass {{ keystore_pass }} -dname "CN={{ inventory_hostname }}"
    -ext SAN=DNS:{{ inventory_hostname }},IP:{{ ansible_host }}
  args:
    creates: "{{ kafka_certs_dir }}/kafka.keystore.jks"
```

---

### 2. Автоматизация обновления (Rolling Upgrade)

Обновление Kafka без простоя требует последовательного перезапуска нод. В Ansible это реализуется через `serial: 1`.

```yaml
- name: Обновление конфигурации Kafka (Rolling)
  hosts: kafka_cluster
  serial: 1 # Выполнять по одной ноде за раз
  tasks:
    - name: Обновление server.properties
      template:
        src: server.properties.j2
        dest: /opt/kafka/config/server.properties
      notify: restart kafka

    - name: Ожидание вхождения ноды в ISR
      shell: "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe"
      register: topic_status
      until: "'Isr' in topic_status.stdout"
      retries: 20
      delay: 30
```

---

## Дополнительная информация

### Тюнинг JVM: Почему 6-8 ГБ Heap?

Одной из самых частых ошибок является выделение Kafka 32 ГБ+ оперативной памяти под Heap.
- **Page Cache:** Kafka спроектирована так, что она почти не держит данные в памяти приложения. Она использует системные вызовы `sendfile`, которые читают данные из кэша файловой системы (Page Cache) напрямую в сетевой сокет.
- **Производительность:** Если вы отдадите 90% RAM под JVM Heap, ОС не сможет эффективно кэшировать файлы сегментов, что приведет к резкому росту операций чтения с диска (Disk I/O) и падению производительности всего кластера.

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура журналов и режим KRaft.
- **[Гарантии доставки](./delivery_guarantees.md)** — как настройки `acks` влияют на надежность после деплоя.
- **[Kafka для мониторинга](./kafka_for_monitoring.md)** — метрики JMX, которые стоит собирать.

### Инструменты

- **[Confluent Ansible Roles](https://github.com/confluentinc/cp-ansible):** Официальные роли от Confluent.
- **[JMX Exporter:](https://github.com/prometheus/jmx_exporter)** Рекомендуется устанавливать через Ansible как Java Agent.
