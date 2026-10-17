# Подписание и верификация Docker-образов

**Актуально для:** Docker Engine 29.x, Cosign v3.1.3, Notation v1.3.2, Harbor v2.15+, Kubernetes 1.29+, Kyverno 1.19+ (2026)

Данный документ описывает методы обеспечения безопасности цепочки поставок (**Supply Chain Security**) для контейнерных образов через механизмы контроля целостности и подтверждения подлинности.

## Определения

**Подписание и верификация образов (Image Signing and Verification)** — криптографический процесс, гарантирующий, что образ был создан доверенным источником и не подвергался изменениям с момента подписания.

**Целостность (Integrity)** — гарантия неизменности содержимого образа. Любое изменение в слоях или конфигурации приведет к несовпадению дайджеста.

**Подлинность (Authenticity)** — подтверждение того, что образ опубликован именно тем субъектом (человеком или системой), который владеет ключом подписи.

**Аттестация (Attestation)** — подписанные метаданные, описывающие артефакт. Основные типы: **Provenance** (кто и как собрал) и **SBOM** (из чего состоит).

**OCI 1.1 Referrers** — стандарт связи артефактов (подписей, SBOM) с образом через API реестра без использования тегов-пустышек.

**VSA (Verification Summary Attestation)** — агрегированная аттестация, подтверждающая, что образ прошёл проверку подписи, SLSA-уровня и наличия валидного SBOM. Используется Admission Controllers (Kyverno, OPA Gatekeeper) для принятия решения об развёртывании.

## Предварительные требования

- **Docker Engine 29.x** — для команд `docker buildx`, `docker inspect` и работы с реестром.
- **Cosign v3.1.3** — для keyless-подписи образов через OIDC. В 2026 году Cosign по умолчанию использует OCI 1.1 Referrers и поддерживает PQC-алгоритмы (ML-DSA).
- **Notation v1.3.2** — для корпоративной подписи через X.509 PKI и HSM.
- **Harbor v2.15+** — реестр с поддержкой OCI 1.1 Referrers API для хранения подписей без тегов-пустышек.
- **Kubernetes 1.29+** с **Kyverno 1.19+** или **OPA Gatekeeper** — для принудительной проверки подписей на этапе deployment.
- **OIDC-провайдер** — GitHub Actions, GitLab CI, Google Workload Identity или корпоративный IdP для keyless-подписи (Fulcio).
- **Для self-hosted:** внутренние Fulcio и Rekor (или прямой доступ к публичным Sigstore) с настроенным DNS и TLS.

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

### 4. Жизненный цикл подписи и верификации

Эффективное управление подписью требует последовательного применения на всех этапах:

1. **Сборка и подпись в CI/CD:** Cosign или Notation подписывают образ перед push в реестр.
2. **Хранение в реестре:** Подпись и аттестации (SBOM, Provenance) хранятся через OCI 1.1 Referrers API.
3. **Верификация в CI/CD:** `cosign verify` проверяет подпись и identity перед допуском образа к следующей стадии.
4. **Admission Control в Kubernetes:** Kyverno/OPA Gatekeeper проверяют подпись и VSA-аттестацию перед запуском пода.

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

## Устранение неполадок

### Ошибка: `cosign verify` — "no signatures found" или "no matching signatures"

- **Причина:** Реестр не поддерживает OCI 1.1 Referrers API, либо подпись хранится как `.sig`-тег (устаревший формат).
- **Решение:** Используйте Harbor v2.15+ или GHCR/ECR с поддержкой Referrers. Проверьте подпись через `cosign verify-attestation` или `crane manifest`. Если реестр устарел, подписывайте с флагом `--legacy-include-operations`.

### Ошибка: Keyless-подпись в CI/CD — "OIDC token not available" / "identity token not found"

- **Причина:** GitHub Actions workflow не имеет прав `id-token: write`, либо self-hosted GitLab Runner не настроен для выдачи OIDC-токена.
- **Решение:** Добавьте в workflow:
  ```yaml
  permissions:
    id-token: write
    contents: read
    packages: write
  ```
  Для self-hosted GitLab Runner — настройте `COSIGN_PASSWORD`, `--token` или внутренний Fulcio с JWT-авторизацией. См. **[артефакт подписи в GitLab CI](../../CI-CD/DevSecOps/secure_release_pipeline.md)**.

### Ошибка: `certificate-identity mismatch` при `cosign verify`

- **Причина:** Переданное в `--certificate-identity` значение не совпадает с identity в сертификате Fulcio.
- **Решение:** Сначала выполните `cosign verify` без фильтров, чтобы увидеть реальный identity, затем уточните флаг:
  ```bash
  cosign verify --key cosign.pub my-registry.com/app:v1  # посмотреть identity
  cosign verify --certificate-identity "<actual-identity>" --certificate-oidc-issuer "<issuer>" my-registry.com/app:v1
  ```

### Ошибка: Kyverno imageVerify не блокирует неподписанные образы

- **Причина:** Политика имеет `background: false`, но `match.kinds` не включает нужные типы ресурсов; либо `imageReferences` не охватывает registry URL.
- **Решение:** Убедитесь, что `imageReferences` использует wildcard (`my-registry.com/*`) и `validateFailureAction: Enforce`. Проверьте через `kubectl describe clusterpolicy check-image-signature` — счётчик `ImageVerificationFailures` должен расти.

### Предупреждение: "Docker Content Trust / Notary v1 is deprecated"

- **Причина:** Используется устаревший механизм Docker Content Trust (Notary v1), который не поддерживает OCI 1.1 Referrers и имеет проблемы с масштабируемостью.
- **Решение:** Мигрируйте на **Cosign** или **Notation** с OCI 1.1 Referrers. Отключите DCT: `export DOCKER_CONTENT_TRUST=0`. Подробнее: **[Sigstore и Cosign](../../Security/Tools/sigstore.md)**.

### Ошибка: `cosign verify-attestation` — "predicate type mismatch"

- **Причина:** Аттестация хранится в формате CycloneDX, но `--type spdx` при верификации.
- **Решение:** Укажите тип, совпадающий с тем, что использовано при `cosign attest`:
  ```bash
  cosign verify-attestation --type cyclonedx --key cosign.pub my-registry.com/app:v1
  ```

### Ошибка: Harbor не отображает подпись в UI

- **Причина:** Образ подписан с использованием `.sig`-тегов, а Harbor ожидает подпись через OCI 1.1 Referrers.
- **Решение:** Переподпишите образ с `--type sls://cosign.sig` (автоматически в Cosign v3.1.3) или используйте Notation с OCI 1.1. См. **[Harbor: подпись образа с помощью Cosign](../../Docker/Docker_registries/Harbor/usage.md#сценарий-4-подпись-образа-с-помощью-cosign)**.

## Лучшие практики

1.  **Фиксация по дайджесту:** Используйте `image@sha256:...` вместо тегов (`:latest`, `:1.0`) в production. Теги могут быть переназначены, что приводит к запуску неаудированного образа.

2.  **Keyless-подпись (Cosign):** Используйте Cosign без ключей через OIDC — эфемерные ключи устраняют риск кражи долгоживущих секретов. Сертификаты Fulcio живут 10–20 минут и автоматически ротируются.

3.  **Проверка identity, а не только подписи:** Не достаточно проверить, что подпись существует. Всегда используйте `--certificate-identity` и `--certificate-oidc-issuer` для подтверждения, **кто** подписал образ. Это предотвращает атаки типа "злоумышленник получил ключ и подписал под себя".

4.  **OCI 1.1 Referrers:** Используйте Harbor v2.15+ или GHCR для хранения подписей через Referrers API. Не используйте устаревшие `.sig`-теги — они затрудняют GC и создают "мусор" в реестре.

5.  **Короткоживущие сертификаты:** Fulcio выдаёт сертификаты на 10–20 минут. Не пытайтесь увеличить срок жизни — это ослабляет безопасность. Используйте Rekor для долгосрочного аудита (SET — Signed Entry Timestamp).

6.  **Фиксация версий инструментов в CI:** Никогда не используйте `latest` или `v3` для Cosign/Notation в CI/CD. Фиксируйте конкретную версию (`cosign-installer@v3.5.0` или `go install github.com/sigstore/cosign/v2/cmd/cosign@v3.5.1`) и проверяйте SHA256-контрольные суммы. **Supply Chain Integrity:** В 2026 году была зафиксирована компрометация цепочки поставок Sigstore ([CVE-2026-33634](https://nvd.nist.gov/vuln/detail/CVE-2026-33634)) — компрометированы теги v0.69.4 и связанные GitHub Actions. Та же угроза применима к Cosign: скачивайте только из официальных источников и проверяйте подписи артефактов.

7.  **VSA-ориентированный admission control:** Не просто проверяйте подпись — требуйте VSA-аттестацию (Verification Summary Attestation), которая агрегирует результаты проверки подписи, SLSA-уровня и SBOM. Kyverno с `verifyImages` и `verifyImages.verifyDigest` обеспечивает это на уровне Kubernetes.

8.  **Аттестации SBOM:** Привязывайте SBOM (CycloneDX или SPDX) к образу через `cosign attest`. Блокируйте deployment образов без валидного SBOM — это обеспечивает traceability всех компонентов. См. **[Docker SBOM](./docker_sbom.md)**.

9.  **Не использовать Docker Content Trust:** DCT (Notary v1) устарел, не поддерживает OCI 1.1 и имеет проблемы с масштабируемостью. Используйте Cosign или Notation.

10. **Автоматизация в CI/CD:** Интегрируйте подпись и верификацию в пайплайн с security gates. Прерывание сборки при отсутствии подписи — эффективнее post-hoc аудита. См. **[Безопасный релиз в CI/CD](../../CI-CD/DevSecOps/secure_release_pipeline.md)**.

## Граничные случаи и ограничения

1. **Мульти-архитектурные образы (multi-arch):** При подписании multi-arch образа (manifest list) подпись привязывается к каждому child-образу по отдельности. Убедитесь, что все архитектурные варианты подписаны. `cosign verify` проверяет только тот manifest, который выбран клиентом (обычно amd64).

2. **Air-gapped / офлайн-реестры:** В изолированных сетях публичный Sigstore недоступен. Используйте self-hosted Fulcio и Rekor:
   ```bash
   cosign sign --yes \
     --fulcio-url https://fulcio.internal \
     --rekor-url https://rekor.internal \
     harbor.internal/my-app:v1
   ```
   Для верификации аналогично: `--fulcio-url` и `--rekor-url`.

3. **Самоподписанные реестры (self-signed TLS):** Если реестр использует self-signed сертификат, Cosign может отказаться его подписывать. Добавьте сертификат в системное хранилище или используйте `SSL_CERT_FILE=/path/to/ca.crt`.

4. **PQC-подпись (ML-DSA):** ML-DSA не поддерживается в стабильных релизах Cosign на 2026 год. Для подготовки к постквантовой миграции используйте гибридную подпись (ECDSA через Fulcio + ML-DSA через KMS с аннотациями). Обратите внимание: не все реестры и Policy Controllers поддерживают PQC-подпись — проверьте совместимость перед внедрением в production.

5. **Кросс-реестр промоция (image promotion):** При promotion образа из staging в production (staging-registry/app:v1 → prod-registry/app:v1) подпись не переносится автоматически, так как дайджест может измениться. Решение: либо переподписывайте в prod-реестре, либо используйте `cosign copy` для переноса подписей. См. **[promotion in GitLab CI](../../CI-CD/GitLab_CI/Tutorials/container_registry_management.md)**.

## Дополнительная информация

**Связанные документы:**
- **[Sigstore и Cosign](../../Security/Tools/sigstore.md)** — глубокий разбор ключевых компонентов (Fulcio, Rekor, keyless, PQC).
- **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)** — общая методология, Notation, VSA, OCI 1.1 Referrers.
- **[Docker SBOM](./docker_sbom.md)** — генерация аттестаций состава ПО (SBOM, Provenance).
- **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — теория SCA и SBOM.

**Глубокое изучение:**
- **[Cosign keyless signing](../../Security/Tools/sigstore.md#keyless-подпись-в-github-actions-2026)** — подпись через OIDC. В Docker: `cosign sign --yes image:tag` через токен GitHub Actions/GitLab CI, проверка через `--certificate-identity` и `--certificate-oidc-issuer`.
- **[Notation (OCI)](../../Security/Supply_Chain_Security/artifact_signing.md)** — PKI-based подпись. В Docker: `notation sign --key ca.key image:tag`, проверка через `notation verify`, интеграция с Harbor v2.15+.
- **[Kyverno admission](../../Kubernetes/Security/kyverno/Scenarios/security_policies.md)** — блокировка неподписанных. В Docker/K8s: `imageVerify` policy для проверки Cosign/Notation перед запуском Pod.
- **[Harbor: подпись образа с помощью Cosign](../../Docker/Docker_registries/Harbor/usage.md#сценарий-4-подпись-образа-с-помощью-cosign)** — практический сценарий подписи и верификации в Harbor.
- **[Безопасный релиз в CI/CD](../../CI-CD/DevSecOps/secure_release_pipeline.md)** — Cosign + SBOM attestation + VEX в GitLab CI/CD pipeline.

**Инструменты:** `Cosign v3.1.3`, `Notation v1.3.2`, `crane`, `Syft v1.54+` (SBOM), `Kyverno 1.19+`.

