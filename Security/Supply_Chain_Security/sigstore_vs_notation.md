# Sigstore vs Notation: сравнение и выбор

**Актуально для:** Cosign v3.1.3, Notation v1.3.2, Harbor v2.15+, Kyverno v1.19+, GitLab Runner 16.0+, OIDC (GitLab Server 15.7+, GitHub Actions)

## Определения

* **Sigstore:** Экосистема для keyless-подписи артефактов, включающая **Fulcio** (CA для эфемерных сертификатов), **Rekor** (transparency log) и **Cosign** (CLI для подписи/верификации). Использует OIDC для аутентификации CI/CD-раннеров без долгоживущих ключей.
* **Notation:** CLI-инструмент от CNCF (подпроект OCI) для подписи OCI-артефактов с использованием X.509-сертификатов. Поддерживает интеграцию с HSM, Vault и внутренними CA. Ориентирован на корпоративные среды.
* **Keyless Signing (Подпись без ключей):** Модель, при которой приватный ключ генерируется эфемерно (в памяти CI-раннера), сертификат выпускается на короткий срок (10–20 минут) через OIDC, а все события записываются в transparency log (Rekor).
* **Enterprise PKI Signing (Подпись через PKI):** Модель, при которой используется долгоживущий ключ, хранящийся в HSM или Vault. Сертификат выдаётся внутренней CA. Требует ротации ключей и ведения CRL/OCSP.
* **OCI 1.1 Referrers API:** Стандарт для связывания метаданных (подписей, SBOM) с основным артефактом через поле `subject`, а не через дополнительные теги.

## Основные концепции

### Сравнение архитектур

| Критерий | Sigstore (Cosign) | Notation |
| :--- | :--- | :--- |
| **Модель ключей** | Keyless (ephemeral) + long-lived | Long-lived (X.509 + HSM/Vault) |
| **Аутентификация** | OIDC (GitLab, GitHub, corporate IdP) | X.509 certificates / HSM |
| **Transparency Log** | Rekor (append-only ledger) | Не встроен (опционально через Rekor) |
| **Хранение подписей** | OCI 1.1 Referrers API | OCI 1.1 Referrers API |
| **Постквантовая криптография** | ML-DSA (FIPS 204) | Ограниченная поддержка |
| **Интеграция с HSM** | Ограниченная (экспериментальная) | Полная (PKCS#11) |
| **Интеграция с Vault** | Через OIDC | Нативная (Vault PKI) |
| **Admission Control** | Kyverno, OPA Gatekeeper | Kyverno, OPA Gatekeeper |
| **Стоимость инфраструктуры** | Низкая (keyless, без HSM) | Высокая (HSM, internal CA) |
| **Сложность настройки** | Низкая (keyless) / Средняя (self-hosted) | Средняя / Высокая |

### Когда выбирать Sigstore

**Идеально для:**
- CI/CD пайплайны с OIDC (GitLab, GitHub Actions, Gitea)
- Нетребовательные к комплаенсу среды
- Нужен быстрый старт без инфраструктуры HSM
- Публичные/ open-source проекты
- On-prem с self-hosted Fulcio/Rekor

**Пример:**
```bash
# Keyless подпись — нулевая инфраструктура
cosign sign --yes ghcr.io/my-org/my-app:v1.0.0
# → OIDC токен от GitLab → Fulcio → ephemeral сертификат → подпись
```

### Когда выбирать Notation

**Идеально для:**
- Корпоративные среды с внутренней PKI
- Требования к аудиту и HSM (FIPS 140-2/3)
- Закрытые реестры (Harbor, GitLab Container Registry)
- Регуляторные требования (SOC 2, ISO 27001)
- Air-gapped среды без доступа к внешнему OIDC

**Пример:**
```bash
# Подпись через внутреннюю CA и HSM (Notation v1.x: плагин для HSM)
notation sign --plugin notation-keysource-hsm --id "slot-0" harbor.internal/my-app:v1.0.0
# → Подпись через ключ в HSM, сертификат от внутренней CA
```

## Предварительные требования

### Инструменты и версии

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Cosign** | v3.1.3 | Keyless-подпись образов; OCI 1.1 Referrers |
| **Notation** | v1.3.2 | Корпоративная подпись через X.509 / HSM / internal CA |
| **Harbor** | v2.15+ | OCI-реестр с поддержкой Referrers API |
| **GitLab Server** | 15.7+ | OIDC ID-токены для keyless-подписи |
| **GitLab Runner** | 16.0+ | Передача `id_tokens` в job |
| **Kyverno** | v1.19+ | Admission control для верификации подписей |
| **HSM** | PKCS#11 3.0+ | Требуется для Notation (YubiHSM, Nitrokey, SafeNet) |

### Инфраструктурные требования

* **OIDC provider:** GitLab Server ≥ 15.7 или GitHub Actions. Необходимо настроить `id_tokens` в `.gitlab-ci.yml` с `aud: sigstore`.
* **Self-hosted Sigstore:** Fulcio (CA) и Rekor (transparency log) — отдельные сервисы в изолированной сети. Для air-gapped сред — разверните их внутри периметра.
* **Internal CA:** X.509 CA (например, HashiCorp Vault PKI) с сертификатом, добавленным в trust store Notation.
* **OIDC issuer URL:** При верификации через `cosign verify --certificate-oidc-issuer` укажите URL провайдера OIDC (например, `https://gitlab.internal/`), а не URL Fulcio.
* **HSM:** PKCS#11 модуль должен быть установлен на runner и доступен через `notation-keysource-hsm` плагин.

### Начальное состояние окружения

* Реестр Harbor развернут с включённым OCI 1.1 Referrers API.
* DNS резолвит `harbor.internal`, `fulcio.internal`, `rekor.internal`, `git.internal`.
* Для Notation: корневой сертификат internal CA уже добавлен в trust store (`notation cert add`).

## Практические сценарии

### Сценарий 1: Настройка Sigstore (keyless) для GitLab CI

```yaml
# .gitlab-ci.yml: keyless подпись через внутренний Fulcio
sign-image:
  stage: deploy
  image: alpine:3.21
  id_tokens:
    SIGSTORE_ID_TOKEN:
      aud: sigstore
  script:
    - apk add --no-cache cosign
    # Настройка переменных для self-hosted Fulcio/Rekor
    - export FULCIO_URL=https://fulcio.internal
    - export REKOR_URL=https://rekor.internal
    - export OIDC_ISSUER=https://gitlab.internal/  # URL GitLab, выдающий OIDC токен

    # Подпись с использованием OIDC токена
    # Cosign автоматически обнаруживает SIGSTORE_ID_TOKEN из id_tokens
    - cosign sign --yes \
        --fulcio-url $FULCIO_URL \
        --rekor-url $REKOR_URL \
        harbor.internal/my-app:$CI_COMMIT_SHA
    # → Подпись прикреплена через OCI 1.1 Referrers API

    # Верификация (OIDC issuer = GitLab, а не Fulcio)
    - cosign verify \
        --certificate-identity-regexp "https://gitlab.internal/my-org/my-app/-/jobs" \
        --certificate-oidc-issuer $OIDC_ISSUER \
        harbor.internal/my-app:$CI_COMMIT_SHA
    # → Verified 1 signature
```

### Сценарий 2: Настройка Notation (X.509 + HSM) для Harbor

```bash
# 1. Добавление корневого сертификата внутренней CA
notation cert add --type ca --store internal-ca /path/to/ca.pem

# 2. Просмотр trust store
notation cert list
# → TYPE    STORE           SUBJECT
# ca      internal-ca      CN=MyCorp Internal CA

# 3. Подпись образа через HSM (Notation plugin)
notation sign --plugin notation-keysource-hsm --id "my-hsm-key-id" harbor.internal/my-app:v1.0.0

# 4. Верификация с trust policy
cat > trustpolicy.json << 'EOF'
{
  "version": "1.0",
  "trustPolicies": [
    {
      "name": "harbor-internal",
      "registryScopes": ["harbor.internal/*"],
      "trustStores": ["ca:internal-ca"],
      "trustedIdentities": ["x509.subject:CN=MyCorp Internal CI Signing"]
    }
  ]
}
EOF

export NOTATION_TRUST_POLICY=trustpolicy.json
notation verify harbor.internal/my-app:v1.0.0
# → Successfully verified signature for harbor.internal/my-app:v1.0.0
```

### Сценарий 3: Гибридная конфигурация (оба инструмента)

```yaml
# CI/CD: подпись через Cosign (keyless) + Notation (internal CA)
sign-artifacts:
  stage: sign
  script:
    # Cosign: keyless для OCI-образов
    - cosign sign --yes harbor.internal/my-app:$TAG
    
    # Notation: корпоративная подпись для Harbor (согласно политике)
    - notation sign --plugin notation-keysource-hsm --id "hsm-key-id" harbor.internal/my-app:$TAG
    
    # Обе подписи прикрепляются через Referrers API
    # Harbor покажет обе подписи в UI
```

### Сценарий 4: Миграция с Notation на Sigstore

```bash
# 1. Экспорт текущих подписей Notation
notation list harbor.internal/my-app:v1.0.0
# → sha256:abc123...

# 2. Подпись через Cosign (keyless)
cosign sign --yes harbor.internal/my-app:v1.0.0

# 3. Верификация: проверка обеих подписей
# Notation (старая)
NOTATION_TRUST_POLICY=old-policy.json notation verify harbor.internal/my-app:v1.0.0

# Cosign (новая)
cosign verify \
  --certificate-identity-regexp "https://git.internal/my-org/my-app" \
  --certificate-oidc-issuer "https://git.internal" \
  harbor.internal/my-app:v1.0.0

# 4. Обновление политики Kyverno
# Добавление нового attestora с публичным ключом Cosign
kubectl patch clusterpolicy verify-images --type merge -p '{
  "spec": {"rules": [{"name": "check-signature", "verifyImages": [
    {"imageReferences": ["harbor.internal/*"], "attestors": [
      {"entries": [
        {"keys": {"publicKeys": "'"$COSIGN_PUB"'"}},
        {"keys": {"publicKeys": "'"$NOTATION_PUB"'"}}]}
    ]}
  ]}]}
}'
```

### Сценарий 5: Проверка подписей из Kyverno

```yaml
# Kyverno: политика, проверяющая подпись Cosign ИЛИ Notation
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-cosign-or-notation
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["harbor.internal/*"]
          attestors:
            - count: 1
              entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...  # Cosign key
                      -----END PUBLIC KEY-----
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...  # Notation key
                      -----END PUBLIC KEY-----
```

## Лучшие практики

1. **Начните с Sigstore (keyless):** Минимальные затраты на инфраструктуру, быстрый старт. Добавьте Notation позже при требованиях к HSM.
2. **Используйте оба для критичных сервисов:** Двойная подпись (Cosign + Notation) обеспечивает максимальную устойчивость.
3. **Ротация ключей:** Для Notation — раз в 90 дней. Для Sigstore — автоматически (ephemeral).
4. **Храните публичные ключи в Git:** Публичные ключи для верификации хранятся в репозитории и версионируются.
5. **Тестируйте верификацию:** В CI/CD обязательно проверяйте `cosign verify` / `notation verify` перед деплоем.

## Валидация внедрения

### Проверка подписей и trust policy

После настройки выполните комплексную проверку всех компонентов:

```bash
# 1. Проверка наличия подписей через Referrers API
cosign verify harbor.internal/my-app:v1.0.0 \
  --certificate-oidc-issuer "https://gitlab.internal/" \
  --certificate-identity-regexp "https://gitlab.internal/my-org/my-app"
# → Verified 1 signature

# 2. Проверка Notation подписи и trust store
notation cert list
# → TYPE    STORE           SUBJECT
# → ca      internal-ca     CN=MyCorp Internal CA

notation verify harbor.internal/my-app:v1.0.0
# → Successfully verified signature for harbor.internal/my-app:v1.0.0

# 3. Проверка Referrers API реестра (Harbor)
docker buildx imagetools inspect harbor.internal/my-app:v1.0.0
# → Manifest has 1 signature(s) associated

# 4. Проверка Kyverno политики
kubectl describe clusterpolicy verify-image-signature | grep -A5 Status
# → rule check-cosign-or-notation: pass
```

### Проверка OIDC-аутентификации (GitLab CI)

```bash
# 1. Проверка id_tokens в job
# В .gitlab-ci.yml убедитесь, что:
#   id_tokens:
#     SIGSTORE_ID_TOKEN:
#       aud: sigstore
# 2. Проверка токена внутри job:
echo $SIGSTORE_ID_TOKEN | cut -d. -f2 | base64 -d | jq .
# → {"aud":"sigstore","iss":"https://gitlab.internal/",...}
```

## Очистка

### Удаление подписей

```bash
# 1. Удаление подписи Cosign из реестра
# Cosign не предоставляет прямую команду для удаления подписи.
# Используйте Harbor API:
curl -u "robot$ci-bot:$ROBOT_SECRET" -X DELETE \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:<SIG_DIGEST>"

# 2. Удаление подписи Notation
notation list harbor.internal/my-app:v1.0.0
# → sha256:abc123...
# Затем удалите через Harbor API (как показано выше для Cosign)

# 3. Очистка trust store Notation
notation cert delete --store internal-ca --type ca --all
# → Certificate deleted from store internal-ca
```

### Отзыв сертификатов (Notation)

```bash
# 1. Удаление сертификата из trust store
notation cert delete --type ca --store internal-ca --all
# → Certificate revoked and removed from trust store

# 2. Ротация корневого сертификата
notation cert add --type ca --store internal-ca-new ./ca-new.pem
# → Далее обновите trust policy для использования internal-ca-new
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `cosign: error signing` | Fulcio недоступен или OIDC токен невалиден | `curl -k $FULCIO_URL`; проверьте `SIGSTORE_ID_TOKEN` и claims (`aud: sigstore`) в GitLab |
| `cosign: error verifying` | `--certificate-oidc-issuer` указывает на Fulcio, а не на OIDC провайдера | Используйте URL GitLab/GitHub в `--certificate-oidc-issuer`, а не `FULCIO_URL` |
| `notation: key not found` | Ключ не добавлен в trust store | `notation cert add --type ca --store <name> <cert.pem>` |
| `certificate identity mismatch` | Идентичность в политике не совпадает с OIDC claim | Проверьте точное совпадение `--certificate-identity` с claim `sub` в токене |
| `Referrers API 404` | Реестр не поддерживает OCI 1.1 | Обновите Harbor до v2.15+ или используйте другой реестр |
| `notation: plugin not found` | HSM-плагин не установлен | `notation plugin install --url <hsm-plugin-url>` |
| `Rekor: inclusion proof failed` | Transparency log недоступен (air-gapped) | Используйте `--tlog-upload=false` или self-hosted Rekor |

## Граничные случаи и ограничения

* **Self-hosted без OIDC:** GitLab Server версии < 15.7 не выдаёт ID-токены. GitLab Runner должен быть ≥ 16.0 для передачи токенов в job. Используйте key-based подпись с Notation или `--identity-token` для передачи токена вручную.
* **HSM и PQC:** HSM пока не поддерживают ML-DSA (PQC). Для постквантовых подписей используйте Sigstore с software keys.
* **Air-gapped:** Sigstore требует доступ к Fulcio/Rekor. В air-gapped — только Notation с внутренней CA.
* **Стоимость HSM:** Notation с HSM требует аппаратного модуля (SafeNet, YubiHSM). Sigstore (keyless) — бесплатен.

## Дополнительная информация

### Связанные документы

* [Подпись артефактов](./artifact_signing.md) — детальный разбор Cosign, Notation, VSA.
* [Целостность сборки](./build_integrity.md) — SLSA и интеграция подписи в пайплайн.
* [Sigstore: Безопасность цепочки поставок](../../Security/Tools/sigstore.md) — глубокое погружение в Fulcio/Rekor.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз.
