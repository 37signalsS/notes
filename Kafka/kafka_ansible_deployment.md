# Развертывание Apache Kafka с помощью Ansible

**Автоматизация развертывания Kafka через Ansible** — это стандарт де-факто для управления жизненным циклом (Lifecycle Management) кластеров на выделенных серверах (Bare Metal) или виртуальных машинах. Использование Ansible обеспечивает идемпотентность конфигурации, упрощает масштабирование и позволяет внедрять лучшие практики безопасности (TLS, SASL) централизованно.

---

## Определения

- **Ansible Role (Роль):** Структурированный набор плейбуков, шаблонов и переменных для выполнения конкретной задачи (установка Kafka, настройка тюнинга).
- **Inventory (Инвентарь):** Файл или скрипт, содержащий список всех хостов кластера и их группировку (например, `controllers` и `brokers`).
- **KRaft (Kafka Raft):** Режим работы без ZooKeeper, использующий протокол Raft для управления метаданными. В Kafka 3.x+ это основной режим для промышленной эксплуатации, а с Kafka 4.0 — единственный поддерживаемый режим.
- **Node ID:** Уникальный числовой идентификатор брокера в кластере, обязательный для KRaft.
- **Voters:** Список узлов (контроллеров), участвующих в голосовании по протоколу Raft для обеспечения консенсуса.
- **Handlers (Обработчики):** Задачи в Ansible, которые запускаются только при изменении конфигурации (например, перезапуск сервиса Kafka после смены настроек в `server.properties`).
- **Control Node:** Управляющая машина, с которой запускаются Ansible-плейбуки. Требует Python 3.9+ и Ansible 2.14+.
- **Managed Node:** Целевой сервер, на котором развертывается Kafka. Доступен по SSH с Control Node.

---

## Предварительные требования

### Требования к управляющей машине (Control Node)

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
|-----------|-------------------|---------------------|------------|
| Python | 3.9 | 3.11+ | Ansible требует Python на Control Node |
| Ansible | 2.14 | 2.16+ | Проверка: `ansible --version` |
| SSH Client | OpenSSH 8.0 | OpenSSH 9.0+ | Для подключения к managed nodes |

### Требования к целевым серверам (Managed Nodes)

| Компонент | Минимальные требования | Рекомендуемые требования | Примечание |
|-----------|----------------------|-------------------------|------------|
| ОС | Ubuntu 20.04, CentOS 8, RHEL 8 | Ubuntu 22.04 LTS, RHEL 9 | Поддерживаемые версии |
| Java | OpenJDK 17 | OpenJDK 21 LTS | Kafka 3.7+ требует Java 17+ |
| RAM | 8 GB | 16 GB+ | 6-8 GB Heap для Kafka, остальное для Page Cache |
| CPU | 4 vCPU | 8+ vCPU | Зависит от нагрузки |
| Диск | 500 GB SSD | 1+ TB NVMe | Для логов Kafka (log.dirs) |
| Файловые дескрипторы | 65536 | 100000+ | Настраивается через `ulimit` |

### Сетевые требования

| Порт | Протокол | Назначение |
|------|----------|------------|
| 9092 | TCP | PLAINTEXT или SASL (клиенты) |
| 9093 | TCP | Controller quorum (KRaft) |
| 9094 | TCP | TLS/SSL (клиенты) |
| 8080 | TCP | JMX Exporter (опционально) |

### Установка Ansible на Control Node

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3-pip python3-venv
python3 -m venv ~/ansible-venv
source ~/ansible-venv/bin/activate
pip install ansible==2.16.*

# Проверка установки
ansible --version
# → ansible [core 2.16.x]
```

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

### Архитектура KRaft в Kafka 4.0

Начиная с Kafka 4.0, ZooKeeper полностью удален. Все метаданные хранятся в внутреннем топике `__cluster_metadata`, управляемом кворумом контроллеров. Это упрощает развертывание и снижает операционные затраты.

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
kafka_version=3.9.0
scala_version=2.13
kafka_heap_opts=-Xmx6G -Xms6G
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
Environment="KAFKA_HEAP_OPTS={{ kafka_heap_opts }}"
Environment="KAFKA_JVM_PERFORMANCE_OPTS={{ kafka_jvm_performance_opts }}"
ExecStart=/opt/kafka/bin/kafka-server-start.sh /opt/kafka/config/server.properties
ExecStop=/opt/kafka/bin/kafka-server-stop.sh
Restart=on-failure
RestartSec=30
LimitNOFILE=100000
LimitNPROC=65536

[Install]
WantedBy=multi-user.target
```

#### Шаг 3: Плейбук с тюнингом (`playbook.yaml`)

```yaml
- name: Развертывание кластера Kafka KRaft
  hosts: kafka_cluster
  become: yes
  roles:
    - role: kafka
      vars:
        # Системные настройки
        kafka_user: kafka
        kafka_group: kafka
        kafka_data_dir: /var/lib/kafka/data
        kafka_install_dir: /opt/kafka
        
        # JVM Тюнинг (Java 17/21)
        # Не давайте Kafka слишком много Heap, оставьте RAM для Page Cache ОС
        kafka_jvm_performance_opts: >-
          -XX:+UseG1GC 
          -XX:MaxGCPauseMillis=20 
          -XX:InitiatingHeapOccupancyPercent=35 
          -XX:+ExplicitGCInvokesConcurrent
          -XX:+ParallelRefProcEnabled
        
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
          
          # Настройки KRaft
          controller.listener.names: "CONTROLLER"
          inter.broker.listener.name: "INTERNAL"
          listeners: "INTERNAL://:9092,CONTROLLER://:9093"
          advertised.listeners: "INTERNAL://{{ ansible_host }}:9092"
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
        value: 100000
      loop: [ 'soft', 'hard' ]

    - name: Увеличение лимитов процессов
      pam_limits:
        domain: "{{ kafka_user }}"
        limit_type: "{{ item }}"
        limit_item: nproc
        value: 65536
      loop: [ 'soft', 'hard' ]

    - name: Настройка параметров ядра для сети и диска
      sysctl:
        name: "{{ item.key }}"
        value: "{{ item.value }}"
        state: present
        sysctl_set: yes
        reload: yes
      with_dict:
        net.core.rmem_max: 16777216
        net.core.wmem_max: 16777216
        net.ipv4.tcp_rmem: "4096 87380 16777216"
        net.ipv4.tcp_wmem: "4096 65536 16777216"
        vm.swappiness: 1
        vm.dirty_ratio: 60
        vm.dirty_background_ratio: 10
        vm.max_map_count: 262144
```

#### Шаг 5: Автоматизация TLS (SSL)

Пример генерации Keystore для каждого брокера через Ansible:

```yaml
- name: Создание директории для сертификатов
  file:
    path: "{{ kafka_certs_dir }}"
    state: directory
    owner: "{{ kafka_user }}"
    group: "{{ kafka_group }}"
    mode: '0700'

- name: Генерация Keystore для брокера
  shell: >
    keytool -genkey -keystore {{ kafka_certs_dir }}/kafka.keystore.jks
    -alias {{ inventory_hostname }} -validity 3650
    -keyalg RSA -keysize 4096 -storepass {{ keystore_pass }}
    -keypass {{ keystore_pass }} -dname "CN={{ inventory_hostname }}"
    -ext SAN=DNS:{{ inventory_hostname }},IP:{{ ansible_host }}
  args:
    creates: "{{ kafka_certs_dir }}/kafka.keystore.jks"
  no_log: true

- name: Генерация Truststore
  shell: >
    keytool -export -keystore {{ kafka_certs_dir }}/kafka.keystore.jks
    -alias {{ inventory_hostname }} -file {{ kafka_certs_dir }}/{{ inventory_hostname }}.cer
    -storepass {{ keystore_pass }} -rfc
  args:
    creates: "{{ kafka_certs_dir }}/{{ inventory_hostname }}.cer"
  no_log: true
```

#### Шаг 6: Валидация развертывания

```bash
# Проверка статуса сервиса на всех нодах
ansible kafka_cluster -i inventory/hosts.ini -m command -a "systemctl status kafka"

# Проверка логов на ошибки
ansible kafka_cluster -i inventory/hosts.ini -m command -a "journalctl -u kafka --no-pager -n 50"

# Проверка кворума KRaft
ansible kafka-node-1 -i inventory/hosts.ini -m shell -a \
  "/opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status"
# Ожидаемый вывод: LeaderId: 1, VoterCount: 3, LeaderHighWatermark: ...

# Проверка топиков
ansible kafka-node-1 -i inventory/hosts.ini -m shell -a \
  "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list"
```

---

### 2. Автоматизация обновления (Rolling Upgrade)

Обновление Kafka без простоя требует последовательного перезапуска нод. В Ansible это реализуется через `serial: 1`.

```yaml
- name: Обновление конфигурации Kafka (Rolling)
  hosts: kafka_cluster
  serial: 1 # Выполнять по одной ноде за раз
  max_fail_percentage: 0 # Остановиться при первой ошибке
  
  tasks:
    - name: Обновление server.properties
      template:
        src: server.properties.j2
        dest: /opt/kafka/config/server.properties
        owner: "{{ kafka_user }}"
        group: "{{ kafka_group }}"
        mode: '0644'
      notify: restart kafka

    - name: Ожидание вхождения ноды в ISR
      shell: "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe"
      register: topic_status
      until: "'Isr' in topic_status.stdout"
      retries: 30
      delay: 10
      changed_when: false

    - name: Проверка кворума после перезапуска
      shell: "/opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status"
      register: quorum_status
      until: "'LeaderId' in quorum_status.stdout"
      retries: 10
      delay: 5
      changed_when: false

  handlers:
    - name: restart kafka
      systemd:
        name: kafka
        state: restarted
        daemon_reload: yes
```

---

### 3. Настройка SASL/PLAIN аутентификации

Для production-сред рекомендуется использовать SASL для аутентификации клиентов и межброкерного взаимодействия.

#### Шаг 1: Конфигурация JAAS (`templates/kafka_server_jaas.conf.j2`)

```conf
KafkaServer {
    org.apache.kafka.common.security.plain.PlainLoginModule required
    user_admin="{{ sasl_admin_password }}"
    user_client1="{{ sasl_client1_password }}"
    user_client2="{{ sasl_client2_password }}";
};

KafkaClient {
    org.apache.kafka.common.security.plain.PlainLoginModule required
    username="admin"
    password="{{ sasl_admin_password }}";
};
```

#### Шаг 2: Плейбук для настройки SASL

```yaml
- name: Настройка SASL аутентификации
  hosts: kafka_cluster
  become: yes
  vars:
    sasl_admin_password: "{{ vault_sasl_admin_password }}"
    sasl_client1_password: "{{ vault_sasl_client1_password }}"
    sasl_client2_password: "{{ vault_sasl_client2_password }}"
  
  tasks:
    - name: Создание JAAS конфигурации
      template:
        src: kafka_server_jaas.conf.j2
        dest: /opt/kafka/config/kafka_server_jaas.conf
        owner: "{{ kafka_user }}"
        group: "{{ kafka_group }}"
        mode: '0600'
      notify: restart kafka

    - name: Добавление SASL в server.properties
      lineinfile:
        path: /opt/kafka/config/server.properties
        regexp: "^{{ item.key }}="
        line: "{{ item.key }}={{ item.value }}"
      loop:
        - { key: "sasl.enabled.mechanisms", value: "PLAIN" }
        - { key: "sasl.mechanism.inter.broker.protocol", value: "PLAIN" }
        - { key: "security.inter.broker.protocol", value: "SASL_SSL" }
        - { key: "security.protocol", value: "SASL_SSL" }
      notify: restart kafka

    - name: Настройка переменной окружения для JAAS
      lineinfile:
        path: /etc/default/kafka
        line: 'KAFKA_OPTS="-Djava.security.auth.login.config=/opt/kafka/config/kafka_server_jaas.conf"'
        create: yes
      notify: restart kafka
```

#### Шаг 3: Валидация SASL

```bash
# Создание тестового топика с аутентификацией
cat > /tmp/client.properties <<EOF
security.protocol=SASL_SSL
sasl.mechanism=PLAIN
sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required \
  username="admin" \
  password="{{ sasl_admin_password }}";
EOF

/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka-node-1:9094 \
  --command-config /tmp/client.properties --create --topic test-sasl --partitions 1 --replication-factor 1
```

---

### 4. Масштабирование кластера (добавление брокеров)

Добавление новых брокеров в существующий кластер без простоя.

#### Шаг 1: Обновление инвентаря

```ini
[kafka_cluster]
kafka-node-1 ansible_host=10.0.1.1 kafka_node_id=1
kafka-node-2 ansible_host=10.0.1.2 kafka_node_id=2
kafka-node-3 ansible_host=10.0.1.3 kafka_node_id=3
kafka-node-4 ansible_host=10.0.1.4 kafka_node_id=4  # Новый брокер

[kafka_cluster:vars]
kafka_controller_quorum_voters: "1@10.0.1.1:9093,2@10.0.1.2:9093,3@10.0.1.3:9093,4@10.0.1.4:9093"
```

#### Шаг 2: Плейбук для добавления брокера

```yaml
- name: Добавление нового брокера в кластер
  hosts: kafka-node-4
  become: yes
  serial: 1
  
  tasks:
    - name: Установка Kafka (используем основной плейбук)
      include_role:
        name: kafka

    - name: Обновление controller.quorum.voters на всех нодах
      lineinfile:
        path: /opt/kafka/config/server.properties
        regexp: "^controller.quorum.voters="
        line: "controller.quorum.voters={{ kafka_controller_quorum_voters }}"
      delegate_to: "{{ item }}"
      loop: "{{ groups['kafka_cluster'] }}"
      notify: restart kafka

    - name: Ожидание присоединения нового брокера к кворуму
      shell: "/opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status"
      register: quorum_status
      until: "'VoterCount' in quorum_status.stdout"
      retries: 20
      delay: 15
      changed_when: false

- name: Запуск ребалансировки
  hosts: kafka-node-1
  tasks:
    - name: Запуск Kafka Reassign Partitions
      shell: >
        /opt/kafka/bin/kafka-reassign-partitions.sh 
        --bootstrap-server localhost:9092
        --broker-list "1,2,3,4"
        --generate
      register: reassign_plan
      changed_when: false
```

---

### 5. Настройка мониторинга через JMX Exporter

```yaml
- name: Установка JMX Exporter
  hosts: kafka_cluster
  become: yes
  vars:
    jmx_exporter_version: "0.19.0"
    jmx_exporter_port: 8080
  
  tasks:
    - name: Скачивание JMX Exporter
      get_url:
        url: "https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/{{ jmx_exporter_version }}/jmx_prometheus_javaagent-{{ jmx_exporter_version }}.jar"
        dest: /opt/kafka/libs/jmx_prometheus_javaagent.jar
        owner: "{{ kafka_user }}"
        group: "{{ kafka_group }}"
        mode: '0644'

    - name: Создание конфигурации JMX Exporter
      copy:
        dest: /opt/kafka/config/jmx_exporter.yml
        content: |
          startDelaySeconds: 0
          lowercaseOutputName: true
          lowercaseOutputLabelNames: true
          rules:
            - pattern: "kafka.server<type=(.+), name=(.+)><>Value"
              name: kafka_server_$1_$2
              type: GAUGE
            - pattern: "kafka.controller<type=(.+), name=(.+)><>Value"
              name: kafka_controller_$1_$2
              type: GAUGE
        owner: "{{ kafka_user }}"
        group: "{{ kafka_group }}"
        mode: '0644'

    - name: Добавление JMX Exporter в Kafka сервис
      lineinfile:
        path: /etc/default/kafka
        line: 'KAFKA_OPTS="${KAFKA_OPTS} -javaagent:/opt/kafka/libs/jmx_prometheus_javaagent.jar={{ jmx_exporter_port }}:/opt/kafka/config/jmx_exporter.yml"'
      notify: restart kafka
```

---

## Troubleshooting

| Симптом | Причина | Диагностика | Решение |
|---------|---------|-------------|---------|
| `java.net.BindException: Address already in use` | Порт занят другим процессом | `ss -tlnp \| grep 9092` | Остановите конкурирующий процесс или измените порт |
| `kafka.errors.NotControllerException` | Запрос ушел не на контроллер | Проверьте `kafka-metadata-quorum.sh describe --status` | Используйте `--bootstrap-server` с любым брокером, клиент сам найдет контроллер |
| `InconsistentClusterIdException` | Несовпадение Cluster ID при форматировании | Проверьте `/var/lib/kafka/data/meta.properties` | Убедитесь, что используете один Cluster ID для всех нод |
| `java.lang.OutOfMemoryError: Java heap space` | Недостаточно Heap | Проверьте `kafka.log` и `jstat -gcutil` | Увеличьте `KAFKA_HEAP_OPTS` до 8G, проверьте нагрузку |
| `Too many open files` | Превышен лимит файловых дескрипторов | `cat /proc/$(pgrep kafka)/limits \| grep "Max open files"` | Увеличьте `LimitNOFILE` в systemd unit до 100000 |
| `SSLHandshakeException` | Проблема с TLS сертификатами | `openssl s_client -connect host:9094` | Проверьте срок действия сертификатов и SAN |
| `ReplicaFetcherThread` ошибки | Проблемы с репликацией | `kafka-topics.sh --under-replicated-partitions` | Проверьте сеть между брокерами и `min.insync.replicas` |

### Диагностические команды

```bash
# Проверка состояния кластера
/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092

# Проверка логов в реальном времени
journalctl -u kafka -f

# Проверка метрик JMX
curl -s localhost:8080/metrics | grep kafka_server

# Проверка сетевых соединений
ss -tlnp | grep -E '9092|9093|9094'
```

---

## Best Practices

1. **Разделение Controller и Broker ролей** В production-средах рекомендуется разделять узлы на чистые контроллеры (3-5 нод) и чистые брокеры для повышения стабильности.

2. **Используйте Ansible Vault для секретов** Никогда не храните пароли и ключи в открытом виде:
   ```bash
   ansible-vault encrypt_string 'my_secret_password' --name 'sasl_admin_password'
   ```

3. **Настройте резервное копирование** Регулярно резервируйте директорию `/var/lib/kafka/data` и конфигурации.

4. **Мониторинг кворума** Настройте алерты на падение кворума контроллеров (потеря более половины нод).

5. **Тестируйте обновления в staging** Всегда тестируйте обновления версий Kafka на staging-среде перед production.

6. **Используйте отдельные диски для логов** Выделите отдельный физический диск или раздел для `log.dirs` для изоляции I/O.

7. **Настройте log rotation** Настройте `log.retention.hours` и `log.retention.bytes` в соответствии с бизнес-требованиями.

---

## Edge Cases

### Kafka 4.0 и удаление ZooKeeper

Начиная с Kafka 4.0, ZooKeeper полностью удален. При миграции с Kafka 3.x на 4.0 необходимо:
1. Убедиться, что кластер работает в режиме KRaft
2. Обновить все клиентские библиотеки
3. Проверить совместимость всех интеграций

### Миграция с ZooKeeper на KRaft

Для миграции существующего кластера с ZooKeeper на KRaft используйте поэтапный подход:
1. Включите двойной режим (ZooKeeper + KRaft) в Kafka 3.3+
2. Постепенно переведите контроллеры на KRaft
3. Отключите ZooKeeper после полной миграции

### Работа с большими кластерами (10+ нод)

При масштабировании более 10 брокеров:
- Используйте отдельные ноды для контроллеров (минимум 3-5)
- Настройте `auto.leader.rebalance.enable=true`
- Рассмотрите использование Cruise Control для автоматической балансировки

### Мульти-региональные кластеры

Для географически распределенных кластеров:
- Используйте MirrorMaker 2 для репликации между регионами
- Настройте `replica.socket.timeout.ms` с учетом задержек сети
- Рассмотрите использование Rack Awareness (`broker.rack`)

---

## Дополнительная информация

### Тюнинг JVM: Почему 6-8 ГБ Heap?

Одной из самых частых ошибок является выделение Kafka 32 ГБ+ оперативной памяти под Heap.
- **Page Cache:** Kafka спроектирована так, что она почти не держит данные в памяти приложения. Она использует системные вызовы `sendfile`, которые читают данные из кэша файловой системы (Page Cache) напрямую в сетевой сокет.
- **Производительность:** Если вы отдадите 90% RAM под JVM Heap, ОС не сможет эффективно кэшировать файлы сегментов, что приведет к резкому росту операций чтения с диска (Disk I/O) и падению производительности всего кластера.

### Структура проекта Ansible

```
kafka-ansible/
├── inventory/
│   ├── hosts.ini              # Статический инвентарь
│   └── group_vars/
│       ├── all.yml            # Общие переменные
│       └── kafka_cluster.yml  # Переменные кластера
├── roles/
│   └── kafka/
│       ├── tasks/
│       │   ├── main.yml
│       │   ├── install.yml
│       │   ├── configure.yml
│       │   └── tls.yml
│       ├── templates/
│       │   ├── server.properties.j2
│       │   ├── kafka.service.j2
│       │   └── kafka_server_jaas.conf.j2
│       ├── handlers/
│       │   └── main.yml
│       └── defaults/
│           └── main.yml
├── playbooks/
│   ├── deploy.yml
│   ├── upgrade.yml
│   └── scale.yml
└── ansible.cfg
```

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура журналов и режим KRaft.
- **[Гарантии доставки](./delivery_guarantees.md)** — как настройки `acks` влияют на надежность после деплоя.
- **[Kafka для мониторинга](./kafka_for_monitoring.md)** — метрики JMX, которые стоит собирать.

### Инструменты

- **[Confluent Ansible Roles](https://github.com/confluentinc/cp-ansible):** Официальные роли от Confluent.
- **[JMX Exporter:](https://github.com/prometheus/jmx_exporter)** Рекомендуется устанавливать через Ansible как Java Agent.
- **[Ansible Lint](https://ansible.readthedocs.io/projects/lint/):** Инструмент для проверки качества Ansible кода.
