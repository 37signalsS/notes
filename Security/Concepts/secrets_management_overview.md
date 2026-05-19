# Secrets Management Overview

## Definitions

**Secrets Management** — процесс безопасного хранения, контроля доступа, аудита и ротации чувствительных данных: паролей, API-ключей, токенов, TLS-сертификатов, SSH-ключей.

**Секрет** — любые данные, компрометация которых нарушает конфиденциальность, целостность или доступность системы.

**Ключевая задача:** исключить хранение секретов в открытом виде в коде, Git, логах, конфигурационных файлах.

## Basic Concepts

### Стратегии управления секретами

| Стратегия | Описание | Применение |
|-----------|----------|------------|
| **Централизованное хранилище** | Единое защищённое место (Vault, AWS Secrets Manager) | Крупные проекты, production |
| **Шифрование в Git (GitOps)** | Секреты шифруются, хранятся в Git рядом с кодом | GitOps-пайплайны |
| **Нативные решения платформы** | Встроенные средства (Kubernetes Secrets, Docker Secrets) | Среды с ограниченными требованиями |
| **Переменные окружения CI/CD** | Секреты управляются CI/CD-системой | Small projects, CI/CD-стадии |

### Принципы безопасности

- **Шифрование на rest:** секреты шифруются при хранении (KMS, PGP, age)
- **Минимальные привилегии:** доступ только для необходимых сервисов/пользователей
- **Ротация:** периодическая смена секретов без простоя систем
- **Аудит:** логирование всех операций чтения/записи/удаления
- **Никогда в логах:** секрет не должен попадать в stdout/stderr, логи, метрики

### Сравнение подходов

| Критерий | CI/CD Variables | SOPS | HashiCorp Vault | K8s Secrets (с шифрованием) |
| :--- | :--- | :--- | :--- | :--- |
| **Простота** | Высокая | Средняя | Низкая | Средняя |
| **Безопасность** | Средняя | Высокая | Очень высокая | Высокая |
| **Централизация** | Низкая | Средняя (репозиторий) | Высокая | Средняя (кластер) |
| **GitOps** | Нет | Да | Частично | Да (Sealed Secrets / SOPS) |
| **Динамические секреты** | Нет | Нет | Да | Нет |
| **Аудит** | Ограниченный | Через Git | Детальный | Через K8s audit / Git |

## Practical Scenarios

### HashiCorp Vault — централизованное управление

SSoT: [Vault overview](../../Vault/overview.md)

Для масштабных и зрелых проектов. Обеспечивает хранениеение, аудит, динамическую генерацию и ротацию секретов.

```bash
# Записать секрет
vault kv put secret/db password="SuperSecret123"

# Прочитать секрет
vault kv get secret/db

# Динамический секрет (PostgreSQL)
vault write database/creds/readonly
```

Интеграции: [Vault + Docker](../../Vault/guides/vault_docker_integration.md), [Vault + ArgoCD](../../GitOps/ArgoCD/argocd_vault_integration.md), [Vault + Nomad](../../Nomad/practical_scenarios.md#секреты-через-vault).

### Kubernetes Secrets — нативный подход

SSoT: [Kubernetes Secrets](../../Kubernetes/Base/secrets/secrets_basics.md)

Ресурс `Secret` хранит данные в base64 в etcd — **по умолчанию не шифруется**. Требуется включение [EncryptionConfiguration](../../Kubernetes/Base/secrets/security.md) или внешнее шифрование.

**Инструменты шифрования для Git:**

- **[Sealed Secrets](../../Kubernetes/Security/sealed_secrets_overview.md)** — шифрует так, что расшифровать может только контроллер в кластере
- **[SOPS](../Tools/sops_overview.md)** — шифрование файлов через KMS, PGP, age
- **[External Secrets Operator](../../Kubernetes/Base/secrets/external_managers.md)** — синхронизация из Vault, AWS Secrets Manager, GCP Secret Manager

### SOPS + GitOps

SSoT: [SOPS overview](../Tools/sops_overview.md), [GitOps Secrets](../../GitOps/secrets_encryption.md)

Шифрование значений (не ключей) в YAML/JSON/ENV-файлах. Ключи шифрования — в KMS, PGP, age, HCVault. Файлы коммитятся в Git в зашифрованном виде.

```bash
# Шифрование файла
sops --encrypt --age age1... secret.yaml > secret.enc.yaml

# Расшифровка
sops --decrypt secret.enc.yaml
```

### Переменные окружения в CI/CD

SSoT: [CI/CD Secrets Management](../../CI-CD/DevSecOps/secrets_management.md)

Секреты хранятся в настройках CI/CD (GitLab CI Variables, GitHub Secrets), передаются в пайплайн как env vars. Подходит для токенов деплоя, credentials registry, SSH-ключей.

**Ограничения:** нет динамической генерации, ограниченный аудит, сложная ротация без прерывания пайплайна.

### Docker Secrets

SSoT: [Docker Secrets Management](../../Docker/Docker_security/secrets_management.md)

Для Docker Swarm и Docker Compose. Секреты монтируются в `/run/secrets/` внутри контейнера, не хранятся в image.

### Паттерн доставки секретов в K8s-приложения

SSoT: [Application Secrets Management](../../Kubernetes/Security/application_secrets_management.md)

InitContainer читает секреты из внешнего хранилища → записывает в shared emptyDir volume → приложение читает из volume (tmpfs).

## Additional Information

### Динамические секреты (Vault)

Vault генерирует временные credentials по запросу (БД, AWS, RabbitMQ и др.). После истечения TTL — автоматический отзыв. Преимущества:

- Уникальные credentials на каждый запрос
- Автоматическая ротация и отзыв
- Минимизация blast radius при компрометации

Примеры: [динамические секреты PostgreSQL](../../Vault/concepts.md#движки-секретов-secret-engines), [AWS IAM credentials](../../Vault/concepts.md).

### Рекомендации по выбору инструмента

| Масштаб | Рекомендация |
|---------|-------------|
| **Small project / pet-project** | CI/CD Variables (GitLab CI, GitHub Actions) |
| **GitOps-команда** | SOPS + age/PGP, хранение в Git |
| **Kubernetes-кластер (без внешнего хранилища)** | Sealed Secrets или SOPS + EncryptionConfiguration |
| **Enterprise / production** | HashiCorp Vault + динамические секреты + аудит |
| **Multi-cloud** | Vault или External Secrets Operator (синхронизация из нескольких облачных KMS) |

### Связанные концепции

- [CI/CD Secrets Management](../../CI-CD/DevSecOps/secrets_management.md) — секреты в пайплайнах
- [Docker Secrets Management](../../Docker/Docker_security/secrets_management.md) — секреты в контейнерах
- [GitOps Secrets Encryption](../../GitOps/secrets_encryption.md) — SOPS, Sealed Secrets, Vault, External Secrets
- [Kubernetes Secrets](../../Kubernetes/Base/secrets/secrets_basics.md) — создание, хранение, безопасность
- [Vault overview](../../Vault/overview.md) — централизованное управление секретами
- [Zero Trust к управлению секретами](../../Vault/zero_trust.md) — подход Zero Trust
