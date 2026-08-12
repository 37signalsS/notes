# Подпись артефактов

## Определения

* **Artifact Signing (Подпись артефактов):** Процесс криптографического подтверждения аутентичности (авторства) и целостности программных объектов (образов, бинарных файлов, аттестаций, SBOM, весов ИИ-моделей).
* **Identity-based Signing (Keyless):** Подпись на основе идентичности (через OIDC), исключающая необходимость управления долгоживущими закрытыми ключами. Сертификат выпускается на короткий срок (например, 10 минут) и привязывается к email или GitHub/GitLab раннеру.
* **Timestamping (Метка времени):** Подтверждение того, что подпись была создана в период действия сертификата. Критично для долгосрочной валидации (LTV) через RFC 3161.
* **Transparency Log (Журнал прозрачности):** Публичный, доступный только для добавления (append-only) реестр всех событий подписи (**Rekor**, **IETF SCITT**). Обеспечивает аудит и обнаружение компрометации сертификатов.
* **ML-DSA (Module-Lattice Digital Signature Algorithm):** Основной постквантовый алгоритм цифровой подписи (стандарт **FIPS 204**), устойчивый к атакам квантовых компьютеров. Заменяет ECDSA/RSA в критических контурах.
* **OCI 1.1 Referrers API:** Стандарт OCI для связывания метаданных (подписей, SBOM) с основным артефактом. Позволяет реестру хранить подписи как связанные объекты, а не через дополнительные теги.
* **VSA (Verification Summary Attestation):** Сводная аттестация, агрегирующая результаты проверки подписей и SLSA-уровней. Используется для принятия автоматических решений о развертывании (Admission Control).

## Основные концепции

В 2026 году подпись артефактов стала блокирующим требованием для комплаенса (EU CRA, NIST SSDF). Основной целью является переход от доверия к "периметру" к доверию к конкретным криптографическим доказательствам (Cryptographic Proofs).

### Современные модели подписи

| Модель | Технология | Сфера применения | Плюсы |
| :--- | :--- | :--- | :--- |
| **Identity (Keyless)** | Sigstore (Fulcio/Rekor) | Cloud Native, CI/CD пайплайны | Нет риска кражи ключей, встроенный аудит |
| **Enterprise PKI** | Notation (X.509) | Закрытые корпоративные реестры | Интеграция с HSM и существующими CA |
| **Binary Signing** | OpenSSL / PQC-tools | Бинарные файлы, прошивки | Независимость от инфраструктуры реестров |

### Стек технологий (2026)

*   **Sigstore (Cosign v3.x):** Де-факто стандарт. Поддерживает эфемерные ключи, PQC-профили и OCI 1.1. Все события записываются вRekor для публичного аудита.
*   **Notation (v1.x):** Отраслевой стандарт для корпоративных реестров (Azure ACR, AWS ECR, Harbor). Поддерживает Trust Stores и интеграцию с KMS.
*   **TUF (The Update Framework):** Обеспечивает защиту от атак на компрометацию систем дистрибуции (защита от отката версий).

### Инфраструктура Referrers (OCI 1.1)

В 2026 году использование тегов типа `image:v1.0.0.sig` считается устаревшим. Спецификация OCI 1.1 внедряет модель **графа зависимостей**, где:
1. Подпись является отдельным артефактом в реестре.
2. Она ссылается на дайджест основного образа через поле `subject`.
3. Реестр позволяет эффективно запрашивать все связанные подписи и SBOM через `/v2/<name>/referrers/<digest>`.
Это упрощает сборку мусора (GC) и делает структуру артефактов прозрачной.

## Практические сценарии

### Подпись через Sigstore Cosign (Keyless)

Основной метод для CI/CD пайплайнов. В 2026 году Cosign по умолчанию использует **OCI 1.1 Referrers** и поддерживает постквантовые алгоритмы.

```bash
# 1. Подписание образа с использованием ML-DSA (PQC)
# В CI идентичность подтверждается через OIDC токен среды
cosign sign --yes --tlog-upload=true --sign-algorithm mldsa ghcr.io/my-org/my-app:v1.0.0

# 2. Верификация с проверкой идентичности и записи в Rekor
cosign verify \
  --certificate-identity "https://github.com/my-org/my-repo/.github/workflows/release.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/my-org/my-app:v1.0.0
```

### Подпись через Notation (корпоративный стандарт)

Применяется для X.509 сертификатов и интеграции с KMS/HSM.

```bash
# 1. Подпись с использованием ключа из AWS KMS / Azure Key Vault
notation sign --key "alias/signing-key" my-registry.com/my-app:v1.0.0

# 2. Верификация с использованием Trust Policy (trustpolicy.json)
# Политика определяет, какие издатели и идентичности считаются доверенными
notation verify my-registry.com/my-app:v1.0.0

# 3. Инспекция графа метаданных (Referrers)
notation ls my-registry.com/my-app:v1.0.0
```

### Подпись и верификация ИИ-моделей

Для защиты весов моделей от подмены (Model Hijacking) используется подпись блобов с привязкой к OIDC.

```bash
# Подписание файла модели с генерацией бандла (подпись + сертификат + tlog proof)
cosign sign-blob --yes ./model.safetensors --bundle model.bundle --sign-algorithm mldsa

# Верификация модели перед загрузкой в GPU
cosign verify-blob ./model.safetensors \
  --bundle model.bundle \
  --certificate-identity "ai-engineer@corp.com" \
  --certificate-oidc-issuer "https://accounts.google.com"
```

### Верификация VSA в Kubernetes (Admission Control)

В 2026 году блокировка деплоя выполняется на основе **VSA**, которая подтверждает выполнение всей политики безопасности (подписи + SLSA).

```yaml
# Пример политики Kyverno для проверки VSA аттестации
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-vsa-attestation
spec:
  rules:
    - name: check-vsa
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["ghcr.io/my-org/*"]
          attestations:
            - type: https://slsa.dev/verification_summary/v1
              attestors:
                - entries:
                    - keys:
                        publicKeys: |-
                          -----BEGIN PUBLIC KEY-----
                          ...
                          -----END PUBLIC KEY-----
              conditions:
                - all:
                  - key: "{{ json_parse(attestation.statement).predicate.slsa_level }}"
                    operator: Equals
                    value: "Build_L3"
```

## Дополнительная информация

### Долгосрочная валидация и PQC

*   **RFC 3161 (Timestamping):** Использование внешних сервисов меток времени (TSA) обязательно для обеспечения валидности подписей после истечения сертификата.
*   **Миграция на PQC (Post-Quantum):** 
    *   Стандарт **FIPS 204 (ML-DSA)** является обязательным для новых систем с 2026 года.
    *   Sigstore и Notation поддерживают гибридные схемы (например, ECDSA + ML-DSA) для обеспечения совместимости со старыми клиентами.
*   **IETF SCITT:** Новый стандарт для обеспечения прозрачности и доверия к любым артефактам цепочки поставок через неизменяемые журналы событий.

### Рекомендации по эксплуатации

1.  **OCI 1.1 Referrers:** Откажитесь от использования тегов `.sig`. Реестры с поддержкой OCI 1.1 (Harbor 2.11+, ECR, ACR) обеспечивают более надежное связывание и очистку артефактов.
2.  **Admission Enforcement:** Подпись бесполезна без автоматической проверки. Используйте **Kyverno** или **Ratify** для блокировки неподписанного кода в рантайме.
3.  **Short-lived Certificates:** Минимизируйте время жизни сертификатов (Fulcio выдает их на 10 минут), чтобы исключить необходимость ведения списков отзыва (CRL).

### Связанные документы

* [Обзор безопасности цепочки поставок](./overview.md) — фундаментальные принципы, SLSA v2.0 и регуляторика (EU CRA).
* [Целостность сборки](./build_integrity.md) — SLSA v2.0, аттестации и герметичность.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация по CycloneDX 1.6.
* [Sigstore: Безопасность цепочки поставок](../Tools/sigstore.md) — детальный разбор Fulcio/Rekor и OIDC.
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — генерация аттестаций через BuildKit.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — оркестрация рисков и результатов сканирования.
