# Artifact Signing

## Definitions

* **Artifact Signing:** Криптографический процесс обеспечения проверяемой аутентичности (происхождение от доверенного субъекта) и целостности (отсутствие изменений) программных артефактов: контейнерные образы, бинарные файлы, SBOM, аттестации, Git-теги.
* **Authenticity:** Гарантия создания артефакта доверенным источником (разработчик, CI/CD-система).
* **Integrity:** Гарантия неизменности артефакта с момента подписания.
* **Keyless Signing:** Модель подписи с использованием короткоживущих OIDC-сертификатов вместо долгоживущих ключей. Запись о подписи публикуется в публичный неизменяемый лог (Rekor).

## Basic Concepts

Подпись артефактов — один из столпов [безопасности цепочки поставок](./overview.md). Позволяет выстраивать политики допуска, блокируя развёртывание неподписанных или подделанных артефактов.

### Модели подписи

| Модель | Управление ключами | Сценарий применения |
| :--- | :--- | :--- |
| **Keyless (OIDC/Sigstore)** | Короткоживущие сертификаты, выдаваемые Fulcio на основе OIDC-идентичности | CI/CD-пайплайны (рекомендуется) |
| **GPG/PKI** | Долгоживущие ключи, управляемые вручную | Git-теги, файлы, legacy-системы |

### Инструменты

| Инструмент | Область применения | Модель ключей | Ссылка |
| :--- | :--- | :--- | :--- |
| **Cosign (Sigstore)** | Контейнеры, файлы, аттестации, Helm-чарты | Keyless (OIDC) или ключи | [Sigstore](../Tools/sigstore.md) |
| **Notary v2 / notation** | Контейнерные образы | PKI/сертификаты | — |
| **GPG / Minisign** | Файлы, Git-теги | Управляемые вручную ключи | [GPG](../../Linux/Security/Tools/gpg_and_openpgp.md) |

### Архитектура Sigstore (Keyless)

Основной современный стек для CI/CD — [Sigstore](../Tools/sigstore.md):

* **Fulcio** — выдаёт короткоживущие сертификаты на основе OIDC (GitHub, Google, Microsoft).
* **Rekor** — публичный неизменяемый лог записей о подписях (аудит и прозрачность).
* **Cosign** — CLI-утилита для подписи и верификации OCI-артефактов.

## Practical Scenarios

### Подпись контейнерного образа в CI/CD (Keyless)

Рекомендуемый сценарий для автоматизированных систем — не требует управления статическими секретами.

```bash
# 1. Подписание образа с использованием OIDC-токена CI/CD
cosign sign --yes ghcr.io/my-org/my-app:v1.0.0

# 2. Верификация с проверкой OIDC-идентичности подписавшего
cosign verify \
  --certificate-identity-regexp "https://github.com/my-org/my-repo/.github/workflows/release.yml" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/my-org/my-app:v1.0.0
```

### Подпись релизного Git-тега через GPG

```bash
# Создание подписанного тега
git tag -s v1.0.0 -m "Release v1.0.0"

# Верификация подписи
git verify-tag v1.0.0
```

### Политика допуска в Kubernetes (Kyverno)

Политика блокирует создание подов с образами, не подписанными доверенным CI/CD-пайплайном:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
  - name: verify-cosign
    match:
      any:
      - resources:
          kinds: ["Pod"]
    verifyImages:
    - imageReferences: "ghcr.io/my-org/my-app:*"
      attestors:
      - entries:
        - keyless:
            issuer: "https://token.actions.githubusercontent.com"
            subjectRegExp: "https://github.com/my-org/my-repo/.github/workflows/release.yml@refs/heads/main"
```

### Подпись и верификация файлов

```bash
# Подпись файла (с ключом)
cosign sign-blob --key cosign.key myfile.tar.gz > myfile.sig

# Верификация подписи файла
cosign verify-blob --key cosign.pub --signature myfile.sig myfile.tar.gz
```

## Additional Information

### Рекомендации

* **Предпочитайте Keyless для CI/CD:** Модель OIDC устраняет риски утечки долгоживущих ключей и упрощает ротацию.
* **Подписывайте все артефакты:** Образы, SBOM, SLSA-аттестации, Helm-чарты, бинарные релизы.
* **Верифицируйте на каждом этапе:** Проверка подписи — обязательный шаг в CI/CD перед развёртыванием и на стороне кластера через admission-политики.
* **Изолируйте среду подписи:** Процесс должен выполняться в защищённой, минимальной среде CI/CD с минимальными привилегиями.
* **Используйте дайджесты:** Для production-развёртывания фиксируйте образы по дайджесту (`image@sha256:...`) в дополнение к подписи.

### Связанные документы

* [Sigstore: Keyless-подпись](../Tools/sigstore.md) — инструментарий для подписи OCI-артефактов
* [Подпись Docker-образов](../../Docker/Docker_security/image_signature_and_verification.md) — специфика контейнерных образов
* [Контроль целостности сборки](./build_integrity.md) — SLSA, provenance, reproducible builds
* [GPG и OpenPGP](../../Linux/Security/Tools/gpg_and_openpgp.md) — классическая модель подписи
