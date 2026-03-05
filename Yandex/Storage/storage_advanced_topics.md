# Yandex Storage: Дополнительные темы

## 1. Интеграции

### Docker

- **[Docker overview](../../Docker/docker_overview.md)** — хранение образов в Object Storage

### Kubernetes

- **[Kubernetes](../../Kubernetes/)** — Persistent Volumes из Block/File Storage

### Terraform

- **[IaC overview](../../Concepts/iac_overview.md)** — декларативное управление хранилищами

## 2. Безопасность

| Механизм | Описание |
| :--- | :--- |
| **IAM-политики** | Доступ к бакетам и дискам |
| **Шифрование** | SSE-S3, SSE-KMS для Object Storage |
| **Security Groups** | Сетевой доступ к File Storage |
| **Приватный доступ** | Через VPC без выхода в интернет |

## 3. Best Practices

### Object Storage

- Используйте lifecycle-политики для экономии
- Включайте версионирование для критичных данных
- Применяйте префиксы для организации объектов
- Используйте multipart upload для файлов >100 МБ

### Block Storage

- Делайте снапшоты перед обновлениями
- Используйте SSD для БД и latency-критичных приложений
- Монтируйте диски через /etc/fstab для авто-подключения

### File Storage

- Используйте для общих данных между ВМ
- Настраивайте backup через снапшоты
- Мониторьте использование места

## 4. Актуальная информация (2025–2026)

- **Object Storage:** добавлен класс Cold Storage (Q4 2025)
- **Block Storage:** новые типы network-ssd-readonly (Q3 2025)
- **Лимиты:** увеличены до 100 бакетов на каталог

## Связанные документы

- **[Основные концепции](./storage_concepts.md)** — определения и типы хранилищ
- **[Практические сценарии](./storage_practical_scenarios.md)** — создание бакетов, дисков, монтирование
- **[Compute Cloud](../Compute-Cloud.md)** — диски для ВМ
- **[Managed Databases](../Managed-Databases.md)** — бэкапы БД
- **[CI/CD](../../CI-CD/artifact_management.md)** — управление артефактами
- **[Docker](../../Docker/docker_overview.md)** — хранение образов
- **[Kubernetes](../../Kubernetes/)** — Persistent Volumes
- **[Terraform](../../Concepts/iac_overview.md)** — инфраструктура как код
