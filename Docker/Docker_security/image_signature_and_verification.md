# Подписание и верификация Docker-образов

## Определения

**Подписание и верификация образов** — криптографический процесс гарантии подлинности (источник) и целостности (отсутствие изменений) Docker-образа. Часть процесса **[подписания артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)**.

- **Целостность (Integrity)**: Сверка дайджестов (`sha256`) слоев и манифеста.
- **Подлинность (Authenticity)**: Цифровые подписи, подтверждающие издателя.
- **Аттестация (Attestation)**: Подписанные метаданные (provenance, **[SBOM](./docker_sbom.md)**, сканирование).

## Базовые концепции

### 1. Digest Pinning (целостность)

Использование полного дайджеста (`image@sha256:...`) вместо тега (`image:latest`) — базовая практика целостности. Docker/containerd проверяют дайджесты слоев по умолчанию.

### 2. Цифровые подписи (подлинность)

Подписи позволяют настраивать политики запуска только доверенных образов.

| Технология | Описание | Статус |
| :--- | :--- | :--- |
| **Sigstore/Cosign** | Стандарт для OCI-артефактов, работает на основе дайджестов (`digest`). Может подписывать как сам образ, так и аттестации (отчеты сканеров, SBOM). Поддерживается интеграция с реестрами (например, **Harbor** может запрещать pull неподписанных образов). **[Подробнее](../../Security/Tools/sigstore.md)** | **Рекомендуемый** |
| **Notary v1 / DCT** | Механизм Docker Content Trust (DCT). В отличие от Cosign, позволяет жестко привязывать подпись к конкретному тегу (чтобы тег нельзя было переставить на другой дайджест). | Встроено в Docker, но реже используется для новых систем |
| **Simple Signing (GPG)**| Механизм для Podman/Skopeo | Специфичен |

## Практические сценарии

### 1. Фиксация по дайджесту (гарантия целостности)

```bash
# 1. Получить дайджест для образа
docker inspect alpine:latest --format '{{index .RepoDigests 0}}'
# Вывод: docker.io/library/alpine@sha256:21a3deaa...

# 2. Использовать дайджест в production
# image: alpine@sha256:21a3deaa...
```

### 2. Проверка подписи с помощью Cosign и Sigstore

**[Cosign](../../Security/Tools/sigstore.md)** — это основной инструмент для подписания и проверки OCI-артефактов в экосистеме Sigstore.

```bash
# Подписать образ (например, в CI/CD)
cosign sign --key my-key.pem my-registry/my-app:1.0

# Проверить подпись образа перед запуском
cosign verify --key my-key.pub my-registry/my-app:1.0
```

### 3. Создание аттестаций о происхождении (SLSA Provenance)

BuildKit может автоматически генерировать и прикреплять к образу аттестации, соответствующие спецификации **[SLSA](https://slsa.dev/)**, что позволяет отследить всю цепочку сборки.

```bash
docker buildx build \
  --tag my-registry/my-app:1.0 \
  --provenance=true \
  --sbom=true \
  .
```

Аттестации `provenance` и `sbom` будут подписаны и прикреплены к манифесту образа.

### 4. Принудительная проверка в Podman (`policy.json`)

Инструменты `podman` и `skopeo` используют системный файл `/etc/containers/policy.json` для определения политик доверия.

```json
// /etc/containers/policy.json
{
  "default": [{"type": "insecureAcceptAnything"}],
  "transports": {
    "docker": {
      "my-registry.example.com": [
        {
          "type": "sigstoreSigned",
          "keyPath": "/etc/containers/cosign.pub"
        }
      ]
    }
  }
}
```

При такой политике `podman pull my-registry.example.com/app` автоматически провалится, если образ не подписан ключом `cosign.pub`.

## Дополнительная информация

**Docker Content Trust (Notary v1):** Активируется через `DOCKER_CONTENT_TRUST=1`. Проверяет подписи для `pull`/`push`/`build`. **Не рекомендуется** для новых систем в пользу Sigstore/Cosign (сложное управление ключами, нет поддержки аттестаций).

**Сводка:** **Целостность (Digest)** — встроена в Docker, защищает от изменений. **Подлинность (Signature)** — требует политик (Kubernetes admission, `policy.json`). **Происхождение (Attestation)** — подписанные метаданные сборки.

**Связанные документы:** **[SBOM](./docker_sbom.md)**, **[сканирование уязвимостей](./vulnerability_scanning.md)**, **[Sigstore](../../Security/Tools/sigstore.md)**, **[подписание артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)**, **[безопасность публичных реестров](../Docker_registries/public_registry_security.md)**.
