# Yandex Compute Cloud

## Определения

**Compute Cloud** — сервис предоставления вычислительных ресурсов в Yandex Cloud. Позволяет создавать и управлять виртуальными машинами (ВМ) с различными конфигурациями CPU, памяти и дисков.

**Виртуальная машина (VM)** — изолированное вычислительное окружение с собственной ОС, работающее на платформе виртуализации Yandex Cloud.

**Прерываемая ВМ (Preemptible)** — ВМ со сниженной стоимостью, которая может быть остановлена через 24 часа или при нехватке ресурсов. Не покрывается SLA.

---

## Основные концепции

### Платформы виртуализации

| Платформа | Процессор | Сценарии |
| :--- | :--- | :--- |
| **standard-v3** | Intel Xeon Cascade Lake | Универсальные нагрузки |
| **standard-v4a** | AMD Zen 4 (Q3–Q4 2025) | Новые универсальные нагрузки |
| **highfreq-v3** | Intel Xeon Cascade Lake (3.4 ГГц) | Высокопроизводительные вычисления |
| **highfreq-v4a** | AMD Zen 4 (3.8 ГГц) | Вычисления с низкой задержкой |
| **gpu-v1** | NVIDIA V100, A100, L4 | ML/DL, рендеринг, видеокодирование |

### Типы дисков

| Тип | Характеристики | Сценарии |
| :--- | :--- | :--- |
| **network-ssd** | Высокая IOPS, низкая задержка | Базы данных, системы реального времени |
| **network-ssd-nonreplicated** | Макс. производительность, 3 копии в одной зоне | Критичные к задержкам БД |
| **network-hdd** | Экономичное хранение | Файловые серверы, архивы |
| **network-ssd-readonly** | Только чтение, высокая плотность | Статические данные, реплики БД |

### Сетевые возможности

- **Подсети** — логические сегменты сети в одной зоне доступности
- **Security Groups** — правила контроля входящего/исходящего трафика на L3/L4
- **Публичные IP** — для прямого доступа из интернета
- **NAT Gateway** — исходящий доступ в интернет для приватных ВМ

### Автоматизация и конфигурация

- **Cloud-init** — скрипты первичной настройки ВМ
- **Метаданные** — сервисные данные (SSH-ключи, токены IAM)
- **Сервисные аккаунты** — для доступа ВМ к API Yandex Cloud
- **Снимки (snapshots)** — резервные копии дисков

### Прерываемые ВМ

**Преимущества:**

- Сниженная стоимость (до 70% дешевле обычных)

**Ограничения:**

- Максимальное время работы: 24 часа
- Принудительная остановка при нехватке ресурсов
- Не покрываются SLA
- Не гарантируется запуск при дефиците ресурсов

**Сценарии использования:**

- CI/CD агенты и сборочные задачи
- Пакетная обработка данных (batch jobs)
- Отказоустойчивые распределённые системы
- Высокопроизводительные вычисления (HPC) с контрольными точками

**Особенности:**

- Данные сохраняются после остановки
- Instance Groups автоматически перезапускают ВМ через 22–24 часа (случайный интервал)
- Конвертация между обычными и прерываемыми ВМ возможна

---

## Практические сценарии

### Быстрый запуск ВМ через yc CLI

Минимальная команда для тестовой ВМ:

```bash
yc compute instance create \
  --name demo-vm \
  --zone ru-central1-a \
  --hostname demo-vm \
  --platform standard-v3 \
  --cores 2 --memory 4 \
  --create-boot-disk image-folder-id=standard-images,image-family=ubuntu-2204-lts,size=20 \
  --network-interface subnet-name=default-ru-central1-a,nat-ip-version=ipv4 \
  --ssh-key ~/.ssh/id_rsa.pub
```

### ВМ с сервисным аккаунтом и cloud-init

Для автоматизированной настройки и доступа к API:

```bash
yc compute instance create \
  --name app-vm \
  --zone ru-central1-b \
  --platform standard-v3 \
  --cores 2 --memory 4 \
  --create-boot-disk image-folder-id=standard-images,image-family=ubuntu-2204-lts,type=network-ssd,size=20 \
  --network-interface subnet-name=default-ru-central1-b,nat-ip-version=ipv4 \
  --service-account-name sa-app \
  --metadata-from-file user-data=cloud-init.yaml
```

Пример `cloud-init.yaml`:

```yaml
#cloud-config
package_update: true
packages:
  - git
  - docker.io
  - jq
runcmd:
  - [systemctl, enable, --now, docker]
  - [usermod, -aG, docker, ubuntu]
  - [systemctl, restart, networking]
```

### Прерываемая ВМ для CI-агента

```bash
yc compute instance create \
  --name ci-runner \
  --zone ru-central1-a \
  --platform standard-v3 \
  --cores 4 --memory 8 \
  --preemptible \
  --create-boot-disk image-folder-id=standard-images,image-family=ubuntu-2204-lts,size=30 \
  --network-interface subnet-name=default-ru-central1-a,nat-ip-version=ipv4 \
  --service-account-name sa-ci \
  --metadata-from-file user-data=ci-setup.yaml
```

### Выбор параметров: практические ориентиры

| Параметр | Рекомендации |
| :--- | :--- |
| **Образ ОС** | LTS-версии (Ubuntu 22.04/24.04, AlmaLinux 9) для стабильности |
| **vCPU/RAM** | 2 vCPU/4 ГБ — легковесные сервисы; 4 vCPU/8 ГБ — CI/сборка; 8+ vCPU — продакшен |
| **Диск** | SSD для БД и CI/CD; HDD для файловых хранилищ и логов |
| **Публичный IP** | Включать только для bastion, веб-серверов; для остальных — NAT Gateway |
| **Security Groups** | Минимальные права: SSH только с доверенных IP, порты приложений — из внутренней сети |

### Управление ВМ

```bash
# Остановка
yc compute instance stop --name demo-vm

# Запуск
yc compute instance start --name demo-vm

# Перезапуск
yc compute instance restart --name demo-vm

# Удаление
yc compute instance delete --name demo-vm

# Получить информацию
yc compute instance get --name demo-vm

# Список всех ВМ в каталоге
yc compute instance list
```

### Снимки дисков

```bash
# Создание снимка
yc compute disk snapshot create --disk-name boot-disk --name boot-snapshot

# Создание диска из снимка
yc compute disk create --name restored-disk --source-snapshot-name boot-snapshot --size 20

# Список снимков
yc compute snapshot list
```

---

## Дополнительная информация

### Связанные документы

- **[VPC](./VPC.md)** — настройка сетей, подсетей, security groups
- **[Resource Manager](./Resource-Manager.md)** — управление каталогами и сервисными аккаунтами
- **[Storage](./Storage.md)** — объектные и блочные хранилища для данных ВМ
- **[Managed Databases](./Managed-Databases.md)** — управляемые БД как альтернатива развёртыванию на ВМ

### Интеграции

- **[Kubernetes](../Kubernetes/)** — управляемые кластеры K8s используют Compute Cloud для нод
- **[Docker](../Docker/docker_overview.md)** — контейнеризация приложений на ВМ
- **[Ansible](../Ansible/ansible_introduction.md)** — автоматизация настройки ВМ
- **[Terraform](../Concepts/iac_overview.md)** — декларативное управление ВМ

### Мониторинг

- **[Yandex Monitoring](./Monitoring.md)** — метрики ВМ (CPU, память, диск, сеть)
- **[Cloud Logging](./Monitoring.md#логи-→-метрики)** — централизованный сбор логов

### Безопасность

- **[Security Groups](./VPC.md#security-groups)** — сетевой уровень защиты
- **[IAM](../Security/)** — управление доступом через сервисные аккаунты
- **[KMS](../Security/)** — шифрование дисков

### Актуальные версии

- **Платформы:** standard-v3, standard-v4a (AMD Zen 4), highfreq-v3, highfreq-v4a
- **ОС:** Ubuntu 22.04/24.04 LTS, AlmaLinux 8/9, Debian 11/12, CentOS 7/8/9, Windows Server 2019/2022
- **PostgreSQL в Managed:** 14, 15, 16, 17, 18 (версии 10–13 прекращены)
