# SBOM и подпись артефактов в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

**SBOM (Software Bill of Materials)** — машиночитаемый список всех компонентов и зависимостей в составе программного продукта. Форматы: SPDX, CycloneDX, Syft JSON.

**CycloneDX** — формат SBOM, разработанный OWASP. Легковесный, поддерживает зависимости, уязвимости, компоненты.

**SPDX (Software Package Data Exchange)** — формат SBOM, разработанный Linux Foundation. Богаче по метаданным, поддерживает лицензии.

**Cosign** — инструмент для подписи контейнерных образов и артефактов. Часть экосистемы Sigstore. Поддерживает key-based и keyless (Fulcio + Rekor) подпись.

**Sigstore** — инфраструктура для подписи артефактов. Включает Fulcio (CA), Rekor (transparency log), Cosign (CLI).

**SLSA Provenance** — аттестация происхождения артефакта (кто, где, из чего собран). Формат: SLSA v1.2+.

**Attestation** — цифровое подтверждение происхождения и целостности артефакта. Включает SBOM, provenance, VEX (Vulnerability Exploitability eXchange).

** Fulcio** — корневой CA сертификат Sigstore. Выдаёт сертификаты, привязанные к identity (email, GitHub/GitLab runner, workload identity).

**Rekor** — transparency log Sigstore. Записывает все подписи для аудита и верификации.

## Предварительные требования

* GitLab CE/EE 17.x–19.x с включенным Container Registry
* GitLab Runner 17.x–19.x с поддержкой Docker executor или Kubernetes executor
* Роль `Maintainer` в проекте для настройки CI/CD переменных и protected branches
* Docker Engine 20.10+ или Kubernetes 1.24+ для выполнения задач
* Доменные имена: `gitlab.example.com`, `registry.gitlab.example.com` должны разрешаться из Runner'ов
* TLS: Валидные сертификаты для GitLab и Registry; self-signed допустимы только в development-средах
* NTP: Синхронизация времени между Runner'ами и GitLab Server для корректной проверки OIDC-подписей
* Для keyless подписи: включенный OIDC Workload Identity Federation в GitLab
* Для air-gapped сред: внутренний Sigstore stack (Fulcio + Rekor) или sideload корневых сертификатов
* Доступ в сеть: Runner'ы имеют egress к GitLab API (TCP 443), Registry (TCP 443), и внешним mirror'ам при необходимости

## Основные концепции

### Архитектура подписи артефактов в GitLab CI/CD

```
Build → SBOM Generation (Syft)
       → Sign (Cosign + Sigstore)
       → Attest (Provenance + SBOM)
       → Push to Registry
       → Verify in Deploy stage
```

### Сравнение инструментов подписи

| Инструмент | Тип подписи | Transparency log | Key management | GitLab интеграция |
| :--- | :--- | :--- | :--- | :--- |
| **Cosign** | Key-based / Keyless | Rekor | Key pair / Fulcio | Да (через CI job) |
| **Notation** | Key-based | Нет | Key pair / Sigstore | Да (через CI job) |
| **Docker Content Trust** | Key-based | Notary | Key pair | Да (через Docker) |

### Форматы SBOM

| Формат | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **CycloneDX** | Легковесный, широко поддерживается | Меньше метаданных | Рекомендуется для GitLab CI |
| **SPDX** | Богатые метаданные, лицензии | Сложнее в обработке | Для compliance-ориентированных команд |
| **Syft JSON** | Гибкий, поддерживает все форматы | Менее стандартизирован | Для внутренних инструментов |

### Уровни подписи

| Уровень | Описание | Безопасность |
| :--- | :--- | :--- |
| **L0: No signature** | Без подписи | Нет |
| **L1: Key-based signature** | Подпись статическим ключом | Средняя (ключ хранится в секретах) |
| **L2: Keyless + OIDC** | Подпись через Fulcio, identity = CI pipeline | Высокая (без секретов) |
| **L3: Keyless + Sigstore + Rekor** | Подпись + transparency log | Максимальная (аудит, прозрачность) |

### Нативный SBOM в GitLab

GitLab 12.7+ поддерживает SBOM через `artifacts:reports:cyclonedx`:

```yaml
generate_sbom:
  stage: test
  image: aquasec/trivy:latest
  script:
    - trivy image --format cyclonedx --output sbom.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  artifacts:
    reports:
      cyclonedx: sbom.json
    expire_in: 90 days
```

SBOM автоматически отображается в UI: **Packages & Registries → Container Registry → Security → Dependencies**.

## Практические сценарии

### Сценарий 1: Генерация SBOM через Syft

**Установка:**
```bash
# Установка Syft
brew install syft  # macOS
# Или
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh
```

**Генерация SBOM в GitLab CI:**
```yaml
stages:
  - build
  - sbom
  - sign

build_image:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker build -t $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

generate_sbom:
  stage: sbom
  image: anchore/syft:latest
  script:
    - syft $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA -o cyclonedx-json > sbom.json
    - syft $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA -o spdx-json > sbom.spdx.json
  artifacts:
    paths:
      - sbom.json
      - sbom.spdx.json
    expire_in: 1 week
    reports:
      cyclonedx: sbom.json
```

**Валидация:** Проверьте, что SBOM сгенерирован и содержит компоненты:

```bash
jq '.components | length' sbom.json
# → число > 0
jq empty sbom.spdx.json
# → no output = valid JSON
```

### Сценарий 2: Подпись образа через Cosign (key-based)

**Генерация ключей:**
```bash
# Генерация ключевой пары
cosign generate-key-pair

# Ключи:
# - cosign.key (приватный, хранить в CI/CD переменных)
# - cosign.pub (публичный, коммитить в репозиторий)
```

**Подпись образа:**
```yaml
sign_image:
  stage: sign
  image: gcr.io/projectsigstore/cosign:v2.4.0
  script:
    - echo "$COSIGN_KEY" > /tmp/cosign.key
    - cosign sign --key /tmp/cosign.key \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  variables:
    COSIGN_KEY:
      masked: true
      protected: true
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: on_success
    - if: $CI_COMMIT_TAG
```

**Валидация:** Проверьте, что образ подписан:

```bash
cosign verify --key cosign.pub \
  $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
# → Signature verified
```

### Сценарий 3: Keyless подпись через Fulcio (GitLab OIDC)

**Включение workload identity в GitLab:**
1. Перейдите в `Settings → CI/CD → Token Access`
2. Включите `Workload Identity Federation`
3. Настройте OIDC провайдера (GitLab.com или self-hosted)

**Подпись без ключей:**
```yaml
sign_image_keyless:
  stage: sign
  image: gcr.io/projectsigstore/cosign:v2.4.0
  script:
    - COSIGN_EXPERIMENTAL=1 cosign sign --yes \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  variables:
    COSIGN_EXPERIMENTAL: "1"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: on_success
    - if: $CI_COMMIT_TAG
```

**Валидация:** Проверьте keyless подпись:

```bash
cosign verify \
  --certificate-identity-regexp '^https://gitlab\.com/.*$' \
  --certificate-oidc-issuer https://gitlab.com \
  $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
# → Signature verified
```

### Сценарий 4: Генерация SLSA Provenance

GitLab не имеет официального SLSA generator, поэтому provenance создаётся вручную в формате SLSA v1.2+:

```yaml
generate_provenance:
  stage: sbom
  image: alpine:latest
  script:
    - apk add --no-cache jq
    - |
      cat > provenance.json <<EOF
      {
        "builder": {
          "id": "https://gitlab.com/${CI_PROJECT_PATH}/-/pipelines/${CI_PIPELINE_ID}"
        },
        "buildType": "https://gitlab.com/build-types/gitlab-ci",
        "metadata": {
          "buildInvocationId": "${CI_PIPELINE_ID}",
          "buildStartedOn": "${CI_PIPELINE_CREATED_AT}",
          "buildFinishedOn": "${CI_PIPELINE_FINISHED_AT}",
          "completeness": {
            "parameters": true,
            "environment": false,
            "materials": true
          }
        }
      }
      EOF
    - jq . provenance.json
  artifacts:
    paths:
      - provenance.json
    expire_in: 1 week
```

**Валидация:** Убедитесь, что `provenance.json` корректен:

```bash
jq empty provenance.json
# → no output = valid JSON
```

### Сценарий 5: Attestation через Cosign

**Создание аттестации SBOM:**
```yaml
attest_sbom:
  stage: sign
  image: gcr.io/projectsigstore/cosign:v2.4.0
  script:
    - syft $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA -o cyclonedx-json > sbom.cdx.json
    - cosign attest --predicate sbom.cdx.json \
        --type cyclonedx \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: on_success
    - if: $CI_COMMIT_TAG
```

**Валидация:** Проверьте attestation:

```bash
cosign verify-attestation --key cosign.pub \
  $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
# → Attestation verified
```

**Создание аттестации Provenance:**
```yaml
attest_provenance:
  stage: sign
  image: gcr.io/projectsigstore/cosign:v2.4.0
  script:
    - |
      cat > provenance.json <<EOF
      {
        "builder": {
          "id": "https://gitlab.com/${CI_PROJECT_PATH}/-/pipelines/${CI_PIPELINE_ID}"
        },
        "buildType": "https://gitlab.com/build-types/gitlab-ci",
        "metadata": {
          "buildInvocationId": "${CI_PIPELINE_ID}",
          "buildStartedOn": "${CI_PIPELINE_CREATED_AT}",
          "buildFinishedOn": "${CI_PIPELINE_FINISHED_AT}",
          "completeness": {
            "parameters": true,
            "environment": false,
            "materials": true
          }
        }
      }
      EOF

      cosign attest --predicate provenance.json \
        --type slsaprovenance \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: on_success
    - if: $CI_COMMIT_TAG
```

**Валидация:** Проверьте provenance attestation:

```bash
cosign verify-attestation --key cosign.pub \
  --type slsaprovenance \
  $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
# → Attestation verified
```

### Сценарий 6: Проверка подписи при деплое

```yaml
deploy:
  stage: deploy
  image: gcr.io/projectsigstore/cosign:v2.4.0
  script:
    - |
      # Проверка подписи образа
      cosign verify \
        --certificate-identity-regexp '^https://gitlab\.com/org/.*$' \
        --certificate-oidc-issuer https://gitlab.com \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

      # Проверка наличия SBOM аттестации
      cosign verify-attestation \
        --certificate-identity-regexp '^https://gitlab\.com/org/.*$' \
        --certificate-oidc-issuer https://gitlab.com \
        --type cyclonedx \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

      # Деплой только после проверки
      kubectl set image deployment/myapp \
        myapp=$CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA \
        -n production
  environment: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: on_success
    - if: $CI_COMMIT_TAG
```

**Валидация:** Перед деплоем проверьте все артефакты:

```bash
# 1. Проверка подписи образа
cosign verify --key cosign.pub \
  $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

# 2. Проверка SBOM аттестации
cosign verify-attestation --key cosign.pub \
  --type cyclonedx \
  $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

# 3. Проверка provenance аттестации
cosign verify-attestation --key cosign.pub \
  --type slsaprovenance \
  $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

# Все команды должны завершиться с кодом 0
```

### Сценарий 7: VEX (Vulnerability Exploitability eXchange)

**Создание VEX документа:**
```yaml
vex_analysis:
  stage: security
  image: aquasec/trivy:latest
  script:
    - |
      # Сканирование уязвимостей
      trivy image --format cyclonedx --output trivy-report.json \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

      # Создание VEX документа (упрощённый пример)
      cat > vex.json <<EOF
      {
        "version": 1,
        "statements": [
          {
            "vulnerability": {
              "id": "CVE-2024-1234"
            },
            "product": {
              "id": "$CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA"
            },
            "status": "not_affected",
            "justification": "vulnerable_code_not_in_execute_path",
            "impact": "none"
          }
        ]
      }
      EOF
  artifacts:
    paths:
      - trivy-report.json
      - vex.json
```

**Валидация:** Проверьте VEX документ:

```bash
jq '.statements | length' vex.json
# → число затронутых CVE
jq empty trivy-report.json
# → no output = valid JSON
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `cosign: signature verification failed` | Подпись не найдена или неверный ключ | Проверьте `--key` или `--certificate-identity-regexp` |
| `Fulcio certificate not found` | Keyless подпись не настроена | Проверьте `COSIGN_EXPERIMENTAL=1` и OIDC конфигурацию |
| `SBOM attestation not found` | Аттестация не была создана | Проверьте, что `cosign attest` выполнен успешно |
| `Rekor transparency log unavailable` | Проблемы с доступом к Rekor | Используйте `--rekor-url` или локальный Rekor |
| `Syft не находит зависимости` | Язык/фреймворк не поддерживается | Проверьте supported languages Syft |

## Граничные случаи и ограничения

| Случай | Поведение | Рекомендация |
| :--- | :--- | :--- |
| **Multi-arch образы** | Cosign подписывает manifest list, но не отдельные платформы | Подписывайте manifest list; верификация проходит для всех платформ |
| **Большие SBOM (>5 МБ)** | `artifacts:reports:cyclonedx` имеет лимит размера | Храните SBOM как артефакт с `expire_in`, а не в Registry metadata |
| **Air-gapped среда** | Rekor/Fulcio недоступны из внешней сети | Разверните internal Sigstore stack или используйте key-based подпись |
| **Self-hosted GitLab без HTTPS** | OIDC keyless подпись требует HTTPS | Используйте key-based подпись или включите HTTPS |
| **Immutable tags** | Повторная подпись того же тега невозможна | Используйте уникальные теги (`$CI_COMMIT_SHA`) или дайте новый tag |
| **Временные подписи (TUF)** | Cosign может использовать TUF для корневых сертификатов | Настройте TUF mirror для air-gapped сред |
| **SBOM для бинарных артефактов** | Syft лучше работает с container images | Для бинарников используйте `syft dir:.` или `syft path:/binary` |
| **Подпись уже запущенного job** | Подпись должна быть в том же pipeline | Используйте `needs:` для гарантии порядка стадий |

## Очистка и retention

* **SBOM артефакты:** Храните 90 дней для compliance, 30 дней для development-пайплайнов.
* **Подписи в Registry:** Cosign хранит подписи в Registry неограниченно. Настройте retention policy для Registry tags.
* **Ключи подписи:** Ротовращайте ключи каждые 90 дней. Архивируйте старые ключи в encrypted storage.
* **Transparency log:** Rekor не удаляет записи. Учитывайте это при планировании retention.
* **VEX документы:** Храните вместе с SBOM; удаляйте через `artifacts:expire_in`.

## Best Practices

### Разработка (Dev)

1. **Генерируйте SBOM для каждого образа:** Добавьте задачу в `.pre` стадию.
2. **Используйте keyless подпись:** Без секретов, проще в эксплуатации.
3. **Проверяйте подпись при деплое:** Никогда не деплойте неподписанные образы.
4. **Версионируйте политики SBOM:** Храните политики в Git, ревьюьте изменения.
5. **Используйте CycloneDX для GitLab:** Лучше поддерживается экосистемой.

### Эксплуатация (DevOps/SRE)

1. **Мониторьте compliance:** Регулярно проверяйте, что все образы в registry подписаны.
2. **Автоматизируйте проверку:** Интегрируйте проверку подписи в deploy stage.
3. **Храните публичные ключи в репозитории:** `cosign.pub` коммитить в Git.
4. **Используйте Sigstore transparency log:** Для аудита всех подписей.
5. **Настройте алерты на неподписанные образы:** Prometheus + GitLab API.

### Sysadmin

1. **Настройте internal Fulcio/Rekor:** Для air-gapped окружений разверните свой Sigstore stack.
2. **Ограничьте доступ к ключам подписи:** Key-based подход требует защиты приватных ключей.
3. **Аудит подписей:** Регулярно проверяйте transparency log на аномалии.
4. **Резервное копирование ключей:** Key-based подход требует бэкапа ключей.

## Дополнительная информация

### Связанные файлы

- **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — общие принципы защиты CI/CD
- **[Подпись образов Docker](../../../Docker/Docker_security/image_signature_and_verification.md)** — Cosign, Notation, Notary
- **[Supply Chain Security](../../../Security/Supply_Chain_Security/overview.md)** — обзор безопасности цепочки поставок
- **[Artifact Signing](../../../Security/Supply_Chain_Security/artifact_signing.md)** — практическое руководство

### Внешние ресурсы

- [Cosign Documentation](https://docs.sigstore.dev/cosign/overview/)
- [Syft Documentation](https://github.com/anchore/syft)
- [SLSA Framework](https://slsa.dev/)
- [CycloneDX](https://cyclonedx.org/)
- [SPDX](https://spdx.dev/)
