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
| **Изоляция и TEE** | Защита от компрометации сборочного узла | Эфемерные раннеры в **Confidential Virtual Machines** (CVM) |
| **Герметичность** | Блокировка внешних атак во время сборки | `network=none`, использование Content Addressable Storage (CAS) и доверенных прокси |
| **Аттестация (Provenance)** | Непрерывная прослеживаемость | Нативные генераторы в CI/CD (GitHub Actions, Tekton Chains, GitLab Runner) |
| **Прозрачность (Logging)** | Обнаружение компрометации ключей | Запись аттестаций в Ledger-системы прозрачности (**Rekor**, **IETF SCITT**) |
| **Верификация VSA** | Автоматизация контроля | Enforcement политик в Kubernetes через Kyverno/OPA на основе аттестаций |

### Уровни SLSA v2.0 (Build Track)

В 2026 году уровни SLSA базируются на проверяемых доказательствах (Evidence-based security).

1.  **Build L1:** Наличие аттестации (Provenance), автоматически сгенерированной системой сборки.
2.  **Build L2:** Сборка в Hosted-среде с использованием эфемерных ресурсов. Аттестация подписана ключом системы сборки, что гарантирует защиту от подмены артефакта.
3.  **Build L3:** Гарантированная изоляция (Hardened Build). Требует использования **TEE** или эквивалентных механизмов защиты памяти, исключающих влияние инфраструктуры поставщика на процесс сборки.

### Требования SLSA v2.0 (Source Track)

Для критических систем (Class II по EU CRA) обязательным является выполнение требований к исходному коду:
* **Two-party review:** Ни один коммит не попадает в основную ветку без одобрения независимого ревьюера.
* **Verified History:** Все изменения подписаны через **Sigstore** или персональные ключи (SSH/GPG).
* **Immutable History:** Запрет на force-push и переписывание истории в репозиториях.

## Практические сценарии

### Настройка герметичной сборки в Docker (BuildKit)

Герметичность гарантирует, что сборка не скачивает зависимости из интернета в процессе выполнения, что исключает подмену пакетов "на лету".

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
        - imageReferences: ["my-registry.com/*"]
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

### Защита от новых угроз (2026)

*   **Confidential Builds (CVM/TEE):** Использование **Intel TDX** или **AMD SEV-SNP** для создания доверенных анклавов сборки. Это защищает секреты и процесс компиляции от привилегированных пользователей облака и администраторов инфраструктуры CI/CD.
*   **Ledger-based Trust:** Переход от простых журналов к децентрализованным реестрам (**IETF SCITT**), обеспечивающим криптографическое доказательство неизменности аттестаций во времени.
*   **AI/ML Model Integrity:** Фиксация не только кода, но и дайджестов весов моделей и наборов данных (Dataset Provenance) для предотвращения атак типа Data Poisoning и Model Hijacking.

### Рекомендации по эксплуатации

1.  **Hardened Images:** Используйте **Chainguard** или **Wolfi** как базовые образы; они поставляются с предустановленными SBOM, имеют минимальную поверхность атаки и нулевое количество известных уязвимостей.
2.  **Short-lived Certificates:** Откажитесь от долгоживущих GPG/SSH ключей в CI в пользу **Sigstore Fulcio** (подписи на основе OIDC-идентичности раннера).
3.  **Blast Radius Reduction:** Каждая сборка должна выполняться в выделенном эфемерном окружении с минимально необходимыми привилегиями (Least Privilege).

### Связанные документы

* [Обзор безопасности цепочки поставок](./overview.md) — общие принципы, SLSA v2.0 и регуляторика (EU CRA).
* [Подпись артефактов](./artifact_signing.md) — Sigstore, Cosign и VSA-аттестации.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX и инвентаризация по CycloneDX 1.6.
* [Sigstore: Безопасность цепочки поставок](../Tools/sigstore.md) — глубокое погружение в инфраструктуру подписи.
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — генерация аттестаций через BuildKit.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — оркестрация рисков цепочки поставок.
