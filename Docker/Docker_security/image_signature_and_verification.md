# Подписание и верификация Docker-образов

Данный документ описывает методы обеспечения безопасности цепочки поставок (**Supply Chain Security**) для контейнерных образов через механизмы контроля целостности и подтверждения подлинности.

## Определения

**Подписание и верификация образов (Image Signing and Verification)** — криптографический процесс, гарантирующий, что образ был создан доверенным источником и не подвергался изменениям с момента подписания.

**Целостность (Integrity)** — гарантия неизменности содержимого образа. Любое изменение в слоях или конфигурации приведет к несовпадению дайджеста.

**Подлинность (Authenticity)** — подтверждение того, что образ опубликован именно тем субъектом (человеком или системой), который владеет ключом подписи.

**Аттестация (Attestation)** — подписанные метаданные, описывающие артефакт. Основные типы: **Provenance** (кто и как собрал) и **SBOM** (из чего состоит).

**OCI 1.1 Referrers** — стандарт связи артефактов (подписей, SBOM) с образом через API реестра без использования тегов-пустышек.

## Базовые концепции

### 1. Фиксация дайджеста (Digest Pinning)

Дайджест (например, `sha256:0cae2...`) — это неизменяемый отпечаток образа. В отличие от тегов, которые могут быть переназначены (**Mutable Tags**), дайджест гарантирует воспроизводимость среды.

- **Проблема:** Злоумышленник может подменить образ под существующим тегом (например, `nginx:latest`).
- **Решение:** Использование `nginx@sha256:...` блокирует запуск несанкционированных версий на уровне протокола Docker/OCI.

### 2. Механизмы подписания

Современная экосистема предлагает два основных подхода к управлению ключами:

| Технология | Подход | Сценарий |
| :--- | :--- | :--- |
| **Sigstore / Cosign** | Keyless (OIDC) | Идеально для CI/CD. Подпись выпускается на основе токена GitHub/GitLab, ключ не хранится. |
| **OCI Notation** | X.509 (PKI) | Корпоративные среды с жесткими требованиями к сертификатам и соответствию стандартам. |
| **Docker Content Trust** | Notary v1 | Устаревший (Legacy) механизм, сложен в поддержке и не поддерживает современные OCI-реестры. |

### 3. Инфраструктура Referrers (OCI 1.1)

Ранее подписи хранились как отдельные образы с тегом `.sig`. В спецификации **OCI 1.1** внедрен API Referrers, который позволяет "прикреплять" подписи и аттестации к основному образу. Это упрощает сборку мусора (GC) в реестре и делает связи между артефактами явными.

## Практические сценарии

### 1. Использование дайджестов (Digest Pinning)

```bash
# Получение дайджеста для образа
docker pull nginx:latest
docker inspect --format='{{index .RepoDigests 0}}' nginx:latest
# Результат: nginx@sha256:0cae2...

# Использование в Dockerfile
FROM nginx@sha256:0cae2...
```

### 2. Генерация аттестаций (Docker Buildx)

Современный BuildKit позволяет прикреплять SBOM и Provenance напрямую к манифесту образа как аттестации.

```bash
docker buildx build \
  --tag my-registry.com/app:v1 \
  --sbom=true \
  --provenance=mode=max \
  --push .
```
*Подробнее про состав компонентов:* **[Docker SBOM](./docker_sbom.md)**.

### 3. Подписание образа (Cosign Keyless)

Рекомендуемый способ для CI/CD, не требующий хранения секретных ключей. Использует OIDC-токен среды выполнения (например, GitHub Actions).

```bash
# Подписание в CI/CD (GitHub Actions автоматически предоставит токен)
cosign sign --yes my-registry.com/app:v1

# Верификация подписи
cosign verify \
  --certificate-identity "https://github.com/my-org/my-repo/.github/workflows/release.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  my-registry.com/app:v1
```
*Инструкции по установке и ключам:* **[Sigstore: Безопасность цепочки поставок](../../Security/Tools/sigstore.md)**.

### 4. Подписание через Notation (OCI Standard)

**Notation** — это CLI-инструмент от проекта Notary Project, ориентированный на использование инфраструктуры PKI (X.509 сертификаты).

1.  **Добавление ключа и сертификата:**
    ```bash
    notation cert add --type ca --store my-certs cert.pem
    ```
2.  **Подписание образа:**
    ```bash
    notation sign my-registry.com/app:v1 --key my-key
    ```
3.  **Верификация:**
    ```bash
    notation verify my-registry.com/app:v1
    ```

### 5. Верификация в кластере (Admission Control)

Ручная проверка подписей в CLI не масштабируется. В Kubernetes для автоматизации используются **Admission Controllers**.

#### Сценарий с Kyverno
Kyverno позволяет блокировать запуск подов, образы которых не проходят проверку.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-image-signature
spec:
  rules:
    - name: verify-signature
      match:
        any:
        - resources:
            kinds:
            - Pod
      verifyImages:
      - imageReferences:
        - "my-registry.com/*"
        attestations:
        - predicateType: cosign.sigstore.dev/attestation/v1
          attestor:
            entries:
            - keys:
                publicKeys: |-
                  -----BEGIN PUBLIC KEY-----
                  ...
                  -----END PUBLIC KEY-----
```

## Дополнительная информация

**Связанные документы:**
- **[Sigstore и Cosign](../../Security/Tools/sigstore.md)** — глубокий разбор инструментария.
- **[Подписание артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)** — общая методология и теория.
- **[Docker SBOM](./docker_sbom.md)** — генерация аттестаций состава ПО.
