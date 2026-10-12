# Развертывание Apache Kafka с помощью Ansible

**Актуально для:** Apache Kafka 3.9.x / 4.0+ (KRaft), Ansible core 2.16+

**Автоматизация развертывания Kafka через Ansible** — это стандарт де-факто для управления жизненным циклом (Lifecycle Management) кластеров на выделенных серверах (Bare Metal) и в частных виртуализированных средах (KVM, Proxmox, VMware). Использование Ansible обеспечивает строгую идемпотентность конфигурации, повторяемость развертывания, автоматизацию тюнинга операционной системы и централизованное управление безопасностью (mTLS, SASL/SCRAM).

---

## Определения

- **Ansible Role (Роль):** Структурированный набор плейбуков, шаблонов Jinja2, файлов и обработчиков (handlers) для автоматизации отдельного слоя (установка пакетов, настройка ОС, запуск сервиса Kafka).
- **Directory Inventory:** Структура каталогов инвентаря (`inventory/hosts.ini` или `hosts.yml` вместе с `group_vars/` и `host_vars/`), разделяющая конфигурации брокеров и контроллеров по группам.
- **KRaft (Kafka Raft Metadata mode):** Архитектура управления метаданными на основе протокола Raft без использования внешнего сервиса ZooKeeper. Начиная с Kafka 4.0, KRaft является единственным поддерживаемым режимом.
- **Node ID (`node.id`):** Уникальный целочисленный идентификатор узла в кластере KRaft. Заменяет устаревший параметр `broker.id`.
- **Process Roles (`process.roles`):** Список ролей узла в KRaft. Возможные значения: `broker`, `controller` или `broker,controller` (совмещенный режим).
- **Voters (`controller.quorum.voters`):** Статический или динамический список контроллеров, формирующих кворум Raft для согласования метаданных (формат: `id1@host1:port1,id2@host2:port2,...`).
- **Cluster ID (`cluster.id`):** 16-байтный Base64-идентификатор кластера, генерируемый утилитой `kafka-storage.sh random-uuid` и записываемый в `meta.properties` при форматировании журнала метаданных.
- **Under-Replicated Partitions (URP):** Партиции, для которых количество реплик в ISR (In-Sync Replicas) меньше заданного `replication.factor`. Основной индикатор деградации репликации при обновлениях.
- **Handlers (Обработчики):** Задачи в Ansible, вызываемые через `notify` только при реальном изменении конфигурационных файлов (например, перезапуск сервиса при изменении `server.properties`).
- **Control Node:** Управляющая машина, с которой выполняются плейбуки Ansible (требует Python 3.10+ и Ansible core 2.16+).
- **Managed Node:** Целевой сервер (Bare Metal или виртуальная машина под управлением Linux), на котором развертывается и функционирует Kafka.

---

## Предварительные требования

### Требования к управляющей машине (Control Node)

| Компонент | Минимальная версия | Рекомендуемая версия | Назначение |
|---|---|---|---|
| Python | 3.10 | 3.11+ | Интерпретатор для исполнения модулей Ansible |
| Ansible core | 2.16 | 2.17+ | Ядро системы автоматизации |
| Коллекция `ansible.posix` | 1.5.0 | 2.0+ | Управление `sysctl`, `pam_limits`, `mount` |
| Коллекция `community.general` | 8.0.0 | 9.0+ | Системные утилиты и генерация конфигураций |
| OpenSSH Client | 8.8 | 9.0+ | Защищенный транспорт для управления хостами |

Установка и проверка окружения на Control Node:

```bash
# Подготовка виртуального окружения Python
python3 -m venv ~/ansible-kafka-venv
source ~/ansible-kafka-venv/bin/activate

# Установка Ansible и базовых коллекций
pip install --upgrade pip
pip install "ansible-core>=2.16,<2.18"

ansible-galaxy collection install ansible.posix community.general

# Проверка версии
ansible --version
# → ansible [core 2.16.x]
# → python version = 3.11.x
```

### Требования к целевым серверам (Managed Nodes)

| Ресурс / Компонент | Минимальные требования | Промышленные требования (Production) | Примечание |
|---|---|---|---|
| Операционная система | Ubuntu 22.04 LTS, RHEL / Rocky Linux 9 | Ubuntu 24.04 LTS, Rocky Linux 9.4 | 64-битные дистрибутивы Linux |
| Среда исполнения Java | OpenJDK 17 LTS | OpenJDK 21 LTS | Kafka 4.0+ требует Java 17+ |
| Оперативная память (RAM) | 16 GB | 64–128 GB+ | 6–8 GB под Heap JVM, остальное — под системный Page Cache |
| Процессор (CPU) | 4 ядра | 16–32 vCPU / ядра | Высокая параллелизация сетевых и дисковых потоков |
| Дисковая подсистема | 500 GB NVMe / SATA SSD | 2+ TB NVMe в режиме JBOD (XFS) | Изолированные диски под `log.dirs` с отключенным atime |
| Файловые дескрипторы | 65 536 | 1 000 000 | Настраивается через `pam_limits` и systemd |

### Сетевая матрица портов

| Порт | Протокол | Направление | Назначение |
|---|---|---|---|
| 9092 | TCP | Внутри кластера / Клиенты | Listener `INTERNAL` (межброкерное взаимодействие, PLAINTEXT или SASL_PLAINTEXT) |
| 9093 | TCP | Только между контроллерами | Listener `CONTROLLER` (кворум KRaft Raft metadata) |
| 9094 | TCP | Клиенты | Listener `CLIENT` (внешние/внутренние клиенты, TLS или SASL_SSL) |
| 8080 | TCP | Сервер мониторинга | Prometheus JMX Exporter (метрики брокера и KRaft) |
| 9100 | TCP | Сервер мониторинга | Prometheus `node_exporter` (системные метрики ОС) |

---

## Основные концепции

### Почему Ansible для Apache Kafka?

1. **Идемпотентность и предсказуемость:** Повторный запуск плейбука не вызывает рестарта сервиса или изменения конфигурации, если целевое состояние уже достигнуто.
2. **Низкий overhead по сравнению с контейнеризацией:** На выделенных серверах (Bare Metal) Kafka напрямую взаимодействует с сетевым стеком ядра Linux и дисковой подсистемой без промежуточных сетевых оверлеев (overlay network), гарантируя максимальный IOPS и пропускную способность (throughput).
3. **Управление всем стеком хоста:** В рамках единого плейбука настраиваются дисковые разделы (XFS), параметры ядра (`sysctl`), лимиты процессов (`limits.conf`), правила брандмауэра, сертификаты и systemd-юниты.
4. **Контроль последовательности (Rolling Operations):** Директива `serial: 1` в сочетании с проверкой состояния ISR и кворума позволяет выполнять беспростойные обновления кластера.

### Топологии KRaft: Совмещенный vs Выделенный режим

```
Совмещенный режим (Colocated: 3 узла)
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ Node 1 (Broker + Ctrler)│  │ Node 2 (Broker + Ctrler)│  │ Node 3 (Broker + Ctrler)│
│ ID: 1, Port: 9092/9093  │──│ ID: 2, Port: 9092/9093  │──│ ID: 3, Port: 9092/9093  │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘

Выделенный режим (Dedicated / Isolated: 3 контроллера + N брокеров)
┌───────────────────────┐   ┌───────────────────────┐   ┌───────────────────────┐
│ Controller 1 (ID: 1)  │   │ Controller 2 (ID: 2)  │   │ Controller 3 (ID: 3)  │
│ Port: 9093            │───│ Port: 9093            │───│ Port: 9093            │
└───────────┬───────────┘   └───────────┬───────────┘   └───────────┬───────────┘
            │                           │                           │
   ─────────┴───────────────────────────┴───────────────────────────┴─────────
            │                           │                           │
┌───────────▼───────────┐   ┌───────────▼───────────┐   ┌───────────▼───────────┐
│ Broker 101 (ID: 101)  │   │ Broker 102 (ID: 102)  │   │ Broker 103 (ID: 103)  │
│ Port: 9092 / 9094     │   │ Port: 9092 / 9094     │   │ Port: 9092 / 9094     │
└───────────────────────┘   └───────────────────────┘   └───────────────────────┘
```

- **Совмещенный режим (`broker,controller`):** Подходит для малых и средних кластеров (до 5 узлов). Все узлы участвуют в кворуме Raft и одновременно обслуживают клиентские топики.
- **Выделенный режим (`isolated`):** Рекомендуется для промышленных сред с высокой нагрузкой (High Load) и более чем 5 узлами. Контроллеры изолированы: они не обрабатывают клиентский I/O и не конкурируют за Page Cache и диск, что исключает потерю кворума из-за интенсивных дисковых сбросов брокеров.

### Жизненный цикл автоматизированного развертывания KRaft

1. **Системная подготовка:** Создание пользователя `kafka`, монтирование томов под данные с опциями XFS `noatime,nodiratime`, применение параметров ядра и отключение Transparent Huge Pages (THP).
2. **Генерация PKI / Сертификатов:** Создание корневого CA на Control Node, генерация приватных ключей и сертификатов с расширениями SAN для каждого узла, сборка Java Keystore (JKS) и Truststore.
3. **Инициализация Cluster ID:** На этапе bootstrap генерация единого `cluster.id` через `kafka-storage.sh random-uuid` на первом узле кластера и регистрация его в фактах Ansible.
4. **Форматирование хранилища:** Проверка отсутствия файла `meta.properties` в директории данных. При первом развертывании — вызов `kafka-storage.sh format` с полученным `cluster.id`.
5. **Запуск сервиса:** Генерация конфигурации `server.properties` и запуск юнита `kafka.service` через systemd.
6. **Пост-проверка:** Проверка доступности портов, состояния кворума через `kafka-metadata-quorum.sh` и готовности брокеров принимать трафик.

---

## Практические сценарии

### 1. Промышленное развертывание 3-узлового совмещенного кластера KRaft

Сценарий описывает полную автоматизацию развертывания 3 узлов в совмещенном режиме (`broker,controller`) с тюнингом ОС, XFS, системными лимитами и валидацией.

#### Шаг 1: Инвентарь проекта (`inventory/hosts.ini`)

```ini
[kafka_controllers]
kafka-node-1 ansible_host=10.0.1.1 kafka_node_id=1
kafka-node-2 ansible_host=10.0.1.2 kafka_node_id=2
kafka-node-3 ansible_host=10.0.1.3 kafka_node_id=3

[kafka_brokers]
kafka-node-1
kafka-node-2
kafka-node-3

[kafka_cluster:children]
kafka_controllers
kafka_brokers

[kafka_cluster:vars]
ansible_user=deploy
ansible_become=true
kafka_version=3.9.0
scala_version=2.13
kafka_user=kafka
kafka_group=kafka
kafka_install_dir=/opt/kafka
kafka_data_dir=/var/lib/kafka/data
kafka_log_dir=/var/log/kafka
kafka_heap_opts="-Xms6g -Xmx6g"
kafka_process_roles="broker,controller"
# Voters формируются из всех членов группы контроллеров
kafka_controller_quorum_voters="1@10.0.1.1:9093,2@10.0.1.2:9093,3@10.0.1.3:9093"
```

#### Шаг 2: Системный тюнинг ОС и дисков (Pre-tasks)

В соответствии с правилами [OS тюнинга для Kafka](./kafka_os_tuning.md), параметры ядра должны предотвращать блокировку операций записи и выгрузку Page Cache:

```yaml
# roles/kafka/tasks/system_tuning.yml
---
- name: Создание системной группы kafka
  ansible.builtin.group:
    name: "{{ kafka_group }}"
    state: present
    system: true

- name: Создание системного пользователя kafka
  ansible.builtin.user:
    name: "{{ kafka_user }}"
    group: "{{ kafka_group }}"
    home: "{{ kafka_install_dir }}"
    shell: /usr/sbin/nologin
    system: true
    state: present

- name: Настройка лимитов ресурсов процесса (pam_limits)
  community.general.pam_limits:
    domain: "{{ kafka_user }}"
    limit_type: "{{ item.type }}"
    limit_item: "{{ item.item }}"
    value: "{{ item.value }}"
  loop:
    - { type: 'soft', item: 'nofile', value: 1000000 }
    - { type: 'hard', item: 'nofile', value: 1000000 }
    - { type: 'soft', item: 'nproc', value: 65536 }
    - { type: 'hard', item: 'nproc', value: 65536 }
    - { type: 'soft', item: 'memlock', value: 'unlimited' }
    - { type: 'hard', item: 'memlock', value: 'unlimited' }

- name: Применение оптимальных параметров sysctl для Kafka
  ansible.posix.sysctl:
    name: "{{ item.key }}"
    value: "{{ item.value }}"
    state: present
    sysctl_file: /etc/sysctl.d/99-kafka.conf
    reload: true
  loop:
    # Защита Page Cache от свопирования
    - { key: 'vm.swappiness', value: '1' }
    # Сброс грязных страниц: ранний фоновый сброс без блокировки write()
    - { key: 'vm.dirty_background_ratio', value: '5' }
    - { key: 'vm.dirty_ratio', value: '10' }
    # Лимит областей mmap под индексные файлы Kafka
    - { key: 'vm.max_map_count', value: '262144' }
    # Буферы приема и передачи сокетов
    - { key: 'net.core.rmem_max', value: '16777216' }
    - { key: 'net.core.wmem_max', value: '16777216' }
    - { key: 'net.ipv4.tcp_rmem', value: '4096 87380 16777216' }
    - { key: 'net.ipv4.tcp_wmem', value: '4096 65536 16777216' }
    - { key: 'net.ipv4.tcp_window_scaling', value: '1' }
    - { key: 'net.core.netdev_max_backlog', value: '30000' }
    - { key: 'net.ipv4.tcp_max_syn_backlog', value: '16384' }

- name: Отключение Transparent Huge Pages (THP) через systemd service
  ansible.builtin.copy:
    dest: /etc/systemd/system/disable-thp.service
    mode: '0644'
    content: |
      [Unit]
      Description=Disable Transparent Huge Pages for Kafka
      DefaultDependencies=no
      After=sysinit.target local-fs.target
      Before=basic.target

      [Service]
      Type=oneshot
      ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag'

      [Install]
      WantedBy=basic.target
  notify: Enable and start disable-thp
```

#### Шаг 3: Шаблон сервиса Systemd (`templates/kafka.service.j2`)

При развертывании в systemd критически важно задавать высокий `TimeoutStopSec` (не менее 120 с), чтобы брокер успел корректно синхронизировать сегменты на диск и закрыть соединения (Graceful Shutdown). Дефолтный таймаут systemd (90 с) при высокой нагрузке приводит к принудительному `SIGKILL`, повреждению индексов и долгому восстановлению журнала при следующем старте:

```ini
[Unit]
Description=Apache Kafka Distributed Message Broker (KRaft)
Documentation=https://kafka.apache.org/documentation/
After=network.target network-online.target systemd-sysctl.service disable-thp.service
Wants=network-online.target

[Service]
Type=simple
User={{ kafka_user }}
Group={{ kafka_group }}
EnvironmentFile=-/etc/default/kafka
Environment="KAFKA_HEAP_OPTS={{ kafka_heap_opts }}"
Environment="KAFKA_JVM_PERFORMANCE_OPTS={{ kafka_jvm_performance_opts }}"
Environment="KAFKA_GC_LOG_OPTS=-Xlog:gc*:file={{ kafka_log_dir }}/kafka-gc.log:time,uptime,level,tags:filecount=10,filesize=100M"
ExecStart={{ kafka_install_dir }}/bin/kafka-server-start.sh {{ kafka_install_dir }}/config/server.properties
ExecStop={{ kafka_install_dir }}/bin/kafka-server-stop.sh

Restart=on-failure
RestartSec=10
TimeoutStopSec=120
KillMode=control-group

# Системные лимиты процесса
LimitNOFILE=1000000
LimitNPROC=65536
LimitMEMLOCK=infinity
TasksMax=infinity

[Install]
WantedBy=multi-user.target
```

#### Шаг 4: Конфигурация KRaft (`templates/server.properties.j2`)

```properties
############################# Базовые параметры узла #############################
node.id={{ kafka_node_id }}
process.roles={{ kafka_process_roles }}

############################# Сетевые Listener'ы #############################
# Listener CONTROLLER не указывается в advertised.listeners
listeners=INTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
advertised.listeners=INTERNAL://{{ ansible_host }}:9092
controller.listener.names=CONTROLLER
inter.broker.listener.name=INTERNAL
listener.security.protocol.map=INTERNAL:PLAINTEXT,CONTROLLER:PLAINTEXT,CLIENT:SSL

############################# Кворум KRaft #############################
controller.quorum.voters={{ kafka_controller_quorum_voters }}

############################# Журналы и хранилище #############################
log.dirs={{ kafka_data_dir }}
num.partitions=3
default.replication.factor=3
min.insync.replicas=2

# Потоки сетевого и дискового ввода-вывода
num.network.threads=8
num.io.threads=16
socket.send.buffer.bytes=1048576
socket.receive.buffer.bytes=1048576
socket.request.max.bytes=104857600

# Политики хранения журналов (Retention: 7 дней)
log.retention.hours=168
log.segment.bytes=1073741824
log.retention.check.interval.ms=300000

# Восстановление и завершение
num.recovery.threads.per.data.dir=4
controlled.shutdown.enable=true
auto.create.topics.enable=false
```

#### Шаг 5: Идемпотентная инициализация хранилища KRaft

Форматирование каталогов данных KRaft (`kafka-storage.sh format`) должно выполняться строго один раз с одинаковым `cluster.id` для всех узлов кластера. Повторное форматирование на работающем кластере уничтожает журнал метаданных:

```yaml
# roles/kafka/tasks/kraft_init.yml
---
- name: Проверка наличия инициализированного хранилища (meta.properties)
  ansible.builtin.stat:
    path: "{{ kafka_data_dir }}/meta.properties"
  register: kafka_meta_file

- name: Генерация Cluster ID на первом контроллере (run_once)
  ansible.builtin.command:
    cmd: "{{ kafka_install_dir }}/bin/kafka-storage.sh random-uuid"
  register: generated_cluster_id
  run_once: true
  delegate_to: "{{ groups['kafka_controllers'][0] }}"
  when: not kafka_meta_file.stat.exists
  changed_when: false

- name: Установка факта kafka_cluster_id для всех узлов
  ansible.builtin.set_fact:
    kafka_cluster_id: "{{ hostvars[groups['kafka_controllers'][0]]['generated_cluster_id'].stdout }}"
  when: not kafka_meta_file.stat.exists

- name: Форматирование каталога данных KRaft
  ansible.builtin.command:
    cmd: >
      {{ kafka_install_dir }}/bin/kafka-storage.sh format
      --cluster-id {{ kafka_cluster_id }}
      --config {{ kafka_install_dir }}/config/server.properties
      --ignore-formatted
  become_user: "{{ kafka_user }}"
  when: not kafka_meta_file.stat.exists
  register: format_result
  changed_when: "'Formatting' in format_result.stdout"
```

#### Шаг 6: Главный плейбук развертывания (`playbooks/deploy.yml`)

```yaml
---
- name: Развертывание кластера Apache Kafka KRaft
  hosts: kafka_cluster
  become: true
  vars:
    kafka_jvm_performance_opts: >-
      -server
      -XX:+UseG1GC
      -XX:MaxGCPauseMillis=20
      -XX:InitiatingHeapOccupancyPercent=35
      -XX:G1HeapRegionSize=16M
      -XX:+ExplicitGCInvokesConcurrent
      -XX:+ParallelRefProcEnabled
      -Djava.awt.headless=true

  tasks:
    - name: Применение настроек ядра и системных лимитов
      ansible.builtin.include_tasks: ../roles/kafka/tasks/system_tuning.yml

    - name: Создание каталогов для Kafka
      ansible.builtin.file:
        path: "{{ item }}"
        state: directory
        owner: "{{ kafka_user }}"
        group: "{{ kafka_group }}"
        mode: '0750'
      loop:
        - "{{ kafka_install_dir }}"
        - "{{ kafka_data_dir }}"
        - "{{ kafka_log_dir }}"

    - name: Скачивание и распаковка дистрибутива Kafka
      ansible.builtin.unarchive:
        src: "https://archive.apache.org/dist/kafka/{{ kafka_version }}/kafka_{{ scala_version }}-{{ kafka_version }}.tgz"
        dest: "{{ kafka_install_dir }}"
        remote_src: true
        extra_opts: ['--strip-components=1']
        owner: "{{ kafka_user }}"
        group: "{{ kafka_group }}"
        creates: "{{ kafka_install_dir }}/bin/kafka-server-start.sh"

    - name: Генерация конфигурационного файла server.properties
      ansible.builtin.template:
        src: ../roles/kafka/templates/server.properties.j2
        dest: "{{ kafka_install_dir }}/config/server.properties
        owner: "{{ kafka_user }}"
        group: "{{ kafka_group }}"
        mode: '0640'
      notify: Restart kafka

    - name: Инициализация метаданных хранилища KRaft
      ansible.builtin.include_tasks: ../roles/kafka/tasks/kraft_init.yml

    - name: Установка юнита systemd
      ansible.builtin.template:
        src: ../roles/kafka/templates/kafka.service.j2
        dest: /etc/systemd/system/kafka.service
        mode: '0644'
      notify:
        - Reload systemd
        - Restart kafka

    - name: Запуск и включение сервиса Kafka в автозагрузку
      ansible.builtin.systemd:
        name: kafka
        state: started
        enabled: true

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: true

    - name: Restart kafka
      ansible.builtin.systemd:
        name: kafka
        state: restarted

    - name: Enable and start disable-thp
      ansible.builtin.systemd:
        name: disable-thp
        state: started
        enabled: true
```

#### Шаг 7: Валидация развертывания

После завершения выполнения плейбука выполняется комплексная проверка состояния сервиса, портов и кворума:

```bash
# 1. Проверка статуса сервиса на всех узлах
ansible kafka_cluster -i inventory/hosts.ini -m command -a "systemctl is-active kafka"
# → active

# 2. Проверка открытых портов на первой ноде
ansible kafka-node-1 -i inventory/hosts.ini -m command -a "ss -tulpn"
# → tcp LISTEN 0 50 *:9092 users:(("java",pid=...,fd=...))
# → tcp LISTEN 0 50 *:9093 users:(("java",pid=...,fd=...))

# 3. Проверка статуса кворума метаданных KRaft
ansible kafka-node-1 -i inventory/hosts.ini -m command -a \
  "/opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server 10.0.1.1:9092 describe --status"
# → ClusterId:              c_Z17o6uT-2pW92xVd6VRA
# → LeaderId:               1
# → LeaderEpoch:            1
# → HighWatermark:          124
# → MaxFollowerLag:         0
# → MaxFollowerLagTimeMs:   42
# → CurrentVoters:          [1,2,3]

# 4. Проверка создания тестового топика
ansible kafka-node-1 -i inventory/hosts.ini -m command -a \
  "/opt/kafka/bin/kafka-topics.sh --bootstrap-server 10.0.1.1:9092 --create --topic test-healthcheck --partitions 3 --replication-factor 3"
# → Created topic test-healthcheck.
```

---

### 2. Развертывание с разделением ролей (Dedicated Controllers + Dedicated Brokers)

Для нагруженных сред (>5 узлов) контроллеры отделяются от брокеров данных, предотвращая падение кворума из-за нехватки памяти или перегрузки дисков.

#### Шаг 1: Инвентарь для выделенного режима (`inventory/dedicated_hosts.ini`)

```ini
[kafka_controllers]
ctrl-node-1 ansible_host=10.0.2.1 kafka_node_id=1 kafka_process_roles="controller" kafka_heap_opts="-Xms4g -Xmx4g"
ctrl-node-2 ansible_host=10.0.2.2 kafka_node_id=2 kafka_process_roles="controller" kafka_heap_opts="-Xms4g -Xmx4g"
ctrl-node-3 ansible_host=10.0.2.3 kafka_node_id=3 kafka_process_roles="controller" kafka_heap_opts="-Xms4g -Xmx4g"

[kafka_brokers]
broker-node-1 ansible_host=10.0.2.11 kafka_node_id=101 kafka_process_roles="broker" kafka_heap_opts="-Xms8g -Xmx8g"
broker-node-2 ansible_host=10.0.2.12 kafka_node_id=102 kafka_process_roles="broker" kafka_heap_opts="-Xms8g -Xmx8g"
broker-node-3 ansible_host=10.0.2.13 kafka_node_id=103 kafka_process_roles="broker" kafka_heap_opts="-Xms8g -Xmx8g"

[kafka_cluster:children]
kafka_controllers
kafka_brokers

[kafka_cluster:vars]
kafka_controller_quorum_voters="1@10.0.2.1:9093,2@10.0.2.2:9093,3@10.0.2.3:9093"
```

#### Шаг 2: Адаптация шаблона `server.properties.j2` под роли

```jinja2
node.id={{ kafka_node_id }}
process.roles={{ kafka_process_roles }}
controller.quorum.voters={{ kafka_controller_quorum_voters }}

{% if 'controller' in kafka_process_roles and 'broker' not in kafka_process_roles %}
# Выделенный контроллер: слушает только порт кворума
listeners=CONTROLLER://0.0.0.0:9093
controller.listener.names=CONTROLLER
log.dirs=/var/lib/kafka/metadata
{% elif 'broker' in kafka_process_roles and 'controller' not in kafka_process_roles %}
# Выделенный брокер: слушает трафик данных и подключается к внешним контроллерам
listeners=INTERNAL://0.0.0.0:9092,CLIENT://0.0.0.0:9094
advertised.listeners=INTERNAL://{{ ansible_host }}:9092,CLIENT://{{ ansible_host }}:9094
controller.listener.names=CONTROLLER
inter.broker.listener.name=INTERNAL
log.dirs={{ kafka_data_dir }}
{% else %}
# Совмещенный узел
listeners=INTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
advertised.listeners=INTERNAL://{{ ansible_host }}:9092
controller.listener.names=CONTROLLER
inter.broker.listener.name=INTERNAL
log.dirs={{ kafka_data_dir }}
{% endif %}
```

---

### 3. Автоматизация безопасности: mTLS (PKI) и SASL/SCRAM

Промышленное развертывание требует шифрования трафика между узлами и строгой аутентификации клиентов.

#### Шаг 1: Автоматизация PKI и генерация Keystore/Truststore через Ansible

```yaml
# roles/kafka/tasks/tls_pki.yml
---
- name: Создание каталога сертификатов
  ansible.builtin.file:
    path: /etc/kafka/secrets
    state: directory
    owner: "{{ kafka_user }}"
    group: "{{ kafka_group }}"
    mode: '0700'

- name: Генерация приватного ключа и Keystore для брокера
  ansible.builtin.command:
    cmd: >
      keytool -genkeypair -alias {{ inventory_hostname }}
      -keyalg RSA -keysize 4096 -validity 1095
      -keystore /etc/kafka/secrets/kafka.keystore.jks
      -storepass {{ vault_keystore_password }}
      -keypass {{ vault_keystore_password }}
      -dname "CN={{ inventory_hostname }}, OU=Infra, O=Company, C=RU"
      -ext SAN=DNS:{{ inventory_hostname }},IP:{{ ansible_host }}
    creates: /etc/kafka/secrets/kafka.keystore.jks
  no_log: true

- name: Экспорт CSR из Keystore
  ansible.builtin.command:
    cmd: >
      keytool -certreq -alias {{ inventory_hostname }}
      -keystore /etc/kafka/secrets/kafka.keystore.jks
      -storepass {{ vault_keystore_password }}
      -file /etc/kafka/secrets/{{ inventory_hostname }}.csr
    creates: /etc/kafka/secrets/{{ inventory_hostname }}.csr

- name: Копирование CSR на Control Node для подписания CA
  ansible.builtin.fetch:
    src: /etc/kafka/secrets/{{ inventory_hostname }}.csr
    dest: /tmp/pki_staging/{{ inventory_hostname }}.csr
    flat: true

- name: Подписание сертификата корневым CA на Control Node
  ansible.builtin.command:
    cmd: >
      openssl x509 -req -in /tmp/pki_staging/{{ inventory_hostname }}.csr
      -CA /etc/ansible/ca/ca.crt -CAkey /etc/ansible/ca/ca.key -CAcreateserial
      -out /tmp/pki_staging/{{ inventory_hostname }}.crt
      -days 1095 -sha256
      -extfile <(printf "subjectAltName=DNS:{{ inventory_hostname }},IP:{{ ansible_host }}")
  delegate_to: localhost
  become: false

- name: Доставка подписанного сертификата и CA на Managed Node
  ansible.builtin.copy:
    src: "{{ item.src }}"
    dest: "{{ item.dest }}"
    owner: "{{ kafka_user }}"
    group: "{{ kafka_group }}"
    mode: '0600'
  loop:
    - { src: "/etc/ansible/ca/ca.crt", dest: "/etc/kafka/secrets/ca.crt" }
    - { src: "/tmp/pki_staging/{{ inventory_hostname }}.crt", dest: "/etc/kafka/secrets/server.crt" }

- name: Импорт CA в Truststore узла
  ansible.builtin.command:
    cmd: >
      keytool -importcert -noprompt -alias ca-root
      -file /etc/kafka/secrets/ca.crt
      -keystore /etc/kafka/secrets/kafka.truststore.jks
      -storepass {{ vault_truststore_password }}
    creates: /etc/kafka/secrets/kafka.truststore.jks
  no_log: true

- name: Импорт подписанного сертификата брокера в Keystore
  ansible.builtin.command:
    cmd: >
      keytool -importcert -noprompt -alias {{ inventory_hostname }}
      -file /etc/kafka/secrets/server.crt
      -keystore /etc/kafka/secrets/kafka.keystore.jks
      -storepass {{ vault_keystore_password }}
  register: import_res
  failed_when: import_res.rc != 0 and "already exists" not in import_res.stderr
  changed_when: import_res.rc == 0
  no_log: true
```

#### Шаг 2: Настройка аутентификации SASL/SCRAM-SHA-512

В современных окружениях механизм `SCRAM-SHA-512` является стандартом, превосходящим `PLAIN` по криптостойкости (пароли не передаются в открытом виде даже внутри TLS-туннеля):

```yaml
# Добавление конфигурации JAAS
- name: Создание конфигурации JAAS для SASL/SCRAM
  ansible.builtin.copy:
    dest: /etc/kafka/kafka_jaas.conf
    owner: "{{ kafka_user }}"
    group: "{{ kafka_group }}"
    mode: '0600'
    content: |
      KafkaServer {
          org.apache.kafka.common.security.scram.ScramLoginModule required
          username="admin"
          password="{{ vault_kafka_admin_scram_password }}";
      };

- name: Экспорт переменной KAFKA_OPTS для подключения JAAS
  ansible.builtin.lineinfile:
    path: /etc/default/kafka
    regexp: '^KAFKA_OPTS='
    line: 'KAFKA_OPTS="-Djava.security.auth.login.config=/etc/kafka/kafka_jaas.conf"'
    create: true
    mode: '0644'
  notify: Restart kafka
```

Создание пользователей SCRAM через стандартную CLI-утилиту (выполняется один раз на кластере):

```yaml
- name: Инициализация учетной записи администратора SCRAM-SHA-512
  ansible.builtin.command:
    cmd: >
      {{ kafka_install_dir }}/bin/kafka-configs.sh --bootstrap-server localhost:9092
      --entity-type users --entity-name admin
      --alter --add-config 'SCRAM-SHA-512=[password={{ vault_kafka_admin_scram_password }}]'
  run_once: true
  delegate_to: "{{ groups['kafka_cluster'][0] }}"
  changed_when: true
```

---

### 4. Автоматизация беспростойного обновления (Rolling Upgrade)

Для обновления версий Kafka или внесения изменений в конфигурацию без нарушения доступности кластера используется последовательный перезапуск узлов (`serial: 1`) со строгим контролем синхронизации реплик (ISR) и кворума.

```yaml
# playbooks/rolling_restart.yml
---
- name: Последовательный контролируемый перезапуск узлов Kafka
  hosts: kafka_cluster
  serial: 1
  max_fail_percentage: 0
  become: true

  tasks:
    - name: Перезапуск сервиса Kafka на узле
      ansible.builtin.systemd:
        name: kafka
        state: restarted

    - name: Ожидание доступности порта TCP 9092
      ansible.builtin.wait_for:
        host: "{{ ansible_host }}"
        port: 9092
        delay: 5
        timeout: 120

    - name: Контроль состояния кворума метаданных KRaft
      ansible.builtin.command:
        cmd: "{{ kafka_install_dir }}/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status"
      register: quorum_check
      until: "'LeaderId' in quorum_check.stdout"
      retries: 20
      delay: 5
      changed_when: false

    - name: Ожидание полного восстановления реплик (отсутствие Under-Replicated Partitions)
      ansible.builtin.command:
        cmd: "{{ kafka_install_dir }}/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --under-replicated-partitions"
      register: urp_check
      # Перезапуск следующего узла разрешен только когда вывод пуст (все партиции синхронизированы)
      until: urp_check.stdout == ""
      retries: 60
      delay: 10
      changed_when: false
```

> **Важно:** Проверка `until: urp_check.stdout == ""` критична. Простая проверка на наличие подстроки `'Isr'` ошибочна, так как поле `Isr:` присутствует в описании каждой партиции даже при аварийном выпадении узла из репликации.

---

### 5. Горизонтальное масштабирование (добавление брокеров и ребалансировка)

При расширении кластера новый брокер (`process.roles=broker`) вводится в эксплуатацию без изменения параметров кворума контроллеров.

#### Шаг 1: Добавление хоста в инвентарь

```ini
[kafka_brokers]
kafka-node-1
kafka-node-2
kafka-node-3
kafka-node-4 ansible_host=10.0.1.4 kafka_node_id=4  # Новый рабочий брокер
```

#### Шаг 2: Ввод брокера в эксплуатацию

1. Запустите базовый плейбук деплоя с лимитом на новый хост:
   ```bash
   ansible-playbook -i inventory/hosts.ini playbooks/deploy.yml --limit kafka-node-4
   ```
2. Новый узел подключится к кворуму контроллеров, зарегистрирует свой `node.id=4` и начнет принимать запросы.

#### Шаг 3: Автоматизация ребалансировки партиций (`kafka-reassign-partitions.sh`)

Автоматически новые топики начнут распределяться на новый узел, но существующие данные остаются на прежних узлах. Для перераспределения существующих партиций формируется JSON-план:

```yaml
# playbooks/rebalance.yml
---
- name: Ребалансировка партиций на новые брокеры
  hosts: kafka-node-1
  become: true
  tasks:
    - name: Формирование списка целевых топиков
      ansible.builtin.copy:
        dest: /tmp/topics-to-move.json
        content: |
          {"topics": [{"topic": "orders"}, {"topic": "payments"}], "version": 1}
        mode: '0644'

    - name: Генерация плана распределения партиций
      ansible.builtin.command:
        cmd: >
          {{ kafka_install_dir }}/bin/kafka-reassign-partitions.sh
          --bootstrap-server localhost:9092
          --topics-to-move-json-file /tmp/topics-to-move.json
          --broker-list "1,2,3,4"
          --generate
      register: reassign_plan_raw
      changed_when: false

    - name: Извлечение сгенерированного плана в файл
      ansible.builtin.copy:
        dest: /tmp/reassign-execution.json
        content: "{{ (reassign_plan_raw.stdout_lines | select('match', '^{\"version\":.*') | list)[0] }}"
        mode: '0644'

    - name: Применение плана с ограничением пропускной способности (Throttle 50 MB/s)
      ansible.builtin.command:
        cmd: >
          {{ kafka_install_dir }}/bin/kafka-reassign-partitions.sh
          --bootstrap-server localhost:9092
          --reassignment-json-file /tmp/reassign-execution.json
          --throttle 52428800
          --execute
      register: execute_res
      changed_when: "'Successfully started reassignment' in execute_res.stdout"

    - name: Контроль завершения миграции данных
      ansible.builtin.command:
        cmd: >
          {{ kafka_install_dir }}/bin/kafka-reassign-partitions.sh
          --bootstrap-server localhost:9092
          --reassignment-json-file /tmp/reassign-execution.json
          --verify
      register: verify_res
      until: "'is completed' in verify_res.stdout and 'is in progress' not in verify_res.stdout"
      retries: 60
      delay: 30
      changed_when: false
```

---

### 6. Настройка мониторинга через Prometheus JMX Exporter

Сбор метрик брокера и KRaft контроллера организуется через Java-агент Prometheus JMX Exporter, подключаемый через переменную окружения `KAFKA_OPTS`.

```yaml
# roles/kafka/tasks/monitoring.yml
---
- name: Скачивание JMX Exporter JavaAgent
  ansible.builtin.get_url:
    url: "https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/1.0.1/jmx_prometheus_javaagent-1.0.1.jar"
    dest: "{{ kafka_install_dir }}/libs/jmx_prometheus_javaagent.jar"
    owner: "{{ kafka_user }}"
    group: "{{ kafka_group }}"
    mode: '0644'

- name: Создание конфигурации JMX Exporter под KRaft и метрики брокера
  ansible.builtin.copy:
    dest: "{{ kafka_install_dir }}/config/jmx_exporter.yml"
    owner: "{{ kafka_user }}"
    group: "{{ kafka_group }}"
    mode: '0644'
    content: |
      startDelaySeconds: 0
      ssl: false
      lowercaseOutputName: true
      lowercaseOutputLabelNames: true
      rules:
        # Критические метрики кворума KRaft
        - pattern: "kafka.controller<type=KafkaController, name=(.+)><>Value"
          name: kafka_controller_active_$1
        - pattern: "kafka.controller<type=MetadataLoader, name=(.+)><>Value"
          name: kafka_controller_metadata_loader_$1
        # Метрики репликации и состояния брокера
        - pattern: "kafka.server<type=ReplicaManager, name=UnderReplicatedPartitions><>Value"
          name: kafka_server_replica_under_replicated_partitions_count
        - pattern: "kafka.server<type=ReplicaManager, name=OfflineReplicaCount><>Value"
          name: kafka_server_replica_offline_replica_count
        - pattern: "kafka.server<type=BrokerTopicMetrics, name=(BytesInPerSec|BytesOutPerSec|MessagesInPerSec)><>Count"
          name: kafka_server_brokertopicmetrics_$1_total
        # JVM метрики
        - pattern: "java.lang<type=Memory><HeapMemoryUsage>used"
          name: jvm_heap_memory_used_bytes

- name: Добавление JavaAgent в /etc/default/kafka
  ansible.builtin.lineinfile:
    path: /etc/default/kafka
    regexp: '^KAFKA_JMX_OPTS='
    line: 'KAFKA_JMX_OPTS="-javaagent:{{ kafka_install_dir }}/libs/jmx_prometheus_javaagent.jar=8080:{{ kafka_install_dir }}/config/jmx_exporter.yml"'
    create: true
    mode: '0644'
  notify: Restart kafka
```

Проверка метрик:

```bash
curl -s http://10.0.1.1:8080/metrics | grep kafka_server_replica_under_replicated_partitions_count
# → kafka_server_replica_under_replicated_partitions_count 0.0
```

---

## Troubleshooting

| Симптом | Причина | Диагностика | Решение |
|---|---|---|---|
| `InconsistentClusterIdException` | Рассогласование `cluster.id` в `meta.properties` между узлами | `cat /var/lib/kafka/data/meta.properties \| grep cluster.id` на всех нодах | Привести все узлы к единому Cluster ID; перед повторным форматированием остановить сервис и очистить каталог данных |
| `NotControllerException` / `LeaderRecoveryException` | Запрос административной утилиты направлен на брокер без кворума или кворум потерян | `kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status` | Проверить сетевую доступность порта 9093 между всеми контроллерами (`ss -tulpn`, брандмауэр) |
| `java.net.BindException: Address already in use` | Порт 9092, 9093 или 8080 занят другим процессом или зависшим PID Kafka | `ss -tulpn \| grep -E '9092|9093|8080'` | Найти и завершить зависший процесс (`kill -15 <pid>`); скорректировать порты в `server.properties` |
| `java.lang.OutOfMemoryError: Java heap space` | Недостаточный размер Heap для текущей нагрузки или утечка памяти | Проверить логи GC: `/var/log/kafka/kafka-gc.log` и метрики через `jstat -gcutil <pid> 1000` | Увеличить `KAFKA_HEAP_OPTS` до 8G (не более), проверить количество активных партиций на брокере |
| `Too many open files` | Превышен лимит дескрипторов файлов процесса | `cat /proc/$(pgrep -f kafka)/limits \| grep 'Max open files'` | Проверить применение `pam_limits` и директивы `LimitNOFILE=1000000` в `kafka.service` |
| `SSLHandshakeException: General SSLEngine problem` | Сертификат узла не содержит IP/DNS в SAN, либо истек срок действия, либо нет CA в truststore | `openssl s_client -connect 10.0.1.1:9094 -servername 10.0.1.1` | Перевыпустить сертификат с явным указанием `SAN=DNS:...,IP:...` и пересобрать Keystore |
| Ошибки репликации (`UnderReplicatedPartitions > 0`) | Сетевые задержки, деградация диска ввода-вывода или падение одного из брокеров | `kafka-topics.sh --bootstrap-server localhost:9092 --describe --under-replicated-partitions` | Проверить состояние дисков (`iostat -xz 1`), журнал `journalctl -u kafka` на сбойном узле |
| Долгая остановка сервиса и `SIGKILL` от systemd | Малый `TimeoutStopSec` в systemd при сбросе больших сегментов на диск | `journalctl -u kafka \| grep 'Terminating process with SIGKILL'` | Увеличить `TimeoutStopSec=120` (или 180) в шаблоне `kafka.service.j2` |

### Диагностические сценарии и команды

```bash
# 1. Проверка реальных лимитов запущенного процесса Kafka
cat /proc/$(pgrep -f "kafka.Kafka")/limits | grep -E "open files|max processes"
# → Max open files            1000000              1000000              files
# → Max processes             65536                65536                processes

# 2. Проверка состояния Transparent Huge Pages (должно быть [never])
cat /sys/kernel/mm/transparent_hugepage/enabled
# → always madvise [never]

# 3. Детальный аудит логов systemd в реальном времени
journalctl -u kafka -n 100 -f --no-pager

# 4. Проверка валидности сертификатов Keystore
keytool -list -v -keystore /etc/kafka/secrets/kafka.keystore.jks -storepass changeit | grep -E "Alias name|Valid from|Owner"
```

---

## Best Practices

1. **Разделение ролей для кластеров от 5 узлов:** Начиная с 5 серверов, выделяйте 3 отдельных компактных узла под кворум контроллеров (`process.roles=controller`), а остальные — под брокеры данных (`process.roles=broker`). Это устраняет конкуренцию за ресурсы.
2. **Использование Ansible Vault для секретов:** Никогда не коммитьте пароли от Keystore, Truststore и учетных записей SASL в репозиторий в открытом виде:
   ```bash
   ansible-vault encrypt_string 'SuperSecretP@ssw0rd' --name 'vault_keystore_password'
   ```
3. **Изоляция хранилища под данные и логи:** Размещайте каталог `kafka_data_dir` на выделенном дисковом томе NVMe/SSD, отформатированном в **XFS** с опциями монтирования `noatime,nodiratime,logbufs=8,logbsize=256k`. Журналы сервиса (`/var/log/kafka`) направляйте на отдельный системный диск во избежание заполнения раздела данных.
4. **Контроль параметров сброса Page Cache:** В высоконагруженных системах устанавливайте `vm.dirty_background_ratio=5` и `vm.dirty_ratio=10`. Значения выше 20 вызывают массивные всплески задержек I/O из-за блокирующего синхронного сброса данных ядром.
5. **Безопасный Graceful Shutdown:** Убедитесь, что в конфигурации включен `controlled.shutdown.enable=true`, а в systemd задан `TimeoutStopSec=120`. Это гарантирует передачу лидерства партиций до остановки процесса.
6. **Тестирование ролей через Ansible-Lint:** Регулярно запускайте статический анализ плейбуков для предотвращения ошибок синтаксиса и безопасности:
   ```bash
   ansible-lint playbooks/deploy.yml
   ```

---

## Edge Cases

### Восстановление после потери кворума KRaft

Если 2 из 3 контроллеров безвозвратно вышли из строя, кворум Raft утрачивает большинство и переходит в режим read-only.
- Для восстановления оставшийся контроллер не может самостоятельно выбрать нового лидера.
- В Kafka 3.8+ / 4.0 используется утилита динамической реконфигурации кворума:
  ```bash
  /opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 remove-controller --controller-id 2
  ```
- В аварийном сценарии полной утраты кворума требуется восстановление из резервной копии каталога `metadata.log.dir`.

### Защита от случайного повторного форматирования

Команда `kafka-storage.sh format` при повторном запуске на работающем диске без флага `--ignore-formatted` завершается ошибкой, однако если флаг указан некорректно или каталог данных частично очищен, метаданные могут быть затерты. Задача Ansible обязательно должна включать предварительную проверку `ansible.builtin.stat` файла `meta.properties`.

### Аварийное отключение питания хоста (Unclean Shutdown)

При внезапном отключении питания брокер может обнаружить поврежденный сегмент лога. При следующем старте Kafka выполняет проверку контрольных сумм CRC всех сегментов, начиная с точки последнего чекпоинта (`recovery.point.offset.checkpoint`).
- Количество потоков проверки регулируется параметром `num.recovery.threads.per.data.dir=4`.
- Если на диске поврежден индексный файл (`.index` или `.timeindex`), удаление только поврежденного индекса позволяет брокеру восстановить его из сегмента `.log` без потери данных сообщений.

---

## Дополнительная информация

### Почему Heap ограничен 6–8 ГБ?

В отличие от традиционных Java-сервисов (например, Elasticsearch), Kafka спроектирована для работы в связке с дисковым кэшем операционной системы (**Page Cache**):
- Данные топиков передаются из дискового кэша напрямую в сетевой сокет через системный вызов `sendfile` (Zero-Copy Transfer), минуя пространство пользователя (JVM).
- Если выделить под JVM Heap 32 ГБ или 64 ГБ оперативной памяти, это отнимет ресурсы у Page Cache, приведет к деградации пропускной способности чтения и вызовет длительные паузы сборщика мусора (GC Stop-The-World).
- Рекомендуемый размер: 6–8 ГБ для брокера, 4 ГБ для выделенного контроллера KRaft. Подробный анализ работы GC и подбора параметров см. в [JVM и GC тюнинг для Kafka](./kafka_jvm_gc_tuning.md).

### Референсная структура проекта Ansible

```
kafka-ansible/
├── ansible.cfg
├── inventory/
│   ├── hosts.ini                      # Статический инвентарь (или hosts.yml)
│   └── group_vars/
│       ├── all.yml                    # Общие переменные (версии, пути)
│       ├── kafka_controllers.yml      # Настройки кворума и ресурсов контроллеров
│       └── kafka_brokers.yml          # Настройки I/O и лимитов брокеров
├── roles/
│   └── kafka/
│       ├── tasks/
│       │   ├── main.yml               # Точка входа роли
│       │   ├── system_tuning.yml      # Тюнинг sysctl, limits, THP
│       │   ├── install.yml            # Установка пакетов и дистрибутива
│       │   ├── tls_pki.yml            # Сертификаты, Keystore и Truststore
│       │   ├── kraft_init.yml         # Идемпотентная инициализация KRaft
│       │   └── monitoring.yml         # Установка и настройка JMX Exporter
│       ├── templates/
│       │   ├── server.properties.j2   # Шаблон конфигурации брокера/контроллера
│       │   └── kafka.service.j2       # Шаблон сервиса systemd
│       └── handlers/
│           └── main.yml               # Обработчики рестарта и перезагрузки systemd
└── playbooks/
    ├── deploy.yml                     # Полное развертывание кластера
    ├── rolling_restart.yml            # Беспростойный перезапуск
    └── rebalance.yml                  # Автоматизация ребалансировки партиций
```

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура журналов, брокеров и основы протокола KRaft.
- **[OS тюнинг для Apache Kafka](./kafka_os_tuning.md)** — системные параметры ядра Linux, файловые системы XFS и дисковые планировщики.
- **[JVM и GC тюнинг для Apache Kafka](./kafka_jvm_gc_tuning.md)** — параметры сборщика мусора G1GC, логирование GC и управление памятью.
- **[CLI-инструменты для работы с Apache Kafka](./kafka_cli_tools.md)** — стандартные утилиты управления кворумом, топиками и клиентами.
- **[Гарантии доставки в Apache Kafka](./delivery_guarantees.md)** — влияние параметров `min.insync.replicas` и `acks` на надежность.
- **[Kafka для систем мониторинга](./kafka_for_monitoring.md)** — сбор ключевых JMX-метрик и мониторинг Consumer Lag.
- **[Capacity Planning и Disaster Recovery](./kafka_capacity_dr.md)** — формулы сайзинга аппаратных ресурсов и стратегии восстановления.

### Внешние источники и инструменты

- **[Apache Kafka Documentation](https://kafka.apache.org/documentation/)** — официальная документация проекта Apache Kafka.
- **[Confluent Platform Ansible (cp-ansible)](https://github.com/confluentinc/cp-ansible)** — эталонная открытая реализация Ansible-ролей для платформы Confluent.
- **[Prometheus JMX Exporter](https://github.com/prometheus/jmx_exporter)** — агент для экспорта JMX-метрик Java-приложений в формат Prometheus.
- **[Ansible Lint Documentation](https://ansible.readthedocs.io/projects/lint/)** — статический анализатор качества кода и соблюдения лучших практик Ansible.
