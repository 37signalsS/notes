# Развертывание Apache Kafka с помощью Ansible

## Определения

**Ansible-роль Kafka** — инструмент автоматизации для развертывания и настройки кластеров Apache Kafka. Позволяет быстро поднять отказоустойчивую конфигурацию из нескольких брокеров.

**KRaft (Kafka Raft)** — современный режим консенсуса в Kafka (начиная с версии 3.3), исключающий зависимость от ZooKeeper. В этом режиме метаданные кластера хранятся непосредственно в Kafka, а роли контроллера и брокера могут быть совмещены.

## Подготовка

### Требования к инфраструктуре

Для промышленной эксплуатации (Production) рекомендуются следующие ресурсы на каждую ноду:
- **CPU**: 4 ядра
- **RAM**: 16 ГБ (минимум 2 ГБ для Heap)
- **Disk**: SSD, минимум 500 ГБ на брокера
- **Сеть**: 1 Гбит/с и выше
- **ОС**: Ubuntu 22.04+ или CentOS 8+

### Предварительные условия

1. Установленный Ansible версии 2.15 и выше на управляющей машине.
2. Настроенный SSH-доступ к целевым хостам под пользователем `root` или с правами `sudo`.

---

## Практические сценарии

### 1. Развертывание кластера в режиме KRaft

Сценарий описывает установку кластера из 3 брокеров, где функции контроллера совмещены с функциями брокера.

#### Шаг 1: Подготовка роли

Создайте директорию для проекта и склонируйте роль:
```bash
mkdir -p my_kafka_project/roles/kafka
cd my_kafka_project
git clone https://github.com/dragomirr/ansible-role-kafka.git roles/kafka
```

#### Шаг 2: Настройка инвентаря

Создайте файл `inventory/hosts.ini`:
```ini
[kafka_cluster]
server-1 ansible_host=192.168.10.11 ansible_user=root kafka_node_id=1
server-2 ansible_host=192.168.10.12 ansible_user=root kafka_node_id=2
server-3 ansible_host=192.168.10.13 ansible_user=root kafka_node_id=3
```

#### Шаг 3: Создание плейбука

Создайте файл `playbook.yaml`:
```yaml
- name: Install Kafka
  hosts: kafka_cluster
  become: yes
  roles:
    - role: kafka
      # Настройки кучи JVM
      kafka_heap_size: 2G
      # Автоматическая установка Java и зависимостей
      kafka_install_dependencies: true
      # Предварительное создание топиков
      kafka_topics:
        - name: MyFirstTopic
          replication_factor: 1
          partitions: 10
      # Дополнительные параметры конфигурации (server.properties)
      kafka_additional_config:
        message.max.bytes: 1048576 # 1 MiB
      # Параметры запуска JVM
      kafka_opts:
        - -XX:NewSize=256m
```

#### Шаг 4: Запуск установки

```bash
ansible-playbook -i inventory/hosts.ini playbook.yaml
```

---

### 2. Проверка работоспособности

Выполните команды на одном из брокеров для проверки успешной установки.

**Просмотр списка топиков:**
```bash
/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
```

**Отправка тестового сообщения:**
```bash
echo "Hello, World from Kafka" | /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic MyFirstTopic
```

**Чтение сообщений из топика:**
```bash
/opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic MyFirstTopic --from-beginning
# → Hello, World from Kafka
```

---

## Дополнительная информация

### Типовая структура проекта

```text
├── inventory
│   └── hosts.ini
├── playbook.yaml
└── roles
    └── kafka
        ├── defaults/main.yml    # Переменные роли по умолчанию
        ├── tasks/main.yml       # Основные задачи установки
        ├── templates/           # J2-шаблоны для systemd и конфигов
        └── vars/main.yml        # Внутренние переменные роли
```

### См. также
- **[Обзор Apache Kafka](./kafka_overview.md)** — архитектура, брокеры, топики и партиции.
- **[Kafka для мониторинга](./kafka_for_monitoring.md)** — использование Kafka как буфера для телеметрии.
- **[Миграция на StatefulSet](./deployment_to_statefulset_migration.md)** — развертывание Kafka в Kubernetes.
