# Yandex Storage

## Определения

**Yandex Storage** — семейство сервисов хранения данных в Yandex Cloud, включающее три типа хранилищ: [Object Storage](./storage_concepts.md#object-storage) (S3-совместимое объектное хранилище), [Block Storage](./storage_concepts.md#block-storage-диски) (сетевые диски для ВМ), [File Storage](./storage_concepts.md#file-storage) (управляемое NFS-хранилище).

Сравнение типов, характеристики и лимиты — в [Storage concepts](./storage_concepts.md).

---

## Основные концепции

### Типы хранилищ

| Тип | Интерфейс | Ключевые свойства | Сценарии |
| :--- | :--- | :--- | :--- |
| **Object Storage** | S3 API | Версионирование, lifecycle-политики, 99.999999999% доступность | Артефакты CI/CD, бэкапы, статика, логи, медиа |
| **Block Storage** | Блочное устройство (`/dev/vdb`) | Низкая задержка (<1 мс), снапшоты, онлайн-расширение | Загрузочные диски, БД, `/var/lib/docker` |
| **File Storage** | POSIX/NFS v4 | Общий доступ многим ВМ, POSIX-семантика | Общие тома приложений, медиа-библиотеки, профильные данные |

### Классы хранения Object Storage

**Standard** — базовая стоимость, мгновенный доступ (активные данные). **Infrequent Access** — ниже стоимость, редкий доступ (бэкапы). **Cold Storage** — минимальная стоимость, доступ за часы (архивы).

### Типы дисков Block Storage

**network-ssd** — до 10 000 IOPS, базы данных. **network-ssd-nonreplicated** — до 50 000 IOPS, критичные к задержкам БД. **network-hdd** — до 200 IOPS, файловые серверы, архивы. **network-ssd-readonly** — до 20 000 IOPS, реплики БД, статические данные.

Подробнее о характеристиках и лимитах — [Storage concepts](./storage_concepts.md).

---

## Практические сценарии

Создание бакетов и загрузка объектов, версионирование, lifecycle-политики, настройка статических сайтов — [Storage practical scenarios](./storage_practical_scenarios.md#object-storage-создание-бакета-и-загрузка).

Создание и подключение дисков, снапшоты, монтирование File Storage, бэкапы Managed DB, интеграция с CI/CD — [Storage practical scenarios](./storage_practical_scenarios.md#block-storage-создание-и-подключение-диска).

---

## Дополнительная информация

Интеграции с [Docker](../../Docker/docker_overview.md) (хранение образов), [Kubernetes](../../Kubernetes/) (Persistent Volumes из Block/File Storage), [Terraform](../../Concepts/iac_overview.md) (декларативное управление хранилищами) — в [Storage advanced topics](./storage_advanced_topics.md).

Безопасность: IAM-политики для доступа к бакетам и дискам, шифрование SSE-S3/SSE-KMS для Object Storage, [Security Groups](../VPC.md#security-groups) для сетевого доступа к File Storage, приватный доступ через VPC без выхода в интернет.

Best practices: lifecycle-политики для экономии, версионирование для критичных данных, снапшоты перед обновлениями, multipart upload для файлов >100 МБ.

Диски для ВМ — [Compute Cloud](../Compute-Cloud.md#типы-дисков), бэкапы БД — [Managed Databases](../Managed-Databases.md#бэкапы-и-восстановление), управление артефактами — [CI/CD artifact management](../../CI-CD/artifact_management.md).
