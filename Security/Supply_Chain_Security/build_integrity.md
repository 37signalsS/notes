# Целостность сборки

**Актуально для:** SLSA v1.2 (Build Track L1–L3, Source Track L1–L4), Docker Engine 29.x, BuildKit 0.34+, Cosign v3.1+, Syft v1.54+, Trivy v0.69+, Harbor v2.15+, Kyverno v1.19+, Kubernetes 1.31+, Tekton Chains v2.0+, GitLab Runner 16+

## Определения

* **Build Integrity (Целостность сборки):** Свойство процесса сборки, гарантирующее, что выходной артефакт точно соответствует исходному коду и не подвергался несанкционированным изменениям.
* **Reproducible Build (Воспроизводимая сборка):** Методология, при которой из идентичных исходных данных (код, зависимости, инструменты) всегда создаётся бит-в-бит идентичный артефакт. Позволяет подтвердить отсутствие "закладок" через независимую пересборку.
* **Hermetic Build (Герметичная сборка):** Сборка в полностью изолированной среде без доступа к внешней сети. Все зависимости должны быть предоставлены внутри среды и верифицированы по хеш-суммам (Content Addressable Storage).
* **SLSA (Supply-chain Levels for Software Artifacts):** Фреймворк безопасности (v1.2, ноябрь 2025), разделённый на два независимых трека для обеспечения сквозного доверия:
    * **Build Track:** Защита процесса превращения кода в артефакт (уровни Build L0–L3).
    * **Source Track:** Гарантии целостности исходного кода (двухфакторное ревью, защита веток, криптографическая подпись коммитов).
* **Provenance (Аттестация происхождения):** Машиночитаемые метаданные (формат **in-toto**), описывающие жизненный цикл создания артефакта: кто, где и из какого исходного кода собрал артефакт. В SLSA v1.2 Provenance использует предикат `https://slsa.dev/provenance/v1`.
* **in-toto:** Стандарт (in-toto.io) для описания и верификации жизненного цикла ПО. SLSA Provenance и VSA-аттестации оформляются как in-toto Statements с обязательными полями `_type`, `subject`, `predicateType` и `predicate`.
* **VSA (Verification Summary Attestation):** Сводная аттестация (in-toto), подтверждающая соответствие артефакта требуемому уровню безопасности. Используется Admission-контроллерами для быстрого принятия решений без анализа полных графов Provenance.
* **TEE (Trusted Execution Environment) / Confidential Computing:** Аппаратно изолированная среда выполнения (**Intel TDX**, **AMD SEV-SNP**, **Intel SGX**). Обеспечивает выполнение сборок в анклавах, защищённых от компрометации гипервизора или администратора хоста.

## Основные концепции

Защита целостности сборки фокусируется на исключении возможности внедрения вредоносного кода на этапе компиляции, упаковки или доставки.

### Архитектура защиты целостности сборки

Сквозной поток от исходного кода до артефакта с аттестациями:

```text
Source Code (Git, подпись коммитов)
    │
    ▼
┌─────────────────────────────────────────┐
│  Build Runner (эфемерный, изолированный)  │
│  • Hermetic Build (--network=none)      │
│  • Reproducible (SOURCE_DATE_EPOCH)      │
│  • Vendor / lock-файлы                   │
└─────────────────────────────────────────┘
    │
    ├── SBOM (--attest type=sbom)
    │   └── in-toto Statement (CycloneDX / SPDX)
    ├── Provenance (--attest type=provenance,version=v1)
    │   └── in-toto Statement (SLSA v1.2)
    │
    ▼
[OCI Registry (Harbor v2.15+)]
  └── Referrers API → подпись (Cosign/Notation)
      └── Transparency Log (Rekor / IETF SCITT)

Consumer:
  cosign verify → подпись + аттестации
  Kyverno VSA → admission control
```

### Ключевые практики защиты

| Практика | Назначение | Реализация |
| :--- | :--- | :--- |
| **Изоляция и TEE** | Защита от компрометации сборочного узла | Эфемерные раннеры в изолированных ВМ с аппаратной изоляцией памяти (Intel TDX, AMD SEV-SNP) |
| **Герметичность** | Блокировка внешних атак во время сборки | `--network=none`, использование Content Addressable Storage (CAS) и доверенных прокси |
| **Аттестация (Provenance)** | Непрерывная прослеживаемость | Нативные генераторы в CI/CD (GitLab Runner, Tekton Chains, GitHub Actions self-hosted) |
| **Прозрачность (Logging)** | Обнаружение компрометации ключей | Запись аттестаций в Ledger-системы прозрачности (**Rekor**, **IETF SCITT**) |
| **Верификация VSA** | Автоматизация контроля | Enforcement политик в Kubernetes через Kyverno/OPA на основе аттестаций |

### Уровни SLSA v1.2 (Build Track)

В 2026 году уровни SLSA базируются на проверяемых доказательствах (Evidence-based security).

| Уровень | Требование | Значение для безопасности |
| :--- | :--- | :--- |
| **Build L0** | (нет гарантий) | Нет provenance; артефакт может быть изменён после сборки. |
| **Build L1** | Provenance существует | Наличие аттестации (Provenance), автоматически сгенерированной системой сборки. Базовая прослеживаемость. |
| **Build L2** | Подписанная Provenance от hosted build | Гарантирует, что аттестация создана доверенным сервисом сборки и не была подделана. |
| **Build L3** | Hardened Build Platform | Гарантированная изоляция. Защита от влияния других сборок и компрометации сборочного узла. Требует аппаратной изоляции памяти (Intel TDX, AMD SEV-SNP). |

### Требования SLSA v1.2 (Source Track)

Для критических систем (Class II по EU CRA) обязательным является выполнение требований к исходному коду:
* **Source L1:** Использование системы контроля версий (VCS) для создания дискретных ревизий.
* **Source L2:** Сохранение истории изменений и генерация Source Provenance (неизменяемая история, защита веток).
* **Source L3:** Принудительение организационных технических контролей (например, подпись коммитов через OIDC/SSH-ключи).
* **Source L4:** Двухфакторное ревью (Two-party review) всех изменений и верифицированная идентичность автора (Verified Author).

Подробнее — в [Обзоре безопасности цепочки поставок](./overview.md#2-целостность-и-аттестация-slsa-v12).

## Практические сценарии

### Предварительные требования

Полный список компонентов для on-prem инфраструктуры — в [Обзоре безопасности цепочки поставок](./overview.md#предварительные-требования). Здесь приведены только build-специфичные детали:

| Компонент | Минимальная версия | Build-специфика |
| :--- | :--- | :--- |
| **Docker / BuildKit** | 29.x (BuildKit 0.34+) | Сборка образов с генерацией SBOM (`--attest type=sbom`) и SLSA Provenance (`--attest type=provenance,version=v1`). |
| **Cosign** | v3.1+ | Keyless-подпись образов и аттестаций; ML-DSA (PQC) через KMS (в стабильной версии недоступна). |
| **GitLab Runner** | 16+ | Self-hosted раннер с OIDC для keyless-подписи. |
| **Tekton Chains** | v2.0+ | Генерация SLSA Provenance для Tekton-пайплайнов. |
| **Kyverno** | v1.19+ | Admission-контроль для верификации подписей и VSA-аттестаций через `ImageValidatingPolicy`. |

**Аппаратные требования:**
* CPU с поддержкой AES-NI для ускорения криптографических операций.
* Для Build L3: серверы с поддержкой Intel TDX или AMD SEV-SNP для аппаратной изоляции сборок.
* Минимум 8 ГБ ОЗУ на узел CI/CD-раннера, 16 ГБ — для сборки многомодульных проектов.

### Герметичная сборка в Docker (BuildKit)

Герметичность гарантирует, что сборка не скачивает зависимости из внешней сети в процессе выполнения, что исключает подмену пакетов "на лету".

```dockerfile
# Использование доверенного образа по дайджесту
FROM python@sha256:4a080808a8080808080808080808080808080808080808080808080808080808 AS builder

WORKDIR /app

# Предварительное копирование всех зависимостей в образ
COPY ./vendor /app/vendor

# Сборка с отключенной сети
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

# Сборка Docker-образа с фиксацией меток времени слоёв (BuildKit)
docker buildx build \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  --output type=docker,rewrite-timestamp=true \
  -t my-app:latest .
```

**Верификация воспроизводимости:** соберите образ дважды из одного и того же коммита и сравните дайджесты. Если они совпадают — сборка воспроизводима.

```bash
# 1. Сборка №1
docker buildx build \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  --output type=oci,dest=/tmp/build1.tar \
  .

# 2. Сборка №2 (из того же коммита)
docker buildx build \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  --output type=oci,dest=/tmp/build2.tar \
  .

# 3. Сравнение дайджестов
sha256sum /tmp/build1.tar /tmp/build2.tar
# → оба хеша должны быть идентичны

# 4. Сравнение содержимого через Syft
syft /tmp/build1.tar -o cyclonedx-json > sbom1.json
syft /tmp/build2.tar -o cyclonedx-json > sbom2.json
diff sbom1.json sbom2.json
# → различий быть не должно
```

**Языковые практики:**

| Язык | Флаг/переменная | Цель |
| :--- | :--- | :--- |
| **Go** | `-trimpath -ldflags="-buildid="` | Удаление абсолютных путей и build ID из бинарника |
| **Python** | `SOURCE_DATE_EPOCH` | Фиксация времени в wheel-файлах |
| **Rust** | `SOURCE_DATE_EPOCH` | Фиксация времени сборки cargo |
| **Java** | `SOURCE_DATE_EPOCH` | Фиксация времени в JAR-файлах; `-fdebug-prefix-map` для javac |
| **C/C++** | `-ffile-prefix-map=$(pwd)=.`, `-fdebug-prefix-map` | Удаление абсолютных путей из отладочной информации |

Подробнее о языковых деталях — в [Best Practices для Go](../../Docker/Dockerfile/Docker_best_practices/go.md), [Java](../../Docker/Dockerfile/Docker_best_practices/java.md), [Python](../../Docker/Dockerfile/Docker_best_practices/python.md).

### Нативная аттестация в Docker (BuildKit 0.34+)

BuildKit позволяет генерировать аттестации (SBOM и Provenance) непосредственно во время сборки с помощью флага `--attest`.

```bash
# Сборка с генерацией аттестаций SLSA и SBOM
docker buildx build \
  --tag my-registry.com/my-app:v1.0.0 \
  --attest type=provenance,mode=max,version=v1 \
  --attest type=sbom \
  --push .

# Верификация наличия аттестаций в реестре
docker buildx imagetools inspect my-registry.com/my-app:v1.0.0 --format "{{json .Provenance}}"
```

> **Важно:** `mode=max` включает значения build args в аттестацию. Не передавайте секреты через `--build-arg` — используйте `--secret` и `RUN --mount=type=secret`. Для production-сборок можно использовать `mode=min` (безопаснее, не раскрывает args).

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

# Регистрация раннера с доступом только к внутренному реестру
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
    uses: slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml@v2.1.0
    with:
      base64-subjects: "${{ needs.build.outputs.hashes }}"
      upload-assets: true
```

### Генерация SLSA Provenance через Tekton Chains

[Tekton Chains](https://tekton.dev/docs/chains/) — Kubernetes-native механизк генерации SLSA Provenance для Tekton-пайплайнов. Подходит для on-prem кластеров без GitHub Actions.

```bash
# 1. Установка Tekton Chains в кластере
kubectl apply -f https://raw.githubusercontent.com/tektoncd/chains/main/release.yaml

# 2. Конфигурация для SLSA v1.2 Provenance
kubectl patch configmap chains-config -n tekton-chains \
  -p '{"data":{"artifacts.tekton.dev/signature-format": "slsa"}}'

# 3. Tekton Task с SLSA provenance
```

```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: build-and-sign
  annotations:
    chains.external-node.attack.mitre.org/slsa-level: "3"
spec:
  params:
    - name: IMAGE
      type: string
  results:
    - name: IMAGE_DIGEST
  steps:
    - name: build
      image: gcr.io/kaniko-project/executor:latest
      args:
        - "--dockerfile=Dockerfile"
        - "--context=."
        - "--destination=$(params.IMAGE)"
        - "--destination=$(params.IMAGE)-sha256=$(results.IMAGE_DIGEST)"
```

**Валидация:** после выполнения TaskRun Tekton Chains генерирует in-toto attestation с `predicateType: https://slsa.dev/provenance/v1`:

```bash
# Проверка аттестации в реестре
tkn chains get <taskrun-name> -o json | jq '.attestations[] | select(.payloadType=="https://slsa.dev/provenance/v1")'
# → {"payloadType":"...","payload":"{base64-encoded SLSA provenance}"}
```

### Верификация VSA через Admission Controller

В 2026 году рекомендуется проверять не сырые аттестации, а **VSA (Verification Summary Attestation)**, которая подтверждает, что артефакт соответствует политике организации. Политика использует `ImageValidatingPolicy` (Kyverno v1.19+, `ClusterPolicy` устарел):

```yaml
# Политика Kyverno для проверки VSA (ImageValidatingPolicy)
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-slsa-vsa
spec:
  failurePolicy: Enforce
  rules:
    - name: check-slsa-vsa
      image: harbor.internal/my-app/*
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

Подробнее с troubleshooting — в [Обзоре безопасности цепочки поставок](./overview.md#шаг-6-admission-контроль-и-верификация-vsa).

### Валидация внедрения

После настройки пайплайна выполните комплексную проверку всех компонентов:

```bash
# 1. Проверка целостности подписи и аттестаций
cosign verify $REGISTRY:$IMAGE_TAG \
  --certificate-identity-regexp "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer $FULCIO_URL \
  && echo "Signature OK" || echo "Signature FAIL"

# 2. Проверка наличия SLSA-аттестации (Provenance)
cosign verify-attestation $REGISTRY:$IMAGE_TAG \
  --type slsaprovenance \
  --certificate-identity-regexp "https://harbor.internal/project/my-app" \
  --certificate-oidc-issuer $FULCIO_URL \
  | jq '.payload'
# → Должен вернуть SLSA provenance аттестацию

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

# 6. Верификация provenance через BuildKit
docker buildx imagetools inspect $REGISTRY:$IMAGE_TAG \
  --format '{{ json .Provenance.SLSA }}'
# → {"buildType":"https://mobyproject.org/buildkit@v1", "predicateType":"https://slsa.dev/provenance/v1", ...}
```

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Build L3: изоляция не работает` | Runner работает без поддержки TEE | `dmesg \| grep -i tdx` или `dmesg \| grep -i sev` | Убедитесь, что BIOS включён TDX/SEV-SNP и ядро поддерживает данные технологии. |
| `docker buildx: network=none блокирует сборку` | В vendor-каталоге отсутствуют зависимости | `docker buildx build --progress=plain ...` | Предварительно загрузите зависимости в vendor (pip download / npm ci / go mod vendor). |
| `Provenance не прикреплена к образу` | Сборка не завершилась с `--push` и `--attest` | `docker buildx imagetools inspect ...` | Убедитесь, что сборка включает `--attest type=provenance` и `--push`. |
| `cosign verify: certificate identity mismatch` | Идентичность в политике не совпадает с OIDC-claim | `cosign verify --output text ...` | Проверьте точное совпадение `--certificate-identity` с claim `sub` в токене. |
| `SBOM generation failed: multi-arch` | Syft не поддерживает манифест image index | `syft -o spdx-json ...` | Используйте `docker buildx imagetools inspect --format '{{json .Manifest}}'` и генерацию SBOM для каждого архитектурного варианта отдельно. |

Общие проблемы подписи и VSA-аттестаций — в [Подпись артефактов](./artifact_signing.md#устранение-неполадок) и [Обзоре](./overview.md#валидация-внедрения).

## Лучшие практики и очистка

1.  **Hardened Images:** Используйте **Chainguard** или **Wolfi** как базовые образы; они поставляются с предустановленными SBOM, имеют минимальную поверхность атаки и нулевое количество известных уязвимостей.
2.  **Short-lived Certificates:** Откажитесь от долгоживущих GPG/SSH ключей в CI в пользу **Sigstore Fulcio** (подписи на основе OIDC-идентичности раннера).
3.  **Blast Radius Reduction:** Каждая сборка должна выполняться в выделенном эфемерном окружении с минимально необходимыми привилегиями (Least Privilege).
4.  **Digest-pinning:** Никогда не используйте теги `latest` или `v1` в продакшене. Фиксируйте образы по digest (`image@sha256:...`).
5.  **Эфемерные среды:** Каждая сборка выполняется в чистом Docker-контейнере или виртуальной машине, которая удаляется после выполнения. Никаких постоянных runner'ов с кешем зависимостей.
6.  **Ротация ключей подписи:** Периодически (раз в 90 дней) ротируйте ключи Cosign. Для keyless-сценария обновляйте Fulcio CA-корневой сертификат.
7.  **Очистка артефактов:** Настройте политику удержания (retention) в Harbor: удаляйте неиспользуемые теги и старые аттестации через Harbor API.

## Граничные случаи и ограничения

* **Multi-architecture образы:** `docker buildx build` создаёт image index, а не единый манифест. SBOM и аттестации должны генерироваться для каждого архитектурного варианта (`linux/amd64`, `linux/arm64`) отдельно. Используйте `docker buildx imagetools inspect` для просмотра constituent-манифестов.
* **Air-gapped среды:** Отсутствие доступа к Fulcio/Rekor требует развёртывания внутреннего Sigstore-стока или использования key-based подписи с Notation и внутренней CA. Все образы должны быть предварительно скачаны и подписаны в изолированной зоне.
* **Обратная совместимость PQC:** Алгоритмы ML-DSA/SLH-DSA не поддерживаются клиентами OpenSSL < 3.4. Для гибридной миграции используйте связку `ECDSA + ML-DSA`, пока все узлы не будут обновлены.
* **SBOM дрейф в Runtime:** Даже при корректной сборке, запущенный контейнер может отличаться от SBOM из-за динамической загрузки библиотек (например, через `dlopen`). Для обнаружения используйте eBPF-агенты (Falco/Tetragon) и сравнивайте загруженные библиотеки с SBOM.
* **Откат (Rollback):** При откате на предыдущую версию образа убедитесь, что digest предыдущей версии присутствует в реестре, имеет валидную подпись и VSA-аттестацию. Политика Kyverno должна разрешать только подписанные теги.

Подробнее о многоплатформенных сборках, PQC и air-gapped — в [Обзоре безопасности цепочки поставок](./overview.md#граничные-случаи-и-ограничения).

## Дополнительная информация

### Стандарты и ресурсы

* **SLSA.dev:** <https://slsa.dev/> — спецификации SLSA v1.2 (Build & Source tracks).
* **NIST PQC Standards:** <https://csrc.nist.gov/Projects/post-quantum-cryptography> — стандарты FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) и FIPS 205 (SLH-DSA).
* **EU CRA:** <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act> — официальный текст закона о киберустойчивости ЕС.
* **ECMA-424:** <https://www.ecma-international.org/> — стандарт Cryptography Bill of Materials (CBOM).
* **IETF SCITT:** <https://datatracker.ietf.org/wg/scitt/> — цепочка доверия для программных артефактов (Supply Chain Integrity, Transparency, and Trust).
* **OpenSSF:** <https://openssf.org/> — инициативы GUAC, Scorecard и Sigstore.
* **in-toto:** <https://in-toto.io/> — стандарт описания жизненного цикла ПО; формат-обёртка для SLSA Provenance.
* **Tekton Chains:** <https://tekton.dev/docs/chains/> — генерация SLSA Provenance для Kubernetes-пайплайнов.

### Связанные документы

* [Обзор безопасности цепочки поставок](./overview.md) — фундаментальные принципы, SLSA v1.2 и регуляторика (EU CRA).
* [Подпись артефактов](./artifact_signing.md) — Sigstore, Cosign и VSA-аттестации.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация по CycloneDX 1.7.
* [Безопасность цепочки поставок контейнерных образов](./container_image_supply_chain.md) — distroless, digest pinning, multi-stage builds.
* [Sigstore: Безопасность цепочки поставок](../Tools/sigstore.md) — глубокое погружение в инфраструктуру подписи.
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — генерация аттестаций через BuildKit.
* [Безопасность Buildx builders](../../Docker/Docker_security/buildx_builder_security.md) — изоляция builders, cache security, provenance.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — оркестрация рисков цепочки поставок.
