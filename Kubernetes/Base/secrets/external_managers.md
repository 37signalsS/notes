# Внешние системы управления секретами

## Определения

**External Secret Managers** — внешние хранилища для управления секретами, интегрированные с Kubernetes. Это "золотой стандарт" для production-окружений.

> Преимущество: Secret никогда не хранятся в etcd. Подробнее о проблемах etcd см. [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Принцип работы

Внешние менеджеры решают две ключевые проблемы нативных Secret:

1. **Безопасность хранения** — Secret не хранятся в etcd в открытом виде
2. **Жизненный цикл** — автоматическая ротация, аудит, централизованное управление

### Подходы к интеграции

| Подход | Хранение в Git | Требует внешнее ПО | Сложность | Secret в etcd |
| :--- | :---: | :---: | :---: | :---: |
| **Sealed Secrets** | Да (зашифрованные) | Контроллер | Низкая | Да (расшифрованные) |
| **External Secrets Operator (ESO)** | Нет | Оператор + хранилище | Средняя | Да (синхронизированные) |
| **Secrets Store CSI Driver** | Нет | Драйвер + провайдер | Средняя | Нет |
| **[SOPS](../../../Security/Tools/sops_overview.md)** | Да (зашифрованные) | Ключи (PGP/age/KMS) | Низкая | Да (расшифрованные) |

### Преимущества External Secret Managers

- **Улучшенная безопасность** — Secret никогда не хранятся в etcd (CSI Driver) или хранятся зашифрованными (Sealed Secrets)
- **Централизованное управление** — единое управление секретами across кластеров
- **Автоматическая ротация** — внешние хранилища предлагают автоматическую ротацию
- **Аудит** — централизованный аудит доступа к секретам

## Практические сценарии

### External Secrets Operator (ESO)

1. Установите оператор в кластере
2. Создайте ресурс `ExternalSecret` с описанием, какой секрет откуда получить
3. Оператор аутентифицируется во внешнем хранилище и создаёт нативный Kubernetes Secret
4. Приложение использует Secret как обычно

**Примеры провайдеров:** HashiCorp Vault, AWS Secrets Manager, Google Cloud Secret Manager, Azure Key Vault

> Подробнее об интеграции Vault через CSI Driver см. [Интеграция Vault с Kubernetes](../../../CI-CD/GitLab_CI/Tutorials/vault_kubernetes_integration.md)

### Sealed Secrets

Решает проблему хранения Secret в Git.

1. Установите контроллер Sealed Secrets с парой ключей
2. Используйте `kubeseal` с публичным ключом для шифрования Secret
3. SealedSecret безопасно коммитить в Git
4. Контроллер расшифровывает и создаёт нативный Secret

> Подробнее см. [Sealed Secrets (Security)](../../Security/sealed_secrets_overview.md)

### Secrets Store CSI Driver

Монтирует внешние секреты как тома, не сохраняя в etcd:

1. Установите драйвер и провайдер (Vault Provider, Azure Provider, GCP Provider)
2. Создайте ресурс `SecretProviderClass` с описанием секретов
3. В поде монтируется том типа `secrets-store.csi.k8s.io`
4. CSI Driver извлекает данные из внешнего хранилища и монтирует как файлы
5. Секреты могут быть автоматически обновлены (rotation) без перезапуска пода

**Преимущества перед ESO:**

- Секреты не хранятся в etcd даже в зашифрованном виде
- Автоматическая ротация секретов без перезапуска подов
- Нативная интеграция через стандартный CSI-интерфейс

**Недостатки:**

- Секреты доступны только как файлы (не как environment variables напрямую)
- Требует установки CSI-компонентов на каждый узел кластера

> **Подробно:** [CSI Drivers Comparison](../../Storage/CSI/csi_drivers_comparison.md), [Интеграция Vault с Kubernetes](../../../CI-CD/GitLab_CI/Tutorials/vault_kubernetes_integration.md)

## Дополнительная информация

### Связанные темы

[Основы Secret](secrets_basics.md), [Хранение в etcd](etcd_storage.md), [Безопасность Secret](security.md), [Использование Secret](using_secrets.md), [Sealed Secrets](../../Security/sealed_secrets_overview.md), [CSI Drivers](../../Storage/CSI/csi_drivers_comparison.md).
