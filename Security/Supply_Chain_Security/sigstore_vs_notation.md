# Sigstore vs Notation: сравнение и выбор

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
# Подпись через внутреннюю CA и HSM
notation sign --key "hsm:0" harbor.internal/my-app:v1.0.0
# → Подпись через ключ в HSM, сертификат от внутренней CA
```

## Практические сценарии

### Сценарий 1: Настройка Sigstore (keyless) для GitLab CI

```yaml
# .gitlab-ci.yml: keyless подпись через внутренний Fulcio
sign-image:
  stage: deploy
  image: alpine:3.21
  id_tokens:
    OIDC_TOKEN:
      aud: https://fulcio.internal
  script:
    - apk add --no-cache cosign
    # Настройка переменных для self-hosted Fulcio/Rekor
    - export FULCIO_URL=https://fulcio.internal
    - export REKOR_URL=https://rekor.internal
    - export OIDC_TOKEN=$OIDC_TOKEN
    
    # Подпись с использованием OIDC токена
    - cosign sign --yes \
        --tlog-upload=false \
        --fulcio-url $FULCIO_URL \
        --rekor-url $REKOR_URL \
        harbor.internal/my-app:$CI_COMMIT_SHA
    
    # Верификация
    - cosign verify \
        --certificate-identity "https://git.internal/my-org/my-app/-/jobs/$CI_JOB_ID" \
        --certificate-oidc-issuer $FULCIO_URL \
        harbor.internal/my-app:$CI_COMMIT_SHA
```

### Сценарий 2: Настройка Notation (X.509 + HSM) для Harbor

```bash
# 1. Добавление корневого сертификата внутренней CA
notation cert add --type ca --store internal-ca /path/to/ca.pem

# 2. Просмотр trust store
notation cert list
# → TYPE    STORE           SUBJECT
# ca      internal-ca      CN=MyCorp Internal CA

# 3. Подпись образа через ключ в HSM
notation sign --key "hsm:pkcs11:0" harbor.internal/my-app:v1.0.0

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
    - notation sign --key "hsm:0" harbor.internal/my-app:$TAG
    
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

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `cosign: error signing` | Fulcio недоступен или OIDC токен невалиден | `curl -k $FULCIO_URL`; проверьте `id_token` permissions в GitLab |
| `notation: key not found` | Ключ не добавлен в trust store | `notation cert add --type ca --store <name> <cert.pem>` |
| `certificate identity mismatch` | Идентичность в политике не совпадает с claim | Проверьте точное совпадение `--certificate-identity` с `sub` в токене |
| `Referrers API 404` | Реестр не поддерживает OCI 1.1 | Обновите Harbor до v2.15+ или используйте другой реестр |

## Граничные случаи и ограничения

* **Self-hosted runners без OIDC:** GitLab Runner версии < 16 не поддерживают OIDC. Используйте key-based подпись с Notation.
* **HSM и PQC:** HSM пока не поддерживают ML-DSA (PQC). Для постквантовых подписей используйте Sigstore с software keys.
* **Air-gapped:** Sigstore требует доступ к Fulcio/Rekor. В air-gapped — только Notation с внутренней CA.
* **Стоимость HSM:** Notation с HSM требует аппаратного модуля (SafeNet, YubiHSM). Sigstore (keyless) — бесплатен.

## Дополнительная информация

### Связанные документы

* [Подпись артефактов](./artifact_signing.md) — детальный разбор Cosign, Notation, VSA.
* [Целостность сборки](./build_integrity.md) — SLSA и интеграция подписи в пайплайн.
* [Sigstore: Безопасность цепочки поставок](../../Security/Tools/sigstore.md) — глубокое погружение в Fulcio/Rekor.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз.
