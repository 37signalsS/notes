# Развертывание Apache Kafka с помощью Ansible

**Автоматизация развертывания Kafka через Ansible** — это стандарт де-факто для управления жизненным циклом (Lifecycle Management) кластеров на "голом железе" (Bare Metal) или виртуальных машинах. Использование Ansible обеспечивает идемпотентность конфигурации, упрощает масштабирование и позволяет внедрять лучшие практики безопасности (TLS, SASL) централизованно.

---

## Определения

- **Ansible Role (Роль):** Структурированный набор плейбуков, шаблонов и переменных, предназначенный для выполнения конкретной задачи (в данном случае — полной установки Kafka).
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
2. **Контроль версий:** Вся инфраструктура описывается кодом (IaC), что позволяет версионировать изменения через Git.
3. **Безопасность:** Массовая генерация и деплой SSL-сертификатов на десятки нод за один прогон.
4. **Тюнинг ОС:** Автоматическая настройка лимитов (`ulimit`), TCP-стека и параметров ядра (`sysctl`) под высокие нагрузки.

### Жизненный цикл развертывания в KRaft

Процесс автоматизации развертывания в режиме KRaft включает специфичные шаги:
1. **Генерация Cluster ID:** Использование `kafka-storage.sh random-uuid` один раз для всего кластера.
2. **Форматирование хранилища:** Выполнение `kafka-storage.sh format` с использованием Cluster ID. В Ansible это должно быть защищено проверкой наличия файла `meta.properties`, чтобы избежать повторного форматирования и потери данных.
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

#### Шаг 2: Плейбук с тюнингом (`playbook.yaml`)

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
        
        # JVM Тюнинг (Актуально для Java 17/21)
        # Не давайте Kafka слишком много Heap, оставьте RAM для Page Cache ОС
        kafka_heap_size: "6G" 
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

#### Шаг 3: Настройка ОС через Ansible (Pre-tasks)

Перед установкой самой Kafka важно подготовить ОС:
```yaml
  pre_tasks:
    - name: Увеличение лимитов файловых дескрипторов
      pam_limits:
        domain: "{{ kafka_user }}"
        limit_type: "{{ item }}"
        limit_item: nofile
        value: 65536
      loop: [ 'soft', 'hard' ]

    - name: Настройка параметров ядра для сети
      sysctl:
        name: "{{ item.key }}"
        value: "{{ item.value }}"
        state: present
      with_dict:
        net.core.rmem_max: 16777216
        net.core.wmem_max: 16777216
        net.ipv4.tcp_rmem: "4096 87380 16777216"
        net.ipv4.tcp_wmem: "4096 65536 16777216"
```

---

### 2. Автоматизация обновления (Rolling Upgrade)

Обновление Kafka без простоя (downtime) требует последовательного перезапуска нод. В Ansible это реализуется через `serial: 1`.

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
- **Производительность:** Если вы отдадите 90% RAM под JVM Heap, ОС не сможет эффективно кэшировать файлы сегментов, что приведет к резкому росту операций чтения с диска (Disk I/O) и падению производительности.

### См. также

- **[Управление и тюнинг Java (JVM)](../Linux/Development/java_management.md)** — SSoT по настройке памяти, GC и работе в контейнерах.
- **[Обзор Apache Kafka](./kafka_overview.md)** — основы архитектуры (брокеры, топики).
- **[Kafka для мониторинга](./kafka_for_monitoring.md)** — метрики JMX, которые стоит собирать после деплоя.
- **[Гарантии доставки](./delivery_guarantees.md)** — как настройки `acks` и `min.insync.replicas` влияют на надежность.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — как распределять данные после расширения кластера.

### Инструменты

- **[Confluent Ansible Roles](https://github.com/confluentinc/cp-ansible):** Официальные, наиболее полные роли от Confluent (поддерживают TLS, Kerberos, мониторинг).
- **[JMX Exporter:](https://github.com/prometheus/jmx_exporter)** Рекомендуется устанавливать через Ansible как Java Agent для сбора метрик в Prometheus.
