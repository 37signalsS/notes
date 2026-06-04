# Yandex Cloud — Compute Cloud

## Определения

**Compute Cloud** — сервис предоставления вычислительных ресурсов в Yandex Cloud. Позволяет создавать и управлять виртуальными машинами (ВМ) с различными конфигурациями CPU, памяти и дисков.

**Виртуальная машина (VM)** — изолированное вычислическое окружение с собственной операционной системой, работающее на платформе виртуализации Yandex Cloud.

**Прерываемая ВМ (Preemptible)** — ВМ со сниженной стоимостью, которая может быть остановлена облачной платформой через 24 часа или при нехватке ресурсов. Не покрывается SLA (Service Level Agreement).

---

## Основные концепции

### Платформы виртуализации

| Платформа | Процессор | Сценарии использования |
| :--- | :--- | :--- |
| **standard-v3** | Intel Xeon Cascade Lake | Универсальные нагрузки |
| **standard-v4a** | AMD Zen 4 (Q3–Q4 2025) | Новые универсальные нагрузки |
| **highfreq-v3** | Intel Xeon Cascade Lake (3.4 ГГц) | Высокопроизводительные вычисления |
| **highfreq-v4a** | AMD Zen 4 (3.8 ГГц) | Вычисления с низкой задержкой |
| **gpu-v1** | NVIDIA V100, A100, L4 | ML/DL, рендеринг, видеокодирование |

### Типы дисков

Подробные характеристики дисков (IOPS, пропускная способность, задержки) — в [Storage concepts](./Storage/storage_concepts.md#типы-дисков).

| Тип | Сценарии использования |
| :--- | :--- |
| **network-ssd** | Базы данных, системы реального времени |
| **network-ssd-nonreplicated** | Критичные к задержкам БД |
| **network-hdd** | Файловые серверы, архивы |
| **network-ssd-readonly** | Статические данные, реплики БД |

### Сетевые возможности

- **Подсети** — логические сегменты сети в одной зоне доступности.
- **Security Groups** — правила контроля входящего и исходящего трафика на уровнях L3/L4.
- **Публичные IP** — для прямого доступа из интернета.
- **NAT Gateway** — исходящий доступ в интернет для приватных ВМ без публичного IP.

### Автоматизация и конфигурация

- **Cloud-init** — промышленный стандарт для первичной настройки ВМ (установка пакетов, создание пользователей).
- **Метаданные** — сервисные данные для конфигурации (SSH-ключи, пользовательские скрипты).
- **Сервисные аккаунты** — используются для предоставления ВМ прав доступа к API Yandex Cloud.
- **Снимки (snapshots)** — резервные копии дисков для восстановления или клонирования.

### Прерываемые ВМ (Preemptible VM)

**Особенности и ограничения:**

- Сниженная стоимость (до 70% дешевле стандартных ВМ).
- Максимальное время непрерывной работы: 24 часа.
- Принудительная остановка при дефиците ресурсов в зоне доступности.
- Не гарантируется возможность немедленного запуска при дефиците ресурсов.
- Не покрываются финансовыми гарантиями SLA.

**Сценарии использования:**

- CI/CD агенты и сборочные узлы.
- Пакетная обработка данных (batch jobs) с поддержкой контрольных точек.
- Отказоустойчивые распределённые системы.
- Тестовые среды и разработка.

---

## Практические сценарии

### Быстрый запуск ВМ через yc CLI

Минимальная команда для создания тестовой ВМ:

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

Пример создания ВМ с автоматической установкой Docker:

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

**Пример cloud-init.yaml:**

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
```

### Выбор параметров: практические ориентиры

| Параметр | Рекомендации |
| :--- | :--- |
| **Образ ОС** | LTS-версии (Ubuntu 22.04/24.04, AlmaLinux 9) для стабильности |
| **vCPU/RAM** | 2 vCPU/4 ГБ — легкие сервисы; 4 vCPU/8 ГБ — CI/сборка; 8+ vCPU — продакшен |
| **Диск** | SSD для БД и нагруженных систем; HDD для архивов и логов |
| **Публичный IP** | Только для bastion-хостов и веб-фронтендов; для остальных — NAT Gateway |
| **Security Groups** | SSH только из доверенных сетей, ограничение доступа к портам приложений |

### Основные операции управления

```bash
# Остановка и запуск
yc compute instance stop --name demo-vm
yc compute instance start --name demo-vm

# Перезагрузка
yc compute instance restart --name demo-vm

# Получение информации и список
yc compute instance get --name demo-vm
yc compute instance list

# Удаление
yc compute instance delete --name demo-vm
```

### Работа со снимками дисков

```bash
# Создание снимка загрузочного диска
yc compute disk snapshot create --disk-name boot-disk --name boot-snapshot

# Создание диска из существующего снимка
yc compute disk create --name restored-disk --source-snapshot-name boot-snapshot --size 20
```

---

## Дополнительная информация

Управляемые кластеры [Kubernetes](../Kubernetes/kubernetes_overview.md) используют Compute Cloud для узлов. Контейнеризация приложений на ВМ — [Docker](../Docker/docker_overview.md), автоматизация конфигурации — [Ansible](../Ansible/ansible_introduction.md), декларативное управление инфраструктурой — [Terraform](../Concepts/iac_overview.md).

Метрики производительности (CPU, RAM, Disk, Network) доступны в [Yandex Monitoring](./Monitoring/index.md), сбор и анализ логов — [Cloud Logging](./Monitoring/monitoring_practical_scenarios.md#2-логи--метрики-log-based-metrics).

Сетевая безопасность реализуется через [Security Groups](./VPC.md#security-groups-группы-безопасности), управление правами доступа — [IAM](./Resource_Manager/iam_roles.md), защита данных и ключи — [KMS](./Resource_Manager/overview.md).

Хранение данных и диски — [Storage](./Storage/index.md), управляемые базы данных как сервис — [Managed Databases](./Managed-Databases.md), структура ресурсов и каталоги — [Resource Manager](./Resource_Manager/overview.md).

### Актуальные версии

- **Платформы:** standard-v3, standard-v4a (AMD Zen 4), highfreq-v3, highfreq-v4a.
- **Операционные системы:** Ubuntu 22.04/24.04 LTS, AlmaLinux 8/9, Debian 11/12, CentOS 7/8/9, Windows Server 2019/2022.
