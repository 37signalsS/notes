# Подпись артефактов

## Определения

* **Artifact Signing (Подпись артефактов):** Процесс криптографического подтверждения аутентичности (авторства) и целостности программных объектов (образов, бинарных файлов, аттестаций, SBOM, Helm-чартов, Terraform-модулей).
* **Identity-based Signing (Keyless):** Подпись на основе идентичности (через OIDC), исключающая необходимость управления долгоживущими закрытыми ключами. Сертификат выпускается на короткий срок (например, 10 минут) и привязывается к email или CI-раннеру.
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
| **Identity (Keyless)** | Sigstore (Fulcio/Rekor) | CI/CD пайплайны, self-hosted среды | Нет риска кражи ключей, встроенный аудит |
| **Enterprise PKI** | Notation (X.509) | Закрытые корпоративные реестры, HSM | Интеграция с внутренней CA и KMS |
| **Binary Signing** | OpenSSL / PQC-tools | Бинарные файлы, прошивки, WASM | Независимость от инфраструктуры реестров |

### Архитектура Identity-based подписи (Keyless)

Ключевое отличие модели — отсутствие долгоживущих закрытых ключей. Вместо этого используется эфемерная пара ключей, генерируемая в памяти на время подписи:

1. **Генерация:** CI/CD-раннер создает ephemeral-пару ключей (ECDSA-P256 или ML-DSA) только в оперативной памяти.
2. **Аутентификация:** Раннер получает OIDC-токен от внутреннего провайдера (GitLab, Gitea, corporate IdP).
3. **Сертификация:** Внутренний Fulcio проверяет OIDC-токен и выдает краткосрочный X.509-сертификат (10–20 минут), где Subject = identity раннера.
4. **Публикация:** Метаданные (сертификат + подпись) отправляются во внутренний Rekor для неизменяемого аудита.
5. **Подписание:** Артефакт подписывается ephemeral-закрытым ключом, который затем уничтожается.

Этот механизм исключает компрометацию долгоживущих ключей и упрощает ротацию: при смене identity автоматически выпускается новый сертификат.

### Стек технологий (2026)

*   **Sigstore (Cosign v3.x):** Де-факто стандарт. Поддерживает эфемерные ключи, PQC-профили и OCI 1.1. Все события записываются в Rekor для публичного аудита.
*   **Notation (v1.x):** Отраслевой стандарт для корпоративных реестров (Harbor, GitLab Container Registry). Поддерживает Trust Stores и интеграцию с HSM/Vault.
*   **TUF (The Update Framework):** Обеспечивает защиту от атак на компрометацию систем дистрибуции (защита от отката версий).

### Инфраструктура Referrers (OCI 1.1)

В 2026 году использование тегов типа `image:v1.0.0.sig` считается устаревшим. Спецификация OCI 1.1 внедряет модель **графа зависимостей**, где:
1. Подпись является отдельным артефактом в реестре.
2. Она ссылается на дайджест основного образа через поле `subject`.
3. Реестр позволяет эффективно запрашивать все связанные подписи и SBOM через `/v2/<name>/referrers/<digest>`.
4. Это упрощает сборку мусора (GC) и делает структуру артефактов прозрачной.

### Почему VSA (Verification Summary Attestation)

Проверка отдельных подписей и аттестаций не масштабируется. VSA агрегирует результаты:
- Подпись образа (Cosign/Notation) — действительна?
- SLSA-уровень (Build L1–L3) — достигнут?
- SBOM — прикреплен и не содержит критических CVE?
- CBOM — криптографические алгоритмы соответствуют политике (ML-DSA, нет RSA-2048)?

На основе VSA Admission Controller (Kyverno) принимает решение: allow / audit / enforce.

## Предварительные требования

### Минимальные версии инструментов

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Cosign** | v3.1+ | Keyless-подпись образов и аттестаций с поддержкой ML-DSA (PQC). |
| **Notation** | v1.x+ | Корпоративная подпись через X.509 / HSM / внутреннюю CA. |
| **Syft** | v1.5+ | Генерация SBOM/CBOM в форматах SPDX 3.1 и CycloneDX 1.7. |
| **Harbor** | v2.11+ | Локальный OCI-реестр с поддержкой OCI 1.1 Referrers API. |
| **GitLab Runner** | v16+ / Gitea Runner | Self-hosted CI/CD-раннер с OIDC для keyless-подписи. |
| **Kyverno** | v1.19+ | Admission-контроль для верификации подписей и VSA-аттестаций. |
| **OpenSSL** | v3.4+ | Поддержка PQC-алгоритмов (ML-DSA) для бинарных подписей. |
| **Kubernetes** | 1.29+ | Целевая платформа для деплоя с Admission-политиками. |

### Аппаратные требования

* CPU с поддержкой AES-NI для ускорения криптографических операций.
* Для Build L3: серверы с поддержкой Intel TDX или AMD SEV-SNP для герметичных сборок.
* Минимум 8 ГБ ОЗУ на узел CI/CD-раннера, 16 ГБ — для сборки многомодульных проектов с SBOM.

### Начальное состояние окружения

* Два выделенных сервера bare metal / VM: один для CI/CD (GitLab Runner / Gitea Actions), второй для registry (Harbor).
* Внутренний Fulcio + Rekor развернуты в изолированной сети (или используется внешний Sigstore с proxy).
* Отдельный кластер Kubernetes для продакшна с включенными admission-вебхуками.
* Внутренний DNS-сервер, разрешающий `harbor.internal`, `git.internal`, `fulcio.internal`.

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

#### Self-hosted GitLab Runner с явным указанием внутреннего Fulcio

Для on-prem инфраструктуры с собственным GitLab и Harbor:

```bash
# Установка переменных окружения в раннере
export FULCIO_URL=https://fulcio.internal
export REKOR_URL=https://rekor.internal
export REGISTRY=harbor.internal/my-app
export IMAGE_TAG=v1.0.0

# Подпись образа (ключ не сохраняется на диск)
cosign sign --yes \
  --tlog-upload=false \
  --fulcio-url $FULCIO_URL \
  --rekor-url $REKOR_URL \
  --sign-algorithm mldsa \
  $REGISTRY:$IMAGE_TAG
# → Сгенерирован ephemeral-ключ, подпись прикреплена к образу через Referrers API
```

**Валидация:** Проверка подписи и соответствия алгоритма.

```bash
cosign verify $REGISTRY:$IMAGE_TAG \
  --certificate-identity-regexp "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer $FULCIO_URL \
  --check-claims=true \
  --output json | jq '.signatures[0].publicKey'
# → {"keyType":"ECDSA","keyData":"base64..."}

# Проверка наличия постквантовой подписи
cosign verify-attestation $REGISTRY:$IMAGE_TAG \
  --type slsaprovenance \
  --certificate-identity-regexp "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer $FULCIO_URL \
  | jq '.payload'
```

### Подпись через Notation (корпоративный стандарт)

Применяется для X.509 сертификатов и интеграции с HSM/Vault/внутренней CA.

```bash
# 1. Настройка внутренней CA и добавление корневого сертификата в trust store
notation cert add --type ca --store internal-ca ./ca.pem

# 2. Подпись образа с использованием ключа из внутренней CA / HSM
notation sign --key "internal-ca/signing-key" harbor.internal/my-app:v1.0.0

# 3. Верификация с использованием Trust Policy (trustpolicy.json)
# Политика определяет, какие издатели и идентичности считаются доверенными
notation verify harbor.internal/my-app:v1.0.0

# 4. Инспекция графа метаданных (Referrers)
notation ls harbor.internal/my-app:v1.0.0
```

### Подпись бинарных файлов и Helm-чартов

Cosign работает с любыми файлами, не только с образами:

```bash
# Подписание бинарного файла (WASM, прошивка, исполняемый файл)
cosign sign-blob --yes ./my-app-linux-amd64 \
  --bundle my-app.bundle \
  --sign-algorithm mldsa

# Верификация бинарного файла
cosign verify-blob ./my-app-linux-amd64 \
  --bundle my-app.bundle \
  --certificate-identity "build-service@corp.internal" \
  --certificate-oidc-issuer "https://git.internal"

# Подписание Helm-чарта
cosign sign --yes oci://harbor.internal/charts/my-app-1.4.0.tgz
```

### Подпись и верификация в air-gapped среде

При отсутствии доступа к внешнему Fulcio/Rekor используется key-based подпись с Notation и внутренней CA:

```bash
# 1. Генерация ключевой пары (в air-gapped зоне)
openssl genpkey -algorithm ML-DSA -out signing.key -pkeyopt ml_dsa_paramset:ML-DSA-65
openssl req -new -x509 -key signing.key -out signing.crt -days 365 \
  -subj "/CN=Internal CI Signing/O=MyOrg"

# 2. Подпись образа
notation sign --key signing.key harbor.internal/my-app:v1.0.0

# 3. Верификация (офлайн, без обращения к внешним сервисам)
notation verify --certificate-file signing.crt harbor.internal/my-app:v1.0.0
```

### Верификация VSA в Kubernetes (Admission Control)

В 2026 году блокировка деплоя выполняется на основе **VSA**, которая подтверждает выполнение всей политики безопасности (подписи + SLSA). Детальный пример политики Kyverno с troubleshooting — в **[Целостность сборки](./build_integrity.md#верификация-vsa-через-admission-controller-kyverno)**.

## Валидация внедрения

После настройки подписи выполните комплексную проверку всех компонентов:

```bash
# 1. Проверка целостности подписи и аттестаций
cosign verify $REGISTRY:$IMAGE_TAG \
  --certificate-identity-regexp "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer "https://harbor.internal" \
  && echo "Signature OK" || echo "Signature FAIL"

# 2. Проверка наличия SLSA-аттестации
syft $REGISTRY:$IMAGE_TAG -o spdx-json | jq '.packages[] | select(.name=="slsa-provenance")'
# → Должен вернуть attestation object

# 3. Проверка VSA через Kyverno
kyverno test ./kyverno-tests/ --policy verify-supply-chain.yaml \
  --resource ./test-pod.yaml
# → 1 passed, 0 failed

# 4. Проверка CBOM для криптографических компонентов
cdxgen -t generic --output-format json --output cbom.json .
grep -E '"(RSA|ECDSA|AES)"' cbom.json | wc -l
# → Должен показать 0 уязвимых алгоритмов после миграции на ML-DSA

# 5. Проверка дрейфа SBOM (сравнение эталона и Runtime)
trivy diff sbom:./expected-sbom.json sbom:./runtime-sbom.json
# → Должен показать 0 изменений, если дрейф отсутствует
```

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `cosign: error signing` | Fulcio недоступен или сертификат отклонен | `curl -k $FULCIO_URL` | Проверьте сетевую доступность Fulcio и срок действия OIDC-токена. В on-prem используйте внутренний CA или key-based подпись. |
| `Attestation not found` | SBOM/SLSA не прикреплен к образу | `curl /v2/.../referrers` | Убедитесь, что `docker buildx build` завершился с `--push` и флагами `--attest`. Для локальных тестов используйте `--output type=docker`. |
| `Cosign verify: certificate identity mismatch` | Идентичность в политике Kyverno не совпадает с OIDC-claim | `cosign verify --output text ...` | Проверьте точное совпадение `--certificate-identity` с claim `sub` в токене. |
| `Notation: key not found` | Ключ не добавлен в trust store | `notation cert list` | Добавьте сертификат через `notation cert add --type ca --store <name> <cert.pem>`. |
| `Trivy: false positive на CVE` | Уязвимый код не вызывается (reachability) | `trivy sbom --show-vulnerability-reachability` | Создайте VEX-отчет со статусом `not_affected`. |
| `Kyverno блокирует валидный образ` | Политика содержит устаревший public key | `kyverno apply --policy ... --resource ...` | Обновите public key в `ClusterPolicy` после ротации ключей Cosign. |
| `SBOM generation failed: multi-arch` | Syft не поддерживает манифест image index | `syft -o spdx-json ...` | Используйте `docker buildx imagetools inspect --format '{{json .Manifest}}'` и генерацию SBOM для каждого архитектурного варианта отдельно. |
| `Referrers API 404` | Реестр не поддерживает OCI 1.1 | `curl -v /v2/.../referrers` | Обновите Harbor до v2.11+ или используйте альтернативный реестр с поддержкой Referrers. |

## Лучшие практики и очистка

1. **Least Privilege для CI-раннеров:** Используйте отдельные robot-аккаунты в Harbor с правами `push` только в целевой проект. В Kubernetes применяйте ServiceAccount с минимальными RBAC-правами для пайплайна.
2. **Digest-pinning:** Никогда не используйте теги `latest` или `v1` в продакшне. Фиксируйте образы по digest (`image@sha256:...`).
3. **Эфемерные среды:** Каждая сборка выполняется в чистом Docker-контейнере или виртуальной машине, которая удаляется после выполнения. Никаких постоянных раннеров с кешем зависимостей.
4. **Ротация ключей:** Периодически (раз в 90 дней) ротируйте ключи подписи Cosign. Для keyless-сценария обновляйте Fulcio CA-корневой сертификат.
5. **Short-lived сертификаты:** Минимизируйте время жизни сертификатов (Fulcio выдает их на 10 минут), чтобы исключить необходимость ведения списков отзыва (CRL).
6. **Очистка артефактов:** Настройте политику удержания (retention) в Harbor: удаляйте неиспользуемые теги и старые аттестации через Harbor API.
7. **Аудит:** Ведите журнал всех изменений политик Kyverno и Git-коммитов. Используйте `git log --show-signature` для проверки подлинности истории.

```bash
# Пример очистки старых артефактов в Harbor (через API)
curl -u "admin:Harbor12345" -X POST \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:abc123" \
  -H "Content-Type: application/json" \
  -d '{"with_tag":false,"with_label":false}'
# → 200 OK (артефакт помечен для удаления)
```

## Граничные случаи и ограничения

* **Multi-architecture образы:** `docker buildx build` создает image index, а не единый манифест. Подписи и аттестации должны генерироваться для каждого архитектурного варианта (`linux/amd64`, `linux/arm64`) отдельно. Используйте `docker buildx imagetools inspect` для просмотра constituent-манифестов.
* **Air-gapped среды:** Отсутствие доступа к Fulcio/Rekor требует развертывания внутреннего Sigstore-стока или использования key-based подписи с Notation и внутренней CA. Все образы должны быть предварительно скачаны и подписаны в изолированной зоне.
* **Обратная совместимость PQC:** Алгоритмы ML-DSA/SLH-DSA не поддерживаются клиентами OpenSSL < 3.4. Для гибридной миграции используйте связку `ECDSA + ML-DSA`, пока все узлы не будут обновлены.
* **Откат (Rollback):** При откате на предыдущую версию образа убедитесь, что digest предыдущей версии присутствует в реестре, имеет валидную подпись и VSA-аттестацию. Политика Kyverno должна разрешать только подписанные теги.
* **Срок действия сертификатов:** Keyless-сертификаты Fulcio живут 10–20 минут. Долгосрочная валидация требует наличия SET (Signed Entry Timestamp) в Rekor. При недоступности Rekor валидация через `cosign verify` завершится ошибкой.
* **Self-hosted GitHub Actions:** При использовании self-hosted runner'ов убедитесь, что OIDC-токен корректно прокидывается в job. Для GitLab CI используется `$CI_JOB_JWT` с выставленными `id_token` permissions.

## TUF (The Update Framework): практическое применение

**TUF (The Update Framework)** — open-source фреймворк для защиты целостности процесса обновления ПО. Решает задачу, которую не покрывает простая подпись: защиту от атак на сам механизм дистрибуции (откат версий, подмена репозитория, компрометация ключа издателя).

### Как работает TUF

```
Репозиторий (издатель)
    │
    ├── 1. Генерация целей (targets) + подпись
    │       targets.json (список файлов + хеши)
    │       → подписывается targets-ключом
    │
    ├── 2. Роли и ключи
    │       ├── root: доверие к корневому ключу (хардкод)
    │       ├── root →签字→ snapshot (манифест всех метаданных)
    │       ├── root →签字→ timestamp (свежесть данных)
    │       └── targets →签字→ targets (список файлов)
    │
    └── 3. Клиент при обновлении
            ├── Проверяет timestamp (свежесть)
            ├── Проверяет snapshot (целостность)
            ├── Проверяет targets (хеши файлов)
            └── Скачивает файл и проверяет хеш
```

**Ключевое отличие от простой подписи:** TUF защищает от атак на selbst (self-update attack), где злоумышленник компрометировал сервер обновлений и отдаёт старые/подменённые файлы. Простая подпись не ловит это, потому что подпись валидна, но файл — нет.

### Интеграция с пакетными менеджерами

| Пакетный менеджер | Поддержка TUF | Настройка |
| :--- | :--- | :--- |
| **apt (Debian/Ubuntu)** | Нативная (apt-transport-https) | `/etc/apt/trusted.gpg.d/` + `InRelease` файлы |
| **yum (RHEL/CentOS)** | Нативная (gpgcheck=1) | `/etc/pki/rpm-gpg/` + `repo_gpgcheck=1` |
| **npm** | Через Sigstore (TUF-обёртка) | `sigstore` пакет, `npm audit signatures` |
| **Go modules** | Нативная (GOSUMDB + TUF) | `GONOSUMCHECK`, `GONOSUMDB` |
| **Helm** | Нативная (Helm provenance) | `helm install --verify` |

### Практический пример: TUF-сервер для внутренних обновлений

```bash
# 1. Установка TUF-сервера (tuf-on-server)
go install github.com/theupdateframework/tuf/cmd/tuf-server@latest

# 2. Инициализация репозитория
tuf init

# 3. Добавление целей (файлов для обновления)
tuf add /path/to/update-v1.0.0.tar.gz

# 4. Генерация ключей и подписание
tuf generate
tuf sign

# 5. Запуск сервера
tuf-server --listen :8080 --repo /path/to/tuf-repo

# 6. Клиент: проверка обновлений
tuf-client init http://tuf-server.internal:8080
tuf-client update
```

### TUF в контексте supply chain

TUF дополняет Sigstore/Notation:
- **Sigstore/Notation** защищают *конкретный артефакт* (образ, бинарник)
- **TUF** защищает *систему дистрибуции* (репозиторий, канал обновлений)

Вместе они обеспечивают сквозную защиту: артефакт подписан (Cosign/Notation) И система обновлений защищена от подмены (TUF).

## Дополнительная информация

### Стандарты и ресурсы

* **SLSA.dev:** <https://slsa.dev/> — спецификации SLSA v2.0 (Build & Source tracks).
* **NIST PQC Standards:** <https://csrc.nist.gov/Projects/post-quantum-cryptography> — стандарты FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) и FIPS 205 (SLH-DSA).
* **EU CRA:** <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act> — официальный текст закона о киберустойчивости ЕС.
* **ECMA-424:** <https://www.ecma-international.org/> — стандарт Cryptography Bill of Materials (CBOM).
* **IETF SCITT:** <https://datatracker.ietf.org/wg/scitt/> — цепочка доверия для программных артефактов (Supply Chain Integrity, Transparency, and Trust).
* **OpenSSF:** <https://openssf.org/> — инициативы GUAC, Scorecard и Sigstore.

### Связанные документы

* [Обзор безопасности цепочки поставок](./overview.md) — фундаментальные принципы, SLSA v2.0 и регуляторика (EU CRA).
* [Целостность сборки](./build_integrity.md) — SLSA v2.0, аттестации и воспроизводимость.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация по CycloneDX 1.6.
* [Sigstore: Безопасность цепочки поставок](../Tools/sigstore.md) — детальный разбор Fulcio/Rekor и OIDC.
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — генерация аттестаций через BuildKit.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — оркестрация рисков и результатов сканирования.
