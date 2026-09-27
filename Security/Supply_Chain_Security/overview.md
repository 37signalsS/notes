# Обзор безопасности цепочки поставок (Supply Chain Security)

## Определения

* **Software Supply Chain Security (Безопасность цепочки поставок ПО):** Стратегический подход к защите программных артефактов, их зависимостей, сборочных конвейеров и систем распространения от умышленных атак (инъекции кода, подмена пакетов) и случайных уязвимостей. В 2026 году фокус сместился на **Zero Trust Architecture** для всех участников процесса.
* **SLSA (Supply-chain Levels for Software Artifacts):** Фреймворк и стандарт безопасности (v2.0), обеспечивающий целостность артефактов через проверяемые аттестации. В v2.0 введены раздельные треки: **Build Track** (защита процесса сборки) и **Source Track** (защита исходного кода, включая управление доступом и двухфакторную проверку коммитов).
* **SBOM (Software Bill of Materials — состав ПО):** Машиночитаемый инвентарный список всех компонентов (библиотек, пакетов ОС, драйверов). Стандарт **SPDX 3.0+** и **CycloneDX 1.6+** поддерживают расширенные профили для специализированных систем.
* **CBOM (Cryptography Bill of Materials):** Спецификация криптографических активов (стандарт **ECMA-424** / CycloneDX 1.6). Описывает используемые алгоритмы, длины ключей и протоколы, что критично для миграции на постквантовую криптографию (**PQC**).
* **VEX (Vulnerability Exploitability eXchange):** Формат обмена данными об эксплуатируемости уязвимостей, позволяющий дополнять статический SBOM актуальной информацией о том, влияет ли конкретная CVE на продукт в его текущей конфигурации.
* **NIST SSDF (Secure Software Development Framework, SP 800-218):** Набор практик для безопасной разработки ПО. В 2026 году обновлен для защиты «критического ПО», включая инструменты CI/CD. Обязателен для государственных контрактов через формы самоаттестации.
* **EU Cyber Resilience Act (CRA):** Регуляторный стандарт, вступивший в полную силу в сентябре 2026 года. Разделяет ПО на **Class I (Important)** и **Class II (Highly Critical)**. Обязывает производителей сообщать об эксплуатируемых уязвимостях в течение 24 часов (Article 14).

## Ландшафт угроз (Supply Chain Attacks)

Безопасность цепочки поставок критична из-за смещения вектора атак с эксплуатации приложений на компрометацию процессов их создания.

*   **Typosquatting и Dependency Confusion:** Регистрация вредоносных пакетов со схожими именами (например, `requesst` вместо `requests`) или подмена внутренних пакетов публичными с более высокой версией в реестрах (npm, PyPI).
*   **Компрометация инфраструктуры (Build System Attack):** Внедрение вредоносного кода в CI/CD-пайплайны, скомпрометированные runner'ы или инструменты сборки. В 2026 году участились атаки на **Source Track** через кражу токенов доступа к приватным репозиториям.
*   **Захват учётных записей (Maintainer Takeover):** Получение контроля над популярными Open Source проектами через социальную инженерию или покупку прав на поддержку.
*   **Квантовые угрозы (Harvest Now, Decrypt Later):** Сбор зашифрованного трафика и подписанных артефактов сегодня с целью их расшифровки/подделки в будущем с помощью квантовых компьютеров.

## Основные концепции

Безопасность цепочки поставок строится на принципах эшелонированной защиты, охватывающей путь от написания кода до выполнения (Runtime).

### 1. Инвентаризация и "Living SBOM"

В 2026 году концепция статического SBOM заменена на **Living SBOM** — динамический граф зависимостей, который непрерывно обогащается данными об уязвимостях и их эксплуатируемости (VEX).

* **SCA (Software Composition Analysis):** Автоматизированный поиск известных CVE в зависимостях. Современные инструменты используют семантический анализ и проверку доступности (reachability) уязвимого кода, что снижает количество ложных срабатываний на 80%.
* **VEX-фильтрация:** Устранение шума. Если библиотека содержит уязвимость, но её уязвимые функции не вызываются приложением, статус VEX `not_affected` позволяет не блокировать деплой.
* **CBOM и PQC-инвентаризация:** Обязательный учет криптографических алгоритмов. CBOM позволяет выявить использование уязвимых RSA/ECC и спланировать переход на алгоритмы **NIST PQC**: **ML-KEM** (FIPS 203) для инкапсуляции ключей и **ML-DSA** (FIPS 204) для цифровых подписей.

### 2. Целостность и аттестация (SLSA v2.0)

Фреймворк SLSA в версии 2.0 разделяет требования на два независимых трека, обеспечивая полную защиту от коммита до артефакта.

* **Build Track (Трек сборки):** Уровни 1–3 гарантируют, что артефакт собран в доверенной среде. Включает генерацию **Provenance** (аттестаций в формате in-toto) и использование эфемерных runner'ов.
* **Source Track (Трек исходного кода):** Новый стандарт 2026 года. Фокусируется на защите «головы» цепочки поставок:
    * Двухфакторное подтверждение (Two-party review) всех изменений.
    * Обязательная подпись коммитов через OIDC/SSH-ключи.
    * Неизменяемая история изменений (Immutable history).
* **VSA (Verification Summary Attestation):** Сводный отчет о верификации, который агрегирует результаты обоих треков для принятия решения о деплое.

### 3. Supply Chain Observability (Наблюдаемость)

Централизованный анализ всей цепочки поставок через графовые базы данных и системы управления состоянием безопасности приложений (ASPM).

* **GUAC (Graph for Understanding Artifact Composition):** Инструмент для агрегации SBOM, SLSA-аттестаций и VEX. Позволяет мгновенно определить «область поражения» (blast radius) при обнаружении новой уязвимости.
* **ASPM (Application Security Posture Management):** Платформы оркестрации (например, Cycode, Snyk AppRisk), которые коррелируют данные от SCA, SAST и Runtime для приоритизации рисков.

### 4. Доверенная подпись и верификация

Использование криптографии для подтверждения авторства и неизменности.

* **Sigstore / Cosign:** Стандарт де-факто для keyless-подписи. В 2026 году обязательна поддержка постквантовых подписей для защиты от HNDL-атак.
* **PQC в подписях:** Использование алгоритмов **ML-DSA** и **SLH-DSA** (FIPS 205) для подписи образов и аттестаций. Все новые сертификаты соответствуют стандарту **FIPS 140-3**.
* **Admission Policies:** Автоматическая блокировка запуска в Kubernetes (Kyverno, OPA) образов без валидной подписи, VSA-аттестации или SBOM, соответствующего политике EU CRA.

### 5. Регуляторный комплаенс (EU CRA)

Стандарт CRA 2026 года устанавливает жесткие требования к «прозрачности» ПО.

* **Обязательная отчетность:** Производители обязаны уведомлять ENISA об активно эксплуатируемых уязвимостях в течение 24 часов.
* **Class II Software:** Для критического ПО (гипервизоры, PKI, сетевые интерфейсы) требуется обязательная сертификация третьей стороной.
* **CE Marking:** Программный продукт без знака CE и подтвержденного SBOM/CBOM запрещен к продаже на рынке ЕС.

### Уровни SLSA v2.0 (Build Track)

| Уровень | Требование | Значение для безопасности |
| :--- | :--- | :--- |
| **Build L1** | Наличие аттестации (Provenance) | Базовая прослеживаемость процесса сборки и используемых исходников. |
| **Build L2** | Hosted Build + Подписанная Provenance | Гарантия того, что аттестация создана доверенным сервисом сборки и не была подделана. |
| **Build L3** | Hardened Build Platform | Изоляция процесса сборки, защита от влияния других сборок и компрометации сборочного узла. |

> **Source Track (Требования):** Включает обязательное использование систем контроля версий, двухфакторную проверку кода (Two-party review) и подтвержденную идентичность автора (Verified Author).

## Практические сценарии

### Предварительные требования

Для реализации сквозной защиты цепочки поставок на bare metal / on-prem инфраструктуре необходимы следующие компоненты:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Docker / BuildKit** | 24.0+ (BuildKit 1.11+) | Сборка образов с генерацией SBOM и SLSA-аттестаций. |
| **Cosign** | v3.1+ | Keyless-подпись образов и аттестаций с поддержкой ML-DSA (PQC). |
| **Syft** | v1.5+ | Генерация SBOM/CBOM в форматах SPDX 3.1 и CycloneDX 1.7. |
| **Trivy** | v0.55+ | Сканирование зависимостей и артефактов, VEX-фильтрация. |
| **Grype** | v0.35+ | Анализ достижимости (reachability) уязвимостей. |
| **Harbor** | v2.11+ | Локальный OCI-реестр с поддержкой OCI 1.1 Referrers API. |
| **Kyverno** | v1.19+ | Admission-контроль для верификации подписей и VSA-аттестаций. |
| **Git-сервер** | Gitea 1.21+ / GitLab 16+ | Хостинг исходного кода с защитой веток и подписью коммитов. |
| **Kubernetes** | 1.29+ | Целевая платформа для деплоя с Admission-политиками. |

**Аппаратные требования:**
* CPU с поддержкой AES-NI для ускорения криптографических операций.
* Для Build L3: серверы с поддержкой Intel TDX или AMD SEV-SNP для герметичных сборок.
* Минимум 8 ГБ ОЗУ на узел CI/CD-раннера, 16 ГБ — для сборки многомодульных проектов.

**Начальное состояние окружения:**
* Два выделенных сервера: один для CI/CD (GitLab Runner / GitHub Actions self-hosted), второй для registry (Harbor).
* Отдельный кластер Kubernetes для продакшна с включенными admission-вебхуками.
* Внутренний DNS-сервер, разрешающий `harbor.internal` и `git.internal`.

### Построение защищённого пайплайна на bare metal / on-prem

Ниже приведён полный конвейер для on-prem инфраструктуры без использования внешних облачных сервисов. Каждый шаг включает команды, ожидаемый вывод и валидацию.

#### Шаг 1. Подготовка Git-репозитория и защита веток

На сервере GitLab/Gitea создайте проект и включите обязательную подпись коммитов и двухфакторное ревью.

```bash
# Создание проекта (пример для Gitea через gitea CLI)
gitea admin create-org --org my-org --visibility private
gitea admin create-repo --owner my-org --name my-app --private

# Настройка защиты ветки main через API
curl -X PUT "http://git.internal/api/v1/repos/my-org/my-app/branch_protections" \
  -H "Authorization: Bearer $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "branch_name": "main",
    "enable_push_whitelist": false,
    "enable_merge_whitespace": false,
    "require_signature": true,
    "required_approvals": 1,
    "deny_force_push": true,
    "deny_deletions": true
  }'
# → Ожидаемый ответ: {"id":1,"branch_name":"main",...}
```

**Валидация:** Попытка прямого push в `main` без PR отклоняется; коммит без GPG/SSH-подписи блокируется.

```bash
# Проверка: попытка push без подписи
git commit --allow-empty -m "unsigned commit"
git push origin main
# → remote: ERROR: This commit does not have a signing (GPG or SSH)!
```

#### Шаг 2. Настройка локального реестра Harbor

Разверните Harbor с включенной поддержкой OCI 1.1 Referrers и robot-аккаунтами для CI.

```bash
# Развертывание через Docker Comppose
git clone https://github.com/goharbor/harbor-helm.git
cd harbor-helm
helm upgrade --install harbor ./chart \
  --namespace harbor --create-namespace \
  --set expose.type=nodePort \
  --set expose.tls.enabled=true \
  --set expose.tls.certSource=auto \
  --set externalURL="https://harbor.internal" \
  --set persistence.enabled=true \
  --set persistence.persistentVolumeClaim.registry.storageClass="local-path" \
  --set trivy.enabled=true \
  --set notary.enabled=false

# Создание проекта и robot-аккаунта
curl -u admin:Harbor12345 -X POST "https://harbor.internal/api/v2.0/projects" \
  -H "Content-Type: application/json" \
  -d '{"project_name":"my-app","public":false}'

curl -u admin:Harbor12345 -X POST "https://harbor.internal/api/v2.0/robots" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-bot","duration":-1,"level":"project","permissions":[{"namespace":"my-app","kind":"project","access":[{"resource":"repository","action":"push","resource":"my-app"}]}]}'
# → {"name":"robot$ci-bot","secret":"..."}
```

**Валидация:** Проверка доступности и Referrers API.

```bash
docker login harbor.internal -u robot$ci-bot -p $ROBOT_SECRET
# → Login Succeeded

# Проверка Referrers API (должен вернуть пустой список или 404, если нет артефактов)
curl -u "robot$ci-bot:$ROBOT_SECRET" \
  "https://harbor.internal/v2/my-app/manifests/sha256:abc123/referrers"
# → 200 OK или 404 (если реестр не поддерживает Referrers — требуется Harbor 2.11+)
```

#### Шаг 3. Сборка с генерацией SBOM и SLSA-аттестаций

Используйте Docker BuildKit для герметичной сборки с автоматической генерацией аттестаций. Предварительно зафиксируйте дату сборки через `SOURCE_DATE_EPOCH` для воспроизводимости.

```bash
# Экспорт переменных окружения
export SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)
export REGISTRY=harbor.internal/my-app
export IMAGE_TAG=v1.0.0

# Предварительная сборка зависимостей в vendor-каталог (Python-пример)
pip download -r requirements.txt -d ./vendor --only-binary=:all:

# Герметичная сборка (Dockerfile должен использовать --network=none)
docker buildx build \
  --builder=my-builder \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  --build-arg VENDOR_DIR=/app/vendor \
  --tag $REGISTRY:$IMAGE_TAG \
  --attest type=slsa,provenance=mode=max \
  --attest type=sbom \
  --output type=image,push=true,rewrite-timestamp=true \
  --push .
# → Сборка завершена, аттестации прикреплены к манифесту образа
```

**Валидация:** Проверка наличия аттестаций и SBOM в реестре.

```bash
# Просмотр связанных артефактов (Referrers)
curl -u "robot$ci-bot:$ROBOT_SECRET" \
  "https://harbor.internal/v2/my-app/manifests/sha256:$(skopeo inspect docker://$REGISTRY:$IMAGE_TAG --format '{{.Digest}}' | cut -d: -f2)/referrers"
# → {"manifest":{"layers":[{"mediaType":"application/vnd.dev.cosign.artifact.sig.v1+json",...}]}}

# Проверка SBOM через Syft
syft $REGISTRY:$IMAGE_TAG -o cyclonedx-json | jq '.components | length'
# → Число компонентов (например, 142)
```

#### Шаг 4. Подпись артефактов (keyless, self-hosted)

Для on-prem разверните собственный Sigstore-стек (Fulcio + Rekor) или используйте key-based подпись с внутренней CA. Ниже приведён keyless-вариант с локальным Fulcio.

```bash
# Развертывание Fulcio и Rekor в Kubernetes (только для внутренней сети)
kubectl apply -f https://raw.githubusercontent.com/sigstore/fulcio/release/config/release/generated/fulcio.yaml
kubectl apply -f https://raw.githubusercontent.com/sigstore/rekor/release/rekor-deployment.yaml

# Получение endpoint Fulcio для OIDC
export FULCIO_URL=$(kubectl get svc/fulcio-webhook -n fulcio-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
export REKOR_URL=$(kubectl get svc/rekor-server -n rekor-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Подпись образа с явным указанием внутреннего Fulcio
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

#### Шаг 5. Сканирование и VEX-фильтрация

Сканирование выполняется дважды: на этапе сборки (CI) и перед деплоем (Admission). VEX-отчет фильтрует неэксплуатируемые CVE.

```bash
# Сканирование образа
trivy image --format cyclonedx --output trivy-report.json $REGISTRY:$IMAGE_TAG

# Проверка критических уязвимостей без VEX
trivy image --severity CRITICAL $REGISTRY:$IMAGE_TAG
# → 2026-09-18T13:00:00.000000000Z	INFO	Detected OS: debian
# → 2026-09-18T13:00:01.000000000Z	INFO	Number of vulnerabilities: 0

# Применение VEX-отчета (если уязвимость подтверждена как не эксплуатируемая)
trivy sbom --vex vex-report.json sbom.json
# → Уязвимости со статусом not_affected исключаются из отчета
```

**Валидация:** Zero critical vulnerabilities without VEX `not_affected`.

```bash
# Интеграция с CI (фрагмент пайплайна GitLab CI)
stages:
  - scan

trivy-scan:
  stage: scan
  image: aquasec/trivy:0.55.0
  script:
    - trivy image --exit-code 1 --severity CRITICAL $REGISTRY:$IMAGE_TAG
  only:
    - main
```

#### Шаг 6. Admission-контроль и верификация VSA

Политика Kyverno проверяет подпись, SLSA-уровень и отсутствие критических уязвимостей перед запуском пода.

```yaml
# install-kyverno.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-supply-chain
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: check-image-signature
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["harbor.internal/my-app/*"]
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                      -----END PUBLIC KEY-----
              certificateIdentity: "https://harbor.internal/project/my-app"
              certificateOidcIssuer: "https://harbor.internal"

    - name: check-slsa-vsa
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["harbor.internal/my-app/*"]
          attestations:
            - type: https://slsa.dev/verification_summary/v1
              attestors:
                - entries:
                    - keys:
                        publicKeys: |-
                          -----BEGIN PUBLIC KEY-----
                          MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                          -----END PUBLIC KEY-----
              conditions:
                - all:
                    - key: "{{ json_parse(attestation.statement).predicate.slsa_level }}"
                      operator: Equals
                      value: "Build_L3"
```

**Применение и валидация:**

```bash
# Установка Kyverno CLI и применение политики
kyverno apply install.yaml
kyverno apply verify-supply-chain.yaml --cluster

# Проверка политики на тестовом манифесте
kubectl run test-pod --image=harbor.internal/my-app:v1.0.0 --dry-run=server
# → Если образ неподписан или уровень SLSA ниже L3:
# Error: failed to create pod: admission webhook "validate.kyverno.svc" denied the request:
# resource Pod/test-pod was blocked due to the following policies:
#   verify-supply-chain: check-image-signature: image signature verification failed

# После исправления (подпись + VSA L3):
kubectl run test-pod --image=harbor.internal/my-app:v1.0.0 --dry-run=server
# → pod/test-pod created (dry-run)
```

### Валидация внедрения

После настройки пайплайна выполните комплексную проверку всех компонентов:

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

### Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `cosign: error signing` | Fulcio недоступен или сертификат отклонен | `curl -k $FULCIO_URL` | Проверьте сетевую доступность Fulcio и срок действия OIDC-токена. В on-prem используйте внутренний CA или key-based подпись. |
| `Attestation not found` | SBOM/SLSA не прикреплен к образу | `curl /v2/.../referrers` | Убедитесь, что `docker buildx build` завершился с `--push` и флагами `--attest`. Для локальных тестов используйте `--output type=docker`. |
| `Cosign verify: certificate identity mismatch` | Идентичность в политике Kyverno не совпадает с OIDC-claim | `cosign verify --output text ...` | Проверьте точное совпадение `--certificate-identity` с claim `sub` в токене. |
| `Trivy: false positive на CVE` | Уязвимый код не вызывается (reachability) | `trivy sbom --show-vulnerability-reachability` | Создайте VEX-отчет со статусом `not_affected`. |
| `Kyverno блокирует валидный образ` | Политика содержит устаревший public key | `kyverno apply --policy ... --resource ...` | Обновите public key в `ClusterPolicy` после ротации ключей Cosign. |
| `SBOM generation failed: multi-arch` | Syft не поддерживает манифест image index | `syft -o spdx-json ...` | Используйте `docker buildx imagetools inspect --format '{{json .Manifest}}'` и генерацию SBOM для каждого архитектурного варианта отдельно. |

### Лучшие практики и очистка

1. **Least Privilege для CI-раннеров:** Используйте отдельные robot-аккаунты в Harbor с правами `push` только в целевой проект. В Kubernetes применяйте ServiceAccount с минимальными RBAC-правами для пайплайна.
2. **Digest-pinning:** Никогда не используйте теги `latest` или `v1` в продакшне. Фиксируйте образы по digest (`image@sha256:...`).
3. **Эфемерные среды:** Каждая сборка выполняется в чистром Docker-контейнере или виртуальной машине, которая удаляется после выполнения. Никаких постоянных runner'ов с кешем зависимостей.
4. **Ротация ключей:** Периодически (раз в 90 дней) ротируйте ключи подписи Cosign. Для keyless-сценария обновляйте Fulcio CA-корневой сертификат.
5. **Очистка артефактов:** Настройте политику удержания (retention) в Harbor: удаляйте неу referencing-теги и старые аттестации через Harbor API или `docker buildx prune`.
6. **Аудит:** Ведите журнал всех изменений политик Kyverno и Git-коммитов. Используйте `git log --show-signature` для проверки подлинности истории.

```bash
# Пример очистки старых артефактов в Harbor (через API)
curl -u "admin:Harbor12345" -X POST \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:abc123" \
  -H "Content-Type: application/json" \
  -d '{"with_tag":false,"with_label":false}'
# → 200 OK (артефакт помечен для удаления)
```

### Граничные случаи и ограничения

* **Multi-architecture образы:** `docker buildx build` создает image index, а не единый манифест. SBOM и аттестации должны генерироваться для каждого архитектурного варианта (`linux/amd64`, `linux/arm64`) отдельно. Используйте `docker buildx imagetools inspect` для просмотра constituent-манифестов.
* **Air-gapped среды:** Отсутствие доступа к Fulcio/Rekor требует развертывания внутреннего Sigstore-стока или использования key-based подписи с Notation и внутренней CA. Все образы должны быть предварительно скачаны и подписаны в изолированной зоне.
* **Обратная совместимость PQC:** Алгоритмы ML-DSA/SLH-DSA не поддерживаются клиентами OpenSSL < 3.4. Для гибридной миграции используйте связку `ECDSA + ML-DSA`, пока все узлы не будут обновлены.
* **SBOM дрейф в Runtime:** Даже при корректной сборке, запущенный контейнер может отличаться от SBOM из-за динамической загрузки библиотек (например, через `dlopen`). Для обнаружения используйте eBPF-агенты (Falco/Tetragon) и сравнивайте загруженные библиотеки с SBOM.
* **Откат (Rollback):** При откате на предыдущую версию образа убедитесь, что digest предыдущей версии присутствует в реестре, имеет валидную подпись и VSA-аттестацию. Политика Kyverno должна разрешать только подписанные теги.

## Дополнительная информация

### Стандарты и ресурсы

* **SLSA.dev:** <https://slsa.dev/> — спецификации SLSA v2.0 (Build & Source tracks).
* **NIST PQC Standards:** <https://csrc.nist.gov/Projects/post-quantum-cryptography> — стандарты FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) и FIPS 205 (SLH-DSA).
* **EU CRA:** <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act> — официальный текст закона о киберустойчивости ЕС.
* **ECMA-424:** <https://www.ecma-international.org/> — стандарт Cryptography Bill of Materials (CBOM).
* **IETF SCITT:** <https://datatracker.ietf.org/wg/scitt/> — цепочка доверия для программных артефактов (Supply Chain Integrity, Transparency, and Trust).
* **OpenSSF:** <https://openssf.org/> — инициативы GUAC, Scorecard и Sigstore.

### Связанные документы

* [Примеры реальных атак на цепочку поставок](./supply_chain_attack_examples.md) — SolarWinds, Log4Shell, event-stream, colors.js, 3CX: хронология, защита.
* [Безопасность цепочки поставок контейнерных образов](./container_image_supply_chain.md) — distroless, digest pinning, multi-stage builds, admission control.
* [Сравнение SCA-инструментов](./sca_tools_comparison.md) — Trivy vs Grype vs Snyk vs osv-scanner vs Syft.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация по CycloneDX 1.6.
* [Целостность сборки](./build_integrity.md) — SLSA v2.0, аттестации и воспроизводимость.
* [Подпись артефактов](./artifact_signing.md) — Sigstore, Cosign и PQC-алгоритмы подписи.
* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius, реакция на CVE.
* [Триаж CVE](./cve_triage_workflow.md) — практический workflow классификации, приоритизации и false positives.
* [Защита от Dependency Confusion](./dependency_confusion_prevention.md) — scope, proxy-реестры, lock-файлы.
* [Sigstore vs Notation](./sigstore_vs_notation.md) — сравнение и выбор инструмента подписи.
* [Runtime drift detection](./runtime_drift_detection.md) — обнаружение расхождений SBOM в рантайме.
* [Incident Response supply chain](./supply_chain_incident_response.md) — реагирование на инциденты цепочки поставок.
* [SBOM-политика для разработчиков](./sbom_developer_policy.md) — RACI, quality gate, процесс.
* [Sigstore: Безопасность цепочки поставок](../Tools/sigstore.md) — глубокое погружение в инфраструктуру keyless.
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — генерация SBOM и Provenance через BuildKit.
* [Безопасность публичных реестров](../../Docker/Docker_registries/public_registry_security.md) — защита от атак на upstream-зависимости.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — оркестрация рисков цепочки поставок.
* [Автоматизация обновлений](../../CI-CD/dependency_automation.md) — Renovate/Dependabot для безопасного обновления зависимостей.
* [Атаки на CI/CD](../../CI-CD/DevSecOps/cicd_attacks.md) — классификация векторов атак на пайплайны.
