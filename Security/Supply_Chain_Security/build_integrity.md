# Целостность сборки

## Определения

* **Build Integrity (Целостность сборки):** Свойство процесса сборки, гарантирующее, что выходной артефакт точно соответствует исходному коду и не подвергался несанкционированным изменениям.
* **Reproducible Build (Воспроизводимая сборка):** Методология, при которой из идентичных исходных данных (код, зависимости, инструменты) всегда создается бит-в-бит идентичный артефакт. Позволяет подтвердить отсутствие "закладок" через независимую пересборку.
* **Hermetic Build (Герметичная сборка):** Сборка в полностью изолированной среде без доступа к внешней сети. Все зависимости должны быть предоставлены внутри среды и верифицированы по хеш-суммам (Content Addressable Storage).
* **SLSA (Supply-chain Levels for Software Artifacts):** Фреймворк безопасности (v2.0), разделенный на два независимых трека для обеспечения сквозного доверия:
    * **Build Track:** Защита процесса превращения кода в артефакт (уровни Build L1–L3).
    * **Source Track:** Гарантии целостности исходного кода (двухфакторное ревью, защита веток, криптографическая подпись коммитов).
* **Provenance (Аттестация происхождения):** Машиночитаемые метаданные (формат in-toto), описывающие жизненный цикл создания артефакта. В 2026 году стандарт **SLSA Provenance v1.0** является обязательным для всех критических систем.
* **VSA (Verification Summary Attestation):** Сводная аттестация, подтверждающая соответствие артефакта требуемому уровню безопасности. Используется Admission-контроллерами для быстрого принятия решений без анализа полных графов Provenance.
* **TEE (Trusted Execution Environment) / Confidential Computing:** Аппаратно изолированная среда выполнения (**Intel TDX**, **AMD SEV-SNP**, **Intel SGX**). Обеспечивает выполнение сборок в анклавах, защищенных от компрометации гипервизора или администратора хоста.

## Основные концепции

Защита целостности сборки фокусируется на исключении возможности внедрения вредоносного кода на этапе компиляции, упаковки или доставки.

### Ключевые практики защиты

| Практика | Назначение | Реализация |
| :--- | :--- | :--- |
| **Изоляция и TEE** | Защита от компрометации сборочного узла | Эфемерные раннеры в изолированных ВМ с аппаратной изоляцией памяти (Intel TDX, AMD SEV-SNP) |
| **Герметичность** | Блокировка внешних атак во время сборки | `network=none`, использование Content Addressable Storage (CAS) и доверенных прокси |
| **Аттестация (Provenance)** | Непрерывная прослеживаемость | Нативные генераторы в CI/CD (GitLab Runner, Tekton Chains, GitHub Actions self-hosted) |
| **Прозрачность (Logging)** | Обнаружение компрометации ключей | Запись аттестаций в Ledger-системы прозрачности (**Rekor**, **IETF SCITT**) |
| **Верификация VSA** | Автоматизация контроля | Enforcement политик в Kubernetes через Kyverno/OPA на основе аттестаций |

### Уровни SLSA v2.0 (Build Track)

В 2026 году уровни SLSA базируются на проверяемых доказательствах (Evidence-based security).

1.  **Build L1:** Наличие аттестации (Provenance), автоматически сгенерированной системой сборки.
2.  **Build L2:** Сборка в доверенной изолированной среде с использованием эфемерных ресурсов. Аттестация подписана ключом системы сборки, что гарантирует защиту от подмены артефакта.
3.  **Build L3:** Гарантированная изоляция (Hardened Build). Требует использования аппаратной изоляции памяти (Intel TDX, AMD SEV-SNP), исключающих влияние внешней инфраструктуры на процесс сборки.

### Требования SLSA v2.0 (Source Track)

Для критических систем (Class II по EU CRA) обязательным является выполнение требований к исходному коду:
* **Two-party review:** Ни один коммит не попадает в основную ветку без одобрения независимого ревьюера.
* **Verified History:** Все изменения подписаны через **Sigstore** или персональные ключи (SSH/GPG).
* **Immutable History:** Запрет на force-push и переписывание истории в репозиториях.

## Практические сценарии

### Предварительные требования

Для реализации сквозной защиты целостности сборки на bare metal / on-prem инфраструктуре необходимы следующие компоненты:

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
* Для Build L3: серверы с поддержкой Intel TDX или AMD SEV-SNP для аппаратной изоляции сборок.
* Минимум 8 ГБ ОЗУ на узел CI/CD-раннера, 16 ГБ — для сборки многомодульных проектов.

**Начальное состояние окружения:**
* Два выделенных сервера: один для CI/CD (GitLab Runner / GitHub Actions self-hosted), второй для registry (Harbor).
* Отдельный кластер Kubernetes для продакшна с включенными admission-вебхуками.
* Внутренний DNS-сервер, разрешающий `harbor.internal` и `git.internal`.

### Настройка герметичной сборки в Docker (BuildKit)

Герметичность гарантирует, что сборка не скачивает зависимости из внешней сети в процессе выполнения, что исключает подмену пакетов "на лету".

```dockerfile
# Использование доверенного образа по дайджесту
FROM python@sha256:4a080808a8080808080808080808080808080808080808080808080808080808 AS builder

WORKDIR /app

# Предварительное копирование всех зависимостей в образ
COPY ./vendor /app/vendor

# Сборка с отключенной сетью
# Флаг --network=none гарантирует герметичность
RUN --network=none pip install --no-index --find-links=/app/vendor my-package
```

### Обеспечение воспроизводимости (Reproducible Builds)

Для того чтобы артефакт был бит-в-бит идентичным, необходимо исключить изменчивые данные (метки времени, пути к файлам) из процесса сборки.

```bash
# Использование SOURCE_DATE_EPOCH для фиксации времени
export SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)

# Сборка Go-бинарника с подавлением путей и фиксацией времени
go build -trimpath -ldflags="-buildid=" -o app main.go

# Сборка Docker-образа с фиксацией меток времени слоев (BuildKit)
docker buildx build \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  --output type=docker,rewrite-timestamp=true \
  -t my-app:latest .
```

### Нативная аттестация в Docker (BuildKit v1.11+)

В 2026 году BuildKit позволяет генерировать аттестации (SBOM и Provenance) непосредственно во время сборки с помощью флага `--attest`.

```bash
# Сборка с генерацией аттестаций SLSA и SBOM
docker buildx build \
  --tag my-registry.com/my-app:v1.0.0 \
  --attest type=slsa,provenance=mode=max \
  --attest type=sbom \
  --push .

# Верификация наличия аттестаций в реестре
docker buildx imagetools inspect my-registry.com/my-app:v1.0.0 --format "{{json .Provenance}}"
```

### Self-hosted CI/CD раннер для on-prem инфраструктуры

Для изоляции процесса сборки от внешних сетей используйте self-hosted раннеры.

```bash
# Установка GitLab Runner в режиме Docker (Linux/amd64)
docker run -d --name gitlab-runner \
  --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e TZ=Europe/Moscow \
  --network host \
  gitlab/gitlab-runner:latest

# Регистрация раннера с доступом только к внутреннему реестру
gitlab-runner register \
  --url https://git.internal \
  --token $RUNNER_TOKEN \
  --executor docker \
  --docker-image docker:24.0 \
  --docker-privileged=true \
  --docker-network-mode none \
  --tag-list "linux,amd64,tee,isolated"

# Валидация: в конфигурации раннера (config.toml) должна быть секция [runners.docker]
cat /srv/gitlab-runner/config/config.toml | grep -A5 "\[runners.docker\]"
# → network_mode = "none"
# → privileged = true
```

### Генерация SLSA Build L3 аттестации в GitHub Actions

Использование официальных генераторов гарантирует выполнение требований SLSA L3 (изоляция и невозможность подделки).

```yaml
jobs:
  build:
    outputs:
      hashes: ${{ steps.hash.outputs.hashes }}
    steps:
      - name: Build artifact
        run: go build -trimpath -o app main.go
      - name: Generate hashes
        id: hash
        run: echo "hashes=$(sha256sum app | base64 -w0)" >> "$GITHUB_OUTPUT"

  provenance:
    needs: [build]
    permissions:
      actions: read
      id-token: write
      contents: write
    uses: slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml@v2.0.0
    with:
      base64-subjects: "${{ needs.build.outputs.hashes }}"
      upload-assets: true
```

### Верификация VSA через Admission Controller (Kyverno)

В 2026 году рекомендуется проверять не сырые аттестации, а **VSA (Verification Summary Attestation)**, которая подтверждает, что артефакт соответствует политике организации.

```yaml
# Фрагмент политики Kyverno для проверки VSA
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-slsa-vsa
spec:
  rules:
    - name: verify-vsa
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["my-registry.com/my-app/*"]
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

## Дополнительная информация

### Защита от новых угроз (2026)

*   **Confidential Builds (аппаратная изоляция):** Использование **Intel TDX** или **AMD SEV-SNP** для создания доверенных анклавов сборки на on-prem серверах. Это защищает секреты и процесс компиляции от несанкционированного доступа к хосту.
*   **Ledger-based Trust:** Переход от простых журналов к децентрализованным реестрам (**IETF SCITT**), обеспечивающим криптографическое доказательство неизменности аттестаций во времени.
*   **Гибридные PQC-подписи:** Использование связок `ECDSA + ML-DSA` для обеспечения обратной совместимости во время миграции на постквантовую криптографию.

### Рекомендации по эксплуатации

1.  **Hardened Images:** Используйте **Chainguard** или **Wolfi** как базовые образы; они поставляются с предустановленными SBOM, имеют минимальную поверхность атаки и нулевое количество известных уязвимостей.
2.  **Short-lived Certificates:** Откажитесь от долгоживущих GPG/SSH ключей в CI в пользу **Sigstore Fulcio** (подписи на основе OIDC-идентичности раннера).
3.  **Blast Radius Reduction:** Каждая сборка должна выполняться в выделенном эфемерном окружении с минимально необходимыми привилегиями (Least Privilege).
4.  **Digest-pinning:** Никогда не используйте теги `latest` или `v1` в продакшне. Фиксируйте образы по digest (`image@sha256:...`).
5.  **Эфемерные среды:** Каждая сборка выполняется в чистром Docker-контейнере или виртуальной машине, которая удаляется после выполнения. Никаких постоянных runner'ов с кешем зависимостей.

### Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `cosign: error signing` | Fulcio недоступен или сертификат отклонен | `curl -k $FULCIO_URL` | Проверьте сетевую доступность Fulcio и срок действия OIDC-токена. В on-prem используйте внутренний CA или key-based подпись. |
| `Attestation not found` | SBOM/SLSA не прикреплен к образу | `curl /v2/.../referrers` | Убедитесь, что `docker buildx build` завершился с `--push` и флагами `--attest`. Для локальных тестов используйте `--output type=docker`. |
| `Cosign verify: certificate identity mismatch` | Идентичность в политике Kyverno не совпадает с OIDC-claim | `cosign verify --output text ...` | Проверьте точное совпадение `--certificate-identity` с claim `sub` в токене. |
| `Trivy: false positive на CVE` | Уязвимый код не вызывается (reachability) | `trivy sbom --show-vulnerability-reachability` | Создайте VEX-отчет со статусом `not_affected`. |
| `Kyverno блокирует валидный образ` | Политика содержит устаревший public key | `kyverno apply --policy ... --resource ...` | Обновите public key в `ClusterPolicy` после ротации ключей Cosign. |
| `SBOM generation failed: multi-arch` | Syft не поддерживает манифест image index | `syft -o spdx-json ...` | Используйте `docker buildx imagetools inspect --format '{{json .Manifest}}'` и генерацию SBOM для каждого архитектурного варианта отдельно. |
| `Build L3: изоляция не работает` | Runner работает без поддержки TEE | `dmesg \| grep -i tdx` или `dmesg \| grep -i sev` | Убедитесь, что BIOS включен TDX/SEV-SNP и ядро поддерживает данные технологии. |
| `docker buildx: network=none блокирует сборку` | В vendor отсутствуют зависимости | `docker buildx build --progress=plain ...` | Проверьте, что все зависимости предварительно загружены в vendor-каталог с помощью `pip download` / `npm ci` / `go mod download`. |

### Граничные случаи и ограничения

* **Multi-architecture образы:** `docker buildx build` создает image index, а не единый манифест. SBOM и аттестации должны генерироваться для каждого архитектурного варианта (`linux/amd64`, `linux/arm64`) отдельно. Используйте `docker buildx imagetools inspect` для просмотра constituent-манифестов.
* **Air-gapped среды:** Отсутствие доступа к Fulcio/Rekor требует развертывания внутреннего Sigstore-стока или использования key-based подписи с Notation и внутренней CA. Все образы должны быть предварительно скачаны и подписаны в изолированной зоне.
* **Обратная совместимость PQC:** Алгоритмы ML-DSA/SLH-DSA не поддерживаются клиентами OpenSSL < 3.4. Для гибридной миграции используйте связку `ECDSA + ML-DSA`, пока все узлы не будут обновлены.
* **SBOM дрейф в Runtime:** Даже при корректной сборке, запущенный контейнер может отличаться от SBOM из-за динамической загрузки библиотек (например, через `dlopen`). Для обнаружения используйте eBPF-агенты (Falco/Tetragon) и сравнивайте загруженные библиотеки с SBOM.
* **Откат (Rollback):** При откате на предыдущую версию образа убедитесь, что digest предыдущей версии присутствует в реестре, имеет валидную подпись и VSA-аттестацию. Политика Kyverno должна разрешать только подписанные теги.
* **Self-hosted GitHub Actions без облака:** При использовании self-hosted раннеров убедитесь, что `ACTIONS_RUNNER_REQUIRE_JWT_AUTHENTICATION` отключен или заменен на внутренний OIDC-провайдер, так как GitHub.com не должен участвовать в аутентификации.

### Стандарты и ресурсы

* **SLSA.dev:** <https://slsa.dev/> — спецификации SLSA v2.0 (Build & Source tracks).
* **NIST PQC Standards:** <https://csrc.nist.gov/Projects/post-quantum-cryptography> — стандарты FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) и FIPS 205 (SLH-DSA).
* **EU CRA:** <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act> — официальный текст закона о киберустойчивости ЕС.
* **ECMA-424:** <https://www.ecma-international.org/> — стандарт Cryptography Bill of Materials (CBOM).
* **IETF SCITT:** <https://datatracker.ietf.org/wg/scitt/> — цепочка доверия для программных артефактов (Supply Chain Integrity, Transparency, and Trust).
* **OpenSSF:** <https://openssf.org/> — инициативы GUAC, Scorecard и Sigstore.

### Связанные документы

* [Обзор безопасности цепочки поставок](./overview.md) — общие принципы, SLSA v2.0 и регуляторика (EU CRA).
* [Подпись артефактов](./artifact_signing.md) — Sigstore, Cosign и VSA-аттестации.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация по CycloneDX 1.6.
* [Sigstore: Безопасность цепочки поставок](../../Security/Tools/sigstore.md) — глубокое погружение в инфраструктуру подписи.
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — генерация аттестаций через BuildKit.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — оркестрация рисков цепочки поставок.
